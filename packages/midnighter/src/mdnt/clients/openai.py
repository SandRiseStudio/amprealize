"""OpenAI Fine-Tuning API client for Midnighter BC-SFT training.

Implements the managed OpenAI Fine-Tuning backend (no GPU required).

Environment Variables:
- OPENAI_API_KEY: OpenAI API key for fine-tuning operations
- MDNT_OPENAI_MODEL: Base model for fine-tuning (default: gpt-4o-mini-2024-07-18)
- MDNT_OPENAI_SUFFIX: Model suffix for identification (default: mdnt-bcsft)
- MDNT_OPENAI_MAX_RETRIES: Maximum retries for API calls (default: 5)
- MDNT_OPENAI_RETRY_MIN_WAIT: Minimum wait between retries in seconds (default: 1)
- MDNT_OPENAI_RETRY_MAX_WAIT: Maximum wait between retries in seconds (default: 60)
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, cast
import tempfile

logger = logging.getLogger(__name__)

# Type variable for retry decorator
F = TypeVar("F", bound=Callable[..., Any])

try:
    from openai import OpenAI
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None  # type: ignore
    openai = None  # type: ignore
    OPENAI_AVAILABLE = False


# Retry configuration defaults
DEFAULT_MAX_RETRIES = int(os.getenv("MDNT_OPENAI_MAX_RETRIES", "5"))
DEFAULT_RETRY_MIN_WAIT = float(os.getenv("MDNT_OPENAI_RETRY_MIN_WAIT", "1"))
DEFAULT_RETRY_MAX_WAIT = float(os.getenv("MDNT_OPENAI_RETRY_MAX_WAIT", "60"))


class RetryableError(Exception):
    """Wrapper for errors that should trigger a retry."""
    pass


def with_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    min_wait: float = DEFAULT_RETRY_MIN_WAIT,
    max_wait: float = DEFAULT_RETRY_MAX_WAIT,
    retryable_exceptions: tuple = (),
) -> Callable[[F], F]:
    """Decorator for exponential backoff retry with jitter.

    Implements exponential backoff with full jitter as recommended by AWS:
    https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/

    Args:
        max_retries: Maximum number of retry attempts.
        min_wait: Minimum wait time between retries (seconds).
        max_wait: Maximum wait time between retries (seconds).
        retryable_exceptions: Additional exception types to retry on.

    Returns:
        Decorated function with retry behavior.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Determine if this exception is retryable
                    is_retryable = False
                    wait_time = min_wait

                    # Check for OpenAI-specific rate limit errors
                    if OPENAI_AVAILABLE and openai is not None:
                        if isinstance(e, openai.RateLimitError):
                            is_retryable = True
                            # OpenAI rate limits often include retry-after
                            if hasattr(e, 'response') and e.response is not None:
                                retry_after = e.response.headers.get('retry-after')
                                if retry_after:
                                    try:
                                        wait_time = max(min_wait, float(retry_after))
                                    except ValueError:
                                        pass
                            logger.warning(
                                "Rate limit hit on attempt %d/%d: %s",
                                attempt + 1, max_retries + 1, str(e)
                            )
                        elif isinstance(e, openai.APITimeoutError):
                            is_retryable = True
                            logger.warning(
                                "Timeout on attempt %d/%d: %s",
                                attempt + 1, max_retries + 1, str(e)
                            )
                        elif isinstance(e, openai.APIConnectionError):
                            is_retryable = True
                            logger.warning(
                                "Connection error on attempt %d/%d: %s",
                                attempt + 1, max_retries + 1, str(e)
                            )
                        elif isinstance(e, openai.InternalServerError):
                            is_retryable = True
                            logger.warning(
                                "Server error on attempt %d/%d: %s",
                                attempt + 1, max_retries + 1, str(e)
                            )

                    # Check for custom retryable exceptions
                    if isinstance(e, retryable_exceptions):
                        is_retryable = True

                    # Check for RetryableError wrapper
                    if isinstance(e, RetryableError):
                        is_retryable = True

                    if not is_retryable:
                        raise

                    last_exception = e

                    if attempt >= max_retries:
                        logger.error(
                            "Max retries (%d) exceeded for %s: %s",
                            max_retries, func.__name__, str(e)
                        )
                        raise

                    # Calculate exponential backoff with full jitter
                    # base_wait = min(max_wait, min_wait * (2 ** attempt))
                    # actual_wait = random.uniform(0, base_wait)
                    base_wait = min(max_wait, wait_time * (2 ** attempt))
                    actual_wait = random.uniform(min_wait, base_wait)

                    logger.info(
                        "Retrying %s in %.2fs (attempt %d/%d)",
                        func.__name__, actual_wait, attempt + 2, max_retries + 1
                    )
                    time.sleep(actual_wait)

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception
            return None

        return cast(F, wrapper)
    return decorator


class OpenAIFineTuningStatus(str, Enum):
    """OpenAI fine-tuning job status (maps to their API)."""
    VALIDATING_FILES = "validating_files"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OpenAIFineTuningJob:
    """Represents an OpenAI fine-tuning job."""
    job_id: str
    model: str
    status: OpenAIFineTuningStatus
    training_file: str
    validation_file: Optional[str] = None
    fine_tuned_model: Optional[str] = None
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    trained_tokens: int = 0
    error: Optional[str] = None
    hyperparameters: Dict[str, Any] = field(default_factory=dict)
    result_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "model": self.model,
            "status": self.status.value,
            "training_file": self.training_file,
            "validation_file": self.validation_file,
            "fine_tuned_model": self.fine_tuned_model,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "trained_tokens": self.trained_tokens,
            "error": self.error,
            "hyperparameters": self.hyperparameters,
            "result_files": self.result_files,
        }


@dataclass
class OpenAITrainingFile:
    """Represents an uploaded training file."""
    file_id: str
    filename: str
    bytes: int
    created_at: datetime
    purpose: str = "fine-tune"
    status: str = "processed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "bytes": self.bytes,
            "created_at": self.created_at.isoformat(),
            "purpose": self.purpose,
            "status": self.status,
        }


class OpenAIFineTuningClient:
    """Client for OpenAI Fine-Tuning API operations.

    Supports:
    - JSONL file upload for training data
    - Fine-tuning job creation with hyperparameters
    - Job status monitoring and polling
    - Model retrieval after successful training
    - Job cancellation

    Example usage:
        client = OpenAIFineTuningClient()

        # Upload training data
        file_id = client.upload_training_file(corpus_jsonl)

        # Create fine-tuning job
        job = client.create_job(
            training_file=file_id,
            model="gpt-4o-mini-2024-07-18",
            suffix="my-behavior-model"
        )

        # Poll for completion
        final_job = client.wait_for_completion(job.job_id)
        print(f"Fine-tuned model: {final_job.fine_tuned_model}")
    """

    # Supported base models for fine-tuning (as of January 2025)
    SUPPORTED_MODELS = [
        "gpt-4o-2024-08-06",
        "gpt-4o-mini-2024-07-18",
        "gpt-4-0613",
        "gpt-3.5-turbo-0125",
        "gpt-3.5-turbo-1106",
        "gpt-3.5-turbo-0613",
    ]

    # Default hyperparameters for BC-SFT
    DEFAULT_HYPERPARAMETERS = {
        "n_epochs": 3,
        "batch_size": "auto",
        "learning_rate_multiplier": "auto",
    }

    # OpenAI requires minimum 10 examples
    MIN_EXAMPLES_REQUIRED = 10

    def __init__(
        self,
        api_key: Optional[str] = None,
        organization: Optional[str] = None,
        base_model: Optional[str] = None,
        suffix: Optional[str] = None,
    ):
        """Initialize OpenAI Fine-Tuning client.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            organization: OpenAI organization ID (optional)
            base_model: Default base model for fine-tuning
            suffix: Default suffix for fine-tuned model names
        """
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "OpenAI SDK not installed. Run: pip install midnighter[openai]"
            )

        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY environment variable "
                "or pass api_key parameter."
            )

        self._organization = organization or os.getenv("OPENAI_ORG_ID")
        self._base_model = base_model or os.getenv(
            "MDNT_OPENAI_MODEL",
            "gpt-4o-mini-2024-07-18"
        )
        self._suffix = suffix or os.getenv("MDNT_OPENAI_SUFFIX", "mdnt-bcsft")

        # Initialize OpenAI client
        client_kwargs: Dict[str, Any] = {"api_key": self._api_key}
        if self._organization:
            client_kwargs["organization"] = self._organization

        self._client = OpenAI(**client_kwargs)

        # Retry configuration
        self._max_retries = int(os.getenv("MDNT_OPENAI_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))
        self._retry_min_wait = float(os.getenv("MDNT_OPENAI_RETRY_MIN_WAIT", str(DEFAULT_RETRY_MIN_WAIT)))
        self._retry_max_wait = float(os.getenv("MDNT_OPENAI_RETRY_MAX_WAIT", str(DEFAULT_RETRY_MAX_WAIT)))

        logger.info(
            "OpenAI Fine-Tuning client initialized (base_model=%s, suffix=%s, max_retries=%d)",
            self._base_model, self._suffix, self._max_retries
        )

    @with_retry()
    def upload_training_file(
        self,
        training_data: str,
        filename: Optional[str] = None,
    ) -> OpenAITrainingFile:
        """Upload JSONL training data to OpenAI.

        Args:
            training_data: JSONL formatted string with training examples.
                          Each line must be: {"messages": [{"role": "...", "content": "..."}]}
            filename: Optional filename for the upload

        Returns:
            OpenAITrainingFile with file_id for job creation

        Raises:
            ValueError: If training data format is invalid or has fewer than 10 examples
            openai.APIError: If upload fails
        """
        # Validate JSONL format
        lines = training_data.strip().split("\n")
        if not lines:
            raise ValueError("Training data is empty")

        # OpenAI requires minimum 10 examples
        if len(lines) < self.MIN_EXAMPLES_REQUIRED:
            raise ValueError(
                f"OpenAI fine-tuning requires at least {self.MIN_EXAMPLES_REQUIRED} examples, "
                f"but only {len(lines)} were provided. "
                f"Generate more training examples before uploading."
            )

        for i, line in enumerate(lines):
            try:
                obj = json.loads(line)
                if "messages" not in obj:
                    raise ValueError(
                        f"Line {i+1}: Missing 'messages' field. "
                        "Expected format: {\"messages\": [{\"role\": \"...\", \"content\": \"...\"}]}"
                    )
            except json.JSONDecodeError as e:
                raise ValueError(f"Line {i+1}: Invalid JSON - {e}")

        logger.info(
            "Validated %d training examples (min required: %d)",
            len(lines), self.MIN_EXAMPLES_REQUIRED
        )

        # Write to temporary file for upload
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".jsonl",
            delete=False,
            prefix=filename or "mdnt_training_"
        ) as f:
            f.write(training_data)
            temp_path = f.name

        try:
            with open(temp_path, "rb") as f:
                response = self._client.files.create(
                    file=f,
                    purpose="fine-tune"
                )

            result = OpenAITrainingFile(
                file_id=response.id,
                filename=response.filename,
                bytes=response.bytes,
                created_at=datetime.fromtimestamp(response.created_at),
                purpose=response.purpose,
                status=response.status,
            )

            logger.info(
                "Uploaded training file: %s (%d bytes, %d examples)",
                result.file_id, result.bytes, len(lines)
            )
            return result

        finally:
            # Clean up temporary file
            Path(temp_path).unlink(missing_ok=True)

    def create_job(
        self,
        training_file: str,
        model: Optional[str] = None,
        suffix: Optional[str] = None,
        validation_file: Optional[str] = None,
        hyperparameters: Optional[Dict[str, Any]] = None,
    ) -> OpenAIFineTuningJob:
        """Create a fine-tuning job.

        Args:
            training_file: File ID from upload_training_file()
            model: Base model to fine-tune (defaults to configured model)
            suffix: Suffix for the fine-tuned model name
            validation_file: Optional validation file ID
            hyperparameters: Training hyperparameters override

        Returns:
            OpenAIFineTuningJob with job details
        """
        model = model or self._base_model
        suffix = suffix or self._suffix

        if model not in self.SUPPORTED_MODELS:
            logger.warning(
                "Model %s may not support fine-tuning. Supported: %s",
                model, self.SUPPORTED_MODELS
            )

        # Merge default hyperparameters with overrides
        hp = {**self.DEFAULT_HYPERPARAMETERS}
        if hyperparameters:
            hp.update(hyperparameters)

        create_kwargs: Dict[str, Any] = {
            "training_file": training_file,
            "model": model,
            "suffix": suffix,
            "hyperparameters": hp,
        }
        if validation_file:
            create_kwargs["validation_file"] = validation_file

        response = self._client.fine_tuning.jobs.create(**create_kwargs)

        result = self._job_from_response(response)
        logger.info(
            "Created fine-tuning job: %s (model=%s, status=%s)",
            result.job_id, result.model, result.status.value
        )
        return result

    @with_retry()
    def get_job(self, job_id: str) -> OpenAIFineTuningJob:
        """Get the current status of a fine-tuning job.

        Args:
            job_id: The fine-tuning job ID

        Returns:
            Updated OpenAIFineTuningJob with current status
        """
        response = self._client.fine_tuning.jobs.retrieve(job_id)
        return self._job_from_response(response)

    @with_retry()
    def list_jobs(
        self,
        limit: int = 20,
        after: Optional[str] = None,
    ) -> List[OpenAIFineTuningJob]:
        """List fine-tuning jobs.

        Args:
            limit: Maximum number of jobs to return
            after: Cursor for pagination

        Returns:
            List of fine-tuning jobs
        """
        kwargs: Dict[str, Any] = {"limit": limit}
        if after:
            kwargs["after"] = after

        response = self._client.fine_tuning.jobs.list(**kwargs)
        return [self._job_from_response(job) for job in response.data]

    @with_retry()
    def cancel_job(self, job_id: str) -> OpenAIFineTuningJob:
        """Cancel a fine-tuning job.

        Args:
            job_id: The fine-tuning job ID to cancel

        Returns:
            Updated job with cancelled status
        """
        response = self._client.fine_tuning.jobs.cancel(job_id)
        result = self._job_from_response(response)
        logger.info("Cancelled fine-tuning job: %s", job_id)
        return result

    @with_retry()
    def list_events(
        self,
        job_id: str,
        limit: int = 20,
        after: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List events for a fine-tuning job.

        Args:
            job_id: The fine-tuning job ID
            limit: Maximum number of events to return
            after: Cursor for pagination

        Returns:
            List of event dictionaries
        """
        kwargs: Dict[str, Any] = {"limit": limit}
        if after:
            kwargs["after"] = after

        response = self._client.fine_tuning.jobs.list_events(job_id, **kwargs)
        events = []
        for event in response.data:
            events.append({
                "id": event.id,
                "type": event.type if hasattr(event, 'type') else 'message',
                "message": event.message if hasattr(event, 'message') else str(event),
                "created_at": datetime.fromtimestamp(event.created_at).isoformat(),
                "level": getattr(event, 'level', 'info'),
            })
        return events

    def wait_for_completion(
        self,
        job_id: str,
        poll_interval: float = 30.0,
        timeout: float = 7200.0,  # 2 hours default
        callback: Optional[Callable[["OpenAIFineTuningJob"], None]] = None,
    ) -> OpenAIFineTuningJob:
        """Poll for job completion.

        Args:
            job_id: The fine-tuning job ID
            poll_interval: Seconds between status checks
            timeout: Maximum seconds to wait
            callback: Optional callback(job) for progress updates

        Returns:
            Final job status

        Raises:
            TimeoutError: If job doesn't complete within timeout
        """
        start_time = time.time()
        terminal_statuses = {
            OpenAIFineTuningStatus.SUCCEEDED,
            OpenAIFineTuningStatus.FAILED,
            OpenAIFineTuningStatus.CANCELLED,
        }

        while True:
            job = self.get_job(job_id)

            if callback:
                callback(job)

            if job.status in terminal_statuses:
                logger.info(
                    "Fine-tuning job %s completed with status: %s",
                    job_id, job.status.value
                )
                return job

            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise TimeoutError(
                    f"Fine-tuning job {job_id} did not complete within {timeout}s"
                )

            logger.debug(
                "Job %s status: %s (elapsed: %.1fs)",
                job_id, job.status.value, elapsed
            )
            time.sleep(poll_interval)

    def delete_file(self, file_id: str) -> bool:
        """Delete an uploaded file.

        Args:
            file_id: The file ID to delete

        Returns:
            True if deletion was successful
        """
        try:
            self._client.files.delete(file_id)
            logger.info("Deleted file: %s", file_id)
            return True
        except Exception as e:
            logger.warning("Failed to delete file %s: %s", file_id, e)
            return False

    def _job_from_response(self, response: Any) -> OpenAIFineTuningJob:
        """Convert OpenAI API response to OpenAIFineTuningJob."""
        return OpenAIFineTuningJob(
            job_id=response.id,
            model=response.model,
            status=OpenAIFineTuningStatus(response.status),
            training_file=response.training_file,
            validation_file=getattr(response, 'validation_file', None),
            fine_tuned_model=getattr(response, 'fine_tuned_model', None),
            created_at=datetime.fromtimestamp(response.created_at) if response.created_at else None,
            finished_at=datetime.fromtimestamp(response.finished_at) if getattr(response, 'finished_at', None) else None,
            trained_tokens=getattr(response, 'trained_tokens', 0) or 0,
            error=getattr(response.error, 'message', None) if getattr(response, 'error', None) else None,
            hyperparameters=dict(response.hyperparameters) if hasattr(response, 'hyperparameters') else {},
            result_files=list(response.result_files) if hasattr(response, 'result_files') else [],
        )


def convert_to_openai_format(
    examples: List[Dict[str, Any]],
    system_prompt: Optional[str] = None,
) -> str:
    """Convert training examples to OpenAI fine-tuning JSONL format.

    OpenAI fine-tuning expects:
    {"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}

    Args:
        examples: List of training examples with "prompt" and "response" keys
        system_prompt: Optional system message to prepend to all examples

    Returns:
        JSONL string suitable for OpenAI fine-tuning
    """
    default_system = (
        "You are a helpful AI assistant that follows behavior-conditioned guidelines. "
        "When applying behaviors, cite them in your response."
    )
    system = system_prompt or default_system

    lines = []
    for example in examples:
        prompt = example.get("prompt") or example.get("input", "")
        response = example.get("response") or example.get("output", "")

        if not prompt or not response:
            continue

        # Include behavior context in system message if available
        behaviors = example.get("behaviors") or example.get("behaviors_used", [])
        if behaviors:
            behavior_context = f" Following behaviors: {', '.join(behaviors)}."
            system_with_context = system + behavior_context
        else:
            system_with_context = system

        message_obj = {
            "messages": [
                {"role": "system", "content": system_with_context},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ]
        }
        lines.append(json.dumps(message_obj))

    return "\n".join(lines)
