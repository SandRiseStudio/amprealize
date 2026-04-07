"""Tests for data models."""

import pytest
from datetime import datetime

from mdnt.models import (
    TrainingStatus,
    ModelType,
    TrainingCorpus,
    TrainingExample,
    TrainingJob,
    TrainingJobRequest,
    GenerateCorpusRequest,
    TrainingMetrics,
    ModelRegistry,
    EvaluationResult,
    generate_corpus_id,
    generate_example_id,
    generate_job_id,
)


class TestTrainingStatus:
    """Test TrainingStatus enum."""

    def test_status_values(self):
        """Verify all expected status values exist."""
        assert TrainingStatus.QUEUED.value == "queued"
        assert TrainingStatus.TRAINING.value == "training"
        assert TrainingStatus.COMPLETED.value == "completed"
        assert TrainingStatus.FAILED.value == "failed"
        assert TrainingStatus.CANCELLED.value == "cancelled"


class TestTrainingExample:
    """Test TrainingExample model."""

    def test_create_example(self):
        """Test creating a training example."""
        example = TrainingExample(
            example_id="ex_123",
            corpus_id="corpus_456",
            prompt="How do I use X?",
            response="You should do Y.",
            behaviors_used=["behavior_use_x"],
            citation_count=1,
            quality_metrics={"overall": 0.85},
            token_count=25,
            created_at=datetime.utcnow(),
        )

        assert example.example_id == "ex_123"
        assert example.corpus_id == "corpus_456"
        assert example.prompt == "How do I use X?"
        assert example.quality_metrics["overall"] == 0.85
        assert example.citation_count == 1

    def test_to_dict(self):
        """Test conversion to dict."""
        example = TrainingExample(
            example_id="ex",
            corpus_id="c",
            prompt="Q",
            response="A",
            behaviors_used=["behavior_test"],
            citation_count=0,
            quality_metrics={},
            token_count=10,
            created_at=datetime.utcnow(),
        )

        d = example.to_dict()
        assert d["example_id"] == "ex"
        assert d["prompt"] == "Q"
        assert "created_at" in d


class TestTrainingCorpus:
    """Test TrainingCorpus model."""

    def test_create_corpus(self):
        """Test creating a training corpus."""
        corpus = TrainingCorpus(
            corpus_id="corpus_123",
            name="my-corpus",
            description="A test corpus",
            created_at=datetime.utcnow(),
            total_examples=100,
            example_types=["behavior_conditioned", "general"],
            quality_score=0.9,
        )

        assert corpus.corpus_id == "corpus_123"
        assert corpus.name == "my-corpus"
        assert corpus.total_examples == 100
        assert len(corpus.example_types) == 2

    def test_to_dict(self):
        """Test conversion to dict."""
        corpus = TrainingCorpus(
            corpus_id="c",
            name="n",
            description="d",
            created_at=datetime.utcnow(),
            total_examples=0,
            example_types=[],
            quality_score=0.0,
        )

        d = corpus.to_dict()
        assert d["corpus_id"] == "c"
        assert d["name"] == "n"


class TestTrainingJob:
    """Test TrainingJob model."""

    def test_create_job(self):
        """Test creating a training job."""
        request = TrainingJobRequest(
            model_id="my-model",
            base_model="gpt-4o-mini",
            training_corpus_id="corpus_123",
            training_config={"epochs": 3},
        )

        job = TrainingJob(
            job_id="job_456",
            request=request,
            status=TrainingStatus.QUEUED,
            progress=0.0,
            current_epoch=0,
            total_epochs=3,
            loss_history=[],
            created_at=datetime.utcnow(),
        )

        assert job.job_id == "job_456"
        assert job.status == TrainingStatus.QUEUED
        assert job.request.model_id == "my-model"
        assert job.progress == 0.0

    def test_job_completion(self):
        """Test completed job state."""
        request = TrainingJobRequest(
            model_id="m",
            base_model="base",
            training_corpus_id="c",
            training_config={},
        )

        job = TrainingJob(
            job_id="j",
            request=request,
            status=TrainingStatus.COMPLETED,
            progress=1.0,
            current_epoch=3,
            total_epochs=3,
            loss_history=[0.5, 0.3, 0.1],
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            backend_job_id="ft:abc123",
        )

        assert job.status == TrainingStatus.COMPLETED
        assert job.progress == 1.0
        assert job.backend_job_id == "ft:abc123"


class TestModelRegistry:
    """Test ModelRegistry model."""

    def test_create_registry_entry(self):
        """Test creating a model registry entry."""
        model = ModelRegistry(
            model_id="my-model-v1",
            base_model="gpt-4o-mini",
            training_corpus_id="corpus_123",
            training_config={"epochs": 3},
            checkpoint_path="ft:gpt-4o-mini:org:my-model:abc123",
            metrics={"loss": 0.05, "accuracy": 0.98},
            created_at=datetime.utcnow(),
            status=TrainingStatus.COMPLETED,
        )

        assert model.model_id == "my-model-v1"
        assert model.checkpoint_path.startswith("ft:")
        assert model.metrics["accuracy"] == 0.98


class TestGenerateCorpusRequest:
    """Test GenerateCorpusRequest model."""

    def test_create_request(self):
        """Test creating a corpus generation request."""
        request = GenerateCorpusRequest(
            name="generated-corpus",
            description="A test corpus",
            behavior_ids=["behavior_a", "behavior_b"],
            sample_count=500,
            include_citations=True,
        )

        assert request.name == "generated-corpus"
        assert len(request.behavior_ids) == 2
        assert request.sample_count == 500
        assert request.include_citations is True

    def test_defaults(self):
        """Test default values."""
        request = GenerateCorpusRequest(
            name="test",
            description="test desc",
            behavior_ids=["b"],
        )

        assert request.sample_count == 1000
        assert request.include_citations is True


class TestEvaluationResult:
    """Test EvaluationResult model."""

    def test_create_result(self):
        """Test creating an evaluation result."""
        result = EvaluationResult(
            evaluation_id="eval_123",
            model_id="m",
            test_dataset="test_corpus",
            metrics={
                "accuracy": 0.95,
                "behavior_adherence": 0.92,
                "token_reduction": 0.35,
            },
            baseline_comparison={"accuracy_improvement": 0.1},
            created_at=datetime.utcnow(),
        )

        assert result.model_id == "m"
        assert result.metrics["token_reduction"] == 0.35


class TestIdGenerators:
    """Test ID generator functions."""

    def test_generate_corpus_id(self):
        """Generate unique corpus IDs."""
        id1 = generate_corpus_id()
        id2 = generate_corpus_id()
        assert id1 != id2

    def test_generate_example_id(self):
        """Generate unique example IDs."""
        id1 = generate_example_id()
        id2 = generate_example_id()
        assert id1 != id2

    def test_generate_job_id(self):
        """Generate unique job IDs."""
        id1 = generate_job_id()
        id2 = generate_job_id()
        assert id1 != id2
