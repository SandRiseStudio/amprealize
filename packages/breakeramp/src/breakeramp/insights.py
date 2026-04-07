"""Resource insight analysis for BreakerAmp.

This module provides intelligent analysis of resource metrics with:
- Plain-English status descriptions ("plenty of memory", "nearing capacity")
- Configurable thresholds via environment variables or YAML
- i18n-ready message templates for future localization
- Color-coded severity levels for terminal display

Example:
    from breakeramp.insights import ResourceInsightAnalyzer, InsightConfig

    analyzer = ResourceInsightAnalyzer()  # Uses defaults or env vars
    insights = analyzer.analyze(
        memory_used_mb=6144,
        memory_total_mb=8192,
        cpu_percent=45.0,
        disk_used_mb=50000,
        disk_total_mb=100000,
    )

    for resource, insight in insights.items():
        print(f"{resource}: {insight.message} [{insight.level.name}]")
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Optional
import os


# =============================================================================
# Insight Levels
# =============================================================================


class InsightLevel(Enum):
    """Severity levels for resource insights.

    Each level has an associated color and emoji for terminal display.
    """
    EXCELLENT = auto()     # Well under limits, very healthy
    GOOD = auto()          # Normal operation, no concerns
    OK = auto()            # Acceptable but worth monitoring
    WARNING = auto()       # Approaching limits, attention needed
    CRITICAL = auto()      # At or near capacity, action required
    OVER_PROVISIONED = auto()  # Resources far exceed needs
    UNKNOWN = auto()       # Unable to determine status

    @property
    def color(self) -> str:
        """Rich color name for terminal display."""
        return {
            InsightLevel.EXCELLENT: "bright_green",
            InsightLevel.GOOD: "green",
            InsightLevel.OK: "cyan",
            InsightLevel.WARNING: "yellow",
            InsightLevel.CRITICAL: "red",
            InsightLevel.OVER_PROVISIONED: "magenta",
            InsightLevel.UNKNOWN: "dim",
        }[self]

    @property
    def emoji(self) -> str:
        """Emoji indicator for terminal display."""
        return {
            InsightLevel.EXCELLENT: "🟢",
            InsightLevel.GOOD: "🟢",
            InsightLevel.OK: "🔵",
            InsightLevel.WARNING: "🟡",
            InsightLevel.CRITICAL: "🔴",
            InsightLevel.OVER_PROVISIONED: "🟣",
            InsightLevel.UNKNOWN: "⚪",
        }[self]

    @property
    def shell_color(self) -> str:
        """ANSI escape code for shell scripts."""
        return {
            InsightLevel.EXCELLENT: "\033[92m",   # Bright green
            InsightLevel.GOOD: "\033[32m",        # Green
            InsightLevel.OK: "\033[36m",          # Cyan
            InsightLevel.WARNING: "\033[33m",     # Yellow
            InsightLevel.CRITICAL: "\033[31m",    # Red
            InsightLevel.OVER_PROVISIONED: "\033[35m",  # Magenta
            InsightLevel.UNKNOWN: "\033[90m",     # Gray
        }[self]


# =============================================================================
# Insight Data Structures
# =============================================================================


@dataclass
class ResourceInsight:
    """Analysis result for a single resource metric.

    Attributes:
        level: Severity level of the insight
        message: Human-readable status message
        message_key: i18n message key for localization
        value: Current value of the metric
        limit: Maximum/total value (if applicable)
        percent: Percentage utilization (0-100)
        details: Additional context for verbose mode
    """
    level: InsightLevel
    message: str
    message_key: str
    value: Optional[float] = None
    limit: Optional[float] = None
    percent: Optional[float] = None
    details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "level": self.level.name,
            "message": self.message,
            "message_key": self.message_key,
            "value": self.value,
            "limit": self.limit,
            "percent": self.percent,
            "details": self.details,
        }

    def format_rich(self, verbose: bool = False) -> str:
        """Format for Rich console output with colors."""
        base = f"[{self.level.color}]{self.level.emoji} {self.message}[/{self.level.color}]"
        if verbose and self.details:
            base += f"\n    [dim]{self.details}[/dim]"
        return base

    def format_shell(self, verbose: bool = False) -> str:
        """Format for shell output with ANSI colors."""
        reset = "\033[0m"
        base = f"{self.level.shell_color}{self.level.emoji} {self.message}{reset}"
        if verbose and self.details:
            base += f"\n    \033[90m{self.details}{reset}"
        return base


# =============================================================================
# i18n Message Templates
# =============================================================================


class MessageTemplates:
    """i18n-ready message templates.

    Message keys follow the pattern: {resource}.{condition}
    Templates use {placeholders} for dynamic values.

    To add a new language, subclass and override messages dict.
    """

    # Default English messages
    messages: Dict[str, str] = {
        # Memory messages
        "memory.excellent": "plenty of memory available",
        "memory.good": "memory usage healthy",
        "memory.ok": "memory usage acceptable",
        "memory.warning": "memory nearing capacity",
        "memory.critical": "memory at capacity - performance may degrade",
        "memory.over_provisioned": "memory significantly over-provisioned",
        "memory.unknown": "memory status unknown",

        # CPU messages
        "cpu.excellent": "CPU barely utilized",
        "cpu.good": "CPU usage healthy",
        "cpu.ok": "CPU usage moderate",
        "cpu.warning": "CPU usage elevated",
        "cpu.critical": "CPU maxed out - system under heavy load",
        "cpu.over_provisioned": "CPU significantly under-utilized",
        "cpu.unknown": "CPU status unknown",

        # Disk messages
        "disk.excellent": "plenty of disk space",
        "disk.good": "disk usage healthy",
        "disk.ok": "disk usage acceptable",
        "disk.warning": "disk space running low",
        "disk.critical": "disk nearly full - action required",
        "disk.over_provisioned": "disk significantly over-provisioned",
        "disk.unknown": "disk status unknown",

        # Network/bandwidth messages
        "bandwidth.excellent": "network barely utilized",
        "bandwidth.good": "network usage healthy",
        "bandwidth.ok": "network usage moderate",
        "bandwidth.warning": "high network utilization",
        "bandwidth.critical": "network saturated - may cause timeouts",
        "bandwidth.over_provisioned": "network significantly under-utilized",
        "bandwidth.unknown": "network status unknown",

        # Container-specific messages
        "containers.excellent": "all containers healthy",
        "containers.good": "containers running normally",
        "containers.ok": "some containers restarting",
        "containers.warning": "container health degraded",
        "containers.critical": "containers failing - intervention needed",
        "containers.unknown": "container status unknown",

        # Overall status messages
        "overall.excellent": "system running optimally",
        "overall.good": "no issues detected",
        "overall.ok": "minor issues detected",
        "overall.warning": "attention recommended",
        "overall.critical": "immediate attention required",
        "overall.unknown": "unable to determine status",

        # Detail templates (verbose mode)
        "detail.percent": "{value:.1f}% of {limit} used",
        "detail.absolute": "{value} / {limit} ({percent:.1f}%)",
        "detail.rate": "{value:.1f} {unit}/s of {limit} {unit}/s capacity",
    }

    @classmethod
    def get(cls, key: str, **kwargs: Any) -> str:
        """Get a formatted message by key.

        Args:
            key: Message key (e.g., "memory.warning")
            **kwargs: Values for placeholder substitution

        Returns:
            Formatted message string
        """
        template = cls.messages.get(key, f"[{key}]")
        if kwargs:
            try:
                return template.format(**kwargs)
            except KeyError:
                return template
        return template


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class InsightConfig:
    """Configuration for resource insight thresholds.

    Thresholds are expressed as percentages (0-100).
    Can be loaded from environment variables or YAML.

    Environment variables (prefix: BREAKERAMP_INSIGHT_):
        BREAKERAMP_INSIGHT_MEMORY_WARNING=70
        BREAKERAMP_INSIGHT_MEMORY_CRITICAL=90
        BREAKERAMP_INSIGHT_CPU_WARNING=80
        etc.
    """

    # Memory thresholds (percentage)
    memory_excellent: float = 30.0
    memory_good: float = 50.0
    memory_warning: float = 70.0
    memory_critical: float = 90.0
    memory_over_provisioned: float = 10.0  # Below this = over-provisioned

    # CPU thresholds (percentage)
    cpu_excellent: float = 20.0
    cpu_good: float = 40.0
    cpu_warning: float = 70.0
    cpu_critical: float = 90.0
    cpu_over_provisioned: float = 5.0

    # Disk thresholds (percentage)
    disk_excellent: float = 30.0
    disk_good: float = 50.0
    disk_warning: float = 75.0
    disk_critical: float = 90.0
    disk_over_provisioned: float = 10.0

    # Bandwidth thresholds (percentage of capacity)
    bandwidth_excellent: float = 20.0
    bandwidth_good: float = 40.0
    bandwidth_warning: float = 70.0
    bandwidth_critical: float = 85.0
    bandwidth_over_provisioned: float = 5.0

    # Message templates class (for i18n override)
    message_templates: type = field(default=MessageTemplates)

    @classmethod
    def from_env(cls) -> "InsightConfig":
        """Load configuration from environment variables.

        Environment variable format:
            BREAKERAMP_INSIGHT_{RESOURCE}_{LEVEL}={value}

        Example:
            BREAKERAMP_INSIGHT_MEMORY_WARNING=75
            BREAKERAMP_INSIGHT_CPU_CRITICAL=95
        """
        config = cls()
        prefix = "BREAKERAMP_INSIGHT_"

        for resource in ("memory", "cpu", "disk", "bandwidth"):
            for level in ("excellent", "good", "warning", "critical", "over_provisioned"):
                env_key = f"{prefix}{resource.upper()}_{level.upper()}"
                env_value = os.environ.get(env_key)
                if env_value is not None:
                    try:
                        setattr(config, f"{resource}_{level}", float(env_value))
                    except ValueError:
                        pass  # Ignore invalid values

        return config

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsightConfig":
        """Load configuration from a dictionary (e.g., from YAML).

        Expected structure:
            thresholds:
              memory:
                excellent: 30
                warning: 70
                critical: 90
        """
        config = cls()

        thresholds = data.get("thresholds", data)
        for resource in ("memory", "cpu", "disk", "bandwidth"):
            resource_config = thresholds.get(resource, {})
            for level, value in resource_config.items():
                attr = f"{resource}_{level}"
                if hasattr(config, attr):
                    try:
                        setattr(config, attr, float(value))
                    except (ValueError, TypeError):
                        pass

        return config

    def to_dict(self) -> Dict[str, Dict[str, float]]:
        """Export configuration as nested dictionary."""
        result: Dict[str, Dict[str, float]] = {}
        for resource in ("memory", "cpu", "disk", "bandwidth"):
            result[resource] = {}
            for level in ("excellent", "good", "warning", "critical", "over_provisioned"):
                attr = f"{resource}_{level}"
                result[resource][level] = getattr(self, attr)
        return result


# =============================================================================
# Resource Insight Analyzer
# =============================================================================


class ResourceInsightAnalyzer:
    """Analyzes resource metrics and generates human-readable insights.

    Usage:
        analyzer = ResourceInsightAnalyzer()
        insights = analyzer.analyze(
            memory_used_mb=6000,
            memory_total_mb=8000,
            cpu_percent=45.0,
        )

        # Get formatted output
        for name, insight in insights.items():
            print(insight.format_rich())
    """

    def __init__(self, config: Optional[InsightConfig] = None):
        """Initialize analyzer with configuration.

        Args:
            config: InsightConfig instance. If None, loads from environment.
        """
        self.config = config or InsightConfig.from_env()
        self.messages = self.config.message_templates

    def analyze(
        self,
        memory_used_mb: Optional[float] = None,
        memory_total_mb: Optional[float] = None,
        cpu_percent: Optional[float] = None,
        disk_used_mb: Optional[float] = None,
        disk_total_mb: Optional[float] = None,
        bandwidth_used_mbps: Optional[float] = None,
        bandwidth_total_mbps: Optional[float] = None,
        container_health: Optional[Dict[str, str]] = None,
    ) -> Dict[str, ResourceInsight]:
        """Analyze all provided metrics and return insights.

        Args:
            memory_used_mb: Memory in use (MB)
            memory_total_mb: Total memory available (MB)
            cpu_percent: CPU utilization (0-100)
            disk_used_mb: Disk space in use (MB)
            disk_total_mb: Total disk space (MB)
            bandwidth_used_mbps: Current bandwidth usage (Mbps)
            bandwidth_total_mbps: Total bandwidth capacity (Mbps)
            container_health: Dict of container name -> status

        Returns:
            Dict mapping resource name to ResourceInsight
        """
        insights: Dict[str, ResourceInsight] = {}

        # Memory analysis
        if memory_total_mb is not None and memory_total_mb > 0:
            memory_used = memory_used_mb or 0
            insights["memory"] = self._analyze_resource(
                "memory",
                used=memory_used,
                total=memory_total_mb,
            )

        # CPU analysis
        if cpu_percent is not None:
            insights["cpu"] = self._analyze_resource(
                "cpu",
                percent=cpu_percent,
            )

        # Disk analysis
        if disk_total_mb is not None and disk_total_mb > 0:
            disk_used = disk_used_mb or 0
            insights["disk"] = self._analyze_resource(
                "disk",
                used=disk_used,
                total=disk_total_mb,
            )

        # Bandwidth analysis
        if bandwidth_total_mbps is not None and bandwidth_total_mbps > 0:
            bandwidth_used = bandwidth_used_mbps or 0
            insights["bandwidth"] = self._analyze_resource(
                "bandwidth",
                used=bandwidth_used,
                total=bandwidth_total_mbps,
            )

        # Container health analysis
        if container_health:
            insights["containers"] = self._analyze_containers(container_health)

        # Overall status (if we have any metrics)
        if insights:
            insights["overall"] = self._compute_overall(insights)

        return insights

    def _analyze_resource(
        self,
        resource: str,
        used: Optional[float] = None,
        total: Optional[float] = None,
        percent: Optional[float] = None,
    ) -> ResourceInsight:
        """Analyze a single resource metric.

        Args:
            resource: Resource name (memory, cpu, disk, bandwidth)
            used: Amount used
            total: Total capacity
            percent: Direct percentage (if not calculating from used/total)
        """
        # Calculate percentage if not provided
        if percent is None and used is not None and total is not None and total > 0:
            percent = (used / total) * 100

        if percent is None:
            return ResourceInsight(
                level=InsightLevel.UNKNOWN,
                message=self.messages.get(f"{resource}.unknown"),
                message_key=f"{resource}.unknown",
            )

        # Determine level based on thresholds
        level = self._get_level(resource, percent)
        message_key = f"{resource}.{level.name.lower()}"

        # Build detail string
        details = None
        if used is not None and total is not None:
            details = self.messages.get(
                "detail.absolute",
                value=f"{used:.0f}MB",
                limit=f"{total:.0f}MB",
                percent=percent,
            )
        elif percent is not None:
            details = f"{percent:.1f}% utilization"

        return ResourceInsight(
            level=level,
            message=self.messages.get(message_key),
            message_key=message_key,
            value=used,
            limit=total,
            percent=percent,
            details=details,
        )

    def _get_level(self, resource: str, percent: float) -> InsightLevel:
        """Determine insight level from percentage and thresholds."""
        # Check for over-provisioned first
        over_threshold = getattr(self.config, f"{resource}_over_provisioned", 10.0)
        if percent < over_threshold:
            return InsightLevel.OVER_PROVISIONED

        # Check thresholds from most severe to least
        critical = getattr(self.config, f"{resource}_critical", 90.0)
        warning = getattr(self.config, f"{resource}_warning", 70.0)
        good = getattr(self.config, f"{resource}_good", 50.0)
        excellent = getattr(self.config, f"{resource}_excellent", 30.0)

        if percent >= critical:
            return InsightLevel.CRITICAL
        elif percent >= warning:
            return InsightLevel.WARNING
        elif percent >= good:
            return InsightLevel.OK
        elif percent >= excellent:
            return InsightLevel.GOOD
        else:
            return InsightLevel.EXCELLENT

    def _analyze_containers(
        self,
        health: Dict[str, str],
    ) -> ResourceInsight:
        """Analyze container health status."""
        if not health:
            return ResourceInsight(
                level=InsightLevel.UNKNOWN,
                message=self.messages.get("containers.unknown"),
                message_key="containers.unknown",
            )

        statuses = list(health.values())
        total = len(statuses)
        healthy = sum(1 for s in statuses if s.lower() in ("running", "healthy", "up"))
        unhealthy = sum(1 for s in statuses if s.lower() in ("failed", "dead", "exited"))
        restarting = sum(1 for s in statuses if "restart" in s.lower())

        if unhealthy > 0:
            level = InsightLevel.CRITICAL
        elif restarting > 0:
            level = InsightLevel.WARNING
        elif healthy == total:
            level = InsightLevel.GOOD
        else:
            level = InsightLevel.OK

        message_key = f"containers.{level.name.lower()}"
        details = f"{healthy}/{total} containers healthy"
        if unhealthy > 0:
            details += f", {unhealthy} failed"
        if restarting > 0:
            details += f", {restarting} restarting"

        return ResourceInsight(
            level=level,
            message=self.messages.get(message_key),
            message_key=message_key,
            value=healthy,
            limit=total,
            percent=(healthy / total * 100) if total > 0 else None,
            details=details,
        )

    def _compute_overall(
        self,
        insights: Dict[str, ResourceInsight],
    ) -> ResourceInsight:
        """Compute overall status from individual insights."""
        # Exclude 'overall' if present
        resource_insights = {k: v for k, v in insights.items() if k != "overall"}

        if not resource_insights:
            return ResourceInsight(
                level=InsightLevel.UNKNOWN,
                message=self.messages.get("overall.unknown"),
                message_key="overall.unknown",
            )

        # Find the worst level
        worst_level = InsightLevel.EXCELLENT
        worst_resources: list[str] = []

        for name, insight in resource_insights.items():
            if insight.level == InsightLevel.UNKNOWN:
                continue
            if insight.level.value > worst_level.value:
                worst_level = insight.level
                worst_resources = [name]
            elif insight.level == worst_level:
                worst_resources.append(name)

        # Map to overall message
        if worst_level in (InsightLevel.CRITICAL, InsightLevel.WARNING):
            message_key = f"overall.{worst_level.name.lower()}"
        elif worst_level == InsightLevel.OVER_PROVISIONED:
            message_key = "overall.ok"
        elif worst_level in (InsightLevel.OK, InsightLevel.GOOD, InsightLevel.EXCELLENT):
            message_key = f"overall.{worst_level.name.lower()}"
        else:
            message_key = "overall.unknown"

        details = None
        if worst_resources and worst_level in (InsightLevel.WARNING, InsightLevel.CRITICAL):
            details = f"Issues with: {', '.join(worst_resources)}"

        return ResourceInsight(
            level=worst_level,
            message=self.messages.get(message_key),
            message_key=message_key,
            details=details,
        )

    def format_summary(
        self,
        insights: Dict[str, ResourceInsight],
        verbose: bool = False,
    ) -> str:
        """Format all insights for Rich console output.

        Args:
            insights: Dict of resource name -> ResourceInsight
            verbose: Include detailed information

        Returns:
            Formatted string for Rich console
        """
        lines = []

        # Order: memory, cpu, disk, bandwidth, containers, overall
        order = ["memory", "cpu", "disk", "bandwidth", "containers", "overall"]

        for resource in order:
            if resource in insights:
                insight = insights[resource]
                label = resource.capitalize()
                formatted = insight.format_rich(verbose=verbose)
                if resource == "overall":
                    lines.append("")  # Blank line before overall
                    lines.append(f"[bold]{label}:[/bold] {formatted}")
                else:
                    lines.append(f"  {label}: {formatted}")

        return "\n".join(lines)

    def format_shell_summary(
        self,
        insights: Dict[str, ResourceInsight],
        verbose: bool = False,
    ) -> str:
        """Format all insights for shell script output.

        Args:
            insights: Dict of resource name -> ResourceInsight
            verbose: Include detailed information

        Returns:
            Formatted string with ANSI colors
        """
        lines = []
        reset = "\033[0m"
        bold = "\033[1m"

        order = ["memory", "cpu", "disk", "bandwidth", "containers", "overall"]

        for resource in order:
            if resource in insights:
                insight = insights[resource]
                label = resource.capitalize()
                formatted = insight.format_shell(verbose=verbose)
                if resource == "overall":
                    lines.append("")
                    lines.append(f"{bold}{label}:{reset} {formatted}")
                else:
                    lines.append(f"  {label}: {formatted}")

        return "\n".join(lines)


# =============================================================================
# Utility Functions
# =============================================================================


def analyze_resources(**kwargs: Any) -> Dict[str, ResourceInsight]:
    """Convenience function to analyze resources with default config.

    See ResourceInsightAnalyzer.analyze() for parameters.
    """
    analyzer = ResourceInsightAnalyzer()
    return analyzer.analyze(**kwargs)


def get_insight_summary(
    insights: Dict[str, ResourceInsight],
    verbose: bool = False,
    shell: bool = False,
) -> str:
    """Get formatted summary of insights.

    Args:
        insights: Dict of resource insights
        verbose: Include detailed information
        shell: Use shell ANSI colors instead of Rich markup
    """
    analyzer = ResourceInsightAnalyzer()
    if shell:
        return analyzer.format_shell_summary(insights, verbose=verbose)
    return analyzer.format_summary(insights, verbose=verbose)
