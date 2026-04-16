"""Analytics warehouse.

Returns empty datasets in OSS.  The enterprise edition replaces this
module with a production-grade analytics backend.
"""

from __future__ import annotations


class AnalyticsWarehouse:
    """No-op analytics warehouse for the OSS edition.

    Every query method returns an empty list; ``ingest`` silently discards
    events.  The enterprise edition provides a real implementation.
    """

    def __init__(self, db_path: str | None = None, **kwargs) -> None:
        self.db_path = db_path

    def get_kpi_summary(self, **kwargs) -> list:
        return []

    def get_behavior_usage(self, **kwargs) -> list:
        return []

    def get_token_savings(self, **kwargs) -> list:
        return []

    def get_compliance_coverage(self, **kwargs) -> list:
        return []

    def get_cost_summary(self, **kwargs) -> list:
        return []

    def get_daily_trends(self, **kwargs) -> list:
        return []

    def ingest(self, events: list) -> int:
        return 0
