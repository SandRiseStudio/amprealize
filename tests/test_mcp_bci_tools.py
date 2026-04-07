"""
Test MCP BCI tools parity (bci.*).

Following patterns from test_mcp_behavior_tools.py to ensure:
- JSON-RPC 2.0 protocol compliance
- MCP content format validation
- Full BCI lifecycle coverage (retrieve, compose, parse, validate, analyze)
- Error handling (missing params, invalid inputs)
"""

import json
import os
import pytest
from datetime import datetime, timedelta
from amprealize.mcp_server import MCPServer


def _authenticated_server(server):
    """Authenticate an MCPServer session for testing."""
    server._session_context.user_id = "test-user"
    server._session_context.auth_method = "device_flow"
    server._session_context.is_admin = True
    server._session_context.granted_scopes = {"*"}
    server._session_context.expires_at = datetime.utcnow() + timedelta(hours=1)
    return server


@pytest.fixture
def mcp_server():
    """Create MCP server instance for testing."""
    return _authenticated_server(MCPServer())


@pytest.fixture
def actor():
    """Standard test actor payload."""
    return {
        "id": "test-user-123",
        "role": "DEVELOPER",
        "surface": "MCP_TEST"
    }


# ========== Retrieve Tests ==========

@pytest.mark.asyncio
async def test_bci_retrieve_tool(mcp_server, actor):
    """Test bci.retrieve tool returns relevant behaviors."""
    request = {
        "jsonrpc": "2.0",
        "id": "test-retrieve-1",
        "method": "tools/call",
        "params": {
            "name": "bci.retrieve",
            "arguments": {
                "task": "implement user authentication with JWT tokens",
                "top_k": 3,
                "min_score": 0.0,
                "strategy": "semantic"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "test-retrieve-1"
    assert "result" in response

    result = response["result"]
    assert "content" in result
    assert len(result["content"]) > 0
    assert result["content"][0]["type"] == "text"

    data = json.loads(result["content"][0]["text"])
    assert "behaviors" in data
    assert "retrieval_time_ms" in data
    assert "strategy" in data
    assert data["strategy"] == "semantic"
    assert isinstance(data["behaviors"], list)


@pytest.mark.asyncio
async def test_bci_retrieve_hybrid_tool(mcp_server, actor):
    """Test bci.retrieveHybrid tool combines semantic + keyword search."""
    request = {
        "jsonrpc": "2.0",
        "id": "test-retrieve-hybrid-1",
        "method": "tools/call",
        "params": {
            "name": "bci.retrieveHybrid",
            "arguments": {
                "task": "validate user input and sanitize data",
                "top_k": 5
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "result" in response

    data = json.loads(response["result"]["content"][0]["text"])
    assert "behaviors" in data
    assert data["strategy"] == "hybrid"


@pytest.mark.asyncio
async def test_bci_retrieve_missing_task(mcp_server, actor):
    """Test bci.retrieve with missing required 'task' parameter."""
    request = {
        "jsonrpc": "2.0",
        "id": "test-retrieve-missing-1",
        "method": "tools/call",
        "params": {
            "name": "bci.retrieve",
            "arguments": {
                "top_k": 5
                # Missing required 'task' field
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Should return error for missing required parameter
    assert "error" in response or (
        "result" in response and "error" in json.loads(response["result"]["content"][0]["text"])
    )


# ========== Compose Prompt Tests ==========

@pytest.mark.asyncio
async def test_bci_compose_prompt_tool(mcp_server, actor):
    """Test bci.composePrompt creates behavior-conditioned prompt."""
    request = {
        "jsonrpc": "2.0",
        "id": "test-compose-1",
        "method": "tools/call",
        "params": {
            "name": "bci.composePrompt",
            "arguments": {
                "task": "implement caching layer with Redis",
                "top_k": 3,
                "format": "markdown"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "result" in response

    data = json.loads(response["result"]["content"][0]["text"])
    assert "prompt" in data
    assert "behaviors_used" in data
    assert "total_input_tokens" in data
    assert "format" in data
    assert data["format"] == "markdown"
    assert isinstance(data["prompt"], str)
    assert len(data["prompt"]) > 0


@pytest.mark.asyncio
async def test_bci_compose_batch_prompts_tool(mcp_server, actor):
    """Test bci.composeBatchPrompts handles multiple tasks."""
    request = {
        "jsonrpc": "2.0",
        "id": "test-compose-batch-1",
        "method": "tools/call",
        "params": {
            "name": "bci.composeBatchPrompts",
            "arguments": {
                "tasks": [
                    "setup database migrations",
                    "implement API rate limiting",
                    "add logging and monitoring"
                ],
                "top_k": 2,
                "format": "plain"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert "result" in response
    data = json.loads(response["result"]["content"][0]["text"])
    assert "results" in data
    assert len(data["results"]) == 3
    assert "total_behaviors_retrieved" in data
    assert "avg_retrieval_time_ms" in data

    for result in data["results"]:
        assert "task" in result
        assert "prompt" in result
        assert "behaviors_used" in result


# ========== Citation Tests ==========

@pytest.mark.asyncio
async def test_bci_parse_citations_tool(mcp_server, actor):
    """Test bci.parseCitations extracts behavior references from text."""
    output_text = """
    To solve this problem, I'll use behavior_sanitize_input to validate the data,
    then behavior_cache_results to improve performance, and finally
    behavior_log_errors for monitoring.
    """

    request = {
        "jsonrpc": "2.0",
        "id": "test-parse-1",
        "method": "tools/call",
        "params": {
            "name": "bci.parseCitations",
            "arguments": {
                "output_text": output_text,
                "mode": "auto"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert "result" in response
    data = json.loads(response["result"]["content"][0]["text"])
    assert "citations" in data
    assert "total_citations" in data
    assert "unique_behaviors" in data
    assert data["total_citations"] >= 3
    assert data["unique_behaviors"] >= 3


@pytest.mark.asyncio
async def test_bci_validate_citations_tool(mcp_server, actor):
    """Test bci.validateCitations checks behavior existence."""
    request = {
        "jsonrpc": "2.0",
        "id": "test-validate-1",
        "method": "tools/call",
        "params": {
            "name": "bci.validateCitations",
            "arguments": {
                "citations": [
                    "behavior_unify_execution_records",
                    "behavior_align_storage_layers",
                    "behavior_nonexistent_test"
                ]
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert "result" in response
    data = json.loads(response["result"]["content"][0]["text"])
    assert "valid_citations" in data
    assert "invalid_citations" in data
    assert "missing_behaviors" in data
    assert "validation_rate" in data
    assert "total_checked" in data
    assert data["total_checked"] == 3


# ========== Token Savings Tests ==========

@pytest.mark.asyncio
async def test_bci_compute_token_savings_tool(mcp_server, actor):
    """Test bci.computeTokenSavings calculates efficiency metrics."""
    request = {
        "jsonrpc": "2.0",
        "id": "test-savings-1",
        "method": "tools/call",
        "params": {
            "name": "bci.computeTokenSavings",
            "arguments": {
                "baseline_tokens": 1000,
                "bci_tokens": 540,
                "num_tasks": 10
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert "result" in response
    data = json.loads(response["result"]["content"][0]["text"])
    assert "savings_percentage" in data
    assert "absolute_savings" in data
    assert "efficiency_ratio" in data
    assert "baseline_tokens" in data
    assert "bci_tokens" in data
    # 46% savings: (1000-540)/1000 = 0.46
    assert data["savings_percentage"] == pytest.approx(46.0, abs=0.1)
    assert data["absolute_savings"] == 460


# ========== Trace Analysis Tests ==========

@pytest.mark.asyncio
async def test_bci_segment_trace_tool(mcp_server, actor):
    """Test bci.segmentTrace breaks reasoning into steps."""
    trace_text = """
    First, I need to understand the requirements.
    Then, I'll design the database schema.
    Next, I'll implement the API endpoints.
    Finally, I'll add tests and documentation.
    """

    request = {
        "jsonrpc": "2.0",
        "id": "test-segment-1",
        "method": "tools/call",
        "params": {
            "name": "bci.segmentTrace",
            "arguments": {
                "trace": trace_text,
                "format": "text",
                "min_step_tokens": 5
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert "result" in response
    data = json.loads(response["result"]["content"][0]["text"])
    assert "steps" in data
    assert "total_steps" in data
    assert "total_tokens" in data
    assert "avg_tokens_per_step" in data
    assert data["total_steps"] >= 4


@pytest.mark.asyncio
async def test_bci_detect_patterns_tool(mcp_server, actor):
    """Test bci.detectPatterns finds reusable reasoning patterns."""
    traces = [
        "First validate input, then process data, finally return results.",
        "Start by validating the input parameters carefully.",
        "Always validate inputs before processing to avoid errors."
    ]

    request = {
        "jsonrpc": "2.0",
        "id": "test-patterns-1",
        "method": "tools/call",
        "params": {
            "name": "bci.detectPatterns",
            "arguments": {
                "traces": traces,
                "min_frequency": 2,
                "min_score": 0.3
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert "result" in response
    data = json.loads(response["result"]["content"][0]["text"])
    assert "patterns" in data
    assert "total_patterns" in data
    assert "total_traces_analyzed" in data
    assert data["total_traces_analyzed"] == 3


@pytest.mark.asyncio
async def test_bci_score_reusability_tool(mcp_server, actor):
    """Test bci.scoreReusability evaluates behavior quality."""
    request = {
        "jsonrpc": "2.0",
        "id": "test-score-1",
        "method": "tools/call",
        "params": {
            "name": "bci.scoreReusability",
            "arguments": {
                "behavior_name": "behavior_validate_input",
                "behavior_instruction": "Always validate and sanitize user input before processing to prevent injection attacks and data corruption.",
                "example_traces": [
                    "Used behavior_validate_input to check form data",
                    "Applied behavior_validate_input on API parameters"
                ]
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert "result" in response
    data = json.loads(response["result"]["content"][0]["text"])
    assert "overall_score" in data
    assert "dimension_scores" in data
    assert "recommendations" in data
    assert "is_reusable" in data
    assert isinstance(data["dimension_scores"], list)


# ========== Index Management Tests ==========

@pytest.mark.asyncio
async def test_bci_rebuild_index_tool(mcp_server, actor):
    """Test bci.rebuildIndex refreshes behavior retrieval index."""
    request = {
        "jsonrpc": "2.0",
        "id": "test-rebuild-1",
        "method": "tools/call",
        "params": {
            "name": "bci.rebuildIndex",
            "arguments": {}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert "result" in response
    data = json.loads(response["result"]["content"][0]["text"])
    # rebuildIndex returns Dict[str, Any] with status info
    assert isinstance(data, dict)


# ========== Full Lifecycle Test ==========

@pytest.mark.asyncio
async def test_bci_full_lifecycle(mcp_server, actor):
    """Test complete BCI workflow: retrieve → compose → validate."""
    # Step 1: Retrieve behaviors for a task
    retrieve_request = {
        "jsonrpc": "2.0",
        "id": "lifecycle-retrieve",
        "method": "tools/call",
        "params": {
            "name": "bci.retrieve",
            "arguments": {
                "task": "implement error handling and logging",
                "top_k": 3
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(retrieve_request))
    response = json.loads(response_str)
    assert "result" in response

    retrieve_data = json.loads(response["result"]["content"][0]["text"])
    assert "behaviors" in retrieve_data
    behaviors_retrieved = len(retrieve_data["behaviors"])

    # Step 2: Compose prompt with retrieved behaviors
    compose_request = {
        "jsonrpc": "2.0",
        "id": "lifecycle-compose",
        "method": "tools/call",
        "params": {
            "name": "bci.composePrompt",
            "arguments": {
                "task": "implement error handling and logging",
                "top_k": 3,
                "format": "markdown"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(compose_request))
    response = json.loads(response_str)
    assert "result" in response

    compose_data = json.loads(response["result"]["content"][0]["text"])
    assert "prompt" in compose_data
    assert "behaviors_used" in compose_data
    assert len(compose_data["behaviors_used"]) > 0

    # Step 3: Parse citations from simulated model output
    model_output = f"I used {compose_data['behaviors_used'][0]['behavior_name']} to solve this."

    parse_request = {
        "jsonrpc": "2.0",
        "id": "lifecycle-parse",
        "method": "tools/call",
        "params": {
            "name": "bci.parseCitations",
            "arguments": {
                "output_text": model_output
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(parse_request))
    response = json.loads(response_str)
    assert "result" in response

    parse_data = json.loads(response["result"]["content"][0]["text"])
    assert "citations" in parse_data

    # Step 4: Validate citations
    if len(parse_data["citations"]) > 0:
        cited_behaviors = [c["behavior_name"] for c in parse_data["citations"]]

        validate_request = {
            "jsonrpc": "2.0",
            "id": "lifecycle-validate",
            "method": "tools/call",
            "params": {
                "name": "bci.validateCitations",
                "arguments": {
                    "citations": cited_behaviors
                }
            }
        }

        response_str = await mcp_server.handle_request(json.dumps(validate_request))
        response = json.loads(response_str)
        assert "result" in response

        validate_data = json.loads(response["result"]["content"][0]["text"])
        assert "valid_citations" in validate_data
        assert "validation_rate" in validate_data
