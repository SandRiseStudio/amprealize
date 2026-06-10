"""CLI: amprealize resources analyze."""

from __future__ import annotations

import json

import pytest

from amprealize import cli

pytestmark = pytest.mark.unit


def test_resources_analyze_prints_json(monkeypatch, capsys) -> None:
    def _fake_api_call(
        method: str,
        path: str,
        body: dict,
    ) -> dict:
        assert method == "POST"
        assert path == "/v1/resources:analyze"
        assert "project" in body["query"].lower()
        return {
            "success": True,
            "content": "You have 1 project.",
            "metadata": {
                "analysis_mode": "deterministic",
                "row_count": 1,
            },
            "query_plan": {
                "intent": "count",
                "resource_type": "projects",
            },
        }

    monkeypatch.setattr(cli, "_wi_api_call", _fake_api_call)

    code = cli.main(
        [
            "resources",
            "analyze",
            "how many projects?",
            "--format",
            "json",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["query_plan"]["resource_type"] == "projects"
