"""Midnighter (mdnt) - Behavior-Conditioned Supervised Fine-Tuning library.

Implements BC-SFT methodology for training LLMs with procedural knowledge.
Supports OpenAI Fine-Tuning API and local PyTorch/Transformers backends.

Example:
    from mdnt import MidnighterService, MidnighterHooks

    service = MidnighterService(
        hooks=MidnighterHooks(
            get_behavior=lambda id: my_store.get(id),
        ),
        backend="openai"
    )

    corpus = service.generate_corpus_from_behaviors(
        name="my-corpus",
        behavior_ids=["behavior_x", "behavior_y"],
        sample_count=100
    )

    job = service.start_training_job(
        model_id="my-model",
        base_model="gpt-4o-mini",
        corpus_id=corpus.corpus_id
    )
"""

from .models import (
    TrainingStatus,
    ModelType,
    TrainingCorpus,
    TrainingExample,
    ModelRegistry,
    EvaluationResult,
    CreateCorpusRequest,
    TrainingJobRequest,
    GenerateCorpusRequest,
    TrainingJob,
    TrainingMetrics,
)
from .hooks import MidnighterHooks
from .service import MidnighterService

__version__ = "0.1.0"
__all__ = [
    # Core service
    "MidnighterService",
    "MidnighterHooks",
    # Models
    "TrainingStatus",
    "ModelType",
    "TrainingCorpus",
    "TrainingExample",
    "ModelRegistry",
    "EvaluationResult",
    "CreateCorpusRequest",
    "TrainingJobRequest",
    "GenerateCorpusRequest",
    "TrainingJob",
    "TrainingMetrics",
]
