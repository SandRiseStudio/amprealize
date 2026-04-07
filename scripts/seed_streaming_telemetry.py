#!/usr/bin/env python3
"""
Generate high-volume telemetry events for streaming pipeline validation.

This script streams events to Kafka topics to validate the end-to-end pipeline:
    Event Generator → Kafka → Flink → TimescaleDB → Metabase

Features:
- Configurable event rate (events/second)
- Multiple event types (behavior.retrieved, workflow.executed, run.created, etc.)
- Realistic payload patterns
- Progress tracking and metrics

Usage:
    # Stream 10k events/sec for 1 hour (36 million events)
    python scripts/seed_streaming_telemetry.py \\
        --kafka-servers localhost:9092 \\
        --rate 10000 \\
        --duration 3600

    # Quick validation test (100 events/sec for 1 minute)
    python scripts/seed_streaming_telemetry.py \\
        --kafka-servers localhost:9092 \\
        --rate 100 \\
        --duration 60

    # Burst test (1000 events immediately)
    python scripts/seed_streaming_telemetry.py \\
        --kafka-servers localhost:9092 \\
        --burst 1000
"""

import argparse
import json
import logging
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class TelemetryEventGenerator:
    """Generates realistic telemetry events for the Amprealize platform."""

    def __init__(self) -> None:
        self.templates = [
            ("wf-cicd", "CI/CD Pipeline"),
            ("wf-telemetry", "Telemetry Pipeline"),
            ("wf-review", "Code Review"),
            ("wf-onboard", "Developer Onboarding"),
            ("wf-incident", "Incident Response"),
            ("wf-migration", "Database Migration"),
            ("wf-security", "Security Audit"),
        ]

        self.behaviors = [
            "behavior_instrument_metrics_pipeline",
            "behavior_orchestrate_cicd",
            "behavior_guard_pii",
            "behavior_version_control",
            "behavior_test_automation",
            "behavior_security_scan",
            "behavior_deploy_staging",
            "behavior_unify_execution_records",
            "behavior_align_storage_layers",
            "behavior_externalize_configuration",
        ]

        self.checklists = [
            ("checklist-security", ["sec-001", "sec-002", "sec-003", "sec-004"]),
            ("checklist-quality", ["qa-001", "qa-002", "qa-003"]),
            ("checklist-deployment", ["dep-001", "dep-002", "dep-003", "dep-004", "dep-005"]),
        ]

        self.surfaces = ["cli", "api", "web", "mcp", "vscode"]
        self.roles = ["strategist", "teacher", "student"]
        self.statuses = ["completed", "failed", "cancelled", "in_progress"]

    def generate_event(self, event_type: str | None = None) -> Dict[str, Any]:
        """Generate a single telemetry event."""

        if event_type is None:
            event_type = random.choice([
                "behavior.retrieved",
                "workflow.executed",
                "run.created",
                "run.completed",
                "compliance.step_validated",
                "action.recorded",
            ])

        event_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        run_id = f"run-{random.randint(1000, 9999)}"
        session_id = f"session-{random.randint(100, 999)}"

        actor = {
            "id": f"user-{random.randint(1, 50)}",
            "role": random.choice(self.roles),
            "surface": random.choice(self.surfaces),
        }

        payload: Dict[str, Any] = {}

        if event_type == "behavior.retrieved":
            payload = {
                "behavior_ids": random.sample(self.behaviors, k=random.randint(1, 4)),
                "query": "implement authentication flow",
                "retrieval_strategy": "embedding",
                "result_count": random.randint(1, 10),
            }

        elif event_type == "workflow.executed":
            template_id, template_name = random.choice(self.templates)
            baseline_tokens = random.randint(500, 3000)
            output_tokens = int(baseline_tokens * random.uniform(0.3, 0.8))

            payload = {
                "template_id": template_id,
                "template_name": template_name,
                "behavior_ids": random.sample(self.behaviors, k=random.randint(1, 4)),
                "baseline_tokens": baseline_tokens,
                "output_tokens": output_tokens,
                "token_savings_pct": ((baseline_tokens - output_tokens) / baseline_tokens) * 100,
            }

        elif event_type == "run.created":
            template_id, template_name = random.choice(self.templates)
            payload = {
                "template_id": template_id,
                "template_name": template_name,
                "behavior_count": random.randint(1, 5),
            }

        elif event_type == "run.completed":
            status = random.choices(self.statuses, weights=[0.75, 0.15, 0.05, 0.05])[0]
            payload = {
                "status": status,
                "duration_seconds": random.randint(10, 600),
                "steps_completed": random.randint(1, 10),
            }

        elif event_type == "compliance.step_validated":
            checklist_id, steps = random.choice(self.checklists)
            step_id = random.choice(steps)
            payload = {
                "checklist_id": checklist_id,
                "step_id": step_id,
                "status": random.choice(["passed", "failed", "skipped"]),
                "coverage_score": random.uniform(0.7, 1.0),
            }

        elif event_type == "action.recorded":
            payload = {
                "action_id": str(uuid.uuid4()),
                "action_type": random.choice(["file_edit", "command_run", "api_call"]),
                "success": random.random() > 0.1,  # 90% success rate
            }

        return {
            "event_id": event_id,
            "timestamp": timestamp,
            "event_type": event_type,
            "actor": actor,
            "run_id": run_id,
            "action_id": None,
            "session_id": session_id,
            "payload": payload,
        }


class StreamingProducer:
    """Kafka producer for streaming telemetry events."""

    def __init__(self, kafka_servers: str, topic: str = "telemetry.events") -> None:
        try:
            from kafka import KafkaProducer
        except ImportError:
            logger.error("kafka-python not installed. Run: pip install kafka-python")
            sys.exit(1)

        self.topic = topic
        self.producer = KafkaProducer(
            bootstrap_servers=kafka_servers.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            compression_type="gzip",
            linger_ms=100,  # Batch for 100ms
            batch_size=16384,  # 16KB batches
            acks="all",  # Wait for all replicas
        )

        self.generator = TelemetryEventGenerator()
        self.sent_count = 0
        self.start_time = time.time()

        logger.info(f"Kafka producer initialized: {kafka_servers} → {topic}")

    def send_burst(self, count: int) -> None:
        """Send a burst of events as fast as possible."""
        logger.info(f"Sending burst of {count} events...")

        for i in range(count):
            event = self.generator.generate_event()
            self.producer.send(self.topic, value=event)
            self.sent_count += 1

            if (i + 1) % 1000 == 0:
                logger.info(f"  Sent {i + 1}/{count} events")

        self.producer.flush()
        elapsed = time.time() - self.start_time
        rate = self.sent_count / elapsed

        logger.info(f"✅ Burst complete: {self.sent_count} events in {elapsed:.2f}s ({rate:.0f} events/sec)")

    def stream_at_rate(self, events_per_second: int, duration_seconds: int) -> None:
        """Stream events at a target rate for specified duration."""
        logger.info(f"Streaming {events_per_second} events/sec for {duration_seconds} seconds...")

        target_count = events_per_second * duration_seconds
        interval = 1.0 / events_per_second if events_per_second > 0 else 0

        start = time.time()
        next_event_time = start

        for i in range(target_count):
            event = self.generator.generate_event()
            self.producer.send(self.topic, value=event)
            self.sent_count += 1

            # Rate limiting
            next_event_time += interval
            now = time.time()

            if now < next_event_time:
                time.sleep(next_event_time - now)

            # Progress logging every 10k events
            if (i + 1) % 10000 == 0:
                elapsed = time.time() - start
                current_rate = self.sent_count / elapsed
                progress = ((i + 1) / target_count) * 100
                eta = (target_count - i - 1) / current_rate if current_rate > 0 else 0

                logger.info(
                    f"  Progress: {progress:.1f}% | "
                    f"Sent: {self.sent_count:,} | "
                    f"Rate: {current_rate:.0f}/sec | "
                    f"ETA: {eta:.0f}s"
                )

        self.producer.flush()
        elapsed = time.time() - start
        actual_rate = self.sent_count / elapsed

        logger.info(
            f"✅ Streaming complete: {self.sent_count:,} events in {elapsed:.2f}s "
            f"(target: {events_per_second}/sec, actual: {actual_rate:.0f}/sec)"
        )

    def close(self) -> None:
        """Close producer and print final metrics."""
        self.producer.close()

        elapsed = time.time() - self.start_time
        rate = self.sent_count / elapsed if elapsed > 0 else 0

        logger.info(f"📊 Final metrics:")
        logger.info(f"   Total events: {self.sent_count:,}")
        logger.info(f"   Duration: {elapsed:.2f}s")
        logger.info(f"   Average rate: {rate:.0f} events/sec")


def main():
    """Stream telemetry events to Kafka for pipeline validation."""

    parser = argparse.ArgumentParser(
        description="Generate streaming telemetry for Amprealize pipeline validation"
    )
    parser.add_argument(
        "--kafka-servers",
        default="localhost:9092",
        help="Kafka bootstrap servers (default: localhost:9092)",
    )
    parser.add_argument(
        "--topic",
        default="telemetry.events",
        help="Kafka topic (default: telemetry.events)",
    )
    parser.add_argument(
        "--rate",
        type=int,
        help="Events per second (for streaming mode)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--burst",
        type=int,
        help="Send burst of N events immediately",
    )

    args = parser.parse_args()

    producer = StreamingProducer(
        kafka_servers=args.kafka_servers,
        topic=args.topic,
    )

    try:
        if args.burst:
            producer.send_burst(args.burst)
        elif args.rate:
            producer.stream_at_rate(args.rate, args.duration)
        else:
            logger.error("Must specify --rate or --burst")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
    finally:
        producer.close()


if __name__ == "__main__":
    main()
