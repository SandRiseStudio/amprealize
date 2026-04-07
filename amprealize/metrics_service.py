"""MetricsService - Real-time metrics aggregation and caching layer.

Provides streaming telemetry handlers, cache layer, and integration with
TelemetryKPIProjector and AnalyticsWarehouse for dashboard consumption.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from amprealize.metrics_contracts import (
    MetricsExportRequest,
    MetricsExportResult,
    MetricsSubscription,
    MetricsSummary,
)

try:
    from amprealize.analytics.warehouse import AnalyticsWarehouse
except ImportError:
    AnalyticsWarehouse = None  # type: ignore

try:
    from amprealize.analytics.telemetry_kpi_projector import TelemetryKPIProjector
except ImportError:
    TelemetryKPIProjector = None  # type: ignore


def _utc_now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


class MetricsService:
    """Service for real-time metrics aggregation with caching.

    Features:
    - In-memory + SQLite cache for metrics summaries
    - Integration with AnalyticsWarehouse for batch queries
    - TelemetryKPIProjector integration for event-driven updates
    - SSE streaming support for real-time dashboard updates
    - Export operations (JSON/CSV/Parquet)

    Cache Strategy:
    - Summary metrics cached for 30 seconds by default
    - Cache invalidation on telemetry writes
    - Lazy refresh on cache miss
    """

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        warehouse_path: Optional[str | Path] = None,
        cache_ttl_seconds: int = 30,
    ):
        """Initialize MetricsService.

        Args:
            db_path: Path to SQLite cache database
            warehouse_path: Path to DuckDB analytics warehouse
            cache_ttl_seconds: TTL for cached metrics (default 30s)
        """
        self.cache_ttl_seconds = cache_ttl_seconds

        # Default cache path
        if db_path is None:
            repo_root = Path(__file__).parent.parent
            cache_dir = repo_root / "data" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = cache_dir / "metrics_cache.db"

        self.db_path = str(db_path)
        self._init_cache_db()

        # Warehouse integration
        self.warehouse_path = warehouse_path
        self._warehouse: Optional[AnalyticsWarehouse] = None

        # Active subscriptions for SSE streaming
        self._subscriptions: Dict[str, MetricsSubscription] = {}

    def emit_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        actor: Optional[Any] = None,
    ) -> None:
        """Stub method for compatibility with BreakerAmpService.

        MetricsService is primarily for querying/aggregating metrics, not emitting events.
        Event emission is handled by TelemetryClient. This method exists for backwards
        compatibility and does nothing.

        Args:
            event_type: Type of event (ignored)
            payload: Event payload (ignored)
            actor: Actor context (ignored)
        """
        pass  # No-op for now; telemetry should use TelemetryClient

    def _init_cache_db(self) -> None:
        """Initialize SQLite cache schema."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics_cache (
                    cache_key TEXT PRIMARY KEY,
                    cached_at REAL NOT NULL,
                    ttl_seconds INTEGER NOT NULL,
                    data_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_cache_ttl
                ON metrics_cache(cached_at, ttl_seconds)
            """)
            conn.commit()
        finally:
            conn.close()

    @property
    def warehouse(self) -> AnalyticsWarehouse:
        """Lazy AnalyticsWarehouse connection."""
        if self._warehouse is None:
            if AnalyticsWarehouse is None:
                raise RuntimeError(
                    "AnalyticsWarehouse not available. Install duckdb: "
                    "pip install 'duckdb>=0.9,<1.0'"
                )
            self._warehouse = AnalyticsWarehouse(db_path=self.warehouse_path)
        return self._warehouse

    def _get_cached(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached data if not expired.

        Args:
            cache_key: Key to lookup

        Returns:
            Cached data dict or None if expired/missing
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT cached_at, ttl_seconds, data_json
                FROM metrics_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            cached_at, ttl_seconds, data_json = row
            age_seconds = time.time() - cached_at

            if age_seconds > ttl_seconds:
                # Expired - delete and return None
                conn.execute("DELETE FROM metrics_cache WHERE cache_key = ?", (cache_key,))
                conn.commit()
                return None

            data = json.loads(data_json)
            data["cache_hit"] = True
            data["cache_age_seconds"] = age_seconds
            return data
        finally:
            conn.close()

    def _set_cached(self, cache_key: str, data: Dict[str, Any]) -> None:
        """Store data in cache.

        Args:
            cache_key: Key to store under
            data: Data dictionary to cache
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO metrics_cache (cache_key, cached_at, ttl_seconds, data_json)
                VALUES (?, ?, ?, ?)
                """,
                (cache_key, time.time(), self.cache_ttl_seconds, json.dumps(data)),
            )
            conn.commit()
        finally:
            conn.close()

    def invalidate_cache(self, cache_key: Optional[str] = None) -> int:
        """Invalidate cache entries.

        Args:
            cache_key: Specific key to invalidate (None = all)

        Returns:
            Number of entries invalidated
        """
        conn = sqlite3.connect(self.db_path)
        try:
            if cache_key is None:
                cursor = conn.execute("DELETE FROM metrics_cache")
            else:
                cursor = conn.execute(
                    "DELETE FROM metrics_cache WHERE cache_key = ?",
                    (cache_key,),
                )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def get_summary(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        use_cache: bool = True,
    ) -> MetricsSummary:
        """Get aggregated metrics summary.

        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            use_cache: Whether to use cached data

        Returns:
            MetricsSummary with PRD KPIs
        """
        cache_key = f"summary:{start_date}:{end_date}"

        # Try cache first
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return MetricsSummary(**cached)

        # Cache miss - query warehouse
        try:
            results = self.warehouse.get_kpi_summary(
                start_date=start_date,
                end_date=end_date,
            )

            if not results:
                # No data - return empty summary
                summary_dict = {
                    "snapshot_time": _utc_now_iso(),
                    "behavior_reuse_pct": 0.0,
                    "average_token_savings_pct": 0.0,
                    "task_completion_rate_pct": 0.0,
                    "average_compliance_coverage_pct": 0.0,
                    "total_runs": 0,
                    "runs_with_behaviors": 0,
                    "total_baseline_tokens": 0,
                    "total_output_tokens": 0,
                    "completed_runs": 0,
                    "failed_runs": 0,
                    "total_compliance_events": 0,
                    "cache_hit": False,
                    "cache_age_seconds": 0.0,
                }
            else:
                # Map warehouse result to MetricsSummary
                row = results[0]
                summary_dict = {
                    "snapshot_time": str(row.get("snapshot_time", _utc_now_iso())),
                    "behavior_reuse_pct": float(row.get("behavior_reuse_pct") or 0.0),
                    "average_token_savings_pct": float(row.get("average_token_savings_pct") or 0.0),
                    "task_completion_rate_pct": float(row.get("task_completion_rate_pct") or 0.0),
                    "average_compliance_coverage_pct": float(row.get("average_compliance_coverage_pct") or 0.0),
                    "total_runs": int(row.get("total_runs") or 0),
                    "runs_with_behaviors": int(row.get("runs_with_behaviors") or 0),
                    "total_baseline_tokens": int(row.get("total_baseline_tokens") or 0),
                    "total_output_tokens": int(row.get("total_output_tokens") or 0),
                    "completed_runs": int(row.get("completed_runs") or 0),
                    "failed_runs": int(row.get("failed_runs") or 0),
                    "total_compliance_events": int(row.get("total_compliance_events") or 0),
                    "cache_hit": False,
                    "cache_age_seconds": 0.0,
                }

            # Cache the result
            if use_cache:
                self._set_cached(cache_key, summary_dict)

            return MetricsSummary(**summary_dict)

        except Exception as e:
            # Fallback to empty summary on error
            print(f"Warning: Failed to query metrics warehouse: {e}")
            fallback_dict = {
                "snapshot_time": _utc_now_iso(),
                "behavior_reuse_pct": 0.0,
                "average_token_savings_pct": 0.0,
                "task_completion_rate_pct": 0.0,
                "average_compliance_coverage_pct": 0.0,
                "total_runs": 0,
                "runs_with_behaviors": 0,
                "total_baseline_tokens": 0,
                "total_output_tokens": 0,
                "completed_runs": 0,
                "failed_runs": 0,
                "total_compliance_events": 0,
                "cache_hit": False,
                "cache_age_seconds": 0.0,
            }
            if use_cache:
                self._set_cached(cache_key, fallback_dict)
            return MetricsSummary(**fallback_dict)

    def export_metrics(
        self,
        request: MetricsExportRequest,
    ) -> MetricsExportResult:
        """Export metrics data to file or inline.

        Args:
            request: Export request with format and filters

        Returns:
            MetricsExportResult with export details
        """
        export_id = str(uuid.uuid4())
        created_at = _utc_now_iso()

        # For now, only support JSON inline export
        # CSV/Parquet would require additional dependencies
        if request.format not in ("json",):
            raise ValueError(f"Unsupported export format: {request.format}")

        # Query summary data
        summary = self.get_summary(
            start_date=request.start_date,
            end_date=request.end_date,
            use_cache=False,  # Always fetch fresh for exports
        )

        # Convert to dict list
        data = [
            {
                "snapshot_time": summary.snapshot_time,
                "behavior_reuse_pct": summary.behavior_reuse_pct,
                "average_token_savings_pct": summary.average_token_savings_pct,
                "task_completion_rate_pct": summary.task_completion_rate_pct,
                "average_compliance_coverage_pct": summary.average_compliance_coverage_pct,
                "total_runs": summary.total_runs,
                "runs_with_behaviors": summary.runs_with_behaviors,
                "total_baseline_tokens": summary.total_baseline_tokens,
                "total_output_tokens": summary.total_output_tokens,
                "completed_runs": summary.completed_runs,
                "failed_runs": summary.failed_runs,
                "total_compliance_events": summary.total_compliance_events,
            }
        ]

        # Calculate size
        data_json = json.dumps(data)
        size_bytes = len(data_json.encode("utf-8"))

        return MetricsExportResult(
            export_id=export_id,
            format=request.format,
            row_count=len(data),
            created_at=created_at,
            size_bytes=size_bytes,
            data=data,
        )

    def create_subscription(
        self,
        metrics: Optional[List[str]] = None,
        refresh_interval_seconds: int = 30,
    ) -> MetricsSubscription:
        """Create a new real-time metrics subscription.

        Args:
            metrics: List of metric names to stream (None = all KPIs)
            refresh_interval_seconds: Update frequency

        Returns:
            MetricsSubscription with subscription_id
        """
        subscription_id = str(uuid.uuid4())
        subscription = MetricsSubscription(
            subscription_id=subscription_id,
            metrics=metrics or [],
            refresh_interval_seconds=refresh_interval_seconds,
            created_at=_utc_now_iso(),
            event_count=0,
        )
        self._subscriptions[subscription_id] = subscription
        return subscription

    def stream_subscription(
        self,
        subscription_id: str,
    ) -> Iterator[MetricsSummary]:
        """Stream metrics updates for a subscription (SSE).

        Args:
            subscription_id: Subscription to stream

        Yields:
            MetricsSummary objects at refresh_interval_seconds
        """
        subscription = self._subscriptions.get(subscription_id)
        if subscription is None:
            raise ValueError(f"Subscription not found: {subscription_id}")

        try:
            while True:
                # Fetch latest summary
                summary = self.get_summary(use_cache=True)
                subscription.event_count += 1
                yield summary

                # Wait for next interval
                time.sleep(subscription.refresh_interval_seconds)
        finally:
            # Clean up subscription on exit
            self._subscriptions.pop(subscription_id, None)

    def cancel_subscription(self, subscription_id: str) -> bool:
        """Cancel an active subscription.

        Args:
            subscription_id: Subscription to cancel

        Returns:
            True if subscription existed and was cancelled
        """
        return self._subscriptions.pop(subscription_id, None) is not None

    def list_subscriptions(self) -> List[MetricsSubscription]:
        """List all active subscriptions.

        Returns:
            List of active MetricsSubscription objects
        """
        return list(self._subscriptions.values())
