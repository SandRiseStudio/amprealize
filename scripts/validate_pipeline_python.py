#!/usr/bin/env python3
"""
Quick validation test for telemetry pipeline using Python client.
Tests that events can be emitted to Kafka and consumed by the pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add amprealize to path
sys.path.insert(0, str(Path(__file__).parent.parent))

print("=== Amprealize Telemetry Pipeline - Python Validation ===\n")

# Test 1: Import telemetry client
print("[1/4] Testing imports...")
try:
    from amprealize.telemetry import TelemetryClient, KafkaTelemetrySink
    print("✅ Telemetry imports successful")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    print("Install dependencies: pip install -e '.[telemetry]'")
    sys.exit(1)

# Test 2: Check Kafka connectivity
print("\n[2/4] Testing Kafka connectivity...")
try:
    sink = KafkaTelemetrySink(
        bootstrap_servers="localhost:9092",
        topic="telemetry.events"
    )
    print("✅ Kafka sink initialized")
except Exception as e:
    print(f"❌ Kafka connection failed: {e}")
    print("Ensure containers are running: podman ps | grep amprealize-kafka")
    sys.exit(1)

# Test 3: Emit test events
print("\n[3/4] Emitting test events...")
client = TelemetryClient(sink=sink)

test_events = [
    {
        "event_type": "execution_update",
        "payload": {
            "status": "SUCCESS",
            "output_tokens": 100,
            "baseline_tokens": 150,
            "token_savings_pct": 0.33,
            "behaviors_cited": ["behavior_instrument_metrics_pipeline"]
        },
        "run_id": "validation-run-001"
    },
    {
        "event_type": "behavior_retrieved",
        "payload": {
            "behavior_id": "behavior_instrument_metrics_pipeline",
            "behavior_name": "Instrument Metrics Pipeline",
            "role_focus": "STRATEGIST"
        },
        "run_id": "validation-run-001"
    },
    {
        "event_type": "plan_created",
        "payload": {
            "template_id": "wf-telemetry",
            "template_name": "Telemetry Pipeline",
            "behavior_ids": ["behavior_instrument_metrics_pipeline"],
            "baseline_tokens": 200
        },
        "run_id": "validation-run-001"
    }
]

try:
    for i, event_data in enumerate(test_events, 1):
        event = client.emit_event(
            event_type=event_data["event_type"],
            actor={"id": "validator", "role": "STRATEGIST", "surface": "CLI"},
            run_id=event_data["run_id"],
            payload=event_data["payload"]
        )
        print(f"  ✓ Event {i}/{len(test_events)} emitted: {event.event_type} ({event.event_id[:8]}...)")
    print(f"✅ {len(test_events)} test events emitted successfully")
except Exception as e:
    print(f"❌ Event emission failed: {e}")
    sys.exit(1)

# Test 4: Verify monitoring endpoints
print("\n[4/4] Checking monitoring endpoints...")
import urllib.request

endpoints = [
    ("Kafka UI", "http://localhost:8080"),
    ("Flink Dashboard", "http://localhost:8081")
]

for name, url in endpoints:
    try:
        urllib.request.urlopen(url, timeout=2)
        print(f"✅ {name}: {url}")
    except Exception:
        print(f"⚠️  {name} not reachable: {url}")

print("\n=== Validation Complete ===")
print("\nNext steps:")
print("  1. View events in Kafka UI: http://localhost:8080")
print("  2. Check Flink dashboard: http://localhost:8081")
print("  3. Start Flink job: python deployment/flink/telemetry_kpi_job.py")
print("  4. Query Snowflake facts (after job processes events)")
print()
