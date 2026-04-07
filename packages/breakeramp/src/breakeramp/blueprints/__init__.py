"""BreakerAmp Blueprint Definitions.

Pre-configured environment blueprints for common use cases.

Available blueprints:
- analytics-dashboard: Metabase dashboard for analytics
- ci-test-stack: CI/CD testing environment
- core-data-plane: Core data plane services
- local-test-suite: Local development testing
- metrics-timescaledb: TimescaleDB for metrics
- postgres.timescale.test: TimescaleDB test instance
- streaming-ha: High-availability streaming setup
- streaming-simple: Simple streaming setup
- telemetry-pipeline: Telemetry data pipeline

Usage:
    from breakeramp.blueprints import get_blueprint_path, list_blueprints

    # Get path to a specific blueprint
    path = get_blueprint_path("local-test-suite")

    # List all available blueprints
    names = list_blueprints()
"""

from pathlib import Path
from typing import List, Optional

__all__ = ["get_blueprint_path", "list_blueprints", "BLUEPRINTS_DIR"]

BLUEPRINTS_DIR = Path(__file__).parent


def get_blueprint_path(name: str) -> Optional[Path]:
    """Get the path to a blueprint YAML file.

    Args:
        name: Blueprint name (with or without .yaml extension)

    Returns:
        Path to the blueprint file, or None if not found
    """
    # Normalize name
    if not name.endswith(".yaml"):
        name = f"{name}.yaml"

    blueprint_path = BLUEPRINTS_DIR / name
    if blueprint_path.exists():
        return blueprint_path
    return None


def list_blueprints() -> List[str]:
    """List all available blueprint names.

    Returns:
        List of blueprint names (without .yaml extension)
    """
    blueprints = []
    for path in BLUEPRINTS_DIR.glob("*.yaml"):
        blueprints.append(path.stem)
    return sorted(blueprints)
