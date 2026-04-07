"""Data models for Midnighter BC-SFT training pipeline.

These models are standalone with no external dependencies beyond pydantic.
They define the core data structures for:
- Training corpora and examples
- Training jobs and metrics
- Model registry entries
- Request/response contracts
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class TrainingStatus(str, Enum):
    """Training job status."""
    PENDING = "pending"
    QUEUED = "queued"
    TRAINING = "training"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ModelType(str, Enum):
    """Supported base model types for fine-tuning.

    OpenAI models:
    - GPT_4O_MINI: gpt-4o-mini-2024-07-18 (recommended, cost-effective)
    - GPT_4O: gpt-4o-2024-08-06 (highest quality)

    Local models (experimental):
    - LLAMA_3_1_8B: Meta Llama 3.1 8B
    - QWEN_2_5_14B: Alibaba Qwen 2.5 14B
    - QWEN_2_5_32B: Alibaba Qwen 2.5 32B
    - QWEN_3_14B: Alibaba Qwen 3 14B
    """
    # OpenAI models
    GPT_4O_MINI = "gpt-4o-mini-2024-07-18"
    GPT_4O = "gpt-4o-2024-08-06"
    GPT_4 = "gpt-4-0613"
    GPT_35_TURBO = "gpt-3.5-turbo-0125"

    # Local models (experimental)
    LLAMA_3_1_8B = "llama-3.1-8b"
    QWEN_2_5_14B = "qwen2.5-14b"
    QWEN_2_5_32B = "qwen2.5-32b"
    QWEN_3_14B = "qwen3-14b"


@dataclass(frozen=True)
class TrainingCorpus:
    """Training corpus containing behavior-conditioned examples."""
    corpus_id: str
    name: str
    description: str
    created_at: datetime
    total_examples: int
    example_types: List[str]
    quality_score: float
    usage_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "total_examples": self.total_examples,
            "example_types": self.example_types,
            "quality_score": self.quality_score,
            "usage_count": self.usage_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingCorpus":
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            corpus_id=data["corpus_id"],
            name=data["name"],
            description=data["description"],
            created_at=created_at,
            total_examples=data["total_examples"],
            example_types=data["example_types"],
            quality_score=data["quality_score"],
            usage_count=data.get("usage_count", 0),
        )


@dataclass(frozen=True)
class TrainingExample:
    """Single training example in BC-SFT format."""
    example_id: str
    corpus_id: str
    prompt: str
    response: str
    behaviors_used: List[str]
    citation_count: int
    quality_metrics: Dict[str, float]
    token_count: int
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "example_id": self.example_id,
            "corpus_id": self.corpus_id,
            "prompt": self.prompt,
            "response": self.response,
            "behaviors_used": self.behaviors_used,
            "citation_count": self.citation_count,
            "quality_metrics": self.quality_metrics,
            "token_count": self.token_count,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingExample":
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            example_id=data["example_id"],
            corpus_id=data["corpus_id"],
            prompt=data["prompt"],
            response=data["response"],
            behaviors_used=data["behaviors_used"],
            citation_count=data["citation_count"],
            quality_metrics=data["quality_metrics"],
            token_count=data["token_count"],
            created_at=created_at,
        )


@dataclass(frozen=True)
class ModelRegistry:
    """Model registry entry for fine-tuned models."""
    model_id: str
    base_model: str  # Changed from ModelType to str for flexibility
    training_corpus_id: str
    training_config: Dict[str, Any]
    checkpoint_path: Optional[str]
    metrics: Dict[str, float]
    created_at: datetime
    status: TrainingStatus
    deployment_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "base_model": self.base_model,
            "training_corpus_id": self.training_corpus_id,
            "training_config": self.training_config,
            "checkpoint_path": self.checkpoint_path,
            "metrics": self.metrics,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "deployment_url": self.deployment_url,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelRegistry":
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            model_id=data["model_id"],
            base_model=data["base_model"],
            training_corpus_id=data["training_corpus_id"],
            training_config=data["training_config"],
            checkpoint_path=data.get("checkpoint_path"),
            metrics=data["metrics"],
            created_at=created_at,
            status=TrainingStatus(data["status"]),
            deployment_url=data.get("deployment_url"),
        )


@dataclass(frozen=True)
class EvaluationResult:
    """Model evaluation result after fine-tuning."""
    evaluation_id: str
    model_id: str
    test_dataset: str
    metrics: Dict[str, float]
    baseline_comparison: Dict[str, float]
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "model_id": self.model_id,
            "test_dataset": self.test_dataset,
            "metrics": self.metrics,
            "baseline_comparison": self.baseline_comparison,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class CreateCorpusRequest:
    """Request to create a new training corpus."""
    name: str
    description: str
    source_data: List[Dict[str, Any]]
    behavior_filter: Optional[List[str]] = None
    quality_threshold: float = 0.7
    example_types: Optional[List[str]] = None


@dataclass(frozen=True)
class TrainingJobRequest:
    """Request to start a fine-tuning job."""
    model_id: str
    base_model: str  # Model name or ModelType value
    training_corpus_id: str
    training_config: Dict[str, Any]
    validation_split: float = 0.1
    hyperparameters: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class GenerateCorpusRequest:
    """Request to generate training corpus from behavior data."""
    name: str
    description: str
    behavior_ids: List[str]
    sample_count: int = 1000
    include_citations: bool = True
    quality_filter: bool = True


@dataclass
class TrainingJob:
    """Training job tracking and status."""
    job_id: str
    request: TrainingJobRequest
    status: TrainingStatus
    progress: float
    current_epoch: int
    total_epochs: int
    loss_history: List[float]
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    backend_job_id: Optional[str] = None  # OpenAI job ID or local run ID

    def to_dict(self) -> Dict[str, Any]:
        request_dict = {
            "model_id": self.request.model_id,
            "base_model": self.request.base_model,
            "training_corpus_id": self.request.training_corpus_id,
            "training_config": self.request.training_config,
            "validation_split": self.request.validation_split,
            "hyperparameters": self.request.hyperparameters,
        }
        return {
            "job_id": self.job_id,
            "request": request_dict,
            "status": self.status.value,
            "progress": self.progress,
            "current_epoch": self.current_epoch,
            "total_epochs": self.total_epochs,
            "loss_history": self.loss_history,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "backend_job_id": self.backend_job_id,
        }


@dataclass(frozen=True)
class TrainingMetrics:
    """Real-time training metrics during fine-tuning."""
    job_id: str
    epoch: int
    step: int
    learning_rate: float
    loss: float
    accuracy: float
    token_count: int
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "epoch": self.epoch,
            "step": self.step,
            "learning_rate": self.learning_rate,
            "loss": self.loss,
            "accuracy": self.accuracy,
            "token_count": self.token_count,
            "timestamp": self.timestamp.isoformat(),
        }


# Utility functions
def generate_corpus_id() -> str:
    """Generate a unique corpus ID."""
    return str(uuid.uuid4())


def generate_example_id() -> str:
    """Generate a unique example ID."""
    return str(uuid.uuid4())


def generate_job_id() -> str:
    """Generate a unique job ID."""
    return str(uuid.uuid4())


def generate_model_id(base_model: str, suffix: str = "") -> str:
    """Generate a unique model ID."""
    base = base_model.split("/")[-1].split("-")[0]  # Extract base name
    short_uuid = str(uuid.uuid4())[:8]
    if suffix:
        return f"{base}-{suffix}-{short_uuid}"
    return f"{base}-{short_uuid}"
