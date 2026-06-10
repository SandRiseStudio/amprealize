"""Policy for when workspace inventory / resource-analysis fast path may run in chat.

Following ``behavior_validate_cross_surface_parity`` (Student): shared rules for
reply routing and tests without duplicating regex blocks in the reply service.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from amprealize.chat_action_router import ChatWorkspaceIntent

if TYPE_CHECKING:
    from amprealize.feature_flags import FeatureFlagService

# Tabular / inventory-style phrasing — high confidence for deterministic path.
_INVENTORY_TABULAR_ALLOWLIST = re.compile(
    r"\b("
    r"how many|how much|number of|count\b|list\b|show me|show all|what are the|what is the|"
    r"which boards?|which board\b|what boards?|what board\b|"
    r"which projects?|which project\b|what projects?|what project\b|"
    r"which work items?|which tasks?|which bugs?|"
    r"total\b|enumerate|give me the names of|name the"
    r")\b",
    re.IGNORECASE,
)

# Soft conversational markers — prefer full LLM when strict mode is on.
_CONVERSATIONAL_SOFT_MARKERS = re.compile(
    r"\b("
    r"explain|why\b|should i|help me understand|compare|recommend|opinion|"
    r"in your view|what do you think|feel free|natural|tell me about|describe\b|"
    r"walk me through|best practice|worried|concerned|scared"
    r")\b",
    re.IGNORECASE,
)


def should_use_workspace_inventory_fast_path(
    *,
    message: str,
    chat_query_intent: str,
    feature_flags: "FeatureFlagService",
    user_id: str,
) -> bool:
    """Return False to skip ``_try_direct_workspace_answer`` (force LLM / runner path)."""

    if chat_query_intent in _SKIP_INTENTS_ALWAYS:
        return False
    if chat_query_intent != ChatWorkspaceIntent.LIST_INVENTORY.value:
        # Analytics, mutate, and other intents keep the existing fast-path behavior
        # (e.g. velocity / counts from ResourceAnalysisService).
        return True
    if not feature_flags.is_enabled(
        "feature.chat_inventory_fast_path_strict",
        {"user_id": user_id or ""},
    ):
        return True
    text = message or ""
    if not _INVENTORY_TABULAR_ALLOWLIST.search(text):
        return False
    if _CONVERSATIONAL_SOFT_MARKERS.search(text):
        return False
    return True


# Specificity markers that justify the extra targeted-fetch planner LLM call.
# A broad "what should I work on today?" is answerable from the deterministic
# workspace inventory the reply already has — running the planner there only adds
# latency (and a failure surface) for no quality gain. We only pay for the planner
# when the user points at something the inventory digest does not already cover.
_TARGETED_FETCH_SPECIFIC_MARKERS = re.compile(
    r"\b("
    r"blocked|blocker|stuck|overdue|due|deadline|stale|aging|"
    r"bug|bugs|regression|incident|failing|broken|"
    r"in[\s-]?review|in[\s-]?progress|backlog|done|status\b|"
    r"priority|high[\s-]?priority|critical|urgent|p0|p1|p2|"
    r"assigned to|my\b|mine\b|unassigned|owner|"
    r"epic|feature|milestone|sprint|release|"
    r"project[\s-]|board[\s-]|proj-|work[\s-]?item|item[\s-]?id|"
    r"depend|dependency|dependencies|relate"
    r")\b",
    re.IGNORECASE,
)


def targeted_fetch_warranted(message: str) -> bool:
    """True when a chat query is specific enough to justify the planner LLM call.

    Returns False for broad prioritization phrasing ("what should I work on
    today?", "what's next?") with no concrete entity/filter — those are answered
    from the deterministic inventory the reply already holds, skipping a slow,
    failure-prone extra LLM round-trip. Returns True (conservative) for empty
    input so behavior only changes for clearly-generic asks.
    """

    text = (message or "").strip()
    if not text:
        return True
    return bool(_TARGETED_FETCH_SPECIFIC_MARKERS.search(text))


_SKIP_INTENTS_ALWAYS = frozenset(
    {
        ChatWorkspaceIntent.CONVERSATIONAL_NON_INVENTORY.value,
        ChatWorkspaceIntent.AMBIGUOUS_SCOPE.value,
        ChatWorkspaceIntent.WORKSPACE_PRIORITIZE.value,
    }
)
