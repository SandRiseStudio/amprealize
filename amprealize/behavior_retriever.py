"""Hybrid behavior retrieval service used by the BCI pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import replace
from datetime import datetime, UTC, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:  # pragma: no cover - optional dependency
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    np = None  # type: ignore

from .behavior_service import BehaviorSearchResult, BehaviorService, SearchBehaviorsRequest
from .bci_contracts import BehaviorMatch, RetrieveRequest, RetrievalStrategy, RoleFocus
from .telemetry import TelemetryClient
from .storage.redis_cache import get_cache
from .storage.embedding_metrics import (
    record_model_load,
    record_retrieval_latency,
    record_retrieval_matches,
    increment_cache_hit,
    increment_cache_miss,
    record_degraded_mode,
    record_retrieval_failure,
    record_faiss_index_rebuild,
)

try:  # pragma: no cover - optional dependency
    from sentence_transformers import SentenceTransformer  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    SentenceTransformer = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import faiss  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    faiss = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from sqlalchemy.orm import Session  # type: ignore
    from .storage.postgres_pool import PostgresPool
    SQLALCHEMY_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    Session = None  # type: ignore
    PostgresPool = None  # type: ignore
    SQLALCHEMY_AVAILABLE = False

logger = logging.getLogger(__name__)

_DEFAULT_STORAGE_DIR = Path.home() / ".amprealize" / "data"
_DEFAULT_INDEX_PATH = _DEFAULT_STORAGE_DIR / "behavior_index.faiss"
_DEFAULT_METADATA_PATH = _DEFAULT_STORAGE_DIR / "behavior_index.json"


class BehaviorRetriever:
    """Retrieves behaviors using semantic, keyword, or hybrid strategies.

    The retriever relies on SentenceTransformer + FAISS for semantic retrieval
    when those dependencies are available. If they are missing, it gracefully
    falls back to keyword search using :class:`BehaviorService` to preserve
    functionality during unit tests or lightweight installations.

    Phase 1 Optimization (behavior_curate_behavior_handbook):
    - Lazy loading: Model loads on first use instead of container startup
    - Class-level singleton: Shared model across instances reduces memory
    - Quantized model: sentence-transformers/all-MiniLM-L6-v2 (80MB) vs BGE-M3 (2.3GB)
    - Environment configuration: EMBEDDING_MODEL_NAME, EMBEDDING_MODEL_LAZY_LOAD

    Phase 2 Gradual Rollout (behavior_wire_cli_to_orchestrator):
    - EMBEDDING_ROLLOUT_PERCENTAGE: 0-100 controls traffic split for A/B testing
    - Dict of shared models: Supports both new model + baseline during rollout
    - Deterministic user_id hashing: Ensures consistent cohort assignment
    """

    # Phase 2: Dict of shared models keyed by model name (supports A/B testing during rollout)
    _shared_models: Dict[str, Any] = {}
    _model_lock = threading.Lock()

    def __init__(
        self,
        *,
        behavior_service: Optional[BehaviorService] = None,
        telemetry: Optional[TelemetryClient] = None,
        model_name: Optional[str] = None,
        index_path: Path = _DEFAULT_INDEX_PATH,
        metadata_path: Path = _DEFAULT_METADATA_PATH,
        device: Optional[str] = None,
        use_database: bool = False,
        db_dsn: Optional[str] = None,
        cache_ttl: int = 600,  # 10 minutes for retrieval results
        eager_load_model: Optional[bool] = None,  # Defaults from EMBEDDING_MODEL_LAZY_LOAD env var
    ) -> None:
        self._behavior_service = behavior_service
        self._telemetry = telemetry or TelemetryClient.noop()

        # Phase 2 gradual rollout: Support A/B testing between models
        # EMBEDDING_ROLLOUT_PERCENTAGE=0-100 controls traffic split
        # 0 = all traffic to baseline (BGE-M3), 100 = all traffic to new model
        rollout_pct_str = os.getenv("EMBEDDING_ROLLOUT_PERCENTAGE", "100")
        try:
            self._rollout_percentage = int(rollout_pct_str)
            if not (0 <= self._rollout_percentage <= 100):
                logger.warning(
                    "EMBEDDING_ROLLOUT_PERCENTAGE must be 0-100, got %s; defaulting to 100",
                    rollout_pct_str,
                )
                self._rollout_percentage = 100
        except ValueError:
            logger.warning(
                "EMBEDDING_ROLLOUT_PERCENTAGE must be integer, got %s; defaulting to 100",
                rollout_pct_str,
            )
            self._rollout_percentage = 100

        # Support environment-based model configuration (behavior_externalize_configuration)
        self._model_name = model_name or os.getenv(
            "EMBEDDING_MODEL_NAME",
            "sentence-transformers/all-MiniLM-L6-v2"  # Default to Phase 1 optimized model
        )

        # Baseline model for rollout comparison (always BGE-M3)
        self._baseline_model_name = "BAAI/bge-m3"

        self._index_path = index_path
        self._metadata_path = metadata_path
        self._device = device
        self._use_database = use_database
        self._db_dsn = db_dsn
        self._db_pool: Optional[Any] = None
        self._cache_ttl = cache_ttl

        # Support lazy loading via env var (behavior_externalize_configuration)
        if eager_load_model is None:
            # EMBEDDING_MODEL_LAZY_LOAD=true means eager_load_model=False
            lazy_load_env = os.getenv("EMBEDDING_MODEL_LAZY_LOAD", "false").lower()
            eager_load_model = lazy_load_env not in ("true", "1", "yes")

        self._eager_load_model = eager_load_model

        self._semantic_available = SentenceTransformer is not None and faiss is not None and np is not None
        self._model: Optional[Any] = None
        self._index: Any = None
        self._behavior_ids: List[str] = []
        self._behavior_cache: Dict[str, Dict[str, Any]] = {}

        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database connection pool if use_database=True
        if self._use_database and SQLALCHEMY_AVAILABLE and self._db_dsn:
            try:
                assert PostgresPool is not None
                self._db_pool = PostgresPool(self._db_dsn)
                logger.info("BehaviorRetriever database connection pool initialized")
            except Exception as exc:
                logger.warning("Failed to initialize database pool; falling back to filesystem only: %s", exc)
                self._use_database = False
        elif self._use_database and not SQLALCHEMY_AVAILABLE:
            logger.warning("SQLAlchemy not available; falling back to filesystem-only mode")
            self._use_database = False

        if self._semantic_available:
            # Eagerly load model at initialization to avoid per-query overhead
            # When EMBEDDING_MODEL_LAZY_LOAD=true, model loads on first retrieve() call
            if self._eager_load_model:
                try:
                    self._load_model()
                    logger.info("BehaviorRetriever model %s loaded at initialization", self._model_name)
                except Exception as exc:
                    logger.warning("Failed to eagerly load model; will load on first use: %s", exc)
            else:
                logger.info(
                    "BehaviorRetriever lazy loading enabled; model %s will load on first use",
                    self._model_name,
                )
            self._load_index()
        else:
            logger.info(
                "Semantic retrieval dependencies missing; operating in keyword-only mode."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return "semantic" if self._semantic_available else "keyword"

    def ensure_ready(self) -> Dict[str, Any]:
        if not self._semantic_available:
            record_degraded_mode("dependencies-missing")
            return {
                "status": "degraded",
                "mode": "keyword",
                "reason": "sentence-transformers and faiss not available (install amprealize[ml] to enable semantic retrieval)",
            }
        if self._index is None or not self._behavior_ids:
            return self.build_index()
        return {
            "status": "ready",
            "mode": "semantic",
            "behavior_count": len(self._behavior_ids),
            "model": self._model_name,
        }

    def build_index(self) -> Dict[str, Any]:
        if not self._semantic_available:
            record_degraded_mode("dependencies-missing")
            return {
                "status": "degraded",
                "mode": "keyword",
                "reason": "semantic dependencies unavailable",
            }
        if self._behavior_service is None:
            return {
                "status": "error",
                "reason": "behavior service not configured",
            }

        # Track index rebuild time (Phase 2 monitoring)
        rebuild_start = time.time()

        assert faiss is not None  # narrow optional dependency for type checkers
        approved = self._behavior_service.list_behaviors(status="APPROVED")
        candidates = [entry for entry in approved if entry.get("active_version")]
        if not candidates:
            self._index = faiss.IndexFlatIP(1)
            self._behavior_ids = []
            self._behavior_cache = {}
            self._persist_index()
            record_faiss_index_rebuild(0, time.time() - rebuild_start)
            return {
                "status": "ready",
                "mode": "semantic",
                "behavior_count": 0,
                "model": self._model_name,
            }

        texts = []
        embeddings_list = []
        ids_for_texts = []

        # Separate candidates into those with pre-computed embeddings and those needing encoding
        for entry in candidates:
            version = entry.get("active_version", {})
            embedding = version.get("embedding")
            if embedding and len(embedding) > 0:
                embeddings_list.append(embedding)
            else:
                texts.append(self._build_embedding_text(entry))
                ids_for_texts.append(len(embeddings_list) + len(texts) - 1) # Placeholder index

        model = self._load_model()

        # Encode missing texts
        if texts:
            new_embeddings = model.encode(texts, convert_to_numpy=True)  # pragma: no cover - heavy path
            # Insert new embeddings into the list (preserving order is tricky if we split them)
            # Actually, we need to preserve the order of candidates to match self._behavior_ids
            # So let's rebuild the full list of embeddings in order
            pass

        # Re-do the loop to build the full embedding matrix in order
        final_embeddings = []
        texts_to_encode = []
        indices_to_fill = []

        for idx, entry in enumerate(candidates):
            version = entry.get("active_version", {})
            embedding = version.get("embedding")
            if embedding and len(embedding) > 0:
                final_embeddings.append(embedding)
            else:
                final_embeddings.append(None) # Placeholder
                texts_to_encode.append(self._build_embedding_text(entry))
                indices_to_fill.append(idx)

        if texts_to_encode:
            encoded = model.encode(texts_to_encode, convert_to_numpy=True)
            for i, idx in enumerate(indices_to_fill):
                final_embeddings[idx] = encoded[i]

        embeddings = np.array(final_embeddings, dtype=np.float32)

        faiss.normalize_L2(embeddings)  # pragma: no cover - heavy path  # type: ignore[attr-defined]

        # Use IndexIVFPQ for large behavior sets (>1000) for faster retrieval
        # IndexFlatIP for smaller sets maintains exact search quality
        # Following behavior_curate_behavior_handbook for 250ms P95 target
        n_behaviors = embeddings.shape[0]
        dim = embeddings.shape[1]

        if n_behaviors > 1000:
            # IndexIVFPQ: Approximate search with product quantization
            # nlist: number of clusters for inverted index
            # m: number of subquantizers (must divide dimension)
            # nbits: bits per subquantizer (8 = 256 centroids per subspace)
            nlist = min(256, n_behaviors // 4)  # Fewer clusters for smaller datasets
            m = 8  # 8 subquantizers for 384-dim vectors (all-MiniLM-L6-v2)
            nbits = 8  # Standard 8-bit quantization

            # Quantizer for IVF (inner product)
            quantizer = faiss.IndexFlatIP(dim)  # pragma: no cover - heavy path

            # Create IVF index with PQ compression
            index = faiss.IndexIVFPQ(quantizer, dim, nlist, m, nbits, faiss.METRIC_INNER_PRODUCT)  # pragma: no cover - heavy path

            # Train the index on embeddings (required for IVF)
            index.train(embeddings)  # pragma: no cover - heavy path
            index.add(embeddings)  # pragma: no cover - heavy path

            # Set nprobe for quality vs speed tradeoff
            # Higher nprobe = more accurate but slower
            index.nprobe = min(16, nlist // 2)  # pragma: no cover - heavy path

            logger.info(
                "Built IndexIVFPQ for %d behaviors (nlist=%d, m=%d, nprobe=%d)",
                n_behaviors, nlist, m, index.nprobe
            )
        else:
            # IndexFlatIP: Exact search for smaller datasets
            index = faiss.IndexFlatIP(dim)  # pragma: no cover - heavy path
            index.add(embeddings)  # pragma: no cover - heavy path  # type: ignore[arg-type]

            logger.info("Built IndexFlatIP for %d behaviors (exact search)", n_behaviors)

        self._index = index  # pragma: no cover - heavy path
        # Convert UUIDs to strings for JSON serialization
        self._behavior_ids = [str(entry["behavior"]["behavior_id"]) for entry in candidates]
        self._behavior_cache = {
            str(entry["behavior"]["behavior_id"]): self._behavior_snapshot(entry)
            for entry in candidates
        }
        self._persist_index()

        rebuild_duration = time.time() - rebuild_start
        record_faiss_index_rebuild(len(self._behavior_ids), rebuild_duration)

        self._telemetry.emit_event(
            event_type="bci.behavior_retriever.index_built",
            payload={
                "behavior_count": len(self._behavior_ids),
                "model_name": self._model_name,
                "index_type": "ivfpq" if n_behaviors > 1000 else "flat",
            },
        )

        # Invalidate retrieval cache since index changed
        try:
            get_cache().invalidate_service('retriever')
            logger.info("Invalidated retriever cache after index rebuild")
        except Exception as exc:
            logger.debug("Cache invalidation failed: %s", exc)

        return {
            "status": "ready",
            "mode": "semantic",
            "behavior_count": len(self._behavior_ids),
            "model": self._model_name,
        }

    def retrieve(self, request: RetrieveRequest) -> List[BehaviorMatch]:
        """Retrieve behaviors using caching + semantic/keyword/hybrid strategies.

        Performance optimizations:
        - Redis cache for query results (600s TTL)
        - Lazily loaded model (no per-query loading overhead after first use)
        - Cache key includes query hash + strategy + filters

        E3 Runtime Injection enhancements:
        - Pack-scoped boosting: behaviors in active pack's behavior_refs get 2× score
        - Profile-enriched query: workspace_profile + task_type prepended to embedding query
        - Surface weighting: behaviors tagged with matching surface get 1.1× boost
        - Deterministic fallback: rule-based results when embedding scores are low

        Phase 2 Gradual Rollout:
        - Determines model cohort based on user_id hashing (A/B testing)
        - Routes to all-MiniLM-L6-v2 or BGE-M3 based on EMBEDDING_ROLLOUT_PERCENTAGE
        - Labels metrics with model_name for cohort comparison

        Phase 2 Monitoring (behavior_instrument_metrics_pipeline):
        - Tracks retrieval latency against <250ms P95 SLO target
        - Records cache hits/misses for token savings measurement
        - Emits degraded mode events when semantic unavailable
        """
        # Determine which model cohort to use for this request (Phase 2 rollout)
        cohort_model = self._determine_model_for_cohort(request.user_id)

        # Track retrieval latency for Phase 2 SLO monitoring
        retrieval_start = time.time()

        try:
            # For EMBEDDING strategy, we don't need BehaviorService (uses FAISS directly)
            # For KEYWORD/HYBRID, we need BehaviorService for keyword search
            if request.strategy != RetrievalStrategy.EMBEDDING and not self._behavior_service:
                return []

            # Check cache first
            cache = get_cache()
            cache_params = {
                "query": request.query,
                "strategy": request.strategy.value,
                "top_k": request.top_k,
                "tags": sorted(request.tags) if request.tags else [],
                "role_focus": request.role_focus.value if request.role_focus else None,
                "include_metadata": request.include_metadata,
                "namespace": request.namespace,
                # E3: include context signals in cache key
                "workspace_profile": request.workspace_profile,
                "active_pack_id": request.active_pack_id,
                "surface": request.surface,
                "task_type": request.task_type,
                "phase": request.phase,
            }
            cache_key = cache._make_key("retriever", "query", cache_params)

            try:
                cached = cache.get(cache_key)
                if cached is not None:
                    logger.debug("Cache hit for retrieval query: %s", cache_key)
                    increment_cache_hit(request.strategy.value)
                    self._telemetry.emit_event(
                        event_type="bci.behavior_retriever.cache_hit",
                        payload={"cache_key": cache_key, "query_length": len(request.query or "")},
                    )
                    # Deserialize cached matches
                    matches = [self._match_from_dict(match_dict) for match_dict in cached]
                    record_retrieval_latency(request.strategy.value, time.time() - retrieval_start, cohort_model)
                    record_retrieval_matches(request.strategy.value, len(matches), cohort_model)
                    return matches
            except Exception as exc:
                logger.debug("Cache lookup failed: %s", exc)

            # Cache miss - perform retrieval
            increment_cache_miss(request.strategy.value)

            if not self._semantic_available:
                matches = self._keyword_retrieve(request, limit=request.top_k)
                self._emit_retrieval_event(request, matches, "keyword")
                self._cache_matches(cache_key, matches)
                record_retrieval_latency("keyword-degraded", time.time() - retrieval_start, cohort_model)
                record_retrieval_matches("keyword-degraded", len(matches), cohort_model)
                record_degraded_mode("dependencies-missing")
                return matches

            ready = self.ensure_ready()
            if ready.get("status") != "ready":
                matches = self._keyword_retrieve(request, limit=request.top_k)
                self._emit_retrieval_event(request, matches, "keyword-degraded")
                self._cache_matches(cache_key, matches)
                record_retrieval_latency("keyword-degraded", time.time() - retrieval_start, cohort_model)
                record_retrieval_matches("keyword-degraded", len(matches), cohort_model)
                record_degraded_mode("index-not-ready")
                return matches

            embedding_matches = self._embedding_retrieve(request, cohort_model)
            if request.strategy == RetrievalStrategy.EMBEDDING:
                matches = embedding_matches[: request.top_k]
                matches = self._apply_context_boosts(matches, request)
                matches = self._apply_fallback_rules(request, matches)
                self._emit_retrieval_event(request, matches, "semantic")
                self._cache_matches(cache_key, matches)
                record_retrieval_latency(request.strategy.value, time.time() - retrieval_start, cohort_model)
                record_retrieval_matches(request.strategy.value, len(matches), cohort_model)
                return matches

            keyword_matches = self._keyword_retrieve(request, limit=max(request.top_k * 3, 15))
            if request.strategy == RetrievalStrategy.KEYWORD:
                matches = keyword_matches[: request.top_k]
                matches = self._apply_context_boosts(matches, request)
                matches = self._apply_fallback_rules(request, matches)
                self._emit_retrieval_event(request, matches, "keyword")
                self._cache_matches(cache_key, matches)
                record_retrieval_latency(request.strategy.value, time.time() - retrieval_start, cohort_model)
                record_retrieval_matches(request.strategy.value, len(matches), cohort_model)
                return matches

            matches = self._merge_hybrid(embedding_matches, keyword_matches, request)
            # E3: apply context-aware boosts and fallback rules
            matches = self._apply_context_boosts(matches, request)
            matches = self._apply_fallback_rules(request, matches)
            self._emit_retrieval_event(request, matches, "hybrid")
            self._cache_matches(cache_key, matches)
            record_retrieval_latency(request.strategy.value, time.time() - retrieval_start, cohort_model)
            record_retrieval_matches(request.strategy.value, len(matches), cohort_model)
            return matches

        except Exception as exc:
            logger.exception("Retrieval failed: %s", exc)
            error_type = type(exc).__name__
            record_retrieval_failure(error_type)
            raise
        return matches

    def retrieve_batch(self, requests: List[RetrieveRequest]) -> List[List[BehaviorMatch]]:
        """Batch retrieve behaviors for multiple queries (reduces model inference overhead).

        Performance benefit: Process N queries in one model.encode() call instead of N calls,
        reducing overhead from ~10-50s to single batch inference (~2-5s for 10 queries).

        Args:
            requests: List of retrieval requests to process in batch

        Returns:
            List of match lists, one per request (same order as input)
        """
        if not requests:
            return []

        if not self._semantic_available or not self._behavior_service:
            # Fall back to individual retrieval for keyword-only mode
            return [self.retrieve(req) for req in requests]

        ready = self.ensure_ready()
        if ready.get("status") != "ready":
            return [self.retrieve(req) for req in requests]

        # If the semantic index has no behaviors, short-circuit to avoid
        # unnecessary model encodes (common in fresh developer environments).
        if self._index is None or not self._behavior_ids:
            self._telemetry.emit_event(
                event_type="bci.behavior_retriever.batch_retrieve",
                payload={
                    "batch_size": len(requests),
                    "cache_hits": 0,
                    "cache_misses": 0,
                    "reason": "empty-index",
                },
            )
            return [[] for _ in requests]

        # Check cache for all requests first
        cache = get_cache()
        results: List[Optional[List[BehaviorMatch]]] = [None] * len(requests)
        uncached_indices: List[int] = []
        uncached_queries: List[str] = []

        for idx, request in enumerate(requests):
            cache_params = {
                "query": request.query,
                "strategy": request.strategy.value,
                "top_k": request.top_k,
                "tags": sorted(request.tags) if request.tags else [],
                "role_focus": request.role_focus.value if request.role_focus else None,
                "include_metadata": request.include_metadata,
            }
            cache_key = cache._make_key("retriever", "query", cache_params)

            try:
                cached = cache.get(cache_key)
                if cached is not None:
                    results[idx] = [self._match_from_dict(match_dict) for match_dict in cached]
                else:
                    uncached_indices.append(idx)
                    uncached_queries.append(request.query)
            except Exception:
                uncached_indices.append(idx)
                uncached_queries.append(request.query)

        # Batch encode uncached queries
        if uncached_queries:
            model = self._load_model()
            query_embeddings = model.encode(uncached_queries, convert_to_numpy=True)  # pragma: no cover
            assert faiss is not None
            faiss.normalize_L2(query_embeddings)  # pragma: no cover  # type: ignore[attr-defined]

            # Process each uncached request with pre-computed embedding
            for embedding_idx, request_idx in enumerate(uncached_indices):
                request = requests[request_idx]
                matches = self._embedding_retrieve_with_vector(
                    request, query_embeddings[embedding_idx]
                )

                # Apply strategy-specific processing
                if request.strategy == RetrievalStrategy.EMBEDDING:
                    final_matches = matches[: request.top_k]
                    mode = "semantic"
                elif request.strategy == RetrievalStrategy.KEYWORD:
                    final_matches = self._keyword_retrieve(request, limit=request.top_k)
                    mode = "keyword"
                else:  # HYBRID
                    keyword_matches = self._keyword_retrieve(request, limit=max(request.top_k * 3, 15))
                    final_matches = self._merge_hybrid(matches, keyword_matches, request)
                    mode = "hybrid"

                results[request_idx] = final_matches
                self._emit_retrieval_event(request, final_matches, mode)

                # Cache the result
                cache_params = {
                    "query": request.query,
                    "strategy": request.strategy.value,
                    "top_k": request.top_k,
                    "tags": sorted(request.tags) if request.tags else [],
                    "role_focus": request.role_focus.value if request.role_focus else None,
                    "include_metadata": request.include_metadata,
                }
                cache_key = cache._make_key("retriever", "query", cache_params)
                self._cache_matches(cache_key, final_matches)

        # Emit batch telemetry
        self._telemetry.emit_event(
            event_type="bci.behavior_retriever.batch_retrieve",
            payload={
                "batch_size": len(requests),
                "cache_hits": len(requests) - len(uncached_indices),
                "cache_misses": len(uncached_indices),
            },
        )

        return [r for r in results if r is not None]  # type: ignore[misc]

    def rebuild_index(self) -> Dict[str, Any]:
        result = self.build_index()
        result.setdefault("mode", self.mode)
        result.setdefault("status", "ready" if result.get("mode") == "semantic" else "degraded")
        result["timestamp"] = datetime.now(UTC).isoformat()
        return result

    # ------------------------------------------------------------------
    # E3 Runtime Injection — context-aware boosts & fallbacks
    # ------------------------------------------------------------------

    # Profile → default behavior names (seeded from AGENTS.md Quick Triggers)
    _PROFILE_DEFAULT_BEHAVIORS: Dict[str, List[str]] = {
        "amprealize-platform": [
            "behavior_prefer_mcp_tools",
            "behavior_use_raze_for_logging",
            "behavior_prevent_secret_leaks",
        ],
        "extension-dev": [
            "behavior_integrate_vscode_extension",
            "behavior_prefer_mcp_tools",
        ],
        "api-backend": [
            "behavior_design_api_contract",
            "behavior_use_raze_for_logging",
        ],
        "compliance-sensitive": [
            "behavior_prevent_secret_leaks",
            "behavior_lock_down_security_surface",
        ],
    }

    # Role → mandatory behaviors
    _ROLE_MANDATORY_BEHAVIORS: Dict[str, List[str]] = {
        "STRATEGIST": ["behavior_curate_behavior_handbook"],
        "TEACHER": ["behavior_update_docs_after_changes"],
    }

    def _apply_context_boosts(
        self, matches: List[BehaviorMatch], request: RetrieveRequest
    ) -> List[BehaviorMatch]:
        """Apply pack-scoped, surface, profile-aware, and phase-aware boosts to matches.

        E3 Runtime Injection (AMPREALIZE-288 / T3.2.1):
        - pack_behavior_refs: 2× boost for behaviors in active pack
        - surface: 1.1× boost for behaviors tagged with matching surface

        E3 S3.9 (T3.9.2):
        - phase: boost behaviors whose tags match the current GEP phase's boost_tags
        """
        if not matches:
            return matches

        pack_refs = set(request.pack_behavior_refs or [])
        surface = request.surface
        phase = request.phase

        # Import phase boost config
        from .bci_contracts import PHASE_BOOST_CONFIG
        phase_config = PHASE_BOOST_CONFIG.get(phase, {}) if phase else {}
        phase_boost_tags = set(t.lower() for t in phase_config.get("boost_tags", []))
        phase_boost_factor = phase_config.get("boost_factor", 1.0)

        if not pack_refs and not surface and not phase_boost_tags:
            return matches

        boosted: List[BehaviorMatch] = []
        for m in matches:
            score = m.score

            # Pack boost: behaviors referenced by the active pack get 2× score
            if pack_refs and (m.behavior_id in pack_refs or m.name in pack_refs):
                score *= 2.0

            # Surface boost: behaviors whose tags mention the surface get 1.1×
            if surface and m.tags:
                surface_lower = surface.lower()
                if any(surface_lower in tag.lower() for tag in m.tags):
                    score *= 1.1

            # Phase boost: behaviors whose tags overlap with the GEP phase's boost_tags
            if phase_boost_tags and m.tags:
                match_tags = set(t.lower() for t in m.tags)
                if match_tags & phase_boost_tags:
                    score *= phase_boost_factor

            if score != m.score:
                boosted.append(replace(m, score=score))
            else:
                boosted.append(m)

        # Re-sort and trim after boosting
        boosted.sort(key=lambda b: b.score, reverse=True)
        return boosted[: request.top_k]

    def _apply_fallback_rules(
        self, request: RetrieveRequest, results: List[BehaviorMatch]
    ) -> List[BehaviorMatch]:
        """Inject deterministic behaviors when embedding results are weak.

        Triggers when: top score < 0.3, no results, or pack_behavior_refs
        specified but none present in results.

        E3 Runtime Injection (AMPREALIZE-288 / T3.2.3).
        """
        # Only trigger when results look weak
        top_score = results[0].score if results else 0.0
        needs_fallback = (
            not results
            or top_score < 0.3
            or (
                request.pack_behavior_refs
                and not any(
                    m.behavior_id in request.pack_behavior_refs
                    or m.name in request.pack_behavior_refs
                    for m in results
                )
            )
        )
        if not needs_fallback:
            return results

        # Collect fallback behavior names (deduplicated)
        fallback_names: List[str] = []
        seen: set[str] = set()

        # 1. Pack behavior refs
        for ref in request.pack_behavior_refs or []:
            if ref not in seen:
                fallback_names.append(ref)
                seen.add(ref)

        # 2. Profile defaults
        if request.workspace_profile:
            for name in self._PROFILE_DEFAULT_BEHAVIORS.get(
                request.workspace_profile, []
            ):
                if name not in seen:
                    fallback_names.append(name)
                    seen.add(name)

        # 3. Role mandatory
        if request.role_focus:
            for name in self._ROLE_MANDATORY_BEHAVIORS.get(
                request.role_focus.value, []
            ):
                if name not in seen:
                    fallback_names.append(name)
                    seen.add(name)

        if not fallback_names:
            return results

        # Build fallback matches with a low synthetic score
        existing_ids = {m.behavior_id for m in results} | {m.name for m in results}
        fallback_matches: List[BehaviorMatch] = []
        for name in fallback_names:
            if name in existing_ids:
                continue
            fallback_matches.append(
                BehaviorMatch(
                    behavior_id=name,
                    name=name,
                    version="fallback",
                    instruction="",
                    score=0.1,
                    strategy_breakdown={"fallback": 0.1},
                    citation_label=name,
                )
            )

        # Merge: existing results first, then fallbacks
        merged = list(results) + fallback_matches
        return merged[: request.top_k]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _cache_matches(self, cache_key: str, matches: List[BehaviorMatch]) -> None:
        """Cache retrieval matches with configured TTL."""
        try:
            cache = get_cache()
            serialized = [self._match_to_dict(match) for match in matches]
            cache.set(cache_key, serialized, ttl=self._cache_ttl)
            logger.debug("Cached %d matches with key: %s", len(matches), cache_key)
        except Exception as exc:
            logger.debug("Failed to cache matches: %s", exc)

    def _match_to_dict(self, match: BehaviorMatch) -> Dict[str, Any]:
        """Serialize BehaviorMatch for caching."""
        return {
            "behavior_id": match.behavior_id,
            "name": match.name,
            "version": match.version,
            "instruction": match.instruction,
            "score": match.score,
            "description": match.description,
            "role_focus": match.role_focus.value if match.role_focus else None,
            "tags": list(match.tags) if match.tags else [],
            "strategy_breakdown": dict(match.strategy_breakdown) if match.strategy_breakdown else {},
            "citation_label": match.citation_label,
            "metadata": match.metadata,
        }

    def _match_from_dict(self, data: Dict[str, Any]) -> BehaviorMatch:
        """Deserialize BehaviorMatch from cache."""
        return BehaviorMatch(
            behavior_id=data["behavior_id"],
            name=data["name"],
            version=data["version"],
            instruction=data["instruction"],
            score=float(data["score"]),
            description=data.get("description"),
            role_focus=self._role_focus_from_str(data.get("role_focus")),
            tags=data.get("tags", []),
            strategy_breakdown=data.get("strategy_breakdown", {}),
            citation_label=data.get("citation_label"),
            metadata=data.get("metadata"),
        )

    def _determine_model_for_cohort(self, user_id: Optional[str] = None) -> str:
        """Determine which model to use based on gradual rollout percentage.

        Uses deterministic hash-based routing to ensure consistent model selection
        for the same user across requests (required for A/B testing validity).

        Args:
            user_id: User identifier for deterministic routing. If None, uses
                    session-level routing based on thread ID (less reliable but
                    ensures some request consistency).

        Returns:
            Model name to use (either self._model_name or self._baseline_model_name)

        Phase 2 Rollout Logic:
        - EMBEDDING_ROLLOUT_PERCENTAGE=0: All traffic to baseline (BGE-M3)
        - EMBEDDING_ROLLOUT_PERCENTAGE=50: 50% to new model, 50% to baseline
        - EMBEDDING_ROLLOUT_PERCENTAGE=100: All traffic to new model
        - Hash(user_id) % 100 < rollout_percentage → new model, else baseline

        Behavior: behavior_wire_cli_to_orchestrator
        """
        # 100% rollout → always use new model (optimization path)
        if self._rollout_percentage == 100:
            return self._model_name

        # 0% rollout → always use baseline (safety off-ramp)
        if self._rollout_percentage == 0:
            return self._baseline_model_name

        # Deterministic routing: hash user_id to [0, 99] bucket
        if user_id is None:
            # Fallback: use thread ID for some request consistency
            # Note: This is weaker than user_id routing but ensures repeatable
            # behavior for multi-retrieval workflows in the same thread
            user_id = str(threading.current_thread().ident)

        # SHA256 hash → integer → modulo 100 for uniform distribution
        hash_bytes = hashlib.sha256(user_id.encode("utf-8")).digest()
        bucket = int.from_bytes(hash_bytes[:4], byteorder="big") % 100

        # Route to new model if bucket < rollout_percentage
        if bucket < self._rollout_percentage:
            return self._model_name
        else:
            return self._baseline_model_name

    def _load_model(self, model_name: Optional[str] = None) -> Any:
        """Load embedding model with thread-safe lazy loading and singleton caching.

        Implements double-checked locking pattern to ensure only one model instance
        is loaded across all BehaviorRetriever instances (reduces memory footprint).

        Phase 2 Rollout: Supports loading multiple models (new model + baseline) for
        A/B testing during gradual rollout. Each model is cached separately by name.

        When uvicorn runs with --preload, models are shared across worker processes.
        First request will be ~10-20s slower (model load), subsequent requests fast.

        Args:
            model_name: Model to load. If None, uses self._model_name.

        Phase 2 Monitoring (behavior_instrument_metrics_pipeline):
        - Tracks model load count (should be ≤2 during rollout for A/B testing)
        - Records model load time for lazy loading overhead measurement
        - Emits memory footprint against <750MB SLO target (when available)

        Behavior: behavior_curate_behavior_handbook
        """
        if not self._semantic_available:
            raise RuntimeError("Semantic retrieval dependencies unavailable")

        # Default to configured model name
        if model_name is None:
            model_name = self._model_name

        # Fast path: model already loaded in shared cache
        if model_name in BehaviorRetriever._shared_models:
            return BehaviorRetriever._shared_models[model_name]

        # Slow path: Load model with thread-safe locking (first-use only per model)
        with BehaviorRetriever._model_lock:
            # Double-check: another thread may have loaded while we waited
            if model_name in BehaviorRetriever._shared_models:
                return BehaviorRetriever._shared_models[model_name]

            logger.info("Loading behavior retriever model %s (first use, expect 10-20s delay)", model_name)
            load_start = time.time()

            if SentenceTransformer is None:  # pragma: no cover - defensive
                raise RuntimeError("SentenceTransformer dependency unavailable")

            try:
                loaded_model = SentenceTransformer(
                    model_name,
                    device=self._device
                )  # pragma: no cover - heavy path
                BehaviorRetriever._shared_models[model_name] = loaded_model

                load_duration = time.time() - load_start
                logger.info(
                    "Model %s loaded successfully in %.2fs (shared across instances, %d models total)",
                    model_name,
                    load_duration,
                    len(BehaviorRetriever._shared_models),
                )

                # Track model load for Phase 2 monitoring (behavior_instrument_metrics_pipeline)
                try:
                    # Get model dimensions if available
                    dimensions = getattr(loaded_model, "get_sentence_embedding_dimension", lambda: None)()

                    # Attempt to measure memory footprint (best-effort)
                    # Note: Accurate memory tracking requires process-level RSS monitoring
                    # or model-specific size estimation. This is a placeholder for future enhancement.
                    memory_bytes = None

                    record_model_load(
                        model_name=model_name,
                        load_time_seconds=load_duration,
                        memory_bytes=memory_bytes,
                        dimensions=dimensions,
                        device=str(self._device) if self._device else "cpu",
                    )
                except Exception as exc:
                    logger.debug("Failed to record model load metrics: %s", exc)

                # Emit telemetry for model loading (behavior_instrument_metrics_pipeline)
                self._telemetry.emit_event(
                    event_type="bci.behavior_retriever.model_loaded",
                    payload={
                        "model_name": model_name,
                        "load_duration_seconds": load_duration,
                        "lazy_load": not self._eager_load_model,
                    },
                )

            except Exception as exc:
                logger.exception("Failed to load embedding model %s: %s", model_name, exc)
                record_degraded_mode("model-load-failed")
                raise

            return loaded_model

    def _load_index(self) -> None:
        if not self._index_path.exists() or not self._metadata_path.exists():
            return
        try:
            assert faiss is not None  # narrow optional dependency for type checkers
            self._index = faiss.read_index(str(self._index_path))  # pragma: no cover - heavy path  # type: ignore[attr-defined]
            with self._metadata_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self._behavior_ids = payload.get("behavior_ids", [])
            self._behavior_cache = payload.get("behaviors", {})
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load behavior index; rebuilding. Error: %s", exc)
            self._index = None
            self._behavior_ids = []
            self._behavior_cache = {}

    def _persist_index(self) -> None:
        """Persist index to filesystem and optionally to PostgreSQL (dual-write mode).

        When use_database=True, writes embeddings to both filesystem (for compatibility)
        and PostgreSQL behavior_embeddings table (for multi-node consistency).
        """
        if not self._semantic_available or self._index is None:
            return

        # Always write to filesystem (Phase 1: dual-write; Phase 4: fallback only)
        assert faiss is not None  # narrow optional dependency for type checkers
        faiss.write_index(self._index, str(self._index_path))  # pragma: no cover - heavy path  # type: ignore[attr-defined]
        payload = {
            "model": self._model_name,
            "behavior_ids": self._behavior_ids,
            "behaviors": self._behavior_cache,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        with self._metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

        # Write to database if dual-write mode enabled (Phase 1: preparation)
        if self._use_database and self._db_pool:
            try:
                self._write_to_database()
                logger.info("Dual-write: embeddings persisted to both filesystem and PostgreSQL")
            except Exception as exc:
                logger.error("Failed to persist embeddings to database (filesystem write succeeded): %s", exc)

    def _write_to_database(self) -> None:
        """Write embeddings to PostgreSQL behavior_embeddings table.

        Performs UPSERT (INSERT ... ON CONFLICT UPDATE) to handle incremental updates.
        Computes SHA-256 checksums of embedding bytes for consistency validation.
        """
        if not self._db_pool or not self._semantic_available or self._index is None:
            return

        assert faiss is not None  # narrow optional dependency for type checkers

        # Extract embeddings from FAISS index
        index_size = self._index.ntotal
        if index_size == 0:
            logger.info("No embeddings to persist (empty index)")
            return

        # Reconstruct vectors from FAISS IndexFlatIP
        embeddings = self._index.reconstruct_n(0, index_size)  # pragma: no cover - heavy path

        # Build list of (behavior_id, version, embedding, metadata) tuples
        rows_to_insert = []
        for idx, behavior_id in enumerate(self._behavior_ids):
            if idx >= embeddings.shape[0]:
                logger.warning("Behavior ID %s out of range for embeddings array", behavior_id)
                continue

            cached = self._behavior_cache.get(behavior_id)
            if not cached:
                logger.warning("Behavior %s not found in cache; skipping database write", behavior_id)
                continue

            embedding_vec = embeddings[idx].tolist()
            embedding_bytes = embeddings[idx].tobytes()
            checksum = hashlib.sha256(embedding_bytes).hexdigest()

            rows_to_insert.append({
                "behavior_id": behavior_id,
                "version": cached.get("version", "1.0.0"),
                "embedding": embedding_vec,
                "name": cached.get("name", ""),
                "instruction": cached.get("instruction", ""),
                "description": cached.get("description"),
                "role_focus": cached.get("role_focus", ""),
                "tags": json.dumps(cached.get("tags", [])),
                "trigger_keywords": json.dumps([]),  # Not currently extracted
                "metadata": json.dumps(cached.get("metadata", {})),
                "citation_label": cached.get("citation_label"),
                "embedding_checksum": checksum,
                "model_name": self._model_name,
            })

        if not rows_to_insert:
            logger.warning("No valid rows to insert into behavior_embeddings")
            return

        # Execute batch UPSERT
        with self._db_pool.connection() as conn:
            with conn.cursor() as cur:  # type: ignore[misc]
                # PostgreSQL UPSERT: INSERT ... ON CONFLICT (behavior_id, version) DO UPDATE
                upsert_sql = """
                    INSERT INTO behavior_embeddings (
                        behavior_id, version, embedding, name, instruction, description,
                        role_focus, tags, trigger_keywords, metadata, citation_label,
                        embedding_checksum, model_name, created_at, updated_at
                    ) VALUES (
                        %(behavior_id)s, %(version)s, %(embedding)s::vector, %(name)s, %(instruction)s, %(description)s,
                        %(role_focus)s, %(tags)s::jsonb, %(trigger_keywords)s::jsonb, %(metadata)s::jsonb, %(citation_label)s,
                        %(embedding_checksum)s, %(model_name)s, NOW(), NOW()
                    )
                    ON CONFLICT (behavior_id, version) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        name = EXCLUDED.name,
                        instruction = EXCLUDED.instruction,
                        description = EXCLUDED.description,
                        role_focus = EXCLUDED.role_focus,
                        tags = EXCLUDED.tags,
                        trigger_keywords = EXCLUDED.trigger_keywords,
                        metadata = EXCLUDED.metadata,
                        citation_label = EXCLUDED.citation_label,
                        embedding_checksum = EXCLUDED.embedding_checksum,
                        model_name = EXCLUDED.model_name,
                        updated_at = NOW()
                """

                for row in rows_to_insert:
                    cur.execute(upsert_sql, row)
            conn.commit()

        logger.info("Wrote %d embeddings to behavior_embeddings table", len(rows_to_insert))

    @staticmethod
    def _build_embedding_text(entry: Dict[str, Any]) -> str:
        behavior = entry["behavior"]
        version = entry["active_version"]
        tags = " ".join(behavior.get("tags", []))
        metadata = version.get("metadata") or {}
        summary = metadata.get("summary") or ""
        return "\n".join(
            [
                behavior.get("name", ""),
                behavior.get("description", ""),
                version.get("instruction", ""),
                tags,
                summary,
            ]
        ).strip()

    @staticmethod
    def _behavior_snapshot(entry: Dict[str, Any]) -> Dict[str, Any]:
        behavior = entry["behavior"]
        version = entry["active_version"]
        metadata = version.get("metadata") or {}
        behavior_id = behavior.get("behavior_id")
        # Convert UUID to string for JSON serialization
        if behavior_id is not None and not isinstance(behavior_id, str):
            behavior_id = str(behavior_id)
        # Extract citation_label from metadata if present
        citation_label = metadata.get("citation_label")
        return {
            "behavior_id": behavior_id,
            "name": behavior.get("name"),
            "description": behavior.get("description"),
            "tags": behavior.get("tags", []),
            "version": version.get("version"),
            "instruction": version.get("instruction"),
            "role_focus": version.get("role_focus"),
            "metadata": metadata,
            "namespace": behavior.get("namespace", "core"),
            "citation_label": citation_label,
        }

    @staticmethod
    def _role_focus_from_str(value: Optional[str]) -> Optional[RoleFocus]:
        if value is None:
            return None
        try:
            return RoleFocus(value)
        except ValueError:
            return None

    def _to_behavior_match(
        self,
        *,
        record: Dict[str, Any],
        score: float,
        strategy_breakdown: Dict[str, float],
        include_metadata: bool,
    ) -> BehaviorMatch:
        metadata = record.get("metadata") if include_metadata else None
        citation_label = record.get("citation_label")
        if not citation_label and metadata:
            citation_label = metadata.get("citation_label")
        if not citation_label:
            citation_label = record.get("name")
        return BehaviorMatch(
            behavior_id=record.get("behavior_id", ""),
            name=record.get("name", ""),
            version=record.get("version", ""),
            instruction=record.get("instruction", ""),
            score=float(score),
            description=record.get("description"),
            role_focus=self._role_focus_from_str(record.get("role_focus")),
            tags=list(record.get("tags", [])),
            strategy_breakdown=strategy_breakdown,
            citation_label=citation_label,
            metadata=metadata,
        )

    def _embedding_retrieve(self, request: RetrieveRequest, model_name: Optional[str] = None) -> List[BehaviorMatch]:
        """Retrieve behaviors using semantic embedding similarity.

        Args:
            request: Retrieval request with query and filters
            model_name: Model to use for encoding. If None, uses self._model_name.
                       Phase 2: Used for A/B testing during gradual rollout.
        """
        if not self._semantic_available or self._index is None or not self._behavior_ids:
            return []

        # E3 S3.9 (T3.9.2): enrich query with phase-specific hint for better semantic match
        query = request.query
        if request.phase:
            from .bci_contracts import PHASE_BOOST_CONFIG
            phase_cfg = PHASE_BOOST_CONFIG.get(request.phase, {})
            hint = phase_cfg.get("query_hint", "")
            if hint:
                query = f"{hint} {query}"

        # Encode query with specified model (Phase 2: supports A/B cohorts)
        model = self._load_model(model_name)
        query_vec = model.encode([query], convert_to_numpy=True)  # pragma: no cover - heavy path
        assert faiss is not None
        faiss.normalize_L2(query_vec)  # pragma: no cover - heavy path  # type: ignore[attr-defined]

        return self._embedding_retrieve_with_vector(request, query_vec[0])

    def _embedding_retrieve_with_vector(
        self, request: RetrieveRequest, query_vec: Any
    ) -> List[BehaviorMatch]:
        """Retrieve behaviors using pre-computed query vector (for batch operations)."""
        if not self._semantic_available or self._index is None or not self._behavior_ids:
            return []
        assert faiss is not None  # narrow optional dependency for type checkers

        multiplier = 2 if request.strategy == RetrievalStrategy.HYBRID else 1
        k = min(len(self._behavior_ids), max(request.top_k, 1) * multiplier)
        if k == 0:
            return []

        # Reshape to 2D array for FAISS search
        query_vec_2d = query_vec.reshape(1, -1)  # pragma: no cover
        scores, indices = self._index.search(query_vec_2d, k)  # pragma: no cover - heavy path
        scores_list = scores[0].tolist()
        index_list = indices[0].tolist()

        matches: List[BehaviorMatch] = []
        for score, idx in zip(scores_list, index_list):
            if idx < 0 or idx >= len(self._behavior_ids):
                continue
            behavior_id = self._behavior_ids[idx]
            record = self._behavior_cache.get(behavior_id)
            if not record:
                continue

            # Filter by namespace if specified
            if request.namespace and record.get("namespace") != request.namespace:
                continue

            # Apply Recency and Usage weighting
            final_score = float(score)
            metadata = record.get("metadata", {}) or {}

            # Recency Boost: Decay based on age (default 0 if no date)
            # Formula: score * (1 + recency_weight * exp(-decay * age_in_days))
            created_at_str = metadata.get("created_at")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    age_days = (datetime.now(timezone.utc) - created_at).days
                    # Boost recent items (e.g., < 30 days)
                    # Decay factor 0.05 means ~50% boost retention at 14 days
                    recency_boost = np.exp(-0.05 * max(0, age_days))
                    # Apply small weight (e.g., 0.1) to not overpower semantic match
                    final_score *= (1.0 + 0.1 * recency_boost)
                except (ValueError, TypeError):
                    pass

            # Usage Boost: Logarithmic scale of usage count
            # Formula: score * (1 + usage_weight * log1p(usage_count))
            usage_count = metadata.get("usage_count", 0)
            if isinstance(usage_count, (int, float)) and usage_count > 0:
                # Cap usage boost to avoid dominance of popular but irrelevant items
                usage_factor = np.log1p(usage_count)
                final_score *= (1.0 + 0.05 * usage_factor)

            matches.append(
                self._to_behavior_match(
                    record=record,
                    score=final_score,
                    strategy_breakdown={"embedding": float(score)},
                    include_metadata=request.include_metadata,
                )
            )
        return matches

    def _keyword_retrieve(self, request: RetrieveRequest, *, limit: int) -> List[BehaviorMatch]:
        if self._behavior_service is None:
            return []
        search_request = SearchBehaviorsRequest(
            query=request.query,
            tags=request.tags,
            role_focus=request.role_focus.value if request.role_focus else None,
            status="APPROVED",
            limit=max(limit, 1),
            namespace=request.namespace,
        )
        results = self._behavior_service.search_behaviors(search_request)
        matches: List[BehaviorMatch] = []
        for result in results[:limit]:
            record = self._from_search_result(result)
            matches.append(
                self._to_behavior_match(
                    record=record,
                    score=float(result.score),
                    strategy_breakdown={"keyword": float(result.score)},
                    include_metadata=request.include_metadata,
                )
            )
        return matches

    def _from_search_result(self, result: BehaviorSearchResult) -> Dict[str, Any]:
        metadata = result.active_version.metadata
        return {
            "behavior_id": result.behavior.behavior_id,
            "name": result.behavior.name,
            "description": result.behavior.description,
            "tags": list(result.behavior.tags),
            "version": result.active_version.version,
            "instruction": result.active_version.instruction,
            "role_focus": result.active_version.role_focus,
            "metadata": metadata,
            "citation_label": (metadata or {}).get("citation_label") if metadata else None,
        }

    def _merge_hybrid(
        self,
        embedding_matches: List[BehaviorMatch],
        keyword_matches: List[BehaviorMatch],
        request: RetrieveRequest,
    ) -> List[BehaviorMatch]:
        combined: Dict[str, BehaviorMatch] = {}
        for match in embedding_matches:
            breakdown = dict(match.strategy_breakdown or {})
            combined_score = breakdown.get("embedding", match.score)
            combined[match.behavior_id] = replace(
                match,
                score=combined_score * request.embedding_weight,
                strategy_breakdown={"embedding": breakdown.get("embedding", match.score)},
            )

        for match in keyword_matches:
            breakdown = dict(match.strategy_breakdown or {})
            keyword_score = breakdown.get("keyword", match.score)
            if match.behavior_id in combined:
                existing = combined[match.behavior_id]
                existing_breakdown = dict(existing.strategy_breakdown or {})
                existing_breakdown.setdefault("embedding", existing_breakdown.get("embedding", existing.score))
                existing_breakdown["keyword"] = keyword_score
                combined_score = (
                    existing_breakdown.get("embedding", 0.0) * request.embedding_weight
                    + keyword_score * request.keyword_weight
                )
                combined[match.behavior_id] = replace(
                    existing,
                    score=combined_score,
                    strategy_breakdown=existing_breakdown,
                )
            else:
                combined[match.behavior_id] = replace(
                    match,
                    score=keyword_score * request.keyword_weight,
                    strategy_breakdown={"keyword": keyword_score},
                )

        ranked = sorted(combined.values(), key=lambda match: match.score, reverse=True)
        return ranked[: request.top_k]

    def _emit_retrieval_event(
        self,
        request: RetrieveRequest,
        matches: Sequence[BehaviorMatch],
        mode: str,
    ) -> None:
        try:
            self._telemetry.emit_event(
                event_type="bci.behavior_retriever.retrieve",
                payload={
                    "mode": mode,
                    "query_length": len(request.query or ""),
                    "strategy": request.strategy.value,
                    "top_k": request.top_k,
                    "returned": len(matches),
                },
            )
        except Exception:  # pragma: no cover - telemetry should not break retrieval
            logger.debug("Telemetry emission failed", exc_info=True)
