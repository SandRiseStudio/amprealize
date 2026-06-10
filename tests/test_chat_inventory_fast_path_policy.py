"""Tests for workspace inventory fast-path gating."""

from __future__ import annotations

import pytest

from amprealize.chat_action_router import ChatWorkspaceIntent
from amprealize.chat_inventory_fast_path_policy import should_use_workspace_inventory_fast_path
from amprealize.feature_flags import FeatureFlagService

pytestmark = pytest.mark.unit


def test_skip_fast_path_for_conversational_intent() -> None:
    ff = FeatureFlagService()
    assert (
        should_use_workspace_inventory_fast_path(
            message="who are you?",
            chat_query_intent=ChatWorkspaceIntent.CONVERSATIONAL_NON_INVENTORY.value,
            feature_flags=ff,
            user_id="u1",
        )
        is False
    )


def test_skip_fast_path_for_ambiguous_scope() -> None:
    ff = FeatureFlagService()
    assert (
        should_use_workspace_inventory_fast_path(
            message="which board should I use?",
            chat_query_intent=ChatWorkspaceIntent.AMBIGUOUS_SCOPE.value,
            feature_flags=ff,
            user_id="u1",
        )
        is False
    )


def test_strict_mode_blocks_vague_list_inventory() -> None:
    ff = FeatureFlagService()
    ff.set_flag("feature.chat_inventory_fast_path_strict", enabled=True)
    assert (
        should_use_workspace_inventory_fast_path(
            message="tell me about my projects",
            chat_query_intent=ChatWorkspaceIntent.LIST_INVENTORY.value,
            feature_flags=ff,
            user_id="u1",
        )
        is False
    )


def test_strict_mode_allows_explicit_list_inventory() -> None:
    ff = FeatureFlagService()
    ff.set_flag("feature.chat_inventory_fast_path_strict", enabled=True)
    assert (
        should_use_workspace_inventory_fast_path(
            message="list my projects",
            chat_query_intent=ChatWorkspaceIntent.LIST_INVENTORY.value,
            feature_flags=ff,
            user_id="u1",
        )
        is True
    )


def test_strict_mode_blocks_soft_markers() -> None:
    ff = FeatureFlagService()
    ff.set_flag("feature.chat_inventory_fast_path_strict", enabled=True)
    assert (
        should_use_workspace_inventory_fast_path(
            message="list my projects and explain why",
            chat_query_intent=ChatWorkspaceIntent.LIST_INVENTORY.value,
            feature_flags=ff,
            user_id="u1",
        )
        is False
    )


def test_analytics_intent_still_uses_fast_path() -> None:
    ff = FeatureFlagService()
    ff.set_flag("feature.chat_inventory_fast_path_strict", enabled=True)
    assert (
        should_use_workspace_inventory_fast_path(
            message="how quickly do items move from backlog to in progress?",
            chat_query_intent=ChatWorkspaceIntent.ANALYTICS_OR_RATE.value,
            feature_flags=ff,
            user_id="u1",
        )
        is True
    )
