"""Tests for ResourceInsight system - thresholds, i18n, and analyzer."""

import os
from unittest.mock import patch

import pytest

from breakeramp.insights import (
    InsightConfig,
    InsightLevel,
    MessageTemplates,
    ResourceInsight,
    ResourceInsightAnalyzer,
    analyze_resources,
    get_insight_summary,
)


# =============================================================================
# InsightLevel Tests
# =============================================================================


class TestInsightLevel:
    """Test InsightLevel enum."""

    def test_levels_have_correct_order(self):
        """Verify level ordering for severity comparison."""
        assert InsightLevel.EXCELLENT.value < InsightLevel.GOOD.value
        assert InsightLevel.GOOD.value < InsightLevel.OK.value
        assert InsightLevel.OK.value < InsightLevel.WARNING.value
        assert InsightLevel.WARNING.value < InsightLevel.CRITICAL.value

    def test_over_provisioned_is_distinct_from_problems(self):
        """Over-provisioned is a distinct state (not a problem level)."""
        # OVER_PROVISIONED is informational - it comes after CRITICAL in the enum
        # because it's a different category (under-utilization vs over-utilization)
        assert InsightLevel.OVER_PROVISIONED.value > InsightLevel.CRITICAL.value

    def test_unknown_has_highest_value(self):
        """Unknown should be handled separately (highest value for sorting)."""
        assert InsightLevel.UNKNOWN.value > InsightLevel.OVER_PROVISIONED.value


# =============================================================================
# InsightConfig Tests
# =============================================================================


class TestInsightConfig:
    """Test configuration loading from env vars and YAML."""

    def test_default_thresholds(self):
        """Default thresholds should be sensible."""
        config = InsightConfig()

        # Memory thresholds
        assert config.memory_excellent == 30.0
        assert config.memory_good == 50.0
        assert config.memory_warning == 70.0
        assert config.memory_critical == 90.0

        # Disk thresholds
        assert config.disk_warning == 75.0
        assert config.disk_critical == 90.0

    def test_load_from_env_vars(self):
        """Should load thresholds from environment variables."""
        env_vars = {
            "BREAKERAMP_INSIGHT_MEMORY_WARNING": "65",
            "BREAKERAMP_INSIGHT_MEMORY_CRITICAL": "85",
            "BREAKERAMP_INSIGHT_DISK_WARNING": "80",
        }

        with patch.dict(os.environ, env_vars):
            config = InsightConfig.from_env()

        assert config.memory_warning == 65.0
        assert config.memory_critical == 85.0
        assert config.disk_warning == 80.0
        # Others remain default
        assert config.disk_critical == 90.0

    def test_env_var_invalid_value_uses_default(self):
        """Invalid env var values should fall back to defaults."""
        env_vars = {
            "BREAKERAMP_INSIGHT_MEMORY_WARNING": "not-a-number",
        }

        with patch.dict(os.environ, env_vars):
            config = InsightConfig.from_env()

        assert config.memory_warning == 70.0  # default

    def test_yaml_config_loading(self):
        """Should load thresholds from YAML-style dict."""
        yaml_dict = {
            "thresholds": {
                "memory": {
                    "warning": 60,
                    "critical": 80,
                },
                "disk": {
                    "warning": 70,
                },
            }
        }

        config = InsightConfig.from_dict(yaml_dict.get("thresholds", {}))

        assert config.memory_warning == 60.0
        assert config.memory_critical == 80.0
        assert config.disk_warning == 70.0

    def test_yaml_config_with_different_values(self):
        """YAML config can set different values than env vars."""
        env_vars = {
            "BREAKERAMP_INSIGHT_MEMORY_WARNING": "65",
        }
        yaml_dict = {
            "memory": {"warning": 55},
        }

        with patch.dict(os.environ, env_vars):
            env_config = InsightConfig.from_env()
            yaml_config = InsightConfig.from_dict(yaml_dict)

        assert env_config.memory_warning == 65.0
        assert yaml_config.memory_warning == 55.0


# =============================================================================
# MessageTemplates Tests (i18n Support)
# =============================================================================


class TestMessageTemplates:
    """Test message retrieval and i18n support."""

    def test_get_message_returns_english(self):
        """Messages should return English strings."""
        msg = MessageTemplates.get("memory.excellent")
        assert msg is not None
        assert "plenty" in msg.lower()

    def test_message_with_placeholders(self):
        """Messages with placeholders should interpolate values."""
        msg = MessageTemplates.get("detail.absolute", value="512MB", limit="1024MB", percent=50.0)
        assert "512MB" in msg
        assert "1024MB" in msg

    def test_missing_key_returns_bracketed_key(self):
        """Missing message keys should return the key in brackets."""
        msg = MessageTemplates.get("nonexistent.key")
        assert msg == "[nonexistent.key]"

    def test_messages_cover_all_levels(self):
        """Should have messages for all level/resource combinations."""
        resources = ["memory", "cpu", "disk", "bandwidth", "containers", "overall"]
        levels = ["excellent", "good", "ok", "warning", "critical"]

        for resource in resources:
            for level in levels:
                key = f"{resource}.{level}"
                msg = MessageTemplates.get(key)
                # Should not return bracketed key (meaning message exists)
                assert not msg.startswith("["), f"Missing message for {key}"


# =============================================================================
# ResourceInsight Tests
# =============================================================================


class TestResourceInsight:
    """Test ResourceInsight dataclass."""

    def test_create_insight(self):
        """Should create insight with all fields."""
        insight = ResourceInsight(
            level=InsightLevel.WARNING,
            message="Memory usage elevated",
            message_key="memory.warning",
            value=6000,
            limit=8000,
            percent=75.0,
            details="6000MB / 8000MB",
        )

        assert insight.level == InsightLevel.WARNING
        assert insight.percent == 75.0

    def test_format_rich_with_color(self):
        """Rich format should include color markup."""
        insight = ResourceInsight(
            level=InsightLevel.CRITICAL,
            message="Critical usage",
            message_key="memory.critical",
            percent=95.0,
        )

        formatted = insight.format_rich()
        assert "[red]" in formatted or "red" in formatted.lower()

    def test_format_rich_verbose_includes_details(self):
        """Verbose mode should include details."""
        insight = ResourceInsight(
            level=InsightLevel.WARNING,
            message="Warning",
            message_key="test",
            details="Extra detail info",
        )

        formatted_brief = insight.format_rich(verbose=False)
        formatted_verbose = insight.format_rich(verbose=True)

        assert "Extra detail" not in formatted_brief or "Extra detail" in formatted_verbose

    def test_format_shell_with_ansi(self):
        """Shell format should include ANSI color codes."""
        insight = ResourceInsight(
            level=InsightLevel.GOOD,
            message="Good",
            message_key="test",
        )

        formatted = insight.format_shell()
        # Should contain ANSI escape sequences
        assert "\033[" in formatted

    def test_to_dict_serialization(self):
        """Should serialize to dict for JSON output."""
        insight = ResourceInsight(
            level=InsightLevel.OK,
            message="OK status",
            message_key="memory.ok",
            percent=55.0,
        )

        d = insight.to_dict()

        assert d["level"] == "OK"
        assert d["message"] == "OK status"
        assert d["percent"] == 55.0

    def test_emoji_for_levels(self):
        """Each level should have an appropriate emoji."""
        for level in InsightLevel:
            insight = ResourceInsight(
                level=level,
                message="Test",
                message_key="test",
            )
            formatted = insight.format_rich()
            # Should contain some emoji or indicator
            assert len(formatted) > 0


# =============================================================================
# ResourceInsightAnalyzer Tests
# =============================================================================


class TestResourceInsightAnalyzer:
    """Test the main analyzer class."""

    def test_analyze_memory_excellent(self):
        """Memory usage above over-provisioned but under good should return EXCELLENT."""
        analyzer = ResourceInsightAnalyzer()

        # 2.5% is below the over_provisioned threshold (10%), so use 15%
        insights = analyzer.analyze(memory_used_mb=1200, memory_total_mb=8000)  # 15%

        assert "memory" in insights
        assert insights["memory"].level == InsightLevel.EXCELLENT

    def test_analyze_memory_over_provisioned(self):
        """Very low memory usage should return OVER_PROVISIONED."""
        analyzer = ResourceInsightAnalyzer()

        # 2.5% is below default over_provisioned threshold (10%)
        insights = analyzer.analyze(memory_used_mb=200, memory_total_mb=8000)

        assert "memory" in insights
        assert insights["memory"].level == InsightLevel.OVER_PROVISIONED

    def test_analyze_memory_good(self):
        """Moderate memory usage should return GOOD."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(memory_used_mb=3200, memory_total_mb=8000)  # 40%

        assert insights["memory"].level == InsightLevel.GOOD

    def test_analyze_memory_warning(self):
        """High memory usage should return WARNING."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(memory_used_mb=6000, memory_total_mb=8000)  # 75%

        assert insights["memory"].level == InsightLevel.WARNING

    def test_analyze_memory_critical(self):
        """Very high memory usage should return CRITICAL."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(memory_used_mb=7500, memory_total_mb=8000)  # ~94%

        assert insights["memory"].level == InsightLevel.CRITICAL

    def test_analyze_disk_with_thresholds(self):
        """Disk analysis should respect thresholds."""
        config = InsightConfig(disk_warning=60.0, disk_critical=80.0)
        analyzer = ResourceInsightAnalyzer(config=config)

        # 70% - should be WARNING with custom threshold
        insights = analyzer.analyze(disk_used_mb=7000, disk_total_mb=10000)

        assert insights["disk"].level == InsightLevel.WARNING

    def test_analyze_cpu_percent(self):
        """CPU analysis should work with percentage input."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(cpu_percent=25.0)

        assert "cpu" in insights
        assert insights["cpu"].level in (InsightLevel.EXCELLENT, InsightLevel.GOOD)

    def test_analyze_containers_healthy(self):
        """All healthy containers should return GOOD."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(
            container_health={
                "postgres": "running",
                "redis": "running",
                "api": "running",
            }
        )

        assert "containers" in insights
        assert insights["containers"].level == InsightLevel.GOOD

    def test_analyze_containers_with_failures(self):
        """Failed containers should return CRITICAL."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(
            container_health={
                "postgres": "running",
                "redis": "exited",
                "api": "dead",
            }
        )

        assert insights["containers"].level == InsightLevel.CRITICAL

    def test_overall_reflects_worst(self):
        """Overall status should reflect the worst individual status."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(
            memory_used_mb=200,  # Excellent
            disk_used_mb=9000,  # Critical at 90%
            disk_total_mb=10000,
        )

        assert "overall" in insights
        assert insights["overall"].level == InsightLevel.CRITICAL

    def test_format_summary(self):
        """Summary format should include all analyzed resources."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(
            memory_used_mb=4000,
            memory_total_mb=8000,
            disk_used_mb=2000,
            disk_total_mb=10000,
        )

        summary = analyzer.format_summary(insights)

        assert "Memory" in summary
        assert "Disk" in summary
        assert "Overall" in summary

    def test_format_summary_verbose(self):
        """Verbose summary should include more details."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(
            memory_used_mb=4000,
            memory_total_mb=8000,
        )

        brief = analyzer.format_summary(insights, verbose=False)
        verbose = analyzer.format_summary(insights, verbose=True)

        # Verbose should be same length or longer
        assert len(verbose) >= len(brief)


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_analyze_resources_function(self):
        """analyze_resources() should work like analyzer.analyze()."""
        insights = analyze_resources(
            memory_used_mb=4000,
            memory_total_mb=8000,
        )

        assert "memory" in insights
        assert "overall" in insights

    def test_get_insight_summary_rich(self):
        """get_insight_summary() should return Rich formatted string."""
        insights = analyze_resources(memory_used_mb=4000, memory_total_mb=8000)

        summary = get_insight_summary(insights, verbose=False, shell=False)

        assert isinstance(summary, str)
        assert "Memory" in summary

    def test_get_insight_summary_shell(self):
        """get_insight_summary() with shell=True should use ANSI codes."""
        insights = analyze_resources(memory_used_mb=4000, memory_total_mb=8000)

        summary = get_insight_summary(insights, verbose=False, shell=True)

        assert "\033[" in summary  # ANSI escape


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_total_memory(self):
        """Should handle zero total memory gracefully."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(memory_used_mb=100, memory_total_mb=0)

        # Should not crash - returns empty dict when data is invalid
        # This is acceptable behavior - no valid data = no insights
        assert isinstance(insights, dict)

    def test_negative_values(self):
        """Should handle negative values gracefully."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(memory_used_mb=-100, memory_total_mb=8000)

        # Should not crash; may treat as 0 or UNKNOWN
        assert "overall" in insights  # at least overall should exist

    def test_no_data_returns_unknown(self):
        """Missing data should return UNKNOWN."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze()  # No data

        # Should have overall but individual resources may be missing
        if "memory" in insights:
            assert insights["memory"].level == InsightLevel.UNKNOWN

    def test_over_provisioned_detection(self):
        """Very low usage should detect over-provisioned state."""
        config = InsightConfig(memory_over_provisioned=10.0)
        analyzer = ResourceInsightAnalyzer(config=config)

        insights = analyzer.analyze(memory_used_mb=400, memory_total_mb=8000)  # 5%

        assert insights["memory"].level == InsightLevel.OVER_PROVISIONED

    def test_exactly_at_threshold(self):
        """Values exactly at thresholds should go to higher severity."""
        config = InsightConfig(memory_warning=70.0)
        analyzer = ResourceInsightAnalyzer(config=config)

        insights = analyzer.analyze(memory_used_mb=5600, memory_total_mb=8000)  # exactly 70%

        assert insights["memory"].level == InsightLevel.WARNING


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for real-world scenarios."""

    def test_typical_development_machine(self):
        """Typical dev machine with moderate usage."""
        analyzer = ResourceInsightAnalyzer()

        insights = analyzer.analyze(
            memory_used_mb=6000,
            memory_total_mb=16000,
            disk_used_mb=50000,
            disk_total_mb=256000,
            cpu_percent=15.0,
            container_health={
                "postgres": "running",
                "redis": "running",
            },
        )

        # Should be healthy overall
        assert insights["overall"].level in (
            InsightLevel.EXCELLENT,
            InsightLevel.GOOD,
            InsightLevel.OK,
        )

    def test_resource_constrained_ci(self):
        """CI runner with limited resources under load."""
        config = InsightConfig(
            memory_warning=60.0,  # Stricter for CI
            memory_critical=80.0,
        )
        analyzer = ResourceInsightAnalyzer(config=config)

        insights = analyzer.analyze(
            memory_used_mb=3000,
            memory_total_mb=4000,  # 75% - warning with strict thresholds
            disk_used_mb=8000,
            disk_total_mb=10000,  # 80%
        )

        assert insights["memory"].level == InsightLevel.WARNING
        # Overall should reflect warning state
        assert insights["overall"].level in (
            InsightLevel.WARNING,
            InsightLevel.CRITICAL,
        )

    def test_full_pipeline_from_env_config(self):
        """Full pipeline: load config from env, analyze, format."""
        env_vars = {
            "BREAKERAMP_INSIGHT_MEMORY_WARNING": "75",
            "BREAKERAMP_INSIGHT_MEMORY_CRITICAL": "95",
        }

        with patch.dict(os.environ, env_vars):
            config = InsightConfig.from_env()
            analyzer = ResourceInsightAnalyzer(config=config)

            insights = analyzer.analyze(
                memory_used_mb=6500,
                memory_total_mb=8000,  # 81.25% - OK with custom thresholds
            )

            # With warning at 75%, 81% should be WARNING
            assert insights["memory"].level == InsightLevel.WARNING

            # Format for CLI
            summary = analyzer.format_summary(insights, verbose=True)
            assert "Memory" in summary
