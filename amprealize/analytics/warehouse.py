"""Analytics warehouse - OSS Stub. Full implementation in amprealize-enterprise."""

try:
    from amprealize_enterprise.analytics.warehouse import AnalyticsWarehouse
except ImportError:

    class AnalyticsWarehouse:  # type: ignore[no-redef]
        """OSS stub returning empty data for all analytics queries."""

        def __init__(self, db_path: str | None = None, **kwargs) -> None:
            self.db_path = db_path

        def get_kpi_summary(self, **kwargs) -> list:  # type: ignore[override]
            return []

        def get_behavior_usage(self, **kwargs) -> list:  # type: ignore[override]
            return []

        def get_token_savings(self, **kwargs) -> list:  # type: ignore[override]
            return []

        def get_compliance_coverage(self, **kwargs) -> list:  # type: ignore[override]
            return []

        def get_cost_summary(self, **kwargs) -> list:  # type: ignore[override]
            return []

        def get_daily_trends(self, **kwargs) -> list:  # type: ignore[override]
            return []

        def ingest(self, events: list) -> int:
            return 0
