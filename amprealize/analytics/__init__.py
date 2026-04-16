"""Analytics utilities.

Provides an in-memory KPI projector and a no-op analytics warehouse.
The enterprise edition replaces these with production-grade backends.
"""

from .telemetry_kpi_projector import TelemetryKPIProjector, TelemetryProjection

__all__ = ["TelemetryKPIProjector", "TelemetryProjection"]
