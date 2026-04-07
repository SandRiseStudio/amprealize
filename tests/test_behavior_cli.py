"""Regression tests for behavior-related CLI commands."""

from __future__ import annotations

import json

import pytest

from amprealize import cli

pytestmark = pytest.mark.unit


def test_behaviors_get_for_task_passes_cli_actor_surface(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class _FakeBehaviorService:
        def get_relevant_behaviors_for_task(
            self,
            task_description,
            role,
            limit,
            actor,
            role_context,
        ):
            captured["task_description"] = task_description
            captured["role"] = role
            captured["limit"] = limit
            captured["actor"] = actor
            captured["role_context"] = role_context
            return {
                "task_description": task_description,
                "role": role,
                "behaviors": [],
                "recommended_behaviors": [],
                "role_advisory": "No matching behaviors.",
            }

    monkeypatch.setattr("amprealize.behavior_service.BehaviorService", _FakeBehaviorService)
    monkeypatch.setattr(cli, "_behavior_backend_is_reachable", lambda: True)

    result = cli.main(
        [
            "behaviors",
            "get-for-task",
            "Fix CLI behavior retrieval actor surface bug",
            "--format",
            "json",
        ]
    )

    actor = captured["actor"]
    role_context = captured["role_context"]

    assert result == 0
    assert captured["task_description"] == "Fix CLI behavior retrieval actor surface bug"
    assert captured["role"] == "Student"
    assert captured["limit"] == 5
    assert actor.id == cli.DEFAULT_ACTOR_ID
    assert actor.role == cli.DEFAULT_ACTOR_ROLE
    assert actor.surface == "cli"
    assert role_context.role == "Student"
    assert "Retrieving behaviors for task" in role_context.rationale
    assert '"role_advisory": "No matching behaviors."' in capsys.readouterr().out


def test_behaviors_propose_passes_cli_actor_surface(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class _FakeBehaviorService:
        def propose_behavior(self, request, actor, role_context):
            captured["request"] = request
            captured["actor"] = actor
            captured["role_context"] = role_context
            return {
                "behavior_id": "behavior-test",
                "auto_approved": True,
                "confidence_score": 0.95,
                "message": "ok",
            }

    monkeypatch.setattr("amprealize.behavior_service.BehaviorService", _FakeBehaviorService)

    result = cli.main(
        [
            "behaviors",
            "propose",
            "--name",
            "behavior_test_cli_actor",
            "--description",
            "desc",
            "--instruction",
            "Do the thing",
            "--role",
            "STUDENT",
            "--format",
            "json",
        ]
    )

    actor = captured["actor"]
    role_context = captured["role_context"]
    request = captured["request"]

    assert result == 0
    assert request.name == "behavior_test_cli_actor"
    assert actor.id == cli.DEFAULT_ACTOR_ID
    assert actor.role == cli.DEFAULT_ACTOR_ROLE
    assert actor.surface == "cli"
    assert role_context.behaviors_cited == ["behavior_curate_behavior_handbook"]
    assert '"behavior_id": "behavior-test"' in capsys.readouterr().out


def test_behaviors_get_for_task_falls_back_to_agents_md(monkeypatch, tmp_path, capsys) -> None:
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(
        "\n".join(
            [
                "## Behaviors",
                "",
                "### `behavior_prefer_mcp_tools`",
                "- **When**: Working with MCP tool access or client configuration.",
                "- **Steps**:",
                "  1. Prefer MCP tools over ad-hoc API calls.",
                "  2. Fall back gracefully when the MCP host is unavailable.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_behavior_backend_is_reachable", lambda: False)

    result = cli.main(
        [
            "behaviors",
            "get-for-task",
            "Configure MCP client access",
            "--format",
            "json",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert result == 0
    assert output["source"] == "local_handbook_fallback"
    assert output["agents_path"] == str(agents_md)
    assert output["recommended_behaviors"][0]["name"] == "behavior_prefer_mcp_tools"
    assert output["recommended_behaviors"][0]["score"] > 0.0
