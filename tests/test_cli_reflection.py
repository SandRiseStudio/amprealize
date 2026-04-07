import json
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch, fixture

from amprealize import cli


@fixture(autouse=True)
def reset_cli_state(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_BEHAVIOR_DB_PATH", str(tmp_path / "behaviors.db"))
    cli._reset_action_state_for_testing()


def _run_cli(args: list[str], capsys: CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_reflection_cli_requires_trace_input(capsys: CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli(["reflection", "extract"], capsys)
    assert exit_code == 2
    assert out == ""
    assert "provide --trace" in err.lower()


def test_reflection_cli_outputs_json_candidates(capsys: CaptureFixture[str]) -> None:
    trace_text = (
        "Understand user onboarding requirements\n"
        "Draft reusable behavior checklist for welcome flow\n"
        "Review checklist with mentor for feedback"
    )
    exit_code, out, err = _run_cli(
        [
            "reflection",
            "extract",
            "--trace",
            trace_text,
            "--min-score",
            "0.4",
            "--max-candidates",
            "3",
            "--output",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["trace_step_count"] >= 2
    assert payload["candidates"], "expected at least one reflection candidate"
    top_candidate = payload["candidates"][0]
    assert top_candidate["confidence"] >= 0.4
    assert top_candidate["quality_scores"]["clarity"] >= 0.0


def test_reflection_cli_table_output(capsys: CaptureFixture[str]) -> None:
    trace_text = (
        "Analyze metrics trends for last sprint\n"
        "Highlight reusable reporting workflow steps\n"
        "Document follow-up actions with owners"
    )
    exit_code, out, err = _run_cli(
        [
            "reflection",
            "extract",
            "--trace",
            trace_text,
            "--no-examples",
            "--output",
            "table",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    assert "Slug" in out
    assert "Confidence" in out
    assert "Duplicate" in out
