"""
Unit tests for ContextComposer — context assembly and budget enforcement.

Tests verify:
- Token budget allocation and enforcement
- Data source fragment creation
- Relevance scoring (recency, query relevance, ownership)
- Greedy packing within budget
- Composed context formatting
- Edge cases (empty sources, over-budget fragments)

Part of Phase 3 messaging system: AMPREALIZE-562 / AMPREALIZE-583.

Run with: pytest tests/test_context_composer.py -v
"""
import asyncio

import pytest

# Mark as unit tests - no external services required
pytestmark = pytest.mark.unit
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amprealize.context_composer import (
    ComposedContext,
    ContextComposer,
    ContextFragment,
    DataSourceType,
    RelevanceScorer,
    RelevanceWeights,
    TokenBudget,
    TokenCounter,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def token_budget() -> TokenBudget:
    """Standard token budget for testing."""
    return TokenBudget(
        total_tokens=2000,
        reserved_tokens=200,
        weights={
            DataSourceType.CONVERSATION_HISTORY: 3.0,
            DataSourceType.BEHAVIOR_GUIDANCE: 2.5,
            DataSourceType.USER_PROFILE: 1.5,
            DataSourceType.WORK_ITEM_CONTEXT: 2.0,
            DataSourceType.RUN_CONTEXT: 1.0,
            DataSourceType.EXTERNAL_REFERENCES: 1.0,
        },
        minimum_tokens={
            DataSourceType.CONVERSATION_HISTORY: 100,
            DataSourceType.BEHAVIOR_GUIDANCE: 50,
            DataSourceType.USER_PROFILE: 25,
            DataSourceType.WORK_ITEM_CONTEXT: 50,
            DataSourceType.RUN_CONTEXT: 25,
            DataSourceType.EXTERNAL_REFERENCES: 25,
        },
        maximum_tokens={
            DataSourceType.CONVERSATION_HISTORY: 1000,
            DataSourceType.BEHAVIOR_GUIDANCE: 500,
            DataSourceType.USER_PROFILE: 150,
            DataSourceType.WORK_ITEM_CONTEXT: 400,
            DataSourceType.RUN_CONTEXT: 200,
            DataSourceType.EXTERNAL_REFERENCES: 250,
        },
    )


@pytest.fixture
def mock_conversation_provider() -> AsyncMock:
    """Mock provider returning sample conversation messages."""
    provider = AsyncMock()
    now = datetime.now(timezone.utc)
    provider.get_recent_messages.return_value = [
        {
            "message_id": "msg-001",
            "content": "How do I implement behavior retrieval?",
            "sender_id": "user-123",
            "sender_type": "user",
            "sender_display_name": "Alice",
            "created_at": (now - timedelta(minutes=5)).isoformat(),
        },
        {
            "message_id": "msg-002",
            "content": "You can use the BehaviorService.retrieve() method with your query.",
            "sender_id": "agent-001",
            "sender_type": "agent",
            "sender_display_name": "Amprealize",
            "created_at": (now - timedelta(minutes=4)).isoformat(),
        },
        {
            "message_id": "msg-003",
            "content": "Can you show me an example?",
            "sender_id": "user-123",
            "sender_type": "user",
            "sender_display_name": "Alice",
            "created_at": (now - timedelta(minutes=2)).isoformat(),
        },
    ]
    return provider


@pytest.fixture
def mock_user_provider() -> AsyncMock:
    """Mock provider returning sample user profile."""
    provider = AsyncMock()
    provider.get_user_profile.return_value = {
        "user_id": "user-123",
        "display_name": "Alice Developer",
        "role": "Student",
        "preferences": {
            "communication_style": "concise",
            "expertise_level": "intermediate",
        },
    }
    return provider


@pytest.fixture
def mock_behavior_provider() -> AsyncMock:
    """Mock provider returning sample behaviors."""
    provider = AsyncMock()
    provider.retrieve_behaviors.return_value = [
        {
            "behavior_id": "behavior_use_raze_for_logging",
            "name": "behavior_use_raze_for_logging",
            "instruction": "Use Raze for all structured logging in the codebase.",
            "relevance_score": 0.85,
        },
        {
            "behavior_id": "behavior_prefer_mcp_tools",
            "name": "behavior_prefer_mcp_tools",
            "instruction": "When MCP tools are available, prefer them over CLI.",
            "relevance_score": 0.72,
        },
    ]
    return provider


@pytest.fixture
def mock_work_item_provider() -> AsyncMock:
    """Mock provider returning sample work item."""
    provider = AsyncMock()
    provider.get_work_item.return_value = {
        "work_item_id": "AMPREALIZE-579",
        "title": "Implement ContextComposer with six data sources",
        "description": "Build a context composition service that enriches agent replies.",
        "status": "in_progress",
        "acceptance_criteria": [
            "Six data sources implemented",
            "Token budget allocation working",
            "Relevance scoring complete",
        ],
    }
    return provider


@pytest.fixture
def mock_run_provider() -> AsyncMock:
    """Mock provider returning sample run context."""
    provider = AsyncMock()
    provider.get_run_context.return_value = {
        "run_id": "run-001",
        "status": "running",
        "current_phase": "implementation",
        "progress_percent": 65,
        "recent_steps": [
            {"type": "thought", "summary": "Analyzing existing architecture"},
            {"type": "tool_use", "summary": "Reading runtime_injector.py"},
            {"type": "action", "summary": "Creating context_composer.py"},
        ],
    }
    return provider


@pytest.fixture
def mock_reference_provider() -> AsyncMock:
    """Mock provider returning sample external references."""
    provider = AsyncMock()
    provider.resolve_references.return_value = [
        {
            "reference_id": "ref-001",
            "type": "file",
            "name": "runtime_injector.py",
            "path": "amprealize/runtime_injector.py",
            "content": "RuntimeInjector orchestrates context resolution and prompt composition.",
        },
    ]
    return provider


@pytest.fixture
def full_composer(
    token_budget: TokenBudget,
    mock_conversation_provider: AsyncMock,
    mock_user_provider: AsyncMock,
    mock_behavior_provider: AsyncMock,
    mock_work_item_provider: AsyncMock,
    mock_run_provider: AsyncMock,
    mock_reference_provider: AsyncMock,
) -> ContextComposer:
    """Composer with all mock providers configured."""
    return ContextComposer(
        conversation_provider=mock_conversation_provider,
        user_provider=mock_user_provider,
        behavior_provider=mock_behavior_provider,
        work_item_provider=mock_work_item_provider,
        run_provider=mock_run_provider,
        reference_provider=mock_reference_provider,
        token_budget=token_budget,
    )


# =============================================================================
# TokenCounter Tests
# =============================================================================


class TestTokenCounter:
    """Tests for TokenCounter utility."""

    def test_count_tokens_empty_string(self):
        """Empty string has zero tokens."""
        assert TokenCounter.count_tokens("") == 0

    def test_count_tokens_simple_text(self):
        """Simple text should have reasonable token count."""
        text = "Hello world, this is a test."
        count = TokenCounter.count_tokens(text)
        # Should be > 0 and reasonable (not character count)
        assert 3 <= count <= 15

    def test_count_tokens_consistency(self):
        """Same text should always produce same count."""
        text = "The quick brown fox jumps over the lazy dog."
        count1 = TokenCounter.count_tokens(text)
        count2 = TokenCounter.count_tokens(text)
        assert count1 == count2

    def test_truncate_to_tokens_short_text(self):
        """Short text within budget returns unchanged."""
        text = "Short text"
        result = TokenCounter.truncate_to_tokens(text, max_tokens=100)
        assert result == text

    def test_truncate_to_tokens_exceeds_budget(self):
        """Long text is truncated to fit budget."""
        text = "This is a longer piece of text that should be truncated to fit within a small token budget."
        result = TokenCounter.truncate_to_tokens(text, max_tokens=5)
        # Result should be shorter
        assert len(result) < len(text)
        assert TokenCounter.count_tokens(result) <= 5

    def test_truncate_to_tokens_zero_budget(self):
        """Zero budget returns empty string."""
        result = TokenCounter.truncate_to_tokens("Hello", max_tokens=0)
        assert result == ""


# =============================================================================
# RelevanceScorer Tests
# =============================================================================


class TestRelevanceScorer:
    """Tests for RelevanceScorer."""

    @pytest.fixture
    def scorer(self) -> RelevanceScorer:
        return RelevanceScorer()

    def test_recency_score_recent(self, scorer: RelevanceScorer):
        """Recent timestamps score high."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(minutes=5)
        score = scorer.compute_recency_score(recent, now)
        assert score > 0.9  # Very recent

    def test_recency_score_old(self, scorer: RelevanceScorer):
        """Old timestamps score low."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=48)
        score = scorer.compute_recency_score(old, now)
        assert score < 0.3  # Decayed

    def test_recency_score_none_timestamp(self, scorer: RelevanceScorer):
        """None timestamp returns neutral score."""
        score = scorer.compute_recency_score(None)
        assert score == 0.5

    def test_query_relevance_exact_match(self, scorer: RelevanceScorer):
        """Content containing all query words scores high."""
        content = "How to implement behavior retrieval using BehaviorService"
        query = "behavior retrieval"
        score = scorer.compute_query_relevance(content, query)
        assert score > 0.1  # Has overlap

    def test_query_relevance_no_overlap(self, scorer: RelevanceScorer):
        """Content with no query words scores low."""
        content = "The weather is nice today"
        query = "behavior retrieval"
        score = scorer.compute_query_relevance(content, query)
        assert score == 0.0  # No overlap

    def test_query_relevance_empty(self, scorer: RelevanceScorer):
        """Empty content or query returns 0."""
        assert scorer.compute_query_relevance("", "query") == 0.0
        assert scorer.compute_query_relevance("content", "") == 0.0

    def test_ownership_score_same_user(self, scorer: RelevanceScorer):
        """User's own content scores highest."""
        score = scorer.compute_ownership_score("user-123", "user-123")
        assert score == 1.0

    def test_ownership_score_agent(self, scorer: RelevanceScorer):
        """Agent content scores lower."""
        score = scorer.compute_ownership_score("agent-001", "user-123", "agent")
        assert score == 0.3

    def test_ownership_score_other_user(self, scorer: RelevanceScorer):
        """Other user's content scores medium."""
        score = scorer.compute_ownership_score("user-456", "user-123", "user")
        assert score == 0.6

    def test_ownership_score_no_ids(self, scorer: RelevanceScorer):
        """Missing IDs return neutral score."""
        assert scorer.compute_ownership_score(None, "user-123") == 0.5
        assert scorer.compute_ownership_score("user-123", None) == 0.5

    def test_combined_score(self, scorer: RelevanceScorer):
        """Combined score is weighted sum."""
        # Default weights: 0.4 recency, 0.4 query, 0.2 ownership
        combined = scorer.compute_combined_score(
            recency=1.0, query_relevance=0.5, ownership=0.8
        )
        expected = 0.4 * 1.0 + 0.4 * 0.5 + 0.2 * 0.8
        assert combined == pytest.approx(expected)

    def test_custom_weights(self):
        """Custom weights affect combined score."""
        weights = RelevanceWeights(
            recency_weight=0.1,
            query_relevance_weight=0.8,
            ownership_weight=0.1,
        )
        scorer = RelevanceScorer(weights)
        combined = scorer.compute_combined_score(
            recency=1.0, query_relevance=1.0, ownership=0.0
        )
        expected = 0.1 * 1.0 + 0.8 * 1.0 + 0.1 * 0.0
        assert combined == pytest.approx(expected)


# =============================================================================
# ContextFragment Tests
# =============================================================================


class TestContextFragment:
    """Tests for ContextFragment dataclass."""

    def test_create_fragment(self):
        """Basic fragment creation works."""
        frag = ContextFragment(
            source=DataSourceType.CONVERSATION_HISTORY,
            content="Hello world",
            token_count=2,
        )
        assert frag.source == DataSourceType.CONVERSATION_HISTORY
        assert frag.content == "Hello world"
        assert frag.token_count == 2
        assert frag.combined_score == 0.0
        assert frag.metadata == {}

    def test_fragment_with_metadata(self):
        """Fragment with metadata and scores."""
        frag = ContextFragment(
            source=DataSourceType.BEHAVIOR_GUIDANCE,
            content="Use Raze for logging",
            token_count=5,
            relevance_score=0.85,
            recency_score=0.9,
            ownership_score=0.5,
            combined_score=0.75,
            entity_id="behavior-001",
            entity_type="behavior",
            metadata={"steps": ["Step 1", "Step 2"]},
        )
        assert frag.relevance_score == 0.85
        assert frag.entity_type == "behavior"
        assert "steps" in frag.metadata


# =============================================================================
# TokenBudget Tests
# =============================================================================


class TestTokenBudget:
    """Tests for TokenBudget configuration."""

    def test_default_budget(self):
        """Default budget has sensible values."""
        budget = TokenBudget()
        assert budget.total_tokens == 4000
        assert budget.reserved_tokens == 500
        assert DataSourceType.CONVERSATION_HISTORY in budget.weights

    def test_custom_budget(self, token_budget: TokenBudget):
        """Custom budget values are respected."""
        assert token_budget.total_tokens == 2000
        assert token_budget.reserved_tokens == 200
        assert token_budget.weights[DataSourceType.CONVERSATION_HISTORY] == 3.0

    def test_available_tokens(self, token_budget: TokenBudget):
        """Available tokens = total - reserved."""
        available = token_budget.total_tokens - token_budget.reserved_tokens
        assert available == 1800


# =============================================================================
# ContextComposer Tests
# =============================================================================


class TestContextComposerBasic:
    """Basic ContextComposer functionality tests."""

    def test_composer_initialization(self, full_composer: ContextComposer):
        """Composer initializes with all providers."""
        assert full_composer._conversation_provider is not None
        assert full_composer._user_provider is not None
        assert full_composer._behavior_provider is not None
        assert full_composer._work_item_provider is not None
        assert full_composer._run_provider is not None
        assert full_composer._reference_provider is not None

    def test_composer_with_no_providers(self):
        """Composer works with no providers (returns minimal context)."""
        composer = ContextComposer()
        result = asyncio.run(composer.compose(query="Hello"))
        assert isinstance(result, ComposedContext)
        assert result.fragments_included == []
        assert result.total_tokens == 0


@pytest.mark.asyncio
class TestContextComposerCompose:
    """Tests for ContextComposer.compose() method."""

    async def test_compose_returns_composed_context(
        self, full_composer: ContextComposer
    ):
        """compose() returns a ComposedContext object."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="How do I implement behavior retrieval?",
            work_item_id="AMPREALIZE-579",
            run_id="run-001",
        )
        assert isinstance(result, ComposedContext)
        assert result.total_tokens > 0
        assert len(result.fragments_included) > 0
        assert len(result.sources_included) > 0

    async def test_compose_includes_conversation_history(
        self,
        full_composer: ContextComposer,
        mock_conversation_provider: AsyncMock,
    ):
        """compose() fetches and includes conversation history."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="question",
        )
        mock_conversation_provider.get_recent_messages.assert_called_once_with(
            "conv-001", limit=20
        )
        assert DataSourceType.CONVERSATION_HISTORY in result.sources_included

    async def test_compose_includes_user_profile(
        self,
        full_composer: ContextComposer,
        mock_user_provider: AsyncMock,
    ):
        """compose() fetches and includes user profile."""
        result = await full_composer.compose(
            user_id="user-123",
            query="question",
        )
        mock_user_provider.get_user_profile.assert_called_once_with("user-123")
        assert DataSourceType.USER_PROFILE in result.sources_included

    async def test_compose_includes_behavior_guidance(
        self,
        full_composer: ContextComposer,
        mock_behavior_provider: AsyncMock,
    ):
        """compose() retrieves and includes relevant behaviors."""
        result = await full_composer.compose(
            query="How do I implement logging?",
            role="Student",
        )
        mock_behavior_provider.retrieve_behaviors.assert_called_once_with(
            "How do I implement logging?", top_k=5, role="Student"
        )
        assert DataSourceType.BEHAVIOR_GUIDANCE in result.sources_included

    async def test_compose_includes_work_item_context(
        self,
        full_composer: ContextComposer,
        mock_work_item_provider: AsyncMock,
    ):
        """compose() fetches and includes work item context."""
        result = await full_composer.compose(
            work_item_id="AMPREALIZE-579",
            query="question",
        )
        mock_work_item_provider.get_work_item.assert_called_once_with("AMPREALIZE-579")
        assert DataSourceType.WORK_ITEM_CONTEXT in result.sources_included

    async def test_compose_includes_run_context(
        self,
        full_composer: ContextComposer,
        mock_run_provider: AsyncMock,
    ):
        """compose() fetches and includes run context."""
        result = await full_composer.compose(
            run_id="run-001",
            query="question",
        )
        mock_run_provider.get_run_context.assert_called_once_with("run-001")
        assert DataSourceType.RUN_CONTEXT in result.sources_included

    async def test_compose_includes_external_references(
        self,
        full_composer: ContextComposer,
        mock_reference_provider: AsyncMock,
    ):
        """compose() resolves and includes external references."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            query="Check runtime_injector.py",
        )
        mock_reference_provider.resolve_references.assert_called_once_with(
            "Check runtime_injector.py", "conv-001"
        )
        assert DataSourceType.EXTERNAL_REFERENCES in result.sources_included

    async def test_compose_handles_provider_error(
        self, mock_user_provider: AsyncMock
    ):
        """compose() handles provider errors gracefully."""
        mock_user_provider.get_user_profile.side_effect = Exception("Database error")
        composer = ContextComposer(user_provider=mock_user_provider)

        # Should not raise
        result = await composer.compose(user_id="user-123", query="question")
        assert isinstance(result, ComposedContext)
        # User profile source not included due to error
        assert DataSourceType.USER_PROFILE not in result.sources_included


@pytest.mark.asyncio
class TestContextComposerBudget:
    """Tests for token budget allocation and enforcement."""

    async def test_budget_allocation_respects_weights(
        self, full_composer: ContextComposer
    ):
        """Higher-weighted sources get more token allocation."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="question",
            work_item_id="AMPREALIZE-579",
        )
        allocation = result.token_allocation

        # Conversation history has highest weight (3.0) - should get more tokens
        assert allocation[DataSourceType.CONVERSATION_HISTORY] >= allocation.get(
            DataSourceType.RUN_CONTEXT, 0
        )

    async def test_does_not_exceed_budget(
        self, token_budget: TokenBudget, mock_conversation_provider: AsyncMock
    ):
        """Total tokens should not exceed budget."""
        # Create lots of messages to potentially exceed budget
        messages = [
            {
                "message_id": f"msg-{i}",
                "content": "x" * 200,  # Long messages
                "sender_id": "user-123",
                "sender_type": "user",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            for i in range(50)
        ]
        mock_conversation_provider.get_recent_messages.return_value = messages

        composer = ContextComposer(
            conversation_provider=mock_conversation_provider,
            token_budget=token_budget,
        )

        result = await composer.compose(
            conversation_id="conv-001",
            query="question",
        )

        # Should stay within budget
        assert result.total_tokens <= token_budget.total_tokens

    async def test_budget_utilization_reported(
        self, full_composer: ContextComposer
    ):
        """Budget utilization is reported correctly."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="question",
        )
        assert 0.0 <= result.budget_utilization <= 1.0


@pytest.mark.asyncio
class TestContextComposerGreedyPacking:
    """Tests for greedy packing algorithm."""

    async def test_higher_scored_fragments_included_first(
        self, mock_conversation_provider: AsyncMock
    ):
        """Fragments with higher combined scores are included over lower ones."""
        # Create messages with varying relevance
        now = datetime.now(timezone.utc)
        messages = [
            {  # Old, irrelevant
                "message_id": "msg-old",
                "content": "Old irrelevant message about weather",
                "sender_id": "user-456",
                "sender_type": "user",
                "created_at": (now - timedelta(hours=48)).isoformat(),
            },
            {  # Recent, relevant
                "message_id": "msg-recent",
                "content": "Recent message about behavior retrieval",
                "sender_id": "user-123",
                "sender_type": "user",
                "created_at": (now - timedelta(minutes=5)).isoformat(),
            },
        ]
        mock_conversation_provider.get_recent_messages.return_value = messages

        # Small budget to force exclusion
        budget = TokenBudget(
            total_tokens=200,
            reserved_tokens=50,
            minimum_tokens={s: 10 for s in DataSourceType},
            maximum_tokens={s: 100 for s in DataSourceType},
        )

        composer = ContextComposer(
            conversation_provider=mock_conversation_provider,
            token_budget=budget,
        )

        result = await composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="behavior retrieval",
        )

        # Should include the recent relevant message
        included_ids = [f.entity_id for f in result.fragments_included]
        assert "msg-recent" in included_ids

    async def test_excluded_fragments_tracked(
        self, mock_conversation_provider: AsyncMock
    ):
        """Fragments that don't fit are tracked as excluded."""
        # Create many messages to force exclusions
        now = datetime.now(timezone.utc)
        messages = [
            {
                "message_id": f"msg-{i}",
                "content": f"Message number {i} with some content " * 20,
                "sender_id": "user-123",
                "sender_type": "user",
                "created_at": (now - timedelta(minutes=i)).isoformat(),
            }
            for i in range(10)
        ]
        mock_conversation_provider.get_recent_messages.return_value = messages

        budget = TokenBudget(
            total_tokens=500,
            reserved_tokens=100,
            minimum_tokens={s: 10 for s in DataSourceType},
            maximum_tokens={s: 200 for s in DataSourceType},
        )

        composer = ContextComposer(
            conversation_provider=mock_conversation_provider,
            token_budget=budget,
        )

        result = await composer.compose(
            conversation_id="conv-001",
            query="question",
        )

        # Some fragments should be excluded
        assert len(result.fragments_excluded) > 0


@pytest.mark.asyncio
class TestContextComposerFormatting:
    """Tests for composed context formatting."""

    async def test_formatted_text_has_sections(
        self, full_composer: ContextComposer
    ):
        """Composed text is organized into sections."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="question",
            work_item_id="AMPREALIZE-579",
        )

        # Should have section headers
        assert "##" in result.composed_text

    async def test_formatted_text_includes_content(
        self, full_composer: ContextComposer
    ):
        """Composed text includes fragment content."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="question",
        )

        # Should include user name from profile
        assert "Alice" in result.composed_text or "User" in result.composed_text

    async def test_extra_context_included(self, full_composer: ContextComposer):
        """Extra context is appended to composed text."""
        result = await full_composer.compose(
            query="question",
            extra_context={
                "priority": "high",
                "deadline": "EOD",
            },
        )

        assert "priority" in result.composed_text or "Additional Context" in result.composed_text

    async def test_composition_time_tracked(self, full_composer: ContextComposer):
        """Composition time is measured."""
        result = await full_composer.compose(query="question")
        assert result.composition_time_ms >= 0


@pytest.mark.asyncio
class TestContextComposerEdgeCases:
    """Edge case tests."""

    async def test_empty_query(self, full_composer: ContextComposer):
        """Empty query still composes context."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="",
        )
        assert isinstance(result, ComposedContext)

    async def test_no_providers_returns_empty(self):
        """No providers configured returns empty context."""
        composer = ContextComposer()
        result = await composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="question",
        )
        assert result.fragments_included == []
        assert result.total_tokens == 0

    async def test_provider_returns_empty(self, mock_conversation_provider: AsyncMock):
        """Provider returning empty list is handled."""
        mock_conversation_provider.get_recent_messages.return_value = []
        composer = ContextComposer(
            conversation_provider=mock_conversation_provider
        )

        result = await composer.compose(
            conversation_id="conv-001",
            query="question",
        )
        assert DataSourceType.CONVERSATION_HISTORY not in result.sources_included

    async def test_metadata_in_result(self, full_composer: ContextComposer):
        """Metadata is captured in result."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            work_item_id="AMPREALIZE-579",
            run_id="run-001",
            query="question",
        )
        assert result.metadata["conversation_id"] == "conv-001"
        assert result.metadata["user_id"] == "user-123"
        assert result.metadata["work_item_id"] == "AMPREALIZE-579"
        assert result.metadata["run_id"] == "run-001"


# =============================================================================
# Integration-style Tests (all sources together)
# =============================================================================


@pytest.mark.asyncio
class TestContextComposerIntegration:
    """Integration-style tests with all providers."""

    async def test_full_composition_all_sources(
        self, full_composer: ContextComposer
    ):
        """Full composition with all six data sources."""
        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="How do I implement behavior retrieval?",
            work_item_id="AMPREALIZE-579",
            run_id="run-001",
            role="Student",
        )

        # All six sources should be present
        expected_sources = {
            DataSourceType.CONVERSATION_HISTORY,
            DataSourceType.USER_PROFILE,
            DataSourceType.BEHAVIOR_GUIDANCE,
            DataSourceType.WORK_ITEM_CONTEXT,
            DataSourceType.RUN_CONTEXT,
            DataSourceType.EXTERNAL_REFERENCES,
        }
        assert set(result.sources_included) == expected_sources

        # Should have meaningful content
        assert result.total_tokens > 100
        assert "##" in result.composed_text  # Section headers

        # Should track timing
        assert result.composition_time_ms > 0

    async def test_composition_with_budget_override(
        self, full_composer: ContextComposer
    ):
        """Budget override is respected."""
        tiny_budget = TokenBudget(
            total_tokens=300,
            reserved_tokens=50,
        )

        result = await full_composer.compose(
            conversation_id="conv-001",
            user_id="user-123",
            query="question",
            budget_override=tiny_budget,
        )

        # Should stay within override budget
        assert result.total_tokens <= 300
