"""Data contracts for Advanced Retrieval - reranking models and query expansion."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import uuid


class RetrievalStrategy(str, Enum):
    """Advanced retrieval strategies."""
    SEMANTIC_RERANKING = "semantic_reranking"
    HYBRID_RERANKING = "hybrid_reranking"
    CONTEXTUAL_RERANKING = "contextual_reranking"
    MULTI_STAGE_RERANKING = "multi_stage_reranking"
    LEARNED_RERANKING = "learned_reranking"


class QueryExpansionMethod(str, Enum):
    """Query expansion methods."""
    SYNONYM_EXPANSION = "synonym_expansion"
    SEMANTIC_EXPANSION = "semantic_expansion"
    CONTEXTUAL_EXPANSION = "contextual_expansion"
    NEURAL_EXPANSION = "neural_expansion"
    HYBRID_EXPANSION = "hybrid_expansion"


@dataclass
class QueryExpansion:
    """Query expansion result with multiple expansion methods."""
    expansion_id: str
    original_query: str
    expanded_terms: List[str]
    expansion_method: QueryExpansionMethod
    confidence_scores: Dict[str, float]
    created_at: datetime
    effectiveness_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expansion_id": self.expansion_id,
            "original_query": self.original_query,
            "expanded_terms": self.expanded_terms,
            "expansion_method": self.expansion_method.value,
            "confidence_scores": self.confidence_scores,
            "created_at": self.created_at.isoformat(),
            "effectiveness_score": self.effectiveness_score,
        }


@dataclass
class RerankingResult:
    """Reranking result with multiple ranking signals."""
    result_id: str
    item_id: str
    original_score: float
    reranked_score: float
    ranking_signals: Dict[str, float]
    reranking_strategy: RetrievalStrategy
    confidence: float
    explanation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id,
            "item_id": self.item_id,
            "original_score": self.original_score,
            "reranked_score": self.reranked_score,
            "ranking_signals": self.ranking_signals,
            "reranking_strategy": self.reranking_strategy.value,
            "confidence": self.confidence,
            "explanation": self.explanation,
        }


@dataclass
class MultiStageRankingResult:
    """Results from multi-stage ranking pipeline."""
    pipeline_id: str
    query: str
    stage_results: List[RerankingResult]
    final_results: List[RerankingResult]
    processing_time_ms: float
    total_candidates: int
    strategies_used: List[RetrievalStrategy]
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "query": self.query,
            "stage_results": [r.to_dict() for r in self.stage_results],
            "final_results": [r.to_dict() for r in self.final_results],
            "processing_time_ms": self.processing_time_ms,
            "total_candidates": self.total_candidates,
            "strategies_used": [s.value for s in self.strategies_used],
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class RetrievalMetrics:
    """Metrics for retrieval performance."""
    metrics_id: str
    query: str
    strategy: RetrievalStrategy
    precision_at_k: Dict[int, float]  # P@1, P@5, P@10, etc.
    recall_at_k: Dict[int, float]
    ndcg_at_k: Dict[int, float]  # Normalized Discounted Cumulative Gain
    mrr: float  # Mean Reciprocal Rank
    map_score: float  # Mean Average Precision
    diversity_score: float
    response_time_ms: float
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metrics_id": self.metrics_id,
            "query": self.query,
            "strategy": self.strategy.value,
            "precision_at_k": self.precision_at_k,
            "recall_at_k": self.recall_at_k,
            "ndcg_at_k": self.ndcg_at_k,
            "mrr": self.mrr,
            "map_score": self.map_score,
            "diversity_score": self.diversity_score,
            "response_time_ms": self.response_time_ms,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class RerankingModel:
    """Configuration for reranking models."""
    model_id: str
    name: str
    model_type: str  # cross-encoder, learned ranker, etc.
    base_model: str
    config: Dict[str, Any]
    is_active: bool
    performance_metrics: Dict[str, float]
    training_data_size: int
    last_trained: Optional[datetime]
    deployment_status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "model_type": self.model_type,
            "base_model": self.base_model,
            "config": self.config,
            "is_active": self.is_active,
            "performance_metrics": self.performance_metrics,
            "training_data_size": self.training_data_size,
            "last_trained": self.last_trained.isoformat() if self.last_trained else None,
            "deployment_status": self.deployment_status,
        }


@dataclass
class QueryExpansionRequest:
    """Request to expand a query using specified methods."""
    query: str
    expansion_methods: List[QueryExpansionMethod]
    max_terms: int = 10
    context: Optional[str] = None
    domain: Optional[str] = None


@dataclass
class RerankingRequest:
    """Request to rerank search results."""
    query: str
    candidates: List[Dict[str, Any]]  # items with scores and metadata
    strategy: RetrievalStrategy
    model_id: Optional[str] = None
    context: Optional[str] = None
    max_results: Optional[int] = None


@dataclass
class MultiStageRerankingRequest:
    """Request for multi-stage reranking pipeline."""
    query: str
    candidates: List[Dict[str, Any]]
    strategies: List[RetrievalStrategy]
    context: Optional[str] = None
    early_stopping: bool = True
    performance_threshold: float = 0.1


@dataclass
class QueryIntent:
    """Detected query intent for better retrieval."""
    intent_id: str
    query: str
    primary_intent: str
    secondary_intents: List[str]
    intent_confidence: float
    entities: List[str]
    context_requirements: List[str]
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "query": self.query,
            "primary_intent": self.primary_intent,
            "secondary_intents": self.secondary_intents,
            "intent_confidence": self.intent_confidence,
            "entities": self.entities,
            "context_requirements": self.context_requirements,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ContextualRetrievalRequest:
    """Request for context-aware retrieval."""
    query: str
    user_context: Dict[str, Any]
    session_context: Optional[Dict[str, Any]] = None
    domain_context: Optional[Dict[str, Any]] = None
    personalization_level: float = 0.5


@dataclass
class RetrievalConfiguration:
    """Configuration for retrieval system."""
    config_id: str
    name: str
    default_strategy: RetrievalStrategy
    query_expansion_enabled: bool
    reranking_enabled: bool
    contextual_ranking_enabled: bool
    diversity_threshold: float
    performance_targets: Dict[str, float]
    is_default: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_id": self.config_id,
            "name": self.name,
            "default_strategy": self.default_strategy.value,
            "query_expansion_enabled": self.query_expansion_enabled,
            "reranking_enabled": self.reranking_enabled,
            "contextual_ranking_enabled": self.contextual_ranking_enabled,
            "diversity_threshold": self.diversity_threshold,
            "performance_targets": self.performance_targets,
            "is_default": self.is_default,
        }


@dataclass
class AdvancedRetrievalRequest:
    """Comprehensive retrieval request combining all advanced features."""
    query: str
    candidates: List[Dict[str, Any]]
    enable_expansion: bool = True
    enable_reranking: bool = True
    enable_contextual: bool = True
    strategy: Optional[RetrievalStrategy] = None
    model_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    max_results: int = 20
    diversity_target: float = 0.3
