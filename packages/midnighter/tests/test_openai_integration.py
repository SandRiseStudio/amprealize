"""Integration tests for OpenAI Fine-Tuning client.

These tests require a valid OPENAI_API_KEY in the environment.
Run with: pytest packages/midnighter/tests/test_openai_integration.py -v --run-integration

To run from amprealize root with .env file:
    ./scripts/run_tests.sh --breakeramp packages/midnighter/tests/test_openai_integration.py

Note: These tests will incur OpenAI API costs. File uploads are free but
fine-tuning jobs have per-token costs based on the base model.
"""

import json
import os
import pytest
from datetime import datetime, UTC
from typing import Generator

# Skip entire module if no API key or not running integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("OPENAI_API_KEY"),
        reason="OPENAI_API_KEY not set - skipping OpenAI integration tests"
    ),
]


@pytest.fixture
def openai_client():
    """Create OpenAI Fine-Tuning client."""
    from mdnt.clients.openai import OpenAIFineTuningClient, OPENAI_AVAILABLE

    if not OPENAI_AVAILABLE:
        pytest.skip("openai package not installed")

    return OpenAIFineTuningClient()


@pytest.fixture
def sample_training_data() -> str:
    """Create minimal valid JSONL training data (10+ examples required)."""
    examples = []
    for i in range(12):  # OpenAI requires minimum 10
        example = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that follows behavior-conditioned guidelines."},
                {"role": "user", "content": f"How do I implement feature {i}?"},
                {"role": "assistant", "content": f"Following `behavior_test` (Student): To implement feature {i}, you should start by..."},
            ]
        }
        examples.append(json.dumps(example))
    return "\n".join(examples)


@pytest.fixture
def uploaded_file(openai_client, sample_training_data) -> Generator[str, None, None]:
    """Upload a training file and clean up after test."""
    training_file = openai_client.upload_training_file(sample_training_data)
    yield training_file.file_id
    # Cleanup
    openai_client.delete_file(training_file.file_id)


class TestOpenAIClientInitialization:
    """Test client initialization and configuration."""

    def test_client_initializes_with_env_key(self, openai_client):
        """Client should initialize when OPENAI_API_KEY is set."""
        assert openai_client is not None
        assert openai_client._api_key is not None

    def test_client_has_default_model(self, openai_client):
        """Client should have default base model configured."""
        assert openai_client._base_model in openai_client.SUPPORTED_MODELS


class TestFileUpload:
    """Test training file upload operations."""

    def test_upload_valid_training_file(self, openai_client, sample_training_data):
        """Should successfully upload valid JSONL training data."""
        result = openai_client.upload_training_file(sample_training_data)

        assert result.file_id.startswith("file-")
        assert result.purpose == "fine-tune"
        assert result.bytes > 0
        assert result.status in ("processed", "pending")

        # Cleanup
        openai_client.delete_file(result.file_id)

    def test_upload_rejects_too_few_examples(self, openai_client):
        """Should reject training data with fewer than 10 examples."""
        # Only 5 examples - below OpenAI's minimum
        examples = []
        for i in range(5):
            examples.append(json.dumps({
                "messages": [
                    {"role": "user", "content": f"Q{i}"},
                    {"role": "assistant", "content": f"A{i}"},
                ]
            }))

        with pytest.raises(ValueError, match="at least 10"):
            openai_client.upload_training_file("\n".join(examples))

    def test_upload_rejects_invalid_jsonl(self, openai_client):
        """Should reject malformed JSONL data."""
        # Need at least 10 lines to pass the count check first
        invalid_lines = ["not valid json at all"] * 12
        invalid_data = "\n".join(invalid_lines)

        with pytest.raises(ValueError, match="Invalid JSON"):
            openai_client.upload_training_file(invalid_data)

    def test_upload_rejects_missing_messages(self, openai_client):
        """Should reject examples without 'messages' field."""
        invalid_data = "\n".join([
            json.dumps({"prompt": "Q", "response": "A"})  # Wrong format
            for _ in range(12)
        ])

        with pytest.raises(ValueError, match="Missing 'messages' field"):
            openai_client.upload_training_file(invalid_data)


class TestJobOperations:
    """Test fine-tuning job operations.

    Note: Creating actual fine-tuning jobs incurs costs. These tests
    verify job creation and immediate cancellation to minimize costs.
    """

    def test_list_jobs(self, openai_client):
        """Should list existing fine-tuning jobs."""
        jobs = openai_client.list_jobs(limit=5)

        # Should return a list (may be empty if no previous jobs)
        assert isinstance(jobs, list)
        for job in jobs:
            assert job.job_id
            assert job.model
            assert job.status

    @pytest.mark.slow
    def test_create_and_cancel_job(self, openai_client, uploaded_file):
        """Should create a fine-tuning job and cancel it immediately.

        This test creates a real job (costs apply) but cancels immediately
        to minimize charges. Use sparingly.
        """
        from mdnt.clients.openai import OpenAIFineTuningStatus

        # Create job
        job = openai_client.create_job(
            training_file=uploaded_file,
            model="gpt-4o-mini-2024-07-18",
            suffix="mdnt-test",
        )

        assert job.job_id.startswith("ftjob-")
        assert job.status in [
            OpenAIFineTuningStatus.VALIDATING_FILES,
            OpenAIFineTuningStatus.QUEUED,
            OpenAIFineTuningStatus.RUNNING,
        ]

        # Cancel immediately to avoid costs
        cancelled = openai_client.cancel_job(job.job_id)
        assert cancelled.status == OpenAIFineTuningStatus.CANCELLED

    def test_get_nonexistent_job(self, openai_client):
        """Should handle nonexistent job gracefully."""
        # OpenAI will raise an error for invalid job ID
        with pytest.raises(Exception):  # openai.NotFoundError
            openai_client.get_job("ftjob-nonexistent123")


class TestConvertToOpenAIFormat:
    """Test the format conversion utility."""

    def test_convert_basic_examples(self):
        """Should convert prompt/response pairs to OpenAI format."""
        from mdnt.clients.openai import convert_to_openai_format

        examples = [
            {"prompt": "How do I X?", "response": "You should Y."},
            {"prompt": "What about Z?", "response": "Z is important."},
        ]

        result = convert_to_openai_format(examples)
        lines = result.strip().split("\n")

        assert len(lines) == 2

        for line in lines:
            obj = json.loads(line)
            assert "messages" in obj
            assert len(obj["messages"]) == 3  # system, user, assistant
            assert obj["messages"][0]["role"] == "system"
            assert obj["messages"][1]["role"] == "user"
            assert obj["messages"][2]["role"] == "assistant"

    def test_convert_with_custom_system_prompt(self):
        """Should use custom system prompt when provided."""
        from mdnt.clients.openai import convert_to_openai_format

        examples = [{"prompt": "Q", "response": "A"}]
        custom_system = "You are a specialized assistant."

        result = convert_to_openai_format(examples, system_prompt=custom_system)
        obj = json.loads(result)

        assert obj["messages"][0]["content"] == custom_system

    def test_convert_with_behavior_context(self):
        """Should include behavior context in system message."""
        from mdnt.clients.openai import convert_to_openai_format

        examples = [{
            "prompt": "How do I log?",
            "response": "Use Raze.",
            "behaviors": ["behavior_use_raze_for_logging"],
        }]

        result = convert_to_openai_format(examples)
        obj = json.loads(result)

        system_content = obj["messages"][0]["content"]
        assert "behavior_use_raze_for_logging" in system_content

    def test_convert_skips_empty_examples(self):
        """Should skip examples with empty prompt or response."""
        from mdnt.clients.openai import convert_to_openai_format

        examples = [
            {"prompt": "Valid", "response": "Valid"},
            {"prompt": "", "response": "Missing prompt"},
            {"prompt": "Missing response", "response": ""},
        ]

        result = convert_to_openai_format(examples)
        lines = result.strip().split("\n")

        assert len(lines) == 1  # Only the valid one


class TestMidnighterServiceWithOpenAI:
    """Test MidnighterService with real OpenAI backend.

    These tests use the full service but with real OpenAI calls.
    """

    @pytest.fixture
    def service(self):
        """Create MidnighterService with OpenAI backend."""
        from mdnt import MidnighterService

        # Don't use simulation - use real OpenAI backend
        return MidnighterService(backend="openai")

    def test_export_corpus_for_openai(self, service):
        """Should export corpus in OpenAI-compatible JSONL format."""
        corpus = service.create_corpus(
            name="openai-export-test",
            description="Test corpus for OpenAI format export",
            source_data=[
                {"prompt": f"Question {i}", "response": f"Answer {i}"}
                for i in range(15)
            ],
        )

        # Export as JSONL
        jsonl_data = service.export_corpus(corpus.corpus_id, format="jsonl")

        # Verify it's valid for OpenAI
        lines = jsonl_data.strip().split("\n")
        assert len(lines) >= 10  # OpenAI minimum

        for line in lines:
            obj = json.loads(line)
            assert "messages" in obj
