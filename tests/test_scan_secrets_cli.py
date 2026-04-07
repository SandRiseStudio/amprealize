import json
from pathlib import Path
from typing import List

import pytest
import json
from pathlib import Path
from typing import List

from amprealize import cli


def test_run_scan_table_no_findings(monkeypatch, tmp_path, capsys):
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(cli, "_ensure_pre_commit_available", lambda: None)

    def fake_run(path: Path) -> int:
        path.write_text("[]", encoding="utf-8")
        return 0

    monkeypatch.setattr(cli, "_run_pre_commit", fake_run)

    exit_code = cli.run_scan(output_path=report_path, fmt="table", fail_on_findings=False)

    captured = capsys.readouterr()
    assert "No secrets detected" in captured.out
    assert exit_code == 0
    assert json.loads(report_path.read_text(encoding="utf-8")) == []


def test_run_scan_table_with_findings_and_fail(monkeypatch, tmp_path, capsys):
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(cli, "_ensure_pre_commit_available", lambda: None)

    def fake_run(path: Path) -> int:
        payload: List[dict] = [
            {
                "RuleID": "generic-api-key",
                "File": "services/api.py",
                "StartLine": 42,
            }
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")
        return 1

    monkeypatch.setattr(cli, "_run_pre_commit", fake_run)

    exit_code = cli.run_scan(output_path=report_path, fmt="table", fail_on_findings=True)

    captured = capsys.readouterr()
    assert "Detected 1 potential secret" in captured.out
    assert exit_code == 1


def test_main_dispatches_to_run_scan(monkeypatch):
    invoked = {}

    def fake_run_scan(*, output_path, fmt, fail_on_findings):
        invoked["output_path"] = output_path
        invoked["fmt"] = fmt
        invoked["fail"] = fail_on_findings
        return 0

    monkeypatch.setattr(cli, "run_scan", fake_run_scan)
    result = cli.main(["scan-secrets", "--format", "json", "--fail-on-findings"])

    assert result == 0
    assert invoked["output_path"] == cli.DEFAULT_OUTPUT.resolve()
    assert invoked["fmt"] == "json"
    assert invoked["fail"] is True
