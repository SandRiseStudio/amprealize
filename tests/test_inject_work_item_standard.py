"""Tests for scripts/inject_work_item_standard.py (amprealize-488)."""

import pytest
import sys
from pathlib import Path

# Import the module under test
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import inject_work_item_standard as inject_mod


SAMPLE_MARKDOWN = """\
# My Agent

<rules>
- Do not break things
</rules>

<workflow>
1. Plan
2. Execute
</workflow>
"""

SAMPLE_NO_RULES = """\
# My Agent

Some text without a rules block.
"""


class TestHasSnippet:
    @pytest.mark.unit
    def test_no_sentinel(self) -> None:
        assert inject_mod._has_snippet("plain text") is False

    @pytest.mark.unit
    def test_only_start_sentinel(self) -> None:
        assert inject_mod._has_snippet("<!-- GWS:START -->") is False

    @pytest.mark.unit
    def test_both_sentinels(self) -> None:
        text = "<!-- GWS:START -->\nstuff\n<!-- GWS:END -->"
        assert inject_mod._has_snippet(text) is True


class TestRemoveSnippet:
    @pytest.mark.unit
    def test_removes_between_sentinels(self) -> None:
        text = "before\n<!-- GWS:START -->\ninjected\n<!-- GWS:END -->\nafter"
        result = inject_mod._remove_snippet(text)
        assert "<!-- GWS:START -->" not in result
        assert "injected" not in result
        assert "before\n" in result
        assert "after" in result

    @pytest.mark.unit
    def test_no_sentinels_returns_unchanged(self) -> None:
        text = "nothing special here"
        assert inject_mod._remove_snippet(text) == text


class TestCmdInject:
    @pytest.mark.unit
    def test_inject_after_rules_tag(self, tmp_path: Path) -> None:
        target = tmp_path / "agent.md"
        target.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

        inject_mod.cmd_inject(str(target))

        content = target.read_text(encoding="utf-8")
        assert inject_mod._has_snippet(content)
        # Snippet should appear after </rules>
        rules_pos = content.find("</rules>")
        start_pos = content.find("<!-- GWS:START -->")
        assert start_pos > rules_pos

    @pytest.mark.unit
    def test_inject_appends_when_no_rules(self, tmp_path: Path) -> None:
        target = tmp_path / "agent.md"
        target.write_text(SAMPLE_NO_RULES, encoding="utf-8")

        inject_mod.cmd_inject(str(target))

        content = target.read_text(encoding="utf-8")
        assert inject_mod._has_snippet(content)

    @pytest.mark.unit
    def test_inject_is_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "agent.md"
        target.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

        inject_mod.cmd_inject(str(target))
        first_content = target.read_text(encoding="utf-8")

        inject_mod.cmd_inject(str(target))
        second_content = target.read_text(encoding="utf-8")

        assert first_content == second_content

    @pytest.mark.unit
    def test_inject_missing_file_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            inject_mod.cmd_inject(str(tmp_path / "nonexistent.md"))
        assert exc.value.code == 2


class TestCmdRemove:
    @pytest.mark.unit
    def test_remove_cleans_snippet(self, tmp_path: Path) -> None:
        target = tmp_path / "agent.md"
        target.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

        inject_mod.cmd_inject(str(target))
        assert inject_mod._has_snippet(target.read_text(encoding="utf-8"))

        inject_mod.cmd_remove(str(target))
        assert not inject_mod._has_snippet(target.read_text(encoding="utf-8"))

    @pytest.mark.unit
    def test_remove_no_snippet_is_noop(self, tmp_path: Path) -> None:
        target = tmp_path / "agent.md"
        target.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

        inject_mod.cmd_remove(str(target))
        assert target.read_text(encoding="utf-8") == SAMPLE_MARKDOWN


class TestCmdCheck:
    @pytest.mark.unit
    def test_check_present_exits_zero(self, tmp_path: Path) -> None:
        target = tmp_path / "agent.md"
        target.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
        inject_mod.cmd_inject(str(target))

        with pytest.raises(SystemExit) as exc:
            inject_mod.cmd_check(str(target))
        assert exc.value.code == 0

    @pytest.mark.unit
    def test_check_missing_exits_one(self, tmp_path: Path) -> None:
        target = tmp_path / "agent.md"
        target.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            inject_mod.cmd_check(str(target))
        assert exc.value.code == 1

    @pytest.mark.unit
    def test_check_missing_file_exits_two(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            inject_mod.cmd_check(str(tmp_path / "nonexistent.md"))
        assert exc.value.code == 2
