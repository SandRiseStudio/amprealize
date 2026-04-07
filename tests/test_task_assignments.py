import json
from typing import List

import pytest

from amprealize import cli
from amprealize.adapters import (
    CLITaskAssignmentAdapter,
    MCPTaskAssignmentAdapter,
    RestTaskAssignmentAdapter,
)
from amprealize.task_assignments import TaskAssignmentService


def _run_cli(args: List[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_task_assignment_surface_parity() -> None:
    service = TaskAssignmentService()
    rest = RestTaskAssignmentAdapter(service)
    cli_adapter = CLITaskAssignmentAdapter(service)
    mcp = MCPTaskAssignmentAdapter(service)

    rest_payload = rest.list_assignments({})
    cli_payload = cli_adapter.list_assignments()
    mcp_payload = mcp.list_assignments({})

    assert rest_payload == cli_payload == mcp_payload
    assert any(item["function"] == "Engineering" for item in rest_payload)

    engineering_rest = rest.list_assignments({"function": "engineering"})
    engineering_cli = cli_adapter.list_assignments("engineering")
    engineering_mcp = mcp.list_assignments({"function": "engineering"})

    assert engineering_rest == engineering_cli == engineering_mcp
    assert all(item["function"] == "Engineering" for item in engineering_rest)


def test_cli_tasks_command_filters_by_function(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli(["tasks", "--function", "engineering", "--format", "json"], capsys)
    assert exit_code == 0
    assert err == ""

    payload = json.loads(out)
    assert payload
    assert all(item["function"] == "Engineering" for item in payload)


def test_cli_tasks_invalid_function(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli(["tasks", "--function", "unknown"], capsys)
    assert exit_code == 2
    assert out == ""
    assert "Unknown function" in err
