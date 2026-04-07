#!/usr/bin/env python3
"""Generate sample telemetry events and populate prd_metrics schema.

This script creates realistic sample data for dashboard development and testing.
It generates telemetry events, projects them using TelemetryKPIProjector, and
inserts the resulting facts into the prd_metrics schema in DuckDB.

Usage:
    python scripts/seed_telemetry_data.py [--runs N]

Options:
    --runs N    Number of workflow runs to generate (default: 50)
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import duckdb

from amprealize.analytics import TelemetryKPIProjector
from amprealize.telemetry import TelemetryEvent


def generate_sample_events(num_runs: int = 50) -> List[TelemetryEvent]:
    """Generate realistic sample telemetry events for testing."""

    events: List[TelemetryEvent] = []

    # Sample data
    templates = [
        ("wf-cicd", "CI/CD Pipeline"),
        ("wf-telemetry", "Telemetry Pipeline"),
        ("wf-review", "Code Review"),
        ("wf-onboard", "Developer Onboarding"),
        ("wf-incident", "Incident Response"),
    ]

    behaviors = [
        "behavior_instrument_metrics_pipeline",
        "behavior_orchestrate_cicd",
        "behavior_guard_pii",
        "behavior_version_control",
        "behavior_test_automation",
        "behavior_security_scan",
        "behavior_deploy_staging",
    ]

    checklists = [
        ("checklist-security", ["sec-001", "sec-002", "sec-003", "sec-004"]),
        ("checklist-quality", ["qa-001", "qa-002", "qa-003"]),
        ("checklist-deployment", ["dep-001", "dep-002", "dep-003", "dep-004", "dep-005"]),
    ]

    surfaces = ["CLI", "API", "WEB"]
    roles = ["STRATEGIST", "TEACHER", "STUDENT"]
    statuses = ["COMPLETED", "FAILED", "CANCELLED"]

    base_time = datetime.now() - timedelta(days=30)

    for i in range(num_runs):
        run_id = f"run-{i:04d}"
        template_id, template_name = random.choice(templates)
        surface = random.choice(surfaces)
        role = random.choice(roles)
        run_time = base_time + timedelta(
            days=random.uniform(0, 30),
            hours=random.uniform(0, 24),
        )

        # plan_created event
        selected_behaviors = random.sample(behaviors, k=random.randint(1, 4))
        baseline_tokens = random.randint(500, 3000)

        events.append(TelemetryEvent(
            event_id=f"evt-{i:04d}-plan",
            timestamp=run_time.isoformat(),
            event_type="plan_created",
            actor={"surface": surface, "role": role},
            run_id=run_id,
            action_id=None,
            session_id=f"session-{i // 5}",  # Multiple runs per session
            payload={
                "template_id": template_id,
                "template_name": template_name,
                "behavior_ids": selected_behaviors,
                "baseline_tokens": baseline_tokens,
            },
        ))

        # execution_update event
        output_tokens = int(baseline_tokens * random.uniform(0.3, 0.8))
        savings_pct = (baseline_tokens - output_tokens) / baseline_tokens
        status = random.choices(statuses, weights=[0.80, 0.15, 0.05])[0]  # 80% success

        events.append(TelemetryEvent(
            event_id=f"evt-{i:04d}-exec",
            timestamp=(run_time + timedelta(seconds=random.randint(10, 300))).isoformat(),
            event_type="execution_update",
            actor={"surface": surface, "role": role},
            run_id=run_id,
            action_id=None,
            session_id=f"session-{i // 5}",
            payload={
                "template_id": template_id,
                "behaviors_cited": selected_behaviors,
                "output_tokens": output_tokens,
                "token_savings_pct": savings_pct,
                "status": status,
            },
        ))

        # compliance_step_recorded events (for some runs)
        if random.random() < 0.6:  # 60% of runs have compliance checks
            checklist_id, steps = random.choice(checklists)
            completed_steps = random.randint(len(steps) // 2, len(steps))

            for j, step_id in enumerate(steps[:completed_steps]):
                step_status = "COMPLETED" if j < completed_steps else "PENDING"
                coverage = completed_steps / len(steps)

                events.append(TelemetryEvent(
                    event_id=f"evt-{i:04d}-comp-{j}",
                    timestamp=(run_time + timedelta(seconds=random.randint(1, 100))).isoformat(),
                    event_type="compliance_step_recorded",
                    actor={"surface": surface, "role": role},
                    run_id=run_id,
                    action_id=None,
                    session_id=f"session-{i // 5}",
                    payload={
                        "checklist_id": checklist_id,
                        "step_id": step_id,
                        "status": step_status,
                        "coverage_score": coverage,
                    },
                ))

        # behavior_retrieved events
        if random.random() < 0.8:  # 80% of runs have behavior retrievals
            retrieved_behaviors = random.sample(behaviors, k=random.randint(2, 5))
            events.append(TelemetryEvent(
                event_id=f"evt-{i:04d}-retr",
                timestamp=(run_time - timedelta(seconds=random.randint(1, 30))).isoformat(),
                event_type="behavior_retrieved",
                actor={"surface": surface, "role": role},
                run_id=run_id,
                action_id=None,
                session_id=f"session-{i // 5}",
                payload={
                    "behavior_ids": retrieved_behaviors,
                },
            ))

    return events


def insert_facts_into_duckdb(
    projection,
    db_path: str = "data/telemetry.duckdb",
    schema: str = "prd_metrics",
) -> None:
    """Insert projected facts into DuckDB prd_metrics schema."""

    conn = duckdb.connect(db_path)

    print(f"\n📊 Inserting facts into {schema} schema...")

    # Insert fact_behavior_usage
    if projection.fact_behavior_usage:
        for fact in projection.fact_behavior_usage:
            conn.execute(f"""
                INSERT INTO {schema}.fact_behavior_usage (
                    run_id, template_id, template_name, behavior_ids,
                    behavior_count, has_behaviors, baseline_tokens,
                    actor_surface, actor_role, first_plan_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                fact["run_id"],
                fact["template_id"],
                fact["template_name"],
                fact["behavior_ids"],
                fact["behavior_count"],
                fact["has_behaviors"],
                fact["baseline_tokens"],
                fact["actor_surface"],
                fact["actor_role"],
                fact["first_plan_timestamp"],
            ])
        print(f"  ✅ Inserted {len(projection.fact_behavior_usage)} behavior usage facts")

    # Insert fact_token_savings
    if projection.fact_token_savings:
        for fact in projection.fact_token_savings:
            conn.execute(f"""
                INSERT INTO {schema}.fact_token_savings (
                    run_id, template_id, output_tokens, baseline_tokens, token_savings_pct
                ) VALUES (?, ?, ?, ?, ?)
            """, [
                fact["run_id"],
                fact["template_id"],
                fact["output_tokens"],
                fact["baseline_tokens"],
                fact["token_savings_pct"],
            ])
        print(f"  ✅ Inserted {len(projection.fact_token_savings)} token savings facts")

    # Insert fact_execution_status
    if projection.fact_execution_status:
        for fact in projection.fact_execution_status:
            conn.execute(f"""
                INSERT INTO {schema}.fact_execution_status (
                    run_id, template_id, status, actor_surface, actor_role
                ) VALUES (?, ?, ?, ?, ?)
            """, [
                fact["run_id"],
                fact["template_id"],
                fact["status"],
                fact["actor_surface"],
                fact["actor_role"],
            ])
        print(f"  ✅ Inserted {len(projection.fact_execution_status)} execution status facts")

    # Insert fact_compliance_steps
    if projection.fact_compliance_steps:
        for fact in projection.fact_compliance_steps:
            # Convert sets to lists for DuckDB compatibility
            behavior_ids = fact.get("behavior_ids")
            if isinstance(behavior_ids, set):
                behavior_ids = sorted(list(behavior_ids))

            conn.execute(f"""
                INSERT INTO {schema}.fact_compliance_steps (
                    checklist_id, step_id, status, coverage_score,
                    run_id, session_id, behavior_ids, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                fact.get("checklist_id"),
                fact.get("step_id"),
                fact.get("status"),
                fact.get("coverage_score"),
                fact.get("run_id"),
                fact.get("session_id"),
                behavior_ids,
                fact.get("timestamp"),
            ])
        print(f"  ✅ Inserted {len(projection.fact_compliance_steps)} compliance step facts")

    conn.close()


def main():
    """Generate sample telemetry and populate prd_metrics schema."""

    parser = argparse.ArgumentParser(description="Seed telemetry data for dashboard testing")
    parser.add_argument("--runs", type=int, default=50, help="Number of workflow runs to generate")
    args = parser.parse_args()

    print(f"🌱 Seeding telemetry data with {args.runs} workflow runs...")

    # Generate events
    print(f"\n📝 Generating sample telemetry events...")
    events = generate_sample_events(num_runs=args.runs)
    print(f"  ✅ Generated {len(events)} telemetry events")

    # Project events to facts
    print(f"\n🔄 Projecting events to PRD KPI facts...")
    projector = TelemetryKPIProjector()
    projection = projector.project(events)

    print(f"  ✅ Projected to:")
    print(f"     - {len(projection.fact_behavior_usage)} behavior usage facts")
    print(f"     - {len(projection.fact_token_savings)} token savings facts")
    print(f"     - {len(projection.fact_execution_status)} execution status facts")
    print(f"     - {len(projection.fact_compliance_steps)} compliance step facts")

    # Print KPI summary
    summary = projection.summary
    print(f"\n📈 KPI Summary:")
    print(f"  Behavior Reuse Rate: {summary.get('behavior_reuse_pct', 0):.1f}%")
    print(f"  Avg Token Savings: {summary.get('average_token_savings_pct', 0):.1f}%")
    print(f"  Task Completion Rate: {summary.get('task_completion_rate_pct', 0):.1f}%")
    print(f"  Avg Compliance Coverage: {summary.get('average_compliance_coverage_pct', 0):.1f}%")

    # Insert into DuckDB
    db_path = str(Path(__file__).parent.parent / "data" / "telemetry.duckdb")
    insert_facts_into_duckdb(projection, db_path=db_path)

    print(f"\n✅ Data seeding complete!")
    print(f"💡 Next steps:")
    print(f"   1. Run: python scripts/export_duckdb_to_sqlite.py")
    print(f"   2. Run: python scripts/create_metabase_dashboards.py")
    print(f"   3. View dashboards at: http://localhost:3000")


if __name__ == "__main__":
    main()
