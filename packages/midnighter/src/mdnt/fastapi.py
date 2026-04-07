"""FastAPI route factory for Midnighter BC-SFT service.

Example:
    from fastapi import FastAPI
    from mdnt.fastapi import create_midnighter_routes
    from mdnt import MidnighterHooks

    app = FastAPI()

    routes = create_midnighter_routes(
        prefix="/v1/training",
        hooks=MidnighterHooks(
            get_behavior=my_behavior_store.get,
        ),
    )
    app.include_router(routes)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, HTTPException, Depends
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore
    HTTPException = None  # type: ignore

from .models import TrainingStatus
from .hooks import MidnighterHooks
from .service import MidnighterService


# Request/Response models for FastAPI
if FASTAPI_AVAILABLE:

    class CreateCorpusRequest(BaseModel):
        """Request to create a training corpus."""
        name: str = Field(..., description="Corpus name")
        description: str = Field("", description="Corpus description")
        source_data: List[Dict[str, Any]] = Field(
            ..., description="List of training examples"
        )
        quality_threshold: float = Field(0.7, description="Minimum quality score")

    class GenerateCorpusRequest(BaseModel):
        """Request to generate corpus from behaviors."""
        name: str = Field(..., description="Corpus name")
        description: str = Field("", description="Corpus description")
        behavior_ids: List[str] = Field(..., description="Behavior IDs to generate from")
        sample_count: int = Field(100, description="Number of examples to generate")
        include_citations: bool = Field(True, description="Include behavior citations")
        quality_filter: bool = Field(True, description="Filter by quality score")

    class StartTrainingRequest(BaseModel):
        """Request to start a training job."""
        model_id: str = Field(..., description="Unique model identifier")
        base_model: str = Field("gpt-4o-mini", description="Base model to fine-tune")
        corpus_id: str = Field(..., description="Training corpus ID")
        config: Dict[str, Any] = Field(default_factory=dict, description="Training config")
        validation_split: float = Field(0.1, description="Validation split fraction")

    class CorpusResponse(BaseModel):
        """Training corpus response."""
        corpus_id: str
        name: str
        description: str
        created_at: str
        total_examples: int
        example_types: List[str]
        quality_score: float

    class TrainingJobResponse(BaseModel):
        """Training job response."""
        job_id: str
        model_id: str
        status: str
        progress: float
        current_epoch: int
        total_epochs: int
        created_at: str
        started_at: Optional[str] = None
        completed_at: Optional[str] = None
        error_message: Optional[str] = None
        backend_job_id: Optional[str] = None

    class ModelResponse(BaseModel):
        """Model registry response."""
        model_id: str
        base_model: str
        training_corpus_id: str
        checkpoint_path: Optional[str] = None
        status: str
        created_at: str
        metrics: Dict[str, Any] = Field(default_factory=dict)


def create_midnighter_routes(
    prefix: str = "/v1/training",
    hooks: Optional[MidnighterHooks] = None,
    service: Optional[MidnighterService] = None,
    backend: str = "openai",
    models_dir: str = "./models",
) -> "APIRouter":
    """Create FastAPI router for Midnighter training endpoints.

    Args:
        prefix: URL prefix for routes
        hooks: Integration hooks (required if service not provided)
        service: Pre-configured MidnighterService (optional)
        backend: Training backend: "openai" or "local"
        models_dir: Directory for model checkpoints

    Returns:
        FastAPI APIRouter with training endpoints

    Raises:
        ImportError: If FastAPI is not installed

    Example:
        from fastapi import FastAPI
        from mdnt.fastapi import create_midnighter_routes

        app = FastAPI()
        routes = create_midnighter_routes(
            prefix="/v1/training",
            hooks=my_hooks,
        )
        app.include_router(routes)
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI not installed. Run: pip install midnighter[fastapi]"
        )

    router = APIRouter(prefix=prefix, tags=["training"])

    # Create or use provided service
    _service = service or MidnighterService(
        hooks=hooks or MidnighterHooks(),
        backend=backend,
        models_dir=models_dir,
    )

    def get_service() -> MidnighterService:
        return _service

    # =========================================================================
    # Corpus Endpoints
    # =========================================================================

    @router.post("/corpora", response_model=CorpusResponse)
    async def create_corpus(
        request: CreateCorpusRequest,
        svc: MidnighterService = Depends(get_service),
    ) -> CorpusResponse:
        """Create a new training corpus from source data."""
        try:
            corpus = svc.create_corpus(
                name=request.name,
                description=request.description,
                source_data=request.source_data,
                quality_threshold=request.quality_threshold,
            )
            return CorpusResponse(
                corpus_id=corpus.corpus_id,
                name=corpus.name,
                description=corpus.description,
                created_at=corpus.created_at.isoformat(),
                total_examples=corpus.total_examples,
                example_types=corpus.example_types,
                quality_score=corpus.quality_score,
            )
        except Exception as e:
            logger.exception("Failed to create corpus")
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/corpora/generate", response_model=CorpusResponse)
    async def generate_corpus(
        request: GenerateCorpusRequest,
        svc: MidnighterService = Depends(get_service),
    ) -> CorpusResponse:
        """Generate training corpus from behavior data."""
        try:
            corpus = svc.generate_corpus_from_behaviors(
                name=request.name,
                description=request.description,
                behavior_ids=request.behavior_ids,
                sample_count=request.sample_count,
                include_citations=request.include_citations,
                quality_filter=request.quality_filter,
            )
            return CorpusResponse(
                corpus_id=corpus.corpus_id,
                name=corpus.name,
                description=corpus.description,
                created_at=corpus.created_at.isoformat(),
                total_examples=corpus.total_examples,
                example_types=corpus.example_types,
                quality_score=corpus.quality_score,
            )
        except Exception as e:
            logger.exception("Failed to generate corpus")
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/corpora", response_model=List[CorpusResponse])
    async def list_corpora(
        svc: MidnighterService = Depends(get_service),
    ) -> List[CorpusResponse]:
        """List all training corpora."""
        corpora = svc.list_corpora()
        return [
            CorpusResponse(
                corpus_id=c.corpus_id,
                name=c.name,
                description=c.description,
                created_at=c.created_at.isoformat(),
                total_examples=c.total_examples,
                example_types=c.example_types,
                quality_score=c.quality_score,
            )
            for c in corpora
        ]

    @router.get("/corpora/{corpus_id}", response_model=CorpusResponse)
    async def get_corpus(
        corpus_id: str,
        svc: MidnighterService = Depends(get_service),
    ) -> CorpusResponse:
        """Get a training corpus by ID."""
        corpus = svc.get_corpus(corpus_id)
        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus not found")

        return CorpusResponse(
            corpus_id=corpus.corpus_id,
            name=corpus.name,
            description=corpus.description,
            created_at=corpus.created_at.isoformat(),
            total_examples=corpus.total_examples,
            example_types=corpus.example_types,
            quality_score=corpus.quality_score,
        )

    @router.get("/corpora/{corpus_id}/export")
    async def export_corpus(
        corpus_id: str,
        format: str = "jsonl",
        svc: MidnighterService = Depends(get_service),
    ) -> Dict[str, Any]:
        """Export corpus in specified format."""
        try:
            data = svc.export_corpus(corpus_id, format=format)
            return {"corpus_id": corpus_id, "format": format, "data": data}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # =========================================================================
    # Training Job Endpoints
    # =========================================================================

    @router.post("/jobs", response_model=TrainingJobResponse)
    async def start_training_job(
        request: StartTrainingRequest,
        svc: MidnighterService = Depends(get_service),
    ) -> TrainingJobResponse:
        """Start a fine-tuning training job."""
        try:
            job = svc.start_training_job(
                model_id=request.model_id,
                base_model=request.base_model,
                corpus_id=request.corpus_id,
                config=request.config,
                validation_split=request.validation_split,
            )
            return TrainingJobResponse(
                job_id=job.job_id,
                model_id=job.request.model_id,
                status=job.status.value,
                progress=job.progress,
                current_epoch=job.current_epoch,
                total_epochs=job.total_epochs,
                created_at=job.created_at.isoformat(),
                started_at=job.started_at.isoformat() if job.started_at else None,
                completed_at=job.completed_at.isoformat() if job.completed_at else None,
                error_message=job.error_message,
                backend_job_id=job.backend_job_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.exception("Failed to start training job")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/jobs", response_model=List[TrainingJobResponse])
    async def list_jobs(
        svc: MidnighterService = Depends(get_service),
    ) -> List[TrainingJobResponse]:
        """List all training jobs."""
        jobs = svc.list_jobs()
        return [
            TrainingJobResponse(
                job_id=j.job_id,
                model_id=j.request.model_id,
                status=j.status.value,
                progress=j.progress,
                current_epoch=j.current_epoch,
                total_epochs=j.total_epochs,
                created_at=j.created_at.isoformat(),
                started_at=j.started_at.isoformat() if j.started_at else None,
                completed_at=j.completed_at.isoformat() if j.completed_at else None,
                error_message=j.error_message,
                backend_job_id=j.backend_job_id,
            )
            for j in jobs
        ]

    @router.get("/jobs/{job_id}", response_model=TrainingJobResponse)
    async def get_job(
        job_id: str,
        svc: MidnighterService = Depends(get_service),
    ) -> TrainingJobResponse:
        """Get training job status."""
        job = svc.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return TrainingJobResponse(
            job_id=job.job_id,
            model_id=job.request.model_id,
            status=job.status.value,
            progress=job.progress,
            current_epoch=job.current_epoch,
            total_epochs=job.total_epochs,
            created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            error_message=job.error_message,
            backend_job_id=job.backend_job_id,
        )

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_job(
        job_id: str,
        svc: MidnighterService = Depends(get_service),
    ) -> Dict[str, Any]:
        """Cancel a training job."""
        success = svc.cancel_job(job_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Cannot cancel job (not found or not in cancellable state)"
            )
        return {"job_id": job_id, "cancelled": True}

    # =========================================================================
    # Model Endpoints
    # =========================================================================

    @router.get("/models", response_model=List[ModelResponse])
    async def list_models(
        svc: MidnighterService = Depends(get_service),
    ) -> List[ModelResponse]:
        """List all registered models."""
        models = svc.list_models()
        return [
            ModelResponse(
                model_id=m.model_id,
                base_model=m.base_model,
                training_corpus_id=m.training_corpus_id,
                checkpoint_path=m.checkpoint_path,
                status=m.status.value,
                created_at=m.created_at.isoformat(),
                metrics=m.metrics,
            )
            for m in models
        ]

    @router.get("/models/{model_id}", response_model=ModelResponse)
    async def get_model(
        model_id: str,
        svc: MidnighterService = Depends(get_service),
    ) -> ModelResponse:
        """Get a model from the registry."""
        model = svc.get_model(model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")

        return ModelResponse(
            model_id=model.model_id,
            base_model=model.base_model,
            training_corpus_id=model.training_corpus_id,
            checkpoint_path=model.checkpoint_path,
            status=model.status.value,
            created_at=model.created_at.isoformat(),
            metrics=model.metrics,
        )

    return router
