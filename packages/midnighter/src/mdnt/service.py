"""MidnighterService - BC-SFT training pipeline implementation.

Supports two training backends:
1. OpenAI Fine-Tuning API (managed, recommended for production)
2. Local PyTorch/Transformers (requires GPU, experimental)

Example:
    from mdnt import MidnighterService, MidnighterHooks

    service = MidnighterService(
        hooks=MidnighterHooks(
            get_behavior=my_behavior_store.get,
            on_metric=my_telemetry.emit,
        ),
        backend="openai"
    )

    corpus = service.generate_corpus_from_behaviors(
        name="my-corpus",
        behavior_ids=["behavior_x"],
        sample_count=100
    )

    job = service.start_training_job(
        model_id="my-model",
        base_model="gpt-4o-mini",
        corpus_id=corpus.corpus_id
    )
"""

from __future__ import annotations
from datetime import datetime
import json
import logging
import os
import uuid
from typing import Any, Callable, Dict, List, Optional

from .models import (
    TrainingStatus,
    TrainingCorpus,
    TrainingExample,
    ModelRegistry,
    CreateCorpusRequest,
    TrainingJobRequest,
    GenerateCorpusRequest,
    TrainingJob,
    TrainingMetrics,
    generate_corpus_id,
    generate_example_id,
    generate_job_id,
)
from .hooks import MidnighterHooks

logger = logging.getLogger(__name__)

# Check for backend availability
try:
    from .clients.openai import (
        OpenAIFineTuningClient,
        OpenAIFineTuningJob,
        OpenAIFineTuningStatus,
        convert_to_openai_format,
        OPENAI_AVAILABLE,
    )
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAIFineTuningClient = None  # type: ignore

try:
    from .clients.local import (
        LocalTrainer,
        LocalTrainingConfig,
        LocalTrainingJob,
        convert_to_local_format,
        LOCAL_AVAILABLE,
    )
except ImportError:
    LOCAL_AVAILABLE = False
    LocalTrainer = None  # type: ignore


class MidnighterService:
    """BC-SFT training pipeline for behavior-conditioned model fine-tuning.

    Supports two backends:
    1. OpenAI Fine-Tuning API (managed, no GPU required)
    2. Local PyTorch/Transformers (experimental, requires GPU)

    Configuration via environment variables:
    - MDNT_BACKEND: "openai" (default) or "local"
    - OPENAI_API_KEY: Required for OpenAI backend
    - MDNT_MODELS_DIR: Directory for local model checkpoints

    Example:
        # With hooks for full integration
        service = MidnighterService(
            hooks=MidnighterHooks(
                get_behavior=behavior_service.get,
                on_metric=telemetry.emit_event,
            ),
            backend="openai"
        )

        # Generate corpus from behaviors
        corpus = service.generate_corpus_from_behaviors(
            name="my-corpus",
            behavior_ids=["behavior_x", "behavior_y"],
            sample_count=100
        )

        # Start training
        job = service.start_training_job(
            model_id="my-model",
            base_model="gpt-4o-mini",
            corpus_id=corpus.corpus_id
        )
    """

    def __init__(
        self,
        hooks: Optional[MidnighterHooks] = None,
        backend: Optional[str] = None,
        models_dir: str = "./models",
        openai_client: Optional["OpenAIFineTuningClient"] = None,
        local_trainer: Optional["LocalTrainer"] = None,
    ) -> None:
        """Initialize MidnighterService.

        Args:
            hooks: Integration hooks for behavior retrieval, metrics, etc.
            backend: "openai" or "local" (defaults to MDNT_BACKEND env var)
            models_dir: Directory for local model checkpoints
            openai_client: Pre-configured OpenAI client (optional)
            local_trainer: Pre-configured local trainer (optional)
        """
        self._hooks = hooks or MidnighterHooks()
        self._models_dir = models_dir
        self._backend = backend or os.getenv("MDNT_BACKEND", "openai")

        # Storage (in-memory, override for persistence)
        self._training_jobs: Dict[str, TrainingJob] = {}
        self._corpora: Dict[str, TrainingCorpus] = {}
        self._model_registry: Dict[str, ModelRegistry] = {}
        self._training_examples: Dict[str, TrainingExample] = {}

        # Backend clients
        self._openai_client = openai_client
        self._local_trainer = local_trainer
        self._openai_job_mapping: Dict[str, str] = {}  # job_id -> openai_job_id

        # Ensure models directory exists
        os.makedirs(self._models_dir, exist_ok=True)

        # Validate backend availability
        if self._backend == "openai" and not OPENAI_AVAILABLE:
            logger.warning(
                "OpenAI backend selected but not available. "
                "Install: pip install midnighter[openai]"
            )
        elif self._backend == "local" and not LOCAL_AVAILABLE:
            logger.warning(
                "Local backend selected but not available. "
                "Install: pip install midnighter[local]"
            )

        # Validate hooks
        warnings = self._hooks.validate()
        for warning in warnings:
            logger.warning(warning)

        logger.info(
            "MidnighterService initialized (backend=%s, models_dir=%s)",
            self._backend, self._models_dir
        )

    # =========================================================================
    # Corpus Management
    # =========================================================================

    def create_corpus(
        self,
        name: str,
        description: str,
        source_data: List[Dict[str, Any]],
        quality_threshold: float = 0.7,
    ) -> TrainingCorpus:
        """Create a new training corpus from source data.

        Args:
            name: Corpus name
            description: Corpus description
            source_data: List of training examples with "prompt", "response", etc.
            quality_threshold: Minimum quality score for filtering

        Returns:
            Created TrainingCorpus
        """
        corpus_id = generate_corpus_id()

        # Calculate quality metrics
        quality_scores = []
        example_types = set()

        for item in source_data:
            if "quality_score" in item:
                quality_scores.append(item["quality_score"])
            if "example_type" in item:
                example_types.add(item["example_type"])

        # Filter by quality threshold
        if quality_scores:
            filtered_items = [
                item for item, score in zip(source_data, quality_scores)
                if score >= quality_threshold
            ]
        else:
            filtered_items = source_data

        quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

        corpus = TrainingCorpus(
            corpus_id=corpus_id,
            name=name,
            description=description,
            created_at=datetime.utcnow(),
            total_examples=len(filtered_items),
            example_types=list(example_types) if example_types else ["general"],
            quality_score=quality_score,
        )

        self._corpora[corpus_id] = corpus

        # Store training examples
        self._store_corpus_examples(corpus_id, filtered_items)

        self._emit_metric("corpus_created", {
            "corpus_id": corpus_id,
            "total_examples": len(filtered_items),
            "quality_score": quality_score,
        })

        return corpus

    def generate_corpus_from_behaviors(
        self,
        name: str,
        description: str = "",
        behavior_ids: Optional[List[str]] = None,
        sample_count: int = 100,
        include_citations: bool = True,
        quality_filter: bool = True,
    ) -> TrainingCorpus:
        """Generate training corpus from behavior data using hooks.

        Args:
            name: Corpus name
            description: Corpus description
            behavior_ids: List of behavior IDs to generate examples for
            sample_count: Total number of examples to generate
            include_citations: Whether to include behavior citations in responses
            quality_filter: Whether to filter by quality score

        Returns:
            Generated TrainingCorpus

        Raises:
            ValueError: If get_behavior hook is not configured
        """
        behavior_ids = behavior_ids or []

        if not behavior_ids:
            raise ValueError("At least one behavior_id is required")

        corpus_id = generate_corpus_id()
        training_examples: List[TrainingExample] = []

        # Calculate examples per behavior
        examples_per_behavior = max(1, sample_count // len(behavior_ids))

        # Track which behaviors were found vs not found
        found_behaviors = []
        missing_behaviors = []

        for behavior_id in behavior_ids:
            # Use hooks to retrieve behavior
            behavior = self._hooks.get_behavior(behavior_id)

            if not behavior:
                logger.warning(f"Behavior not found: {behavior_id}")
                missing_behaviors.append(behavior_id)
                continue

            found_behaviors.append(behavior_id)

            # Generate examples for this behavior
            examples = self._generate_examples_for_behavior(
                behavior,
                examples_per_behavior,
                include_citations=include_citations,
                corpus_id=corpus_id,
            )
            training_examples.extend(examples)

        # Validate we found at least some behaviors
        if not found_behaviors:
            raise ValueError(
                f"No behaviors found. Requested: {behavior_ids}. "
                f"Ensure BehaviorService is properly configured and behaviors exist. "
                f"Missing: {missing_behaviors}"
            )

        # Filter by quality
        pre_filter_count = len(training_examples)
        if quality_filter:
            training_examples = [
                ex for ex in training_examples
                if ex.quality_metrics.get("overall_score", 0) >= 0.7
            ]
        post_filter_count = len(training_examples)

        if post_filter_count < 10:
            logger.warning(
                f"Only {post_filter_count} examples after quality filtering "
                f"(from {pre_filter_count}). OpenAI requires at least 10."
            )

        # Calculate average quality
        quality_score = (
            sum(ex.quality_metrics.get("overall_score", 0) for ex in training_examples)
            / len(training_examples)
        ) if training_examples else 0.0

        corpus = TrainingCorpus(
            corpus_id=corpus_id,
            name=name,
            description=description or f"Generated from {len(behavior_ids)} behaviors",
            created_at=datetime.utcnow(),
            total_examples=len(training_examples),
            example_types=["behavior_conditioned"],
            quality_score=quality_score,
        )

        self._corpora[corpus_id] = corpus

        # Store examples
        for example in training_examples:
            self._training_examples[example.example_id] = example

        self._emit_metric("corpus_generated_from_behaviors", {
            "corpus_id": corpus_id,
            "behavior_count": len(behavior_ids),
            "example_count": len(training_examples),
            "quality_score": quality_score,
        })

        return corpus

    def get_corpus(self, corpus_id: str) -> Optional[TrainingCorpus]:
        """Get a training corpus by ID."""
        return self._corpora.get(corpus_id)

    def list_corpora(self) -> List[TrainingCorpus]:
        """List all training corpora."""
        return list(self._corpora.values())

    def export_corpus(self, corpus_id: str, format: str = "jsonl") -> str:
        """Export training corpus in specified format.

        Args:
            corpus_id: Corpus ID to export
            format: Export format: "jsonl" (OpenAI) or "dict" (local)

        Returns:
            Formatted corpus data
        """
        examples = [
            ex for ex in self._training_examples.values()
            if ex.corpus_id == corpus_id
        ]

        if not examples:
            raise ValueError(f"No examples found for corpus {corpus_id}")

        example_dicts = [
            {
                "prompt": ex.prompt,
                "response": ex.response,
                "behaviors": ex.behaviors_used,
            }
            for ex in examples
        ]

        if format.lower() == "jsonl":
            return convert_to_openai_format(example_dicts) if OPENAI_AVAILABLE else json.dumps(example_dicts)
        else:
            return json.dumps(example_dicts, indent=2)

    # =========================================================================
    # Training Jobs
    # =========================================================================

    def start_training_job(
        self,
        model_id: str,
        base_model: str,
        corpus_id: str,
        config: Optional[Dict[str, Any]] = None,
        validation_split: float = 0.1,
    ) -> TrainingJob:
        """Start a fine-tuning training job.

        Args:
            model_id: Unique ID for the fine-tuned model
            base_model: Base model name (e.g., "gpt-4o-mini", "llama-3.1-8b")
            corpus_id: Training corpus ID
            config: Training configuration (epochs, learning_rate, etc.)
            validation_split: Fraction of data to use for validation

        Returns:
            TrainingJob with job details

        Raises:
            ValueError: If corpus not found or has insufficient examples
        """
        if corpus_id not in self._corpora:
            raise ValueError(f"Corpus {corpus_id} not found")

        # Validate example count BEFORE starting job
        examples = [
            ex for ex in self._training_examples.values()
            if ex.corpus_id == corpus_id
        ]

        min_required = 10  # OpenAI minimum
        if len(examples) < min_required:
            raise ValueError(
                f"Corpus {corpus_id} has only {len(examples)} examples, "
                f"but OpenAI requires at least {min_required}. "
                f"Generate more examples with generate_corpus_from_behaviors() "
                f"using a higher sample_count."
            )

        job_id = generate_job_id()
        config = config or {}

        request = TrainingJobRequest(
            model_id=model_id,
            base_model=base_model,
            training_corpus_id=corpus_id,
            training_config=config,
            validation_split=validation_split,
        )

        job = TrainingJob(
            job_id=job_id,
            request=request,
            status=TrainingStatus.QUEUED,
            progress=0.0,
            current_epoch=0,
            total_epochs=config.get("epochs", 3),
            loss_history=[],
            created_at=datetime.utcnow(),
        )

        self._training_jobs[job_id] = job

        # Start training based on backend
        if self._backend == "openai" and OPENAI_AVAILABLE:
            self._start_openai_training(job)
        elif self._backend == "local" and LOCAL_AVAILABLE:
            self._start_local_training(job)
        else:
            # Fallback to simulation if no backend available
            logger.warning("No training backend available, using simulation")
            self._start_training_simulation(job)

        self._emit_metric("training_job_started", {
            "job_id": job_id,
            "model_id": model_id,
            "corpus_id": corpus_id,
            "base_model": base_model,
            "backend": self._backend,
        })

        return job

    def get_job(self, job_id: str) -> Optional[TrainingJob]:
        """Get training job status."""
        return self._training_jobs.get(job_id)

    def list_jobs(self) -> List[TrainingJob]:
        """List all training jobs."""
        return list(self._training_jobs.values())

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a training job."""
        job = self._training_jobs.get(job_id)
        if not job:
            return False

        if job.status not in [TrainingStatus.QUEUED, TrainingStatus.TRAINING]:
            return False

        # Cancel with backend
        if self._backend == "openai" and job_id in self._openai_job_mapping:
            try:
                if self._openai_client:
                    self._openai_client.cancel_job(self._openai_job_mapping[job_id])
            except Exception as e:
                logger.warning(f"Failed to cancel OpenAI job: {e}")

        job.status = TrainingStatus.CANCELLED
        self._emit_metric("training_job_cancelled", {"job_id": job_id})

        return True

    # =========================================================================
    # Model Registry
    # =========================================================================

    def get_model(self, model_id: str) -> Optional[ModelRegistry]:
        """Get a model from the registry."""
        return self._model_registry.get(model_id)

    def list_models(self) -> List[ModelRegistry]:
        """List all registered models."""
        return list(self._model_registry.values())

    def register_model(self, model: ModelRegistry) -> None:
        """Register a fine-tuned model."""
        self._model_registry[model.model_id] = model
        self._emit_metric("model_registered", {
            "model_id": model.model_id,
            "base_model": model.base_model,
            "status": model.status.value,
        })

    # =========================================================================
    # Backend-specific Training
    # =========================================================================

    def _start_openai_training(self, job: TrainingJob) -> None:
        """Start training via OpenAI API."""
        import threading

        def run_openai_training():
            job.status = TrainingStatus.TRAINING
            job.started_at = datetime.utcnow()

            try:
                # Initialize client if needed
                if not self._openai_client:
                    self._openai_client = OpenAIFineTuningClient()

                # Get training examples
                examples = [
                    ex for ex in self._training_examples.values()
                    if ex.corpus_id == job.request.training_corpus_id
                ]

                if len(examples) < self._openai_client.MIN_EXAMPLES_REQUIRED:
                    raise ValueError(
                        f"OpenAI requires at least {self._openai_client.MIN_EXAMPLES_REQUIRED} examples, "
                        f"but corpus has {len(examples)}"
                    )

                # Convert to OpenAI format
                example_dicts = [
                    {"prompt": ex.prompt, "response": ex.response, "behaviors": ex.behaviors_used}
                    for ex in examples
                ]
                jsonl_data = convert_to_openai_format(example_dicts)

                # Upload file
                training_file = self._openai_client.upload_training_file(
                    jsonl_data,
                    filename=f"mdnt_{job.job_id}.jsonl"
                )

                # Create job
                config = job.request.training_config or {}
                hyperparameters = {"n_epochs": config.get("epochs", 3)}

                openai_job = self._openai_client.create_job(
                    training_file=training_file.file_id,
                    suffix=f"mdnt-{job.request.model_id[:8]}",
                    hyperparameters=hyperparameters,
                )

                self._openai_job_mapping[job.job_id] = openai_job.job_id
                job.backend_job_id = openai_job.job_id

                # Poll for completion
                def on_progress(oai_job: OpenAIFineTuningJob):
                    if oai_job.status == OpenAIFineTuningStatus.RUNNING:
                        job.progress = 0.5
                    elif oai_job.status == OpenAIFineTuningStatus.VALIDATING_FILES:
                        job.progress = 0.1

                final_job = self._openai_client.wait_for_completion(
                    openai_job.job_id,
                    poll_interval=30.0,
                    timeout=14400.0,
                    callback=on_progress,
                )

                # Handle result
                if final_job.status == OpenAIFineTuningStatus.SUCCEEDED:
                    job.status = TrainingStatus.COMPLETED
                    job.completed_at = datetime.utcnow()
                    job.progress = 1.0

                    # Register model
                    model = ModelRegistry(
                        model_id=job.request.model_id,
                        base_model=job.request.base_model,
                        training_corpus_id=job.request.training_corpus_id,
                        training_config=job.request.training_config,
                        checkpoint_path=final_job.fine_tuned_model,
                        metrics={
                            "trained_tokens": final_job.trained_tokens,
                            "openai_job_id": final_job.job_id,
                        },
                        created_at=datetime.utcnow(),
                        status=TrainingStatus.COMPLETED,
                    )
                    self.register_model(model)

                    self._emit_metric("training_job_completed", {
                        "job_id": job.job_id,
                        "model_id": job.request.model_id,
                        "fine_tuned_model": final_job.fine_tuned_model,
                        "trained_tokens": final_job.trained_tokens,
                    })

                elif final_job.status == OpenAIFineTuningStatus.FAILED:
                    job.status = TrainingStatus.FAILED
                    job.error_message = final_job.error
                    self._emit_metric("training_job_failed", {
                        "job_id": job.job_id,
                        "error": final_job.error,
                    })

                else:
                    job.status = TrainingStatus.CANCELLED

            except Exception as e:
                logger.exception(f"OpenAI training failed: {e}")
                job.status = TrainingStatus.FAILED
                job.error_message = str(e)
                self._emit_metric("training_job_failed", {
                    "job_id": job.job_id,
                    "error": str(e),
                })

        thread = threading.Thread(
            target=run_openai_training,
            name=f"mdnt-openai-{job.job_id[:8]}",
            daemon=True,
        )
        thread.start()

    def _start_local_training(self, job: TrainingJob) -> None:
        """Start training with local PyTorch backend."""
        job.status = TrainingStatus.TRAINING
        job.started_at = datetime.utcnow()

        try:
            # Initialize trainer if needed
            if not self._local_trainer:
                self._local_trainer = LocalTrainer(models_dir=self._models_dir)

            # Get training examples
            examples = [
                {"prompt": ex.prompt, "response": ex.response, "behaviors": ex.behaviors_used}
                for ex in self._training_examples.values()
                if ex.corpus_id == job.request.training_corpus_id
            ]

            # Create config
            config = LocalTrainingConfig.from_dict(job.request.training_config or {})

            # Progress callback
            def on_progress(local_job: LocalTrainingJob):
                job.progress = local_job.progress
                job.current_epoch = local_job.current_epoch
                job.loss_history.append(local_job.loss) if local_job.loss else None

            # Start training (async)
            local_job = self._local_trainer.start_training(
                model_name=job.request.base_model,
                training_data=examples,
                config=config,
                job_id=job.job_id,
                on_progress=on_progress,
            )

            job.backend_job_id = local_job.job_id

            # Monitor in separate thread
            import threading
            import time

            def monitor_local():
                while True:
                    local_status = self._local_trainer.get_job(job.job_id)
                    if not local_status:
                        break

                    if local_status.status == "completed":
                        job.status = TrainingStatus.COMPLETED
                        job.completed_at = datetime.utcnow()
                        job.progress = 1.0

                        # Register model
                        model = ModelRegistry(
                            model_id=job.request.model_id,
                            base_model=job.request.base_model,
                            training_corpus_id=job.request.training_corpus_id,
                            training_config=job.request.training_config,
                            checkpoint_path=local_status.output_dir,
                            metrics=local_status.metrics,
                            created_at=datetime.utcnow(),
                            status=TrainingStatus.COMPLETED,
                        )
                        self.register_model(model)

                        self._emit_metric("training_job_completed", {
                            "job_id": job.job_id,
                            "model_id": job.request.model_id,
                            "output_dir": local_status.output_dir,
                        })
                        break

                    elif local_status.status == "failed":
                        job.status = TrainingStatus.FAILED
                        job.error_message = local_status.error
                        self._emit_metric("training_job_failed", {
                            "job_id": job.job_id,
                            "error": local_status.error,
                        })
                        break

                    time.sleep(5)

            thread = threading.Thread(
                target=monitor_local,
                name=f"mdnt-monitor-{job.job_id[:8]}",
                daemon=True,
            )
            thread.start()

        except Exception as e:
            logger.exception(f"Local training failed: {e}")
            job.status = TrainingStatus.FAILED
            job.error_message = str(e)

    def _start_training_simulation(self, job: TrainingJob) -> None:
        """Simulate training (for testing without backends)."""
        import threading
        import time

        def simulate():
            job.status = TrainingStatus.TRAINING
            job.started_at = datetime.utcnow()

            steps = job.total_epochs * 10
            for step in range(steps):
                if job.status == TrainingStatus.CANCELLED:
                    return

                job.progress = step / steps
                job.current_epoch = step // 10 + 1
                job.loss_history.append(2.0 - step * 0.05)
                time.sleep(0.1)

            job.status = TrainingStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.progress = 1.0

            model = ModelRegistry(
                model_id=job.request.model_id,
                base_model=job.request.base_model,
                training_corpus_id=job.request.training_corpus_id,
                training_config=job.request.training_config,
                checkpoint_path=f"{self._models_dir}/{job.request.model_id}",
                metrics={"final_loss": job.loss_history[-1] if job.loss_history else 0.0},
                created_at=datetime.utcnow(),
                status=TrainingStatus.COMPLETED,
            )
            self.register_model(model)

        thread = threading.Thread(target=simulate, daemon=True)
        thread.start()

    # =========================================================================
    # Example Generation
    # =========================================================================

    def _generate_examples_for_behavior(
        self,
        behavior: Dict[str, Any],
        sample_count: int,
        include_citations: bool = True,
        corpus_id: str = "",
    ) -> List[TrainingExample]:
        """Generate training examples for a behavior.

        Uses OpenAI for high-quality generation when available,
        falls back to templates otherwise.
        """
        examples = []
        behavior_version = behavior.get("versions", [{}])[0]
        instruction = behavior_version.get("instruction", "")
        behavior_id = behavior.get("behavior_id", "")
        behavior_name = behavior.get("name", behavior_id)

        # Try LLM generation
        use_llm = os.getenv("MDNT_USE_LLM_EXAMPLES", "true").lower() == "true"

        if use_llm and OPENAI_AVAILABLE:
            try:
                examples = self._generate_examples_with_llm(
                    behavior_id=behavior_id,
                    behavior_name=behavior_name,
                    instruction=instruction,
                    sample_count=sample_count,
                    include_citations=include_citations,
                    corpus_id=corpus_id,
                )
                if examples:
                    return examples
            except Exception as e:
                logger.warning(f"LLM example generation failed: {e}")

        # Fallback to templates
        for i in range(sample_count):
            prompt_templates = [
                f"How do I {instruction.lower()[:50]}?",
                f"I need help with: {instruction[:80]}",
                f"Can you explain the process for {instruction.lower()[:60]}?",
                f"What's the best approach to {instruction.lower()[:50]}?",
            ]
            prompt_text = prompt_templates[i % len(prompt_templates)]

            if include_citations:
                response_text = (
                    f"Following `{behavior_id}` (Student): "
                    f"Here's how to approach this task. "
                    f"{instruction[:200]}..."
                )
            else:
                response_text = f"Here's how to approach this task. {instruction[:200]}..."

            example = TrainingExample(
                example_id=generate_example_id(),
                corpus_id=corpus_id,
                prompt=prompt_text,
                response=response_text,
                behaviors_used=[behavior_id],
                citation_count=1 if include_citations else 0,
                quality_metrics={"overall_score": 0.7},
                token_count=len(prompt_text.split()) + len(response_text.split()),
                created_at=datetime.utcnow(),
            )
            examples.append(example)

        return examples

    def _generate_examples_with_llm(
        self,
        behavior_id: str,
        behavior_name: str,
        instruction: str,
        sample_count: int,
        include_citations: bool = True,
        corpus_id: str = "",
    ) -> List[TrainingExample]:
        """Generate high-quality examples using OpenAI."""
        from openai import OpenAI

        client = OpenAI()
        examples = []

        system_prompt = """You are an expert Teacher AI generating training examples for behavior-conditioned fine-tuning.

Generate high-quality (user prompt, assistant response) pairs that demonstrate correct application of a behavior guideline.

Requirements:
1. User prompts should be natural questions that would trigger this behavior
2. Assistant responses should correctly apply the behavior with proper citations
3. Responses should cite the behavior using: `behavior_id` (Role)
4. Vary the complexity and domain of examples

Output format (JSON):
{"prompt": "user question", "response": "assistant response with citation"}"""

        for i in range(sample_count):
            try:
                user_prompt = f"""Generate a training example for:

Behavior ID: {behavior_id}
Behavior Name: {behavior_name}
Instruction: {instruction}

{"Include behavior citation." if include_citations else "No citations."}

Generate example #{i+1} with a unique angle."""

                response = client.chat.completions.create(
                    model=os.getenv("MDNT_TEACHER_MODEL", "gpt-4o-mini"),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.8,
                    max_tokens=500,
                    response_format={"type": "json_object"}
                )

                content = response.choices[0].message.content
                if content:
                    data = json.loads(content)

                    quality_score = self._score_example_quality(
                        data.get("prompt", ""),
                        data.get("response", ""),
                        behavior_id
                    )

                    example = TrainingExample(
                        example_id=generate_example_id(),
                        corpus_id=corpus_id,
                        prompt=data.get("prompt", ""),
                        response=data.get("response", ""),
                        behaviors_used=[behavior_id],
                        citation_count=1 if include_citations and behavior_id in data.get("response", "") else 0,
                        quality_metrics=quality_score,
                        token_count=response.usage.total_tokens if response.usage else 0,
                        created_at=datetime.utcnow(),
                    )
                    examples.append(example)

            except Exception as e:
                logger.warning(f"Failed to generate example {i+1}: {e}")

        return examples

    def _score_example_quality(
        self,
        prompt: str,
        response: str,
        behavior_id: str,
    ) -> Dict[str, float]:
        """Score the quality of a training example."""
        scores = {}

        # Coherence
        scores["coherence"] = min(1.0, len(response.split()) / 20) if response else 0.0

        # Relevance
        relevance_terms = [behavior_id, "following", "behavior", "guideline"]
        matches = sum(1 for t in relevance_terms if t.lower() in response.lower())
        scores["relevance"] = min(1.0, matches / len(relevance_terms))

        # Citation quality
        has_citation = f"`{behavior_id}`" in response or behavior_id in response
        scores["citation_quality"] = 1.0 if has_citation else 0.5

        # Length score
        word_count = len(response.split())
        if 30 <= word_count <= 300:
            scores["length_score"] = 1.0
        elif word_count < 30:
            scores["length_score"] = word_count / 30
        else:
            scores["length_score"] = max(0.5, 1.0 - (word_count - 300) / 300)

        # Overall
        scores["overall_score"] = (
            scores["coherence"] * 0.25 +
            scores["relevance"] * 0.35 +
            scores["citation_quality"] * 0.2 +
            scores["length_score"] * 0.2
        )

        return scores

    def _store_corpus_examples(self, corpus_id: str, data: List[Dict[str, Any]]) -> None:
        """Store training examples for a corpus."""
        for item in data:
            example = TrainingExample(
                example_id=generate_example_id(),
                corpus_id=corpus_id,
                prompt=item.get("prompt", ""),
                response=item.get("response", ""),
                behaviors_used=item.get("behaviors_used", []),
                citation_count=item.get("citation_count", 0),
                quality_metrics=item.get("quality_metrics", {}),
                token_count=item.get("token_count", 0),
                created_at=datetime.utcnow(),
            )
            self._training_examples[example.example_id] = example

    def _emit_metric(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit a metric via hooks."""
        try:
            self._hooks.on_metric(event_type, {
                **data,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "midnighter",
            })
        except Exception as e:
            logger.debug(f"Failed to emit metric: {e}")
