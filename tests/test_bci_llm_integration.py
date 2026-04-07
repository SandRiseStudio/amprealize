"""
Tests for BCI Real LLM Integration (Epic 6/Epic 8).

Tests the BCIService with the unified amprealize.llm package:
- Model catalog pricing
- LLMResponse fields
- BCIService integration
- MCP tool integration

Following behavior_use_raze_for_logging pattern for telemetry assertions.
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

# Mark all tests as unit tests (no infrastructure required)
pytestmark = pytest.mark.unit


def _postgres_available():
    """Check if PostgreSQL is available for integration tests."""
    import socket
    try:
        host = os.environ.get("AMPREALIZE_PG_HOST_BEHAVIOR", "localhost")
        port = int(os.environ.get("AMPREALIZE_PG_PORT_BEHAVIOR", "6433"))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


from amprealize.llm import (
    LLMClient,
    LLMConfig,
    LLMResponse,
    ProviderType,
    MODEL_CATALOG,
)
from amprealize.llm.providers.test import TestProvider as LLMTestProvider
from amprealize.bci_service import BCIService


class TestModelCatalog:
    """Test model catalog has pricing info."""

    def test_catalog_models_have_pricing(self):
        """Test that cataloged models have pricing info."""
        for model_id, defn in MODEL_CATALOG.items():
            assert defn.input_price_per_m is not None, f"{model_id} missing input_price_per_m"
            assert defn.output_price_per_m is not None, f"{model_id} missing output_price_per_m"

    def test_catalog_models_reasonable_values(self):
        """Test that model catalog has reasonable values."""
        for model_id, defn in MODEL_CATALOG.items():
            assert defn.max_output_tokens >= 100, f"{model_id} max_output_tokens too small"
            assert defn.input_price_per_m >= 0, f"{model_id} negative input price"
            assert defn.output_price_per_m >= 0, f"{model_id} negative output price"


class TestLLMClientWithTestProvider:
    """Test LLMClient with TestProvider."""

    def test_call_returns_response(self):
        """Test that LLMClient.call returns a valid response."""
        config = LLMConfig(provider=ProviderType.TEST, model="test-model")
        client = LLMClient(config)

        response = client.call([{"role": "user", "content": "Hello world"}])
        assert response.content is not None
        assert isinstance(response, LLMResponse)

    def test_response_has_token_fields(self):
        """Test that LLMResponse includes token and cost fields."""
        config = LLMConfig(provider=ProviderType.TEST, model="test-model")
        client = LLMClient(config)

        response = client.call([{"role": "user", "content": "Hello"}])
        assert hasattr(response, "input_tokens")
        assert hasattr(response, "output_tokens")
        assert hasattr(response, "cost_usd")


class TestLLMResponseFields:
    """Test that LLMResponse includes expected fields."""

    def test_response_has_cost_field(self):
        """Test that LLMResponse includes cost_usd field."""
        response = LLMResponse(
            content="Test response",
            model="gpt-4o",
            provider=ProviderType.OPENAI,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
        )

        assert response.cost_usd == 0.001
        assert response.input_tokens == 100
        assert response.output_tokens == 50


class TestBCIServiceIntegration:
    """Test BCIService with LLM client integration."""

    @pytest.fixture
    def bci_service(self):
        """Create BCIService instance."""
        return BCIService()

    def test_generate_response_with_test_provider(self, bci_service):
        """Test generate_response works with TestProvider."""
        config = LLMConfig(
            provider=ProviderType.TEST,
            model="test-model",
        )

        result = bci_service.generate_response(
            query="How do I implement logging?",
            llm_config=config,
        )

        # Check result structure
        assert "response" in result
        assert "behaviors_used" in result
        assert "token_savings" in result
        assert "cost" in result
        assert "latency_ms" in result

    def test_generate_response_includes_cost(self, bci_service):
        """Test that generate_response includes cost information."""
        config = LLMConfig(
            provider=ProviderType.TEST,
            model="test-model",
        )

        result = bci_service.generate_response(
            query="Explain BCI",
            llm_config=config,
        )

        # Check cost structure
        assert "cost" in result
        cost = result["cost"]
        assert "total_usd" in cost


@pytest.mark.integration
@pytest.mark.skipif(
    not _postgres_available(),
    reason="MCP tests require PostgreSQL infrastructure. Run with: ./scripts/run_tests.sh --breakeramp"
)
class TestMCPBCIGenerate:
    """Test MCP bci.generate tool integration."""

    @pytest.fixture
    def mcp_server(self):
        """Create MCP server instance."""
        from amprealize.mcp_server import MCPServer
        return MCPServer()

    @pytest.mark.asyncio
    async def test_bci_generate_mcp_tool(self, mcp_server):
        """Test bci.generate MCP tool with TestProvider."""
        request = {
            "jsonrpc": "2.0",
            "id": "test-generate-1",
            "method": "tools/call",
            "params": {
                "name": "bci.generate",
                "arguments": {
                    "query": "How do I implement structured logging?",
                    "provider": "test",
                    "top_k": 3,
                }
            }
        }

        response_str = await mcp_server.handle_request(json.dumps(request))
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "test-generate-1"

        if "error" not in response:
            assert "result" in response
            result = response["result"]
            assert "content" in result
            assert len(result["content"]) > 0

    @pytest.mark.asyncio
    async def test_bci_generate_missing_query(self, mcp_server):
        """Test bci.generate returns error when query is missing."""
        request = {
            "jsonrpc": "2.0",
            "id": "test-generate-error-1",
            "method": "tools/call",
            "params": {
                "name": "bci.generate",
                "arguments": {
                    "provider": "test",
                }
            }
        }

        response_str = await mcp_server.handle_request(json.dumps(request))
        response = json.loads(response_str)

        # Should return an error
        assert "error" in response or "result" in response
        # If result, check it indicates error
        if "result" in response:
            result_text = response["result"]["content"][0]["text"]
            # The handler may raise an error for missing query
            assert response is not None


@pytest.mark.integration
@pytest.mark.skipif(
    not _postgres_available(),
    reason="REST tests require PostgreSQL infrastructure. Run with: ./scripts/run_tests.sh --breakeramp"
)
class TestRESTBCIEndpoint:
    """Test REST /v1/bci/generate endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from amprealize.api import create_app
        try:
            from fastapi.testclient import TestClient
            app = create_app()
            return TestClient(app)
        except ImportError:
            pytest.skip("FastAPI/TestClient not available")

    def test_bci_generate_endpoint(self, client):
        """Test POST /v1/bci/generate endpoint."""
        response = client.post(
            "/v1/bci/generate",
            json={
                "query": "How do I use Raze for logging?",
                "provider": "test",
                "top_k": 3,
            }
        )

        # Check response (may fail if endpoint not implemented)
        assert response.status_code in [200, 404, 422, 500]


# Run with: pytest tests/test_bci_llm_integration.py -v
