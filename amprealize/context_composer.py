"""ContextComposer — Assembles context for agent-aware conversation replies.

Part of Phase 3 messaging system: AMPREALIZE-562 / AMPREALIZE-579.
Composes rich context from six data sources with greedy token budget allocation
and relevance scoring.

Data Sources:
1. conversation_history: Recent messages from the conversation
2. user_profile: User preferences, profile, role information
3. behavior_guidance: Retrieved behaviors from BCI/RuntimeInjector
4. work_item_context: Work item the conversation is about (if any)
5. run_context: Current execution state (if within a run)
6. external_references: Mentioned files, URLs, linked entities
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

# Try to import tiktoken for accurate token counting; fall back to char estimate
try:
    import tiktoken
    _HAS_TIKTOKEN = True
except ImportError:
    tiktoken = None  # type: ignore
    _HAS_TIKTOKEN = False
    logger.warning("tiktoken not installed - using character-based token estimation")


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class DataSourceType(str, Enum):
    """Enumeration of the six context data sources."""
    CONVERSATION_HISTORY = "conversation_history"
    USER_PROFILE = "user_profile"
    BEHAVIOR_GUIDANCE = "behavior_guidance"
    WORK_ITEM_CONTEXT = "work_item_context"
    RUN_CONTEXT = "run_context"
    EXTERNAL_REFERENCES = "external_references"


@dataclass
class ContextFragment:
    """A single fragment of context from one data source.

    Fragments are scored and packed into the token budget.
    """
    source: DataSourceType
    content: str
    token_count: int
    relevance_score: float = 0.0
    recency_score: float = 0.0
    ownership_score: float = 0.0
    combined_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Optional: link to original entity
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None  # "message", "work_item", "behavior", etc.
    timestamp: Optional[datetime] = None


@dataclass
class TokenBudget:
    """Token budget configuration for context composition.

    Defines total budget and allocation weights per data source.
    """
    total_tokens: int = 4000  # Default context window allocation

    # Priority weights for each data source (higher = more tokens allocated)
    # Weights are relative; they'll be normalized during allocation.
    weights: Dict[DataSourceType, float] = field(default_factory=lambda: {
        DataSourceType.CONVERSATION_HISTORY: 3.0,  # Most important - recent context
        DataSourceType.BEHAVIOR_GUIDANCE: 2.5,     # Guide agent behavior
        DataSourceType.USER_PROFILE: 1.5,          # User preferences
        DataSourceType.WORK_ITEM_CONTEXT: 2.0,     # Task-specific context
        DataSourceType.RUN_CONTEXT: 1.0,           # Execution state
        DataSourceType.EXTERNAL_REFERENCES: 1.0,   # Links, files
    })

    # Minimum tokens to reserve per source (floor)
    minimum_tokens: Dict[DataSourceType, int] = field(default_factory=lambda: {
        DataSourceType.CONVERSATION_HISTORY: 200,
        DataSourceType.BEHAVIOR_GUIDANCE: 100,
        DataSourceType.USER_PROFILE: 50,
        DataSourceType.WORK_ITEM_CONTEXT: 100,
        DataSourceType.RUN_CONTEXT: 50,
        DataSourceType.EXTERNAL_REFERENCES: 50,
    })

    # Maximum tokens to allocate per source (ceiling)
    maximum_tokens: Dict[DataSourceType, int] = field(default_factory=lambda: {
        DataSourceType.CONVERSATION_HISTORY: 2000,
        DataSourceType.BEHAVIOR_GUIDANCE: 1000,
        DataSourceType.USER_PROFILE: 300,
        DataSourceType.WORK_ITEM_CONTEXT: 800,
        DataSourceType.RUN_CONTEXT: 400,
        DataSourceType.EXTERNAL_REFERENCES: 500,
    })

    # Reserve for system prompt and generation headroom
    reserved_tokens: int = 500


@dataclass
class RelevanceWeights:
    """Weights for computing combined relevance score.

    Combined = recency * recency_weight + query_relevance * query_weight + ownership * ownership_weight
    """
    recency_weight: float = 0.4
    query_relevance_weight: float = 0.4
    ownership_weight: float = 0.2


@dataclass
class ComposedContext:
    """Result of context composition.

    Contains the assembled context string and metadata about what was included.
    """
    composed_text: str
    total_tokens: int
    fragments_included: List[ContextFragment]
    fragments_excluded: List[ContextFragment]
    sources_included: List[DataSourceType]
    token_allocation: Dict[DataSourceType, int]
    budget_utilization: float  # 0.0 - 1.0
    composition_time_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Token Counting
# ---------------------------------------------------------------------------


class TokenCounter:
    """Counts tokens using tiktoken (preferred) or character estimation."""

    _encoder: Any = None
    _model: str = "gpt-4"  # Default encoding model

    @classmethod
    def set_model(cls, model: str) -> None:
        """Set the model for encoding (e.g., 'gpt-4', 'claude-3')."""
        cls._model = model
        cls._encoder = None  # Reset encoder

    @classmethod
    def _get_encoder(cls) -> Any:
        if cls._encoder is None and _HAS_TIKTOKEN:
            try:
                cls._encoder = tiktoken.encoding_for_model(cls._model)
            except KeyError:
                # Fall back to cl100k_base for unknown models
                cls._encoder = tiktoken.get_encoding("cl100k_base")
        return cls._encoder

    @classmethod
    def count_tokens(cls, text: str) -> int:
        """Count tokens in text.

        Uses tiktoken if available, otherwise estimates ~4 chars per token.
        """
        if not text:
            return 0
        encoder = cls._get_encoder()
        if encoder:
            return len(encoder.encode(text))
        # Fallback: ~4 chars per token (typical for English)
        return max(1, len(text) // 4)

    @classmethod
    def truncate_to_tokens(cls, text: str, max_tokens: int) -> str:
        """Truncate text to fit within max_tokens.

        Returns the longest prefix that fits within the budget.
        """
        if not text or max_tokens <= 0:
            return ""

        encoder = cls._get_encoder()
        if encoder:
            tokens = encoder.encode(text)
            if len(tokens) <= max_tokens:
                return text
            return encoder.decode(tokens[:max_tokens])

        # Fallback: character-based truncation
        estimated_chars = max_tokens * 4
        if len(text) <= estimated_chars:
            return text
        return text[:estimated_chars]


# ---------------------------------------------------------------------------
# Data Source Providers (Protocol)
# ---------------------------------------------------------------------------


class ConversationHistoryProvider(Protocol):
    """Protocol for fetching conversation history."""

    async def get_recent_messages(
        self,
        conversation_id: str,
        limit: int = 20,
        before_message_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch recent messages from a conversation."""
        ...


class UserProfileProvider(Protocol):
    """Protocol for fetching user profile information."""

    async def get_user_profile(
        self,
        user_id: str,
        include_preferences: bool = True,
    ) -> Dict[str, Any]:
        """Fetch user profile and preferences."""
        ...


class BehaviorGuidanceProvider(Protocol):
    """Protocol for retrieving relevant behaviors."""

    async def retrieve_behaviors(
        self,
        query: str,
        top_k: int = 5,
        role: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant behaviors for the query."""
        ...


class WorkItemProvider(Protocol):
    """Protocol for fetching work item context."""

    async def get_work_item(
        self,
        item_id: str,
        include_children: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Fetch work item details."""
        ...


class RunContextProvider(Protocol):
    """Protocol for fetching run execution context."""

    async def get_run_context(
        self,
        run_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch current run state and recent steps."""
        ...


class ExternalReferenceProvider(Protocol):
    """Protocol for resolving external references."""

    async def resolve_references(
        self,
        message_content: str,
        conversation_id: str,
    ) -> List[Dict[str, Any]]:
        """Extract and resolve external references (files, URLs, mentions)."""
        ...


# ---------------------------------------------------------------------------
# Relevance Scoring
# ---------------------------------------------------------------------------


class RelevanceScorer:
    """Computes relevance scores for context fragments.

    Scores are based on:
    - Recency: How recent is the fragment (for messages, run steps)
    - Query relevance: How relevant to the current query/message
    - Ownership: Is this the user's own message/item
    """

    def __init__(self, weights: Optional[RelevanceWeights] = None):
        self.weights = weights or RelevanceWeights()

    def compute_recency_score(
        self,
        timestamp: Optional[datetime],
        reference_time: Optional[datetime] = None,
        decay_hours: float = 24.0,
    ) -> float:
        """Compute recency score with exponential decay.

        Score = exp(-hours_since / decay_hours)
        Recent items score ~1.0, older items decay toward 0.
        """
        if timestamp is None:
            return 0.5  # Neutral score for unknown time

        ref = reference_time or datetime.now(timezone.utc)
        delta = ref - timestamp
        hours_since = max(0, delta.total_seconds() / 3600)

        import math
        return math.exp(-hours_since / decay_hours)

    def compute_query_relevance(
        self,
        content: str,
        query: str,
        use_semantic: bool = False,
    ) -> float:
        """Compute query relevance score.

        For now uses simple keyword overlap. Can be extended with semantic
        embeddings if use_semantic=True.
        """
        if not content or not query:
            return 0.0

        # Simple keyword overlap (Jaccard similarity)
        content_words = set(content.lower().split())
        query_words = set(query.lower().split())

        if not query_words:
            return 0.5

        intersection = content_words & query_words
        union = content_words | query_words

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def compute_ownership_score(
        self,
        actor_id: Optional[str],
        current_user_id: Optional[str],
        actor_type: Optional[str] = None,
    ) -> float:
        """Compute ownership score.

        User's own messages/items score higher.
        Agent messages score lower (already known context).
        """
        if not actor_id or not current_user_id:
            return 0.5

        # User's own content
        if actor_id == current_user_id:
            return 1.0

        # Agent messages (less priority - agent knows its own output)
        if actor_type in ("agent", "system"):
            return 0.3

        # Other participants
        return 0.6

    def compute_combined_score(
        self,
        recency: float,
        query_relevance: float,
        ownership: float,
    ) -> float:
        """Compute weighted combined score."""
        return (
            self.weights.recency_weight * recency +
            self.weights.query_relevance_weight * query_relevance +
            self.weights.ownership_weight * ownership
        )


# ---------------------------------------------------------------------------
# Context Composer
# ---------------------------------------------------------------------------


class ContextComposer:
    """Assembles context from six data sources with token budget allocation.

    The composer:
    1. Fetches fragments from each data source
    2. Scores each fragment for relevance
    3. Allocates token budget per source based on weights
    4. Greedily packs highest-scoring fragments within budget
    5. Returns composed context with metadata
    """

    def __init__(
        self,
        *,
        conversation_provider: Optional[ConversationHistoryProvider] = None,
        user_provider: Optional[UserProfileProvider] = None,
        behavior_provider: Optional[BehaviorGuidanceProvider] = None,
        work_item_provider: Optional[WorkItemProvider] = None,
        run_provider: Optional[RunContextProvider] = None,
        reference_provider: Optional[ExternalReferenceProvider] = None,
        token_budget: Optional[TokenBudget] = None,
        relevance_weights: Optional[RelevanceWeights] = None,
        telemetry: Any = None,
    ):
        """Initialize ContextComposer with data source providers.

        Args:
            conversation_provider: Provides conversation history
            user_provider: Provides user profile information
            behavior_provider: Provides behavior guidance from BCI
            work_item_provider: Provides work item context
            run_provider: Provides run execution context
            reference_provider: Provides external reference resolution
            token_budget: Token budget configuration (default: 4000 tokens)
            relevance_weights: Weights for relevance scoring
            telemetry: Optional telemetry client
        """
        self._conversation_provider = conversation_provider
        self._user_provider = user_provider
        self._behavior_provider = behavior_provider
        self._work_item_provider = work_item_provider
        self._run_provider = run_provider
        self._reference_provider = reference_provider
        self._budget = token_budget or TokenBudget()
        self._scorer = RelevanceScorer(relevance_weights)
        self._telemetry = telemetry

    async def compose(
        self,
        *,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        query: str = "",
        work_item_id: Optional[str] = None,
        run_id: Optional[str] = None,
        role: Optional[str] = None,
        extra_context: Optional[Dict[str, Any]] = None,
        budget_override: Optional[TokenBudget] = None,
    ) -> ComposedContext:
        """Compose context from all available data sources.

        Args:
            conversation_id: Conversation to pull history from
            user_id: User ID for profile and ownership scoring
            query: The current query/message for relevance scoring
            work_item_id: Optional work item context
            run_id: Optional run context
            role: User role (Student, Teacher, Strategist)
            extra_context: Additional context to include
            budget_override: Override default token budget

        Returns:
            ComposedContext with assembled context string and metadata
        """
        t0 = time.monotonic()
        budget = budget_override or self._budget

        # Step 1: Fetch fragments from all sources (parallel)
        all_fragments = await self._fetch_all_fragments(
            conversation_id=conversation_id,
            user_id=user_id,
            query=query,
            work_item_id=work_item_id,
            run_id=run_id,
            role=role,
        )

        # Step 2: Score all fragments
        self._score_fragments(all_fragments, query=query, user_id=user_id)

        # Step 3: Allocate budget per source
        allocation = self._allocate_budget(budget, all_fragments)

        # Step 4: Greedy packing within budget
        included, excluded = self._greedy_pack(all_fragments, allocation)

        # Step 5: Compose final text
        composed_text = self._format_composed_text(included, extra_context)
        total_tokens = TokenCounter.count_tokens(composed_text)

        elapsed_ms = (time.monotonic() - t0) * 1000

        result = ComposedContext(
            composed_text=composed_text,
            total_tokens=total_tokens,
            fragments_included=included,
            fragments_excluded=excluded,
            sources_included=list({f.source for f in included}),
            token_allocation=allocation,
            budget_utilization=total_tokens / budget.total_tokens if budget.total_tokens > 0 else 0,
            composition_time_ms=round(elapsed_ms, 2),
            metadata={
                "conversation_id": conversation_id,
                "user_id": user_id,
                "work_item_id": work_item_id,
                "run_id": run_id,
            },
        )

        # Emit telemetry
        self._emit_telemetry(result)

        return result

    async def _fetch_all_fragments(
        self,
        *,
        conversation_id: Optional[str],
        user_id: Optional[str],
        query: str,
        work_item_id: Optional[str],
        run_id: Optional[str],
        role: Optional[str],
    ) -> List[ContextFragment]:
        """Fetch fragments from all configured data sources."""
        import asyncio

        fragments: List[ContextFragment] = []
        tasks = []

        # Conversation history
        if self._conversation_provider and conversation_id:
            tasks.append(self._fetch_conversation_history(conversation_id))

        # User profile
        if self._user_provider and user_id:
            tasks.append(self._fetch_user_profile(user_id))

        # Behavior guidance
        if self._behavior_provider and query:
            tasks.append(self._fetch_behavior_guidance(query, role))

        # Work item context
        if self._work_item_provider and work_item_id:
            tasks.append(self._fetch_work_item_context(work_item_id))

        # Run context
        if self._run_provider and run_id:
            tasks.append(self._fetch_run_context(run_id))

        # External references
        if self._reference_provider and conversation_id and query:
            tasks.append(self._fetch_external_references(query, conversation_id))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(f"Error fetching context fragment: {result}")
                    continue
                if isinstance(result, list):
                    fragments.extend(result)

        return fragments

    async def _fetch_conversation_history(
        self, conversation_id: str
    ) -> List[ContextFragment]:
        """Fetch and convert conversation messages to fragments."""
        if not self._conversation_provider:
            return []

        try:
            messages = await self._conversation_provider.get_recent_messages(
                conversation_id, limit=20
            )
        except Exception as e:
            logger.warning(f"Failed to fetch conversation history: {e}")
            return []

        fragments = []
        for msg in messages:
            content = msg.get("content", "")
            timestamp = msg.get("created_at")
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    timestamp = None

            if content:
                fragments.append(ContextFragment(
                    source=DataSourceType.CONVERSATION_HISTORY,
                    content=self._format_message(msg),
                    token_count=TokenCounter.count_tokens(content),
                    entity_id=msg.get("message_id"),
                    entity_type="message",
                    timestamp=timestamp,
                    metadata={
                        "sender_id": msg.get("sender_id"),
                        "sender_type": msg.get("sender_type"),
                    },
                ))

        return fragments

    def _format_message(self, msg: Dict[str, Any]) -> str:
        """Format a message for context inclusion."""
        sender = msg.get("sender_display_name") or msg.get("sender_id") or "Unknown"
        sender_type = msg.get("sender_type", "user")
        role_label = "Agent" if sender_type == "agent" else "User"
        content = msg.get("content", "")
        return f"[{role_label}: {sender}] {content}"

    async def _fetch_user_profile(self, user_id: str) -> List[ContextFragment]:
        """Fetch user profile as a context fragment."""
        if not self._user_provider:
            return []

        try:
            profile = await self._user_provider.get_user_profile(user_id)
        except Exception as e:
            logger.warning(f"Failed to fetch user profile: {e}")
            return []

        if not profile:
            return []

        # Format profile for context
        lines = []
        if profile.get("display_name"):
            lines.append(f"User: {profile['display_name']}")
        if profile.get("role"):
            lines.append(f"Role: {profile['role']}")
        if profile.get("preferences"):
            prefs = profile["preferences"]
            if prefs.get("communication_style"):
                lines.append(f"Communication style: {prefs['communication_style']}")
            if prefs.get("expertise_level"):
                lines.append(f"Expertise: {prefs['expertise_level']}")

        if not lines:
            return []

        content = "\n".join(lines)
        return [ContextFragment(
            source=DataSourceType.USER_PROFILE,
            content=content,
            token_count=TokenCounter.count_tokens(content),
            entity_id=user_id,
            entity_type="user",
            relevance_score=1.0,  # Always relevant
            recency_score=1.0,
            ownership_score=1.0,
        )]

    async def _fetch_behavior_guidance(
        self, query: str, role: Optional[str]
    ) -> List[ContextFragment]:
        """Fetch relevant behaviors as context fragments."""
        if not self._behavior_provider:
            return []

        try:
            behaviors = await self._behavior_provider.retrieve_behaviors(
                query, top_k=5, role=role
            )
        except Exception as e:
            logger.warning(f"Failed to fetch behaviors: {e}")
            return []

        fragments = []
        for behavior in behaviors:
            name = behavior.get("name", "")
            instruction = behavior.get("instruction", behavior.get("description", ""))

            if name and instruction:
                content = f"[Behavior: {name}]\n{instruction}"
                fragments.append(ContextFragment(
                    source=DataSourceType.BEHAVIOR_GUIDANCE,
                    content=content,
                    token_count=TokenCounter.count_tokens(content),
                    entity_id=behavior.get("behavior_id"),
                    entity_type="behavior",
                    relevance_score=behavior.get("relevance_score", 0.8),
                    metadata={"steps": behavior.get("steps", [])},
                ))

        return fragments

    async def _fetch_work_item_context(
        self, work_item_id: str
    ) -> List[ContextFragment]:
        """Fetch work item as context fragment."""
        if not self._work_item_provider:
            return []

        try:
            item = await self._work_item_provider.get_work_item(work_item_id)
        except Exception as e:
            logger.warning(f"Failed to fetch work item: {e}")
            return []

        if not item:
            return []

        lines = [f"Work Item: {item.get('title', 'Untitled')}"]
        if item.get("description"):
            lines.append(f"Description: {item['description']}")
        if item.get("status"):
            lines.append(f"Status: {item['status']}")
        if item.get("acceptance_criteria"):
            lines.append("Acceptance Criteria:")
            for criterion in item["acceptance_criteria"]:
                lines.append(f"  - {criterion}")

        content = "\n".join(lines)
        return [ContextFragment(
            source=DataSourceType.WORK_ITEM_CONTEXT,
            content=content,
            token_count=TokenCounter.count_tokens(content),
            entity_id=work_item_id,
            entity_type="work_item",
            relevance_score=1.0,  # Explicitly requested
        )]

    async def _fetch_run_context(self, run_id: str) -> List[ContextFragment]:
        """Fetch run execution context as fragment."""
        if not self._run_provider:
            return []

        try:
            run_ctx = await self._run_provider.get_run_context(run_id)
        except Exception as e:
            logger.warning(f"Failed to fetch run context: {e}")
            return []

        if not run_ctx:
            return []

        lines = [f"Run Status: {run_ctx.get('status', 'unknown')}"]
        if run_ctx.get("current_phase"):
            lines.append(f"Current Phase: {run_ctx['current_phase']}")
        if run_ctx.get("progress_percent") is not None:
            lines.append(f"Progress: {run_ctx['progress_percent']}%")
        if run_ctx.get("recent_steps"):
            lines.append("Recent Steps:")
            for step in run_ctx["recent_steps"][-3:]:
                lines.append(f"  - {step.get('type', 'step')}: {step.get('summary', '')}")

        content = "\n".join(lines)
        return [ContextFragment(
            source=DataSourceType.RUN_CONTEXT,
            content=content,
            token_count=TokenCounter.count_tokens(content),
            entity_id=run_id,
            entity_type="run",
            relevance_score=0.9,  # High relevance if in a run
        )]

    async def _fetch_external_references(
        self, query: str, conversation_id: str
    ) -> List[ContextFragment]:
        """Fetch external references (files, URLs, mentions)."""
        if not self._reference_provider:
            return []

        try:
            refs = await self._reference_provider.resolve_references(
                query, conversation_id
            )
        except Exception as e:
            logger.warning(f"Failed to fetch external references: {e}")
            return []

        fragments = []
        for ref in refs:
            ref_type = ref.get("type", "reference")
            content = ref.get("content", ref.get("summary", ""))

            if content:
                formatted = f"[{ref_type.title()}: {ref.get('name', 'Unknown')}]\n{content}"
                fragments.append(ContextFragment(
                    source=DataSourceType.EXTERNAL_REFERENCES,
                    content=formatted,
                    token_count=TokenCounter.count_tokens(formatted),
                    entity_id=ref.get("reference_id"),
                    entity_type=ref_type,
                    metadata={"url": ref.get("url"), "path": ref.get("path")},
                ))

        return fragments

    def _score_fragments(
        self,
        fragments: List[ContextFragment],
        query: str,
        user_id: Optional[str],
    ) -> None:
        """Score all fragments for relevance (in-place mutation)."""
        now = datetime.now(timezone.utc)

        for frag in fragments:
            # Recency score (for time-based sources)
            if frag.recency_score == 0.0 and frag.timestamp:
                frag.recency_score = self._scorer.compute_recency_score(
                    frag.timestamp, now
                )
            elif frag.recency_score == 0.0:
                frag.recency_score = 0.5  # Neutral if no timestamp

            # Query relevance
            if frag.relevance_score == 0.0:
                frag.relevance_score = self._scorer.compute_query_relevance(
                    frag.content, query
                )

            # Ownership score
            if frag.ownership_score == 0.0:
                frag.ownership_score = self._scorer.compute_ownership_score(
                    frag.metadata.get("sender_id"),
                    user_id,
                    frag.metadata.get("sender_type"),
                )

            # Combined score
            frag.combined_score = self._scorer.compute_combined_score(
                frag.recency_score,
                frag.relevance_score,
                frag.ownership_score,
            )

    def _allocate_budget(
        self,
        budget: TokenBudget,
        fragments: List[ContextFragment],
    ) -> Dict[DataSourceType, int]:
        """Allocate token budget to each data source.

        Uses weighted allocation with min/max bounds.
        """
        available = budget.total_tokens - budget.reserved_tokens

        # Count fragments per source
        source_counts = {}
        for frag in fragments:
            source_counts[frag.source] = source_counts.get(frag.source, 0) + 1

        # Start with minimum allocations
        allocation = {src: budget.minimum_tokens.get(src, 0) for src in DataSourceType}
        remaining = available - sum(allocation.values())

        # Distribute remaining proportionally to weights (only for sources with fragments)
        active_sources = [s for s in DataSourceType if source_counts.get(s, 0) > 0]
        if active_sources and remaining > 0:
            total_weight = sum(budget.weights.get(s, 1.0) for s in active_sources)

            for source in active_sources:
                weight = budget.weights.get(source, 1.0)
                share = int((weight / total_weight) * remaining)
                max_allowed = budget.maximum_tokens.get(source, available)
                allocation[source] = min(allocation[source] + share, max_allowed)

        return allocation

    def _greedy_pack(
        self,
        fragments: List[ContextFragment],
        allocation: Dict[DataSourceType, int],
    ) -> Tuple[List[ContextFragment], List[ContextFragment]]:
        """Greedily pack fragments within budget allocation.

        For each source:
        1. Sort fragments by combined_score (descending)
        2. Include fragments until budget exhausted

        Returns:
            Tuple of (included_fragments, excluded_fragments)
        """
        included: List[ContextFragment] = []
        excluded: List[ContextFragment] = []

        # Group by source and sort
        by_source: Dict[DataSourceType, List[ContextFragment]] = {}
        for frag in fragments:
            by_source.setdefault(frag.source, []).append(frag)

        # Sort each source by combined score (descending)
        for source in by_source:
            by_source[source].sort(key=lambda f: f.combined_score, reverse=True)

        # Greedy pack per source
        for source, frags in by_source.items():
            budget_remaining = allocation.get(source, 0)

            for frag in frags:
                if frag.token_count <= budget_remaining:
                    included.append(frag)
                    budget_remaining -= frag.token_count
                else:
                    excluded.append(frag)

        return included, excluded

    def _format_composed_text(
        self,
        fragments: List[ContextFragment],
        extra_context: Optional[Dict[str, Any]],
    ) -> str:
        """Format included fragments into final context string."""
        sections: Dict[DataSourceType, List[str]] = {}

        # Group fragments by source
        for frag in fragments:
            sections.setdefault(frag.source, []).append(frag.content)

        # Build output in priority order
        source_order = [
            DataSourceType.USER_PROFILE,
            DataSourceType.WORK_ITEM_CONTEXT,
            DataSourceType.BEHAVIOR_GUIDANCE,
            DataSourceType.CONVERSATION_HISTORY,
            DataSourceType.RUN_CONTEXT,
            DataSourceType.EXTERNAL_REFERENCES,
        ]

        lines = []

        for source in source_order:
            if source not in sections:
                continue

            header = self._source_header(source)
            lines.append(f"\n## {header}\n")
            lines.extend(sections[source])

        # Add extra context if provided
        if extra_context:
            lines.append("\n## Additional Context\n")
            for key, value in extra_context.items():
                lines.append(f"- {key}: {value}")

        return "\n".join(lines).strip()

    def _source_header(self, source: DataSourceType) -> str:
        """Return section header for a data source."""
        headers = {
            DataSourceType.CONVERSATION_HISTORY: "Conversation History",
            DataSourceType.USER_PROFILE: "User Context",
            DataSourceType.BEHAVIOR_GUIDANCE: "Behavior Guidance",
            DataSourceType.WORK_ITEM_CONTEXT: "Work Item",
            DataSourceType.RUN_CONTEXT: "Execution Context",
            DataSourceType.EXTERNAL_REFERENCES: "Referenced Resources",
        }
        return headers.get(source, source.value.replace("_", " ").title())

    def _emit_telemetry(self, result: ComposedContext) -> None:
        """Emit telemetry event for context composition."""
        if not self._telemetry:
            return

        try:
            self._telemetry.emit(
                "context_composer.composition",
                {
                    "total_tokens": result.total_tokens,
                    "fragments_included": len(result.fragments_included),
                    "fragments_excluded": len(result.fragments_excluded),
                    "sources_included": [s.value for s in result.sources_included],
                    "budget_utilization": result.budget_utilization,
                    "latency_ms": result.composition_time_ms,
                },
            )
        except Exception as e:
            logger.debug(f"Failed to emit telemetry: {e}")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


__all__ = [
    "ContextComposer",
    "ContextFragment",
    "ComposedContext",
    "DataSourceType",
    "TokenBudget",
    "RelevanceWeights",
    "RelevanceScorer",
    "TokenCounter",
    # Protocols
    "ConversationHistoryProvider",
    "UserProfileProvider",
    "BehaviorGuidanceProvider",
    "WorkItemProvider",
    "RunContextProvider",
    "ExternalReferenceProvider",
]
