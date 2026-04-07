"""Local PyTorch/Transformers training backend for Midnighter (EXPERIMENTAL).

⚠️ EXPERIMENTAL: This backend requires a GPU and significant resources.
For production use, prefer the OpenAI backend: pip install midnighter[openai]

Requirements:
- pip install midnighter[local]
- CUDA-capable GPU with sufficient VRAM
- Sufficient disk space for model checkpoints

This backend supports:
- Hugging Face Transformers models (Llama, Qwen, Mistral, etc.)
- LoRA/QLoRA fine-tuning for memory efficiency
- Gradient checkpointing for large models
- Mixed precision training (fp16/bf16)

Environment Variables:
- MDNT_MODELS_DIR: Directory for model checkpoints (default: ./models)
- MDNT_LOCAL_DEVICE: Training device (default: auto)
- MDNT_LOCAL_DTYPE: Training dtype: fp16, bf16, fp32 (default: auto)
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)

# Check for PyTorch/Transformers availability
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore
    TORCH_AVAILABLE = False

try:
    from transformers import (
        AutoTokenizer,
        AutoModelForCausalLM,
        Trainer,
        TrainingArguments,
        DataCollatorForLanguageModeling,
    )
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

try:
    from datasets import Dataset
    DATASETS_AVAILABLE = True
except ImportError:
    Dataset = None  # type: ignore
    DATASETS_AVAILABLE = False

try:
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    PEFT_AVAILABLE = True
except ImportError:
    PEFT_AVAILABLE = False

LOCAL_AVAILABLE = TORCH_AVAILABLE and TRANSFORMERS_AVAILABLE and DATASETS_AVAILABLE


# Hugging Face model mappings for ModelType enum values
HF_MODEL_MAP = {
    "llama-3.1-8b": "meta-llama/Llama-3.1-8B-Instruct",
    "llama-3.2-3b": "meta-llama/Llama-3.2-3B-Instruct",
    "qwen2.5-14b": "Qwen/Qwen2.5-14B-Instruct",
    "qwen2.5-32b": "Qwen/Qwen2.5-32B-Instruct",
    "qwen3-14b": "Qwen/Qwen3-14B",
    "mistral-7b": "mistralai/Mistral-7B-Instruct-v0.2",
}


@dataclass
class LocalTrainingConfig:
    """Configuration for local PyTorch training.

    Attributes:
        epochs: Number of training epochs
        batch_size: Training batch size (per device)
        learning_rate: Learning rate
        warmup_steps: Number of warmup steps
        weight_decay: Weight decay for regularization
        max_seq_length: Maximum sequence length
        gradient_accumulation_steps: Steps to accumulate gradients
        use_lora: Whether to use LoRA for efficient fine-tuning
        lora_r: LoRA rank (if use_lora=True)
        lora_alpha: LoRA alpha (if use_lora=True)
        lora_dropout: LoRA dropout (if use_lora=True)
        use_4bit: Whether to use 4-bit quantization (QLoRA)
        use_gradient_checkpointing: Enable gradient checkpointing
        logging_steps: Steps between logging
        save_steps: Steps between checkpoints
        fp16: Use FP16 mixed precision
        bf16: Use BF16 mixed precision (preferred for A100/H100)
    """
    epochs: int = 3
    batch_size: int = 4
    learning_rate: float = 2e-5
    warmup_steps: int = 100
    weight_decay: float = 0.01
    max_seq_length: int = 2048
    gradient_accumulation_steps: int = 4
    use_lora: bool = True  # Recommended for memory efficiency
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    use_4bit: bool = False  # QLoRA
    use_gradient_checkpointing: bool = True
    logging_steps: int = 10
    save_steps: int = 100
    fp16: bool = False
    bf16: bool = True  # Preferred on modern GPUs

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "LocalTrainingConfig":
        """Create config from dictionary, using defaults for missing values."""
        return cls(
            epochs=config.get("epochs", 3),
            batch_size=config.get("batch_size", 4),
            learning_rate=config.get("learning_rate", 2e-5),
            warmup_steps=config.get("warmup_steps", 100),
            weight_decay=config.get("weight_decay", 0.01),
            max_seq_length=config.get("max_seq_length", 2048),
            gradient_accumulation_steps=config.get("gradient_accumulation_steps", 4),
            use_lora=config.get("use_lora", True),
            lora_r=config.get("lora_r", 16),
            lora_alpha=config.get("lora_alpha", 32),
            lora_dropout=config.get("lora_dropout", 0.05),
            use_4bit=config.get("use_4bit", False),
            use_gradient_checkpointing=config.get("use_gradient_checkpointing", True),
            logging_steps=config.get("logging_steps", 10),
            save_steps=config.get("save_steps", 100),
            fp16=config.get("fp16", False),
            bf16=config.get("bf16", True),
        )


@dataclass
class LocalTrainingJob:
    """Represents a local training job."""
    job_id: str
    model_name: str
    output_dir: str
    status: str = "pending"
    progress: float = 0.0
    current_epoch: int = 0
    total_epochs: int = 3
    current_step: int = 0
    total_steps: int = 0
    loss: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "model_name": self.model_name,
            "output_dir": self.output_dir,
            "status": self.status,
            "progress": self.progress,
            "current_epoch": self.current_epoch,
            "total_epochs": self.total_epochs,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "loss": self.loss,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "metrics": self.metrics,
        }


class LocalTrainingCallback:
    """Callback for training progress updates."""

    def __init__(
        self,
        job: LocalTrainingJob,
        on_progress: Optional[Callable[[LocalTrainingJob], None]] = None,
    ):
        self.job = job
        self.on_progress = on_progress

    def on_log(self, logs: Dict[str, float]) -> None:
        """Called on each logging step."""
        if "loss" in logs:
            self.job.loss = logs["loss"]
        if "epoch" in logs:
            self.job.current_epoch = int(logs["epoch"])

        self.job.metrics.update(logs)

        if self.on_progress:
            self.on_progress(self.job)

    def on_step_end(self, step: int, total_steps: int) -> None:
        """Called at end of each step."""
        self.job.current_step = step
        self.job.total_steps = total_steps
        self.job.progress = step / total_steps if total_steps > 0 else 0.0

        if self.on_progress:
            self.on_progress(self.job)


class LocalTrainer:
    """Local PyTorch/Transformers training backend.

    ⚠️ EXPERIMENTAL: Requires GPU and significant resources.

    Example:
        trainer = LocalTrainer(models_dir="./models")

        job = trainer.start_training(
            model_name="meta-llama/Llama-3.1-8B-Instruct",
            training_data=examples,
            config=LocalTrainingConfig(epochs=3, use_lora=True),
        )

        # Monitor progress
        while job.status == "training":
            job = trainer.get_job(job.job_id)
            print(f"Progress: {job.progress:.1%}")
            time.sleep(10)
    """

    def __init__(
        self,
        models_dir: Optional[str] = None,
        device: Optional[str] = None,
    ):
        """Initialize local trainer.

        Args:
            models_dir: Directory for model checkpoints
            device: Training device (auto, cuda, cpu)
        """
        if not LOCAL_AVAILABLE:
            missing = []
            if not TORCH_AVAILABLE:
                missing.append("torch")
            if not TRANSFORMERS_AVAILABLE:
                missing.append("transformers")
            if not DATASETS_AVAILABLE:
                missing.append("datasets")
            raise ImportError(
                f"Local training requires: {', '.join(missing)}. "
                "Run: pip install midnighter[local]"
            )

        self._models_dir = models_dir or os.getenv("MDNT_MODELS_DIR", "./models")
        self._device = device or os.getenv("MDNT_LOCAL_DEVICE", "auto")
        self._jobs: Dict[str, LocalTrainingJob] = {}

        # Ensure models directory exists
        Path(self._models_dir).mkdir(parents=True, exist_ok=True)

        # Detect device
        if self._device == "auto":
            if torch.cuda.is_available():
                self._device = "cuda"
                logger.info(f"Using CUDA device: {torch.cuda.get_device_name()}")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                self._device = "mps"
                logger.info("Using Apple MPS device")
            else:
                self._device = "cpu"
                warnings.warn(
                    "No GPU detected. Local training on CPU will be very slow. "
                    "Consider using the OpenAI backend instead."
                )

        logger.info(f"LocalTrainer initialized (models_dir={self._models_dir}, device={self._device})")

    def resolve_model_name(self, model_name: str) -> str:
        """Resolve model name to Hugging Face model ID.

        Args:
            model_name: Model name or ModelType value

        Returns:
            Hugging Face model ID
        """
        return HF_MODEL_MAP.get(model_name, model_name)

    def start_training(
        self,
        model_name: str,
        training_data: List[Dict[str, Any]],
        config: Optional[LocalTrainingConfig] = None,
        job_id: Optional[str] = None,
        on_progress: Optional[Callable[[LocalTrainingJob], None]] = None,
    ) -> LocalTrainingJob:
        """Start a local training job.

        Args:
            model_name: Model name or Hugging Face model ID
            training_data: List of training examples with "prompt" and "response"
            config: Training configuration
            job_id: Optional job ID (generated if not provided)
            on_progress: Optional callback for progress updates

        Returns:
            LocalTrainingJob with job details
        """
        import threading

        config = config or LocalTrainingConfig()
        job_id = job_id or str(uuid.uuid4())

        # Resolve model name
        hf_model = self.resolve_model_name(model_name)

        # Create output directory
        output_dir = os.path.join(self._models_dir, job_id)
        os.makedirs(output_dir, exist_ok=True)

        # Create job
        job = LocalTrainingJob(
            job_id=job_id,
            model_name=hf_model,
            output_dir=output_dir,
            status="pending",
            total_epochs=config.epochs,
        )
        self._jobs[job_id] = job

        # Start training in background thread
        def run_training():
            try:
                self._run_training(job, training_data, config, on_progress)
            except Exception as e:
                logger.exception(f"Training failed for job {job_id}")
                job.status = "failed"
                job.error = str(e)

        thread = threading.Thread(
            target=run_training,
            name=f"mdnt-local-{job_id[:8]}",
            daemon=True,
        )
        thread.start()

        return job

    def _run_training(
        self,
        job: LocalTrainingJob,
        training_data: List[Dict[str, Any]],
        config: LocalTrainingConfig,
        on_progress: Optional[Callable[[LocalTrainingJob], None]] = None,
    ) -> None:
        """Run the actual training (called in background thread)."""
        job.status = "training"
        job.started_at = datetime.utcnow()

        logger.info(f"Starting local training: {job.model_name} ({len(training_data)} examples)")

        # Load tokenizer
        tokenizer = AutoTokenizer.from_pretrained(job.model_name)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        # Prepare dataset
        def format_example(example: Dict[str, Any]) -> str:
            """Format example for training."""
            prompt = example.get("prompt", "")
            response = example.get("response", "")
            behaviors = example.get("behaviors", [])

            if behaviors:
                behavior_str = ", ".join(behaviors)
                return f"<|system|>Following behaviors: {behavior_str}<|end|><|user|>{prompt}<|end|><|assistant|>{response}<|end|>"
            else:
                return f"<|user|>{prompt}<|end|><|assistant|>{response}<|end|>"

        formatted_data = [{"text": format_example(ex)} for ex in training_data]
        dataset = Dataset.from_list(formatted_data)

        # Tokenize
        def tokenize_function(examples: Dict[str, List[str]]) -> Dict[str, Any]:
            return tokenizer(
                examples["text"],
                truncation=True,
                max_length=config.max_seq_length,
                padding="max_length",
            )

        tokenized_dataset = dataset.map(
            tokenize_function,
            batched=True,
            remove_columns=["text"],
        )

        # Load model
        model_kwargs: Dict[str, Any] = {}

        if config.use_4bit and PEFT_AVAILABLE:
            try:
                from transformers import BitsAndBytesConfig
                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.bfloat16 if config.bf16 else torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                )
            except ImportError:
                logger.warning("bitsandbytes not available, skipping 4-bit quantization")

        model = AutoModelForCausalLM.from_pretrained(
            job.model_name,
            device_map="auto" if self._device == "cuda" else None,
            torch_dtype=torch.bfloat16 if config.bf16 else torch.float16,
            **model_kwargs,
        )

        # Apply LoRA if configured
        if config.use_lora and PEFT_AVAILABLE:
            if config.use_4bit:
                model = prepare_model_for_kbit_training(model)

            lora_config = LoraConfig(
                r=config.lora_r,
                lora_alpha=config.lora_alpha,
                lora_dropout=config.lora_dropout,
                target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
                bias="none",
                task_type="CAUSAL_LM",
            )
            model = get_peft_model(model, lora_config)
            model.print_trainable_parameters()

        if config.use_gradient_checkpointing:
            model.gradient_checkpointing_enable()

        # Training arguments
        training_args = TrainingArguments(
            output_dir=job.output_dir,
            num_train_epochs=config.epochs,
            per_device_train_batch_size=config.batch_size,
            gradient_accumulation_steps=config.gradient_accumulation_steps,
            learning_rate=config.learning_rate,
            warmup_steps=config.warmup_steps,
            weight_decay=config.weight_decay,
            logging_steps=config.logging_steps,
            save_steps=config.save_steps,
            fp16=config.fp16,
            bf16=config.bf16,
            optim="adamw_torch",
            report_to=[],  # Disable wandb/tensorboard
            save_total_limit=2,
        )

        # Data collator
        data_collator = DataCollatorForLanguageModeling(
            tokenizer=tokenizer,
            mlm=False,
        )

        # Create callback
        callback = LocalTrainingCallback(job, on_progress)

        # Custom Trainer callback
        from transformers import TrainerCallback

        class ProgressCallback(TrainerCallback):
            def on_log(self, args, state, control, logs=None, **kwargs):
                if logs:
                    callback.on_log(logs)

            def on_step_end(self, args, state, control, **kwargs):
                callback.on_step_end(state.global_step, state.max_steps)

        # Create trainer
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=tokenized_dataset,
            data_collator=data_collator,
            callbacks=[ProgressCallback()],
        )

        # Train
        trainer.train()

        # Save final model
        trainer.save_model(job.output_dir)
        tokenizer.save_pretrained(job.output_dir)

        # Update job status
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        job.progress = 1.0

        logger.info(f"Training completed: {job.job_id}")

    def get_job(self, job_id: str) -> Optional[LocalTrainingJob]:
        """Get job status."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[LocalTrainingJob]:
        """List all jobs."""
        return list(self._jobs.values())

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job (best effort)."""
        job = self._jobs.get(job_id)
        if job and job.status in ["pending", "training"]:
            job.status = "cancelled"
            return True
        return False


def convert_to_local_format(
    examples: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert training examples to local training format.

    Args:
        examples: List of training examples with "prompt" and "response" keys

    Returns:
        Formatted examples for local training
    """
    formatted = []
    for example in examples:
        prompt = example.get("prompt") or example.get("input", "")
        response = example.get("response") or example.get("output", "")

        if not prompt or not response:
            continue

        formatted.append({
            "prompt": prompt,
            "response": response,
            "behaviors": example.get("behaviors") or example.get("behaviors_used", []),
        })

    return formatted
