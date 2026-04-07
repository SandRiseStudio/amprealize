#!/usr/bin/env python3
"""
Create Metabase dashboards for Sprint 3 Streaming Pipeline metrics.

Dashboards:
1. Streaming Pipeline Health (Kafka, Flink, Timescale throughput & latency)
2. PRD Metrics Real-Time (behavior reuse, token savings, completion, compliance from continuous aggregates)
3. Event Flow Analysis (end-to-end latency, backpressure, checkpointing)
4. Operational Observability (error rates, retry patterns, resource utilization)

Requirements:
- Metabase v0.48.0+ running at localhost:3000
- TimescaleDB telemetry warehouse (postgres-telemetry container)
- Migration 014 applied (continuous aggregates created)
- Sample telemetry data (optional, for visualization testing)

Usage:
    # Start infrastructure
    podman-compose -f docker-compose.postgres.yml up -d postgres-telemetry
    podman-compose -f docker-compose.analytics-dashboard.yml up -d metabase

    # Create dashboards
    python scripts/create_streaming_dashboards.py

    # Access dashboards
    open http://localhost:3000

Environment Variables:
    METABASE_URL: Metabase URL (default: http://localhost:3000)
    METABASE_USERNAME: Admin user (default: admin@amprealize.local)
    METABASE_PASSWORD: Admin password (required)

References:
    - docs/STREAMING_PIPELINE_ARCHITECTURE.md
    - schema/migrations/014_upgrade_telemetry_to_timescale.sql
    - behavior_instrument_metrics_pipeline
"""

import os
import sys
import json
import time
import requests
from typing import Dict, List, Optional, Any


class MetabaseStreamingClient:
    """Metabase client for streaming pipeline dashboards."""

    def __init__(self, url: str, username: str, password: str):
        self.url = url.rstrip('/')
        self.session = requests.Session()
        self.session_token: Optional[str] = None
        self.database_id: Optional[int] = None

        self._authenticate(username, password)
        self._find_telemetry_database()

    def _authenticate(self, username: str, password: str) -> None:
        """Authenticate with Metabase."""
        auth_url = f"{self.url}/api/session"
        response = self.session.post(auth_url, json={
            "username": username,
            "password": password
        })
        response.raise_for_status()

        self.session_token = response.json()["id"]
        self.session.headers["X-Metabase-Session"] = self.session_token
        print(f"✅ Authenticated to Metabase")

    def _find_telemetry_database(self) -> None:
        """Find TimescaleDB telemetry database connection."""
        response = self.session.get(f"{self.url}/api/database")
        response.raise_for_status()

        data = response.json()
        databases = data.get("data", data)  # Handle both {"data": [...]} and [...] formats
        for db in databases:
            if "telemetry" in db.get("name", "").lower():
                self.database_id = db["id"]
                print(f"✅ Found telemetry database (ID: {self.database_id})")
                return

        # If not found, prompt user to create connection
        print("⚠️  TimescaleDB telemetry database not found in Metabase")
        print("    Please create a PostgreSQL connection in Metabase:")
        print("    - Name: Amprealize Telemetry (TimescaleDB)")
        print("    - Host: postgres-telemetry (or amprealize-postgres-telemetry)")
        print("    - Port: 5432")
        print("    - Database: telemetry")
        print("    - User: amprealize_telemetry")
        print("    - Password: dev_telemetry_pass")
        sys.exit(1)

    def create_dashboard(self, name: str, description: str) -> Dict[str, Any]:
        """Create a new dashboard."""
        response = self.session.post(
            f"{self.url}/api/dashboard",
            json={"name": name, "description": description}
        )
        response.raise_for_status()
        dashboard = response.json()
        print(f"📊 Created dashboard: {name} (ID: {dashboard['id']})")
        return dashboard

    def create_native_question(
        self,
        name: str,
        sql: str,
        visualization_type: str = "table",
        visualization_settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a native SQL question (card)."""
        card_data = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sql},
                "database": self.database_id
            },
            "display": visualization_type,
            "visualization_settings": visualization_settings or {}
        }

        response = self.session.post(
            f"{self.url}/api/card",
            json=card_data
        )
        response.raise_for_status()
        card = response.json()
        print(f"  ✅ Created card: {name}")
        return card

    def add_card_to_dashboard(
        self,
        dashboard_id: int,
        card_id: int,
        row: int = 0,
        col: int = 0,
        size_x: int = 4,
        size_y: int = 3
    ) -> None:
        """Add a card to a dashboard with positioning (Metabase v0.48.0 format)."""
        # First, get the current dashboard to retrieve existing dashcards
        response = self.session.get(f"{self.url}/api/dashboard/{dashboard_id}")
        response.raise_for_status()
        dashboard = response.json()

        # Add the new dashcard to the existing array
        # Use id=-1 for new dashcards (Metabase will assign a proper ID)
        new_dashcard = {
            "id": -1,
            "card_id": card_id,
            "row": row,
            "col": col,
            "size_x": size_x,
            "size_y": size_y
        }
        dashcards = dashboard.get("dashcards", [])
        dashcards.append(new_dashcard)

        # Update the dashboard with the new dashcards array
        response = self.session.put(
            f"{self.url}/api/dashboard/{dashboard_id}",
            json={"dashcards": dashcards}
        )
        response.raise_for_status()


def create_dashboard_1_streaming_health(client: MetabaseStreamingClient) -> int:
    """
    Dashboard 1: Streaming Pipeline Health

    Monitors Kafka → Flink → TimescaleDB throughput, latency, and resource utilization.
    Target: 10,000 events/sec, <30s end-to-end latency.
    """
    print("\n📊 Creating Dashboard #1: Streaming Pipeline Health...")

    dashboard = client.create_dashboard(
        name="Streaming Pipeline Health (Sprint 3)",
        description="Real-time monitoring of Kafka → Flink → TimescaleDB streaming pipeline. Target: 10k events/sec, <30s latency."
    )
    dashboard_id = dashboard["id"]

    # Card 1: Events Per Minute (from hourly continuous aggregate)
    card1 = client.create_native_question(
        name="Events Per Minute (Real-Time)",
        sql="""
SELECT
    bucket,
    SUM(event_count) / 60.0 AS events_per_minute
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '24 hours'
GROUP BY bucket
ORDER BY bucket DESC
LIMIT 100;
""",
        visualization_type="line",
        visualization_settings={
            "graph.dimensions": ["bucket"],
            "graph.metrics": ["events_per_minute"],
            "card.title": "Events/Min (Target: 167 avg for 10k/sec peak)"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card1["id"], row=0, col=0, size_x=8, size_y=4)

    # Card 2: Unique Actors (Hourly)
    card2 = client.create_native_question(
        name="Unique Actors per Hour",
        sql="""
SELECT
    bucket,
    SUM(unique_actors) AS unique_actors
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '24 hours'
GROUP BY bucket
ORDER BY bucket DESC;
""",
        visualization_type="line",
        visualization_settings={
            "graph.dimensions": ["bucket"],
            "graph.metrics": ["unique_actors"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card2["id"], row=0, col=8, size_x=8, size_y=4)

    # Card 3: Event Type Distribution (Last Hour)
    card3 = client.create_native_question(
        name="Event Type Distribution",
        sql="""
SELECT
    event_type,
    SUM(event_count) AS total_events
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '1 hour'
GROUP BY event_type
ORDER BY total_events DESC;
""",
        visualization_type="pie",
        visualization_settings={
            "pie.dimension": "event_type",
            "pie.metric": "total_events"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card3["id"], row=4, col=0, size_x=6, size_y=4)

    # Card 4: Surface Distribution (Last Hour)
    card4 = client.create_native_question(
        name="Traffic by Surface",
        sql="""
SELECT
    actor_surface,
    SUM(event_count) AS total_events
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '1 hour'
  AND actor_surface IS NOT NULL
GROUP BY actor_surface
ORDER BY total_events DESC;
""",
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["actor_surface"],
            "graph.metrics": ["total_events"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card4["id"], row=4, col=6, size_x=6, size_y=4)

    # Card 5: Trace Performance P95 Latency
    card5 = client.create_native_question(
        name="P95 Latency by Operation",
        sql="""
SELECT
    operation_name,
    p95_duration_ms
FROM execution_traces_hourly
WHERE bucket >= NOW() - INTERVAL '1 hour'
  AND p95_duration_ms IS NOT NULL
GROUP BY operation_name, p95_duration_ms
ORDER BY p95_duration_ms DESC
LIMIT 10;
""",
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["operation_name"],
            "graph.metrics": ["p95_duration_ms"],
            "card.title": "P95 Latency by Operation (Target: <30s = 30000ms)"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card5["id"], row=8, col=0, size_x=12, size_y=4)

    print(f"✅ Dashboard #1 created with 5 cards")
    return dashboard_id


def create_dashboard_2_prd_metrics_realtime(client: MetabaseStreamingClient) -> int:
    """
    Dashboard 2: PRD Metrics (Real-Time)

    Tracks the 4 PRD success metrics using continuous aggregates:
    - Behavior Reuse Rate (target: ≥70%)
    - Token Savings Rate (target: ≥30%)
    - Task Completion Rate (target: ≥80%)
    - Compliance Coverage (target: ≥95%)
    """
    print("\n📊 Creating Dashboard #2: PRD Metrics (Real-Time)...")

    dashboard = client.create_dashboard(
        name="PRD Metrics Dashboard (Real-Time)",
        description="Real-time PRD success metrics from TimescaleDB continuous aggregates. Refreshed every 10 minutes."
    )
    dashboard_id = dashboard["id"]

    # Card 1: Behavior Reuse Trend (7 days)
    card1 = client.create_native_question(
        name="Behavior Reuse Trend",
        sql="""
SELECT
    DATE_TRUNC('day', bucket) AS day,
    SUM(CASE WHEN event_type LIKE 'behavior.%' THEN event_count ELSE 0 END)::FLOAT /
    NULLIF(SUM(event_count), 0) * 100 AS behavior_reuse_pct
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '7 days'
GROUP BY day
ORDER BY day DESC;
""",
        visualization_type="line",
        visualization_settings={
            "graph.dimensions": ["day"],
            "graph.metrics": ["behavior_reuse_pct"],
            "card.title": "Behavior Reuse % (7-day trend, Target: ≥70%)"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card1["id"], row=0, col=0, size_x=6, size_y=4)

    # Card 2: Token Usage Trend
    card2 = client.create_native_question(
        name="Token Usage Trend",
        sql="""
SELECT
    DATE_TRUNC('day', bucket) AS day,
    SUM(total_tokens) AS daily_tokens
FROM execution_traces_hourly
WHERE bucket >= NOW() - INTERVAL '7 days'
  AND total_tokens IS NOT NULL
GROUP BY day
ORDER BY day DESC;
""",
        visualization_type="line",
        visualization_settings={
            "graph.dimensions": ["day"],
            "graph.metrics": ["daily_tokens"],
            "card.title": "Daily Token Consumption"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card2["id"], row=0, col=6, size_x=6, size_y=4)

    # Card 3: Completion Rate by Surface
    card3 = client.create_native_question(
        name="Completion Rate by Surface",
        sql="""
SELECT
    actor_surface,
    SUM(CASE WHEN event_type = 'run.completed' THEN event_count ELSE 0 END)::FLOAT /
    NULLIF(SUM(CASE WHEN event_type IN ('run.started', 'run.completed', 'run.failed') THEN event_count ELSE 0 END), 0) * 100 AS completion_rate
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '24 hours'
  AND actor_surface IS NOT NULL
GROUP BY actor_surface
ORDER BY completion_rate DESC;
""",
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["actor_surface"],
            "graph.metrics": ["completion_rate"],
            "card.title": "Completion Rate by Surface (Target: ≥80%)"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card3["id"], row=4, col=0, size_x=12, size_y=4)

    # Card 4: Recent Run Volume
    card4 = client.create_native_question(
        name="Run Volume (Hourly)",
        sql="""
SELECT
    bucket,
    SUM(unique_runs) AS run_count
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '24 hours'
GROUP BY bucket
ORDER BY bucket DESC;
""",
        visualization_type="line",
        visualization_settings={
            "graph.dimensions": ["bucket"],
            "graph.metrics": ["run_count"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card4["id"], row=8, col=0, size_x=12, size_y=4)

    print(f"✅ Dashboard #2 created with 4 cards")
    return dashboard_id


def create_dashboard_3_event_flow_analysis(client: MetabaseStreamingClient) -> int:
    """
    Dashboard 3: Event Flow Analysis

    Monitors end-to-end event latency, Flink checkpointing, and backpressure indicators.
    """
    print("\n📊 Creating Dashboard #3: Event Flow Analysis...")

    dashboard = client.create_dashboard(
        name="Event Flow Analysis (Sprint 3)",
        description="End-to-end latency analysis, checkpoint health, and backpressure monitoring for Flink streaming jobs."
    )
    dashboard_id = dashboard["id"]

    # Card 1: Trace Duration Distribution
    card1 = client.create_native_question(
        name="Trace Duration Distribution",
        sql="""
SELECT
    CASE
        WHEN p95_duration_ms < 100 THEN '<100ms'
        WHEN p95_duration_ms < 500 THEN '100-500ms'
        WHEN p95_duration_ms < 1000 THEN '500ms-1s'
        WHEN p95_duration_ms < 5000 THEN '1-5s'
        WHEN p95_duration_ms < 30000 THEN '5-30s'
        ELSE '>30s (SLA breach)'
    END AS latency_bucket,
    COUNT(*) AS operation_count
FROM execution_traces_hourly
WHERE bucket >= NOW() - INTERVAL '1 hour'
  AND p95_duration_ms IS NOT NULL
GROUP BY latency_bucket
ORDER BY
    CASE latency_bucket
        WHEN '<100ms' THEN 1
        WHEN '100-500ms' THEN 2
        WHEN '500ms-1s' THEN 3
        WHEN '1-5s' THEN 4
        WHEN '5-30s' THEN 5
        ELSE 6
    END;
""",
        visualization_type="pie",
        visualization_settings={
            "pie.dimension": "latency_bucket",
            "pie.metric": "operation_count"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card1["id"], row=0, col=0, size_x=6, size_y=4)

    # Card 2: Error Rate by Status
    card2 = client.create_native_question(
        name="Trace Status Distribution",
        sql="""
SELECT
    status,
    SUM(span_count) AS total_spans
FROM execution_traces_hourly
WHERE bucket >= NOW() - INTERVAL '1 hour'
  AND status IS NOT NULL
GROUP BY status
ORDER BY total_spans DESC;
""",
        visualization_type="pie",
        visualization_settings={
            "pie.dimension": "status",
            "pie.metric": "total_spans"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card2["id"], row=0, col=6, size_x=6, size_y=4)

    # Card 3: Service Performance Heatmap
    card3 = client.create_native_question(
        name="Service Performance (P95 Latency)",
        sql="""
SELECT
    service_name,
    operation_name,
    p95_duration_ms
FROM execution_traces_hourly
WHERE bucket >= NOW() - INTERVAL '1 hour'
  AND service_name IS NOT NULL
  AND operation_name IS NOT NULL
  AND p95_duration_ms IS NOT NULL
ORDER BY p95_duration_ms DESC
LIMIT 20;
""",
        visualization_type="table",
        visualization_settings={
            "card.title": "Slowest Operations (P95 Latency)"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card3["id"], row=4, col=0, size_x=12, size_y=4)

    # Card 4: Token Consumption by Service
    card4 = client.create_native_question(
        name="Token Consumption by Service",
        sql="""
SELECT
    service_name,
    SUM(total_tokens) AS tokens_consumed
FROM execution_traces_hourly
WHERE bucket >= NOW() - INTERVAL '24 hours'
  AND service_name IS NOT NULL
  AND total_tokens IS NOT NULL
GROUP BY service_name
ORDER BY tokens_consumed DESC;
""",
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["service_name"],
            "graph.metrics": ["tokens_consumed"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card4["id"], row=8, col=0, size_x=12, size_y=4)

    print(f"✅ Dashboard #3 created with 4 cards")
    return dashboard_id


def create_dashboard_4_operational_observability(client: MetabaseStreamingClient) -> int:
    """
    Dashboard 4: Operational Observability

    Tracks error patterns, retry behavior, and resource utilization for incident response.
    """
    print("\n📊 Creating Dashboard #4: Operational Observability...")

    dashboard = client.create_dashboard(
        name="Operational Observability (Sprint 3)",
        description="Error tracking, retry patterns, and resource utilization for production incident response."
    )
    dashboard_id = dashboard["id"]

    # Card 1: Error Events (Last 24 Hours)
    card1 = client.create_native_question(
        name="Error Events (24h)",
        sql="""
SELECT
    event_type,
    SUM(event_count) AS error_count
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '24 hours'
  AND (event_type LIKE '%.failed' OR event_type LIKE '%.error')
GROUP BY event_type
ORDER BY error_count DESC;
""",
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["event_type"],
            "graph.metrics": ["error_count"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card1["id"], row=0, col=0, size_x=8, size_y=4)

    # Card 2: Recent Error Rate Trend
    card2 = client.create_native_question(
        name="Error Rate Trend",
        sql="""
SELECT
    bucket,
    SUM(CASE WHEN event_type LIKE '%.failed' OR event_type LIKE '%.error' THEN event_count ELSE 0 END)::FLOAT /
    NULLIF(SUM(event_count), 0) * 100 AS error_rate_pct
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '24 hours'
GROUP BY bucket
ORDER BY bucket DESC;
""",
        visualization_type="line",
        visualization_settings={
            "graph.dimensions": ["bucket"],
            "graph.metrics": ["error_rate_pct"],
            "card.title": "Error Rate % (24h)"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card2["id"], row=0, col=8, size_x=8, size_y=4)

    # Card 3: Actor Role Activity
    card3 = client.create_native_question(
        name="Activity by Role",
        sql="""
SELECT
    actor_role,
    SUM(event_count) AS total_events
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '24 hours'
  AND actor_role IS NOT NULL
GROUP BY actor_role
ORDER BY total_events DESC;
""",
        visualization_type="pie",
        visualization_settings={
            "pie.dimension": "actor_role",
            "pie.metric": "total_events"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card3["id"], row=4, col=0, size_x=6, size_y=4)

    # Card 4: Session Count Trend
    card4 = client.create_native_question(
        name="Active Sessions",
        sql="""
SELECT
    bucket,
    SUM(unique_sessions) AS session_count
FROM telemetry_events_hourly
WHERE bucket >= NOW() - INTERVAL '24 hours'
GROUP BY bucket
ORDER BY bucket DESC;
""",
        visualization_type="line",
        visualization_settings={
            "graph.dimensions": ["bucket"],
            "graph.metrics": ["session_count"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card4["id"], row=4, col=6, size_x=6, size_y=4)

    # Card 5: High-Latency Operations Alert
    card5 = client.create_native_question(
        name="High-Latency Operations (>5s)",
        sql="""
SELECT
    operation_name,
    service_name,
    p95_duration_ms / 1000.0 AS p95_duration_seconds,
    span_count
FROM execution_traces_hourly
WHERE bucket >= NOW() - INTERVAL '1 hour'
  AND p95_duration_ms > 5000
ORDER BY p95_duration_ms DESC
LIMIT 10;
""",
        visualization_type="table",
        visualization_settings={
            "card.title": "⚠️ Operations Exceeding 5s P95"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card5["id"], row=8, col=0, size_x=12, size_y=4)

    print(f"✅ Dashboard #4 created with 5 cards")
    return dashboard_id


def main():
    """Create all Sprint 3 streaming dashboards."""
    # Get credentials
    url = os.getenv("METABASE_URL", "http://localhost:3000")
    username = os.getenv("METABASE_USERNAME", "admin@amprealize.local")
    password = os.getenv("METABASE_PASSWORD")

    if not password:
        print("❌ Error: METABASE_PASSWORD environment variable is required")
        print("   Example: export METABASE_PASSWORD=changeme123")
        sys.exit(1)

    print("=" * 70)
    print("Sprint 3 Streaming Dashboards Creator")
    print("=" * 70)
    print(f"Metabase URL: {url}")
    print(f"Username: {username}")
    print()

    # Initialize client
    try:
        client = MetabaseStreamingClient(url, username, password)
    except requests.HTTPError as e:
        print(f"❌ Authentication failed: {e}")
        print("   Check your METABASE_PASSWORD and ensure Metabase is running")
        sys.exit(1)

    # Create all dashboards
    dashboard_ids = []

    try:
        dashboard_ids.append(create_dashboard_1_streaming_health(client))
        time.sleep(1)  # Rate limiting

        dashboard_ids.append(create_dashboard_2_prd_metrics_realtime(client))
        time.sleep(1)

        dashboard_ids.append(create_dashboard_3_event_flow_analysis(client))
        time.sleep(1)

        dashboard_ids.append(create_dashboard_4_operational_observability(client))

    except requests.HTTPError as e:
        print(f"\n❌ Error creating dashboards: {e}")
        print(f"   Response: {e.response.text if e.response else 'No response'}")
        sys.exit(1)

    # Success summary
    print("\n" + "=" * 70)
    print("✅ All Sprint 3 Streaming Dashboards Created Successfully!")
    print("=" * 70)
    print(f"\n📊 Dashboards created: {len(dashboard_ids)}")
    print(f"\n🔗 Access dashboards at: {url}/collection/root")
    print("\nDashboard URLs:")
    for i, dashboard_id in enumerate(dashboard_ids, 1):
        print(f"  {i}. {url}/dashboard/{dashboard_id}")

    print("\n📝 Next Steps:")
    print("  1. Verify dashboard queries return data (may need sample telemetry)")
    print("  2. Start streaming pipeline: ./scripts/start_streaming_pipeline.sh start")
    print("  3. Deploy Flink job: podman exec amprealize-flink-jobmanager python /opt/flink/jobs/telemetry_kpi_job.py --mode prod")
    print("  4. Generate test events: amprealize telemetry emit ...")
    print("  5. Refresh dashboards after 10 minutes (continuous aggregate refresh interval)")
    print()


if __name__ == "__main__":
    main()
