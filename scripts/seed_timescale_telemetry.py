#!/usr/bin/env python3
"""
Seed telemetry data directly into TimescaleDB for pipeline validation.

This script generates realistic telemetry events and inserts them directly
into the telemetry_events hypertable, bypassing Kafka for infrastructure testing.

Usage:
    python scripts/seed_timescale_telemetry.py --runs 1000
    python scripts/seed_timescale_telemetry.py --runs 1000 --rate 100
"""

import argparse
import json
import logging
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class TimescaleTelemetrySeeder:
    """Seeds telemetry data directly into TimescaleDB."""

    def __init__(self, postgres_dsn: str) -> None:
        self.conn = psycopg2.connect(postgres_dsn)
        self.conn.autocommit = False

        self.templates = [
            ("wf-cicd", "CI/CD Pipeline"),
            ("wf-telemetry", "Telemetry Pipeline"),
            ("wf-review", "Code Review"),
            ("wf-onboard", "Developer Onboarding"),
            ("wf-incident", "Incident Response"),
        ]

        self.behaviors = [
            "behavior_instrument_metrics_pipeline",
            "behavior_orchestrate_cicd",
            "behavior_guard_pii",
            "behavior_version_control",
            "behavior_test_automation",
        ]

        self.surfaces = ["cli", "api", "web", "mcp", "vscode"]
        self.roles = ["strategist", "teacher", "student"]
        self.statuses = ["completed", "failed", "cancelled"]

    def generate_workflow_events(self, run_id: str, run_time: datetime) -> List[Dict[str, Any]]:
        """Generate events for a single workflow run."""
        events = []
        template_id, template_name = random.choice(self.templates)
        surface = random.choice(self.surfaces)
        role = random.choice(self.roles)
        selected_behaviors = random.sample(self.behaviors, k=random.randint(1, 4))
        baseline_tokens = random.randint(500, 3000)
        output_tokens = int(baseline_tokens * random.uniform(0.3, 0.8))

        # Event 1: plan_created
        events.append({
            "event_id": str(uuid.uuid4()),
            "event_timestamp": run_time,
            "event_type": "plan_created",
            "actor_id": f"user-{random.randint(1, 50)}",
            "actor_role": role,
            "actor_surface": surface,
            "run_id": run_id,
            "session_id": f"session-{random.randint(1, 100)}",
            "payload": {
                "template_id": template_id,
                "template_name": template_name,
                "behavior_ids": selected_behaviors,
                "baseline_tokens": baseline_tokens,
            },
        })

        # Event 2: execution_update
        status = random.choices(self.statuses, weights=[0.80, 0.15, 0.05])[0]
        events.append({
            "event_id": str(uuid.uuid4()),
            "event_timestamp": run_time + timedelta(seconds=random.randint(10, 300)),
            "event_type": "execution_update",
            "actor_id": f"user-{random.randint(1, 50)}",
            "actor_role": role,
            "actor_surface": surface,
            "run_id": run_id,
            "session_id": f"session-{random.randint(1, 100)}",
            "payload": {
                "status": status,
                "output_tokens": output_tokens,
                "baseline_tokens": baseline_tokens,
                "token_savings_pct": ((baseline_tokens - output_tokens) / baseline_tokens) * 100,
            },
        })

        # Event 3: compliance steps (2-3 per run)
        for i in range(random.randint(2, 3)):
            events.append({
                "event_id": str(uuid.uuid4()),
                "event_timestamp": run_time + timedelta(seconds=random.randint(5, 250)),
                "event_type": "compliance_step",
                "actor_id": f"user-{random.randint(1, 50)}",
                "actor_role": role,
                "actor_surface": surface,
                "run_id": run_id,
                "session_id": f"session-{random.randint(1, 100)}",
                "payload": {
                    "checklist_id": f"checklist-{random.randint(1, 5)}",
                    "step_id": f"step-{random.randint(1, 10)}",
                    "status": random.choice(["passed", "failed"]),
                },
            })

        return events

    def insert_events(self, events: List[Dict[str, Any]]) -> None:
        """Insert events into telemetry_events hypertable."""
        cursor = self.conn.cursor()

        for event in events:
            cursor.execute(
                """
                INSERT INTO telemetry_events (
                    event_id, event_timestamp, event_type,
                    actor_id, actor_role, actor_surface,
                    run_id, action_id, session_id, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id, event_timestamp) DO NOTHING
                """,
                (
                    event["event_id"],
                    event["event_timestamp"],
                    event["event_type"],
                    event["actor_id"],
                    event["actor_role"],
                    event["actor_surface"],
                    event["run_id"],
                    event.get("action_id"),
                    event["session_id"],
                    psycopg2.extras.Json(event["payload"]),
                ),
            )

        self.conn.commit()
        cursor.close()

    def seed_runs(self, num_runs: int, rate: int | None = None) -> None:
        """Seed multiple workflow runs."""
        logger.info(f"Seeding {num_runs} workflow runs...")

        base_time = datetime.now(timezone.utc) - timedelta(days=7)
        total_events = 0
        start = time.time()

        for i in range(num_runs):
            run_id = f"run-seed-{i:06d}"
            run_time = base_time + timedelta(
                days=random.uniform(0, 7),
                hours=random.uniform(0, 24),
            )

            events = self.generate_workflow_events(run_id, run_time)
            self.insert_events(events)
            total_events += len(events)

            # Rate limiting
            if rate and i > 0:
                elapsed = time.time() - start
                expected_time = i / rate
                if elapsed < expected_time:
                    time.sleep(expected_time - elapsed)

            # Progress logging
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start
                current_rate = (i + 1) / elapsed
                logger.info(f"  Progress: {i + 1}/{num_runs} runs ({current_rate:.0f} runs/sec)")

        elapsed = time.time() - start
        actual_rate = num_runs / elapsed

        logger.info(f"✅ Seeding complete:")
        logger.info(f"   Runs: {num_runs}")
        logger.info(f"   Events: {total_events}")
        logger.info(f"   Duration: {elapsed:.2f}s")
        logger.info(f"   Rate: {actual_rate:.0f} runs/sec")

    def refresh_continuous_aggregates(self) -> None:
        """Manually refresh continuous aggregates."""
        logger.info("Refreshing continuous aggregates...")
        cursor = self.conn.cursor()

        try:
            cursor.execute("CALL refresh_continuous_aggregate('telemetry_events_hourly', NULL, NULL)")
            cursor.execute("CALL refresh_continuous_aggregate('telemetry_events_daily', NULL, NULL)")
            cursor.execute("CALL refresh_continuous_aggregate('execution_traces_hourly', NULL, NULL)")
            self.conn.commit()
            logger.info("✅ Continuous aggregates refreshed")
        except Exception as e:
            logger.warning(f"Could not refresh continuous aggregates: {e}")
            self.conn.rollback()
        finally:
            cursor.close()

    def get_event_stats(self) -> Dict[str, Any]:
        """Get statistics on seeded events."""
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cursor.execute(
            """
            SELECT
                COUNT(*) as total_events,
                COUNT(DISTINCT run_id) as unique_runs,
                COUNT(DISTINCT event_type) as event_types,
                MIN(event_timestamp) as earliest_event,
                MAX(event_timestamp) as latest_event
            FROM telemetry_events
            WHERE run_id LIKE 'run-seed-%'
            """
        )
        row = cursor.fetchone()
        cursor.close()

        return dict(row) if row else {}

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()


def main():
    """Seed TimescaleDB with telemetry data."""
    parser = argparse.ArgumentParser(description="Seed TimescaleDB telemetry data")
    parser.add_argument("--runs", type=int, default=100, help="Number of workflow runs")
    parser.add_argument("--rate", type=int, help="Runs per second (for rate limiting)")
    parser.add_argument(
        "--dsn",
        default="postgresql://amprealize:password@localhost:5432/amprealize_telemetry",
        help="PostgreSQL DSN",
    )
    args = parser.parse_args()

    seeder = TimescaleTelemetrySeeder(args.dsn)

    try:
        # Seed data
        seeder.seed_runs(args.runs, rate=args.rate)

        # Refresh aggregates
        seeder.refresh_continuous_aggregates()

        # Print stats
        stats = seeder.get_event_stats()
        logger.info(f"\n📊 Event Statistics:")
        logger.info(f"   Total events: {stats.get('total_events', 0):,}")
        logger.info(f"   Unique runs: {stats.get('unique_runs', 0):,}")
        logger.info(f"   Event types: {stats.get('event_types', 0)}")
        logger.info(f"   Time range: {stats.get('earliest_event')} → {stats.get('latest_event')}")

    finally:
        seeder.close()


if __name__ == "__main__":
    main()
