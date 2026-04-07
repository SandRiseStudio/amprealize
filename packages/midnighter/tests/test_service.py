"""Tests for Midnighter service."""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch
from typing import Any, Dict, List

from mdnt import MidnighterService, MidnighterHooks, TrainingStatus


def make_training_data(count: int = 15) -> List[Dict[str, Any]]:
    """Create sufficient training data for OpenAI (min 10 examples)."""
    return [{"prompt": f"Question {i}", "response": f"Answer {i}"} for i in range(count)]


class TestMidnighterHooks:
    """Test hooks configuration."""

    def test_default_hooks(self):
        """Default hooks should return sensible defaults."""
        hooks = MidnighterHooks()

        # Default get_behavior returns None
        assert hooks.get_behavior("any") is None

        # Default on_metric doesn't raise
        hooks.on_metric("test", {"key": "value"})

    def test_custom_get_behavior(self):
        """Custom get_behavior hook should be called."""
        mock_behavior = {"behavior_id": "test_behavior", "name": "Test"}

        hooks = MidnighterHooks(
            get_behavior=lambda bid: mock_behavior if bid == "test_behavior" else None
        )

        assert hooks.get_behavior("test_behavior") == mock_behavior
        assert hooks.get_behavior("other") is None

    def test_custom_on_metric(self):
        """Custom on_metric hook should be called."""
        metrics = []

        hooks = MidnighterHooks(
            on_metric=lambda t, d: metrics.append((t, d))
        )

        hooks.on_metric("test_event", {"foo": "bar"})
        assert len(metrics) == 1
        assert metrics[0][0] == "test_event"
        assert metrics[0][1] == {"foo": "bar"}

    def test_validate_warns_on_missing(self):
        """Validation should warn about missing hooks."""
        hooks = MidnighterHooks()
        warnings = hooks.validate()

        # Should warn about get_behavior
        assert any("get_behavior" in w for w in warnings)


class TestMidnighterService:
    """Test MidnighterService core functionality."""

    @pytest.fixture
    def mock_hooks(self) -> MidnighterHooks:
        """Create mock hooks."""
        behaviors = {
            "behavior_test": {
                "behavior_id": "behavior_test",
                "name": "Test Behavior",
                "versions": [{"instruction": "Do the thing correctly"}],
            }
        }
        return MidnighterHooks(
            get_behavior=lambda bid: behaviors.get(bid),
            on_metric=Mock(),
        )

    @pytest.fixture
    def service(self, mock_hooks: MidnighterHooks) -> MidnighterService:
        """Create test service."""
        return MidnighterService(
            hooks=mock_hooks,
            backend="simulation",  # Use simulation backend for tests
            models_dir="/tmp/mdnt_test_models",
        )

    def test_create_corpus(self, service: MidnighterService):
        """Test creating a training corpus."""
        source_data = [
            {"prompt": "How do I X?", "response": "You should Y.", "quality_score": 0.8},
            {"prompt": "What about Z?", "response": "Z is important.", "quality_score": 0.9},
        ]

        corpus = service.create_corpus(
            name="test-corpus",
            description="A test corpus",
            source_data=source_data,
            quality_threshold=0.7,
        )

        assert corpus.corpus_id  # Valid UUID
        assert corpus.name == "test-corpus"
        assert corpus.total_examples == 2
        assert corpus.quality_score > 0

    def test_create_corpus_filters_by_quality(self, service: MidnighterService):
        """Quality threshold should filter examples."""
        source_data = [
            {"prompt": "Good", "response": "Yes", "quality_score": 0.9},
            {"prompt": "Bad", "response": "No", "quality_score": 0.3},
        ]

        corpus = service.create_corpus(
            name="filtered",
            description="",
            source_data=source_data,
            quality_threshold=0.5,
        )

        assert corpus.total_examples == 1  # Only the good one

    def test_get_corpus(self, service: MidnighterService):
        """Test retrieving a corpus."""
        corpus = service.create_corpus(
            name="test",
            description="",
            source_data=[{"prompt": "Q", "response": "A"}],
        )

        retrieved = service.get_corpus(corpus.corpus_id)
        assert retrieved is not None
        assert retrieved.name == "test"

        # Non-existent corpus
        assert service.get_corpus("corpus_nonexistent") is None

    def test_list_corpora(self, service: MidnighterService):
        """Test listing corpora."""
        assert len(service.list_corpora()) == 0

        service.create_corpus(name="c1", description="", source_data=[])
        service.create_corpus(name="c2", description="", source_data=[])

        corpora = service.list_corpora()
        assert len(corpora) == 2

    def test_generate_corpus_from_behaviors(self, service: MidnighterService):
        """Test generating corpus from behavior data."""
        corpus = service.generate_corpus_from_behaviors(
            name="generated-corpus",
            behavior_ids=["behavior_test"],
            sample_count=5,
            include_citations=True,
        )

        assert corpus.corpus_id  # Valid UUID
        assert corpus.total_examples > 0
        assert "behavior_conditioned" in corpus.example_types

    def test_generate_corpus_requires_behaviors(self, service: MidnighterService):
        """Generating corpus without behaviors should fail."""
        with pytest.raises(ValueError, match="(?i)at least one behavior_id"):
            service.generate_corpus_from_behaviors(
                name="empty",
                behavior_ids=[],
                sample_count=10,
            )

    def test_start_training_job(self, service: MidnighterService):
        """Test starting a training job."""
        # Create corpus first
        corpus = service.create_corpus(
            name="train-corpus",
            description="",
            source_data=[{"prompt": f"Q{i}", "response": f"A{i}"} for i in range(20)],
        )

        job = service.start_training_job(
            model_id="test-model",
            base_model="gpt-4o-mini",
            corpus_id=corpus.corpus_id,
        )

        assert job.job_id  # Valid UUID
        assert job.request.model_id == "test-model"
        assert job.status in [TrainingStatus.QUEUED, TrainingStatus.TRAINING]

    def test_start_training_invalid_corpus(self, service: MidnighterService):
        """Training with invalid corpus should fail."""
        with pytest.raises(ValueError, match="not found"):
            service.start_training_job(
                model_id="model",
                base_model="gpt-4o-mini",
                corpus_id="corpus_nonexistent",
            )

    def test_start_training_insufficient_examples(self, service: MidnighterService):
        """Training with too few examples should fail with clear error."""
        corpus = service.create_corpus(
            name="small-corpus",
            description="",
            source_data=[{"prompt": "Q", "response": "A"}],  # Only 1 example
        )

        with pytest.raises(ValueError, match="at least 10"):
            service.start_training_job(
                model_id="model",
                base_model="gpt-4o-mini",
                corpus_id=corpus.corpus_id,
            )

    def test_get_job(self, service: MidnighterService):
        """Test retrieving job status."""
        corpus = service.create_corpus(
            name="c",
            description="",
            source_data=make_training_data(15),  # Need 10+ for OpenAI
        )

        job = service.start_training_job(
            model_id="m",
            base_model="gpt-4o-mini",
            corpus_id=corpus.corpus_id,
        )

        retrieved = service.get_job(job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id

        # Non-existent job
        assert service.get_job("job_nonexistent") is None

    def test_cancel_job(self, service: MidnighterService):
        """Test cancelling a training job."""
        corpus = service.create_corpus(
            name="c",
            description="",
            source_data=make_training_data(15),  # Need 10+ for OpenAI
        )

        job = service.start_training_job(
            model_id="m",
            base_model="gpt-4o-mini",
            corpus_id=corpus.corpus_id,
        )

        # Cancel before completion
        if job.status in [TrainingStatus.QUEUED, TrainingStatus.TRAINING]:
            success = service.cancel_job(job.job_id)
            assert success

            retrieved = service.get_job(job.job_id)
            assert retrieved.status == TrainingStatus.CANCELLED

    def test_list_jobs(self, service: MidnighterService):
        """Test listing jobs."""
        assert len(service.list_jobs()) == 0

        corpus = service.create_corpus(
            name="c",
            description="",
            source_data=make_training_data(15),  # Need 10+ for OpenAI
        )

        service.start_training_job(model_id="m1", base_model="test", corpus_id=corpus.corpus_id)
        service.start_training_job(model_id="m2", base_model="test", corpus_id=corpus.corpus_id)

        jobs = service.list_jobs()
        assert len(jobs) == 2

    def test_model_registry(self, service: MidnighterService):
        """Test model registry operations."""
        from mdnt.models import ModelRegistry

        model = ModelRegistry(
            model_id="my-model",
            base_model="gpt-4o-mini",
            training_corpus_id="corpus_123",
            training_config={},
            checkpoint_path="/path/to/checkpoint",
            metrics={"loss": 0.1},
            created_at=datetime.utcnow(),
            status=TrainingStatus.COMPLETED,
        )

        service.register_model(model)

        retrieved = service.get_model("my-model")
        assert retrieved is not None
        assert retrieved.base_model == "gpt-4o-mini"

        models = service.list_models()
        assert len(models) == 1

    def test_metrics_emitted(self, service: MidnighterService, mock_hooks: MidnighterHooks):
        """Test that metrics are emitted via hooks."""
        service.create_corpus(
            name="test",
            description="",
            source_data=[{"prompt": "Q", "response": "A"}],
        )

        # Check that on_metric was called
        mock_hooks.on_metric.assert_called()


class TestExportCorpus:
    """Test corpus export functionality."""

    @pytest.fixture
    def service(self) -> MidnighterService:
        return MidnighterService(backend="simulation")

    def test_export_corpus_jsonl(self, service: MidnighterService):
        """Test exporting corpus as JSONL."""
        corpus = service.create_corpus(
            name="export-test",
            description="",
            source_data=[
                {"prompt": "Q1", "response": "A1"},
                {"prompt": "Q2", "response": "A2"},
            ],
        )

        data = service.export_corpus(corpus.corpus_id, format="jsonl")
        assert data  # Not empty

    def test_export_nonexistent_corpus(self, service: MidnighterService):
        """Exporting non-existent corpus should fail."""
        with pytest.raises(ValueError, match="No examples found"):
            service.export_corpus("corpus_nonexistent")


class TestQualityScoring:
    """Test example quality scoring."""

    def test_score_example_quality(self):
        service = MidnighterService(backend="simulation")

        # Good example with citation
        scores = service._score_example_quality(
            prompt="How do I use the behavior?",
            response="Following `behavior_test` (Student): Here's how to use it. First, you should...",
            behavior_id="behavior_test",
        )

        assert "overall_score" in scores
        assert scores["overall_score"] > 0.5
        assert scores["citation_quality"] == 1.0  # Has citation

    def test_score_example_without_citation(self):
        service = MidnighterService(backend="simulation")

        scores = service._score_example_quality(
            prompt="Question",
            response="Answer without any behavior mention.",
            behavior_id="behavior_test",
        )

        assert scores["citation_quality"] < 1.0
