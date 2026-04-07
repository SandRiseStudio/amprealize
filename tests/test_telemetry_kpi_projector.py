from __future__ import annotations

import unittest
from typing import Dict, cast

from amprealize.analytics import TelemetryKPIProjector
from amprealize.telemetry import TelemetryEvent


class TelemetryKPIProjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.projector = TelemetryKPIProjector()

    def test_projector_computes_kpis_and_facts(self) -> None:
        events = [
            TelemetryEvent(
                event_id="evt-1",
                timestamp="2025-10-16T00:00:00Z",
                event_type="plan_created",
                actor={"id": "user-1", "role": "STRATEGIST", "surface": "vscode"},
                run_id=None,
                action_id=None,
                session_id="sess-1",
                payload={
                    "run_id": "run-1",
                    "template_id": "template-1",
                    "template_name": "Demo Workflow",
                    "behavior_ids": ["behavior-a", "behavior-b"],
                    "baseline_tokens": 1000,
                },
            ),
            TelemetryEvent(
                event_id="evt-2",
                timestamp="2025-10-16T00:01:00Z",
                event_type="execution_update",
                actor={"id": "system", "role": "SYSTEM", "surface": "api"},
                run_id=None,
                action_id=None,
                session_id="sess-1",
                payload={
                    "run_id": "run-1",
                    "template_id": "template-1",
                    "status": "COMPLETED",
                    "output_tokens": 600,
                    "baseline_tokens": 1000,
                    "token_savings_pct": 0.4,
                    "behaviors_cited": ["behavior-a", "behavior-b"],
                },
            ),
            TelemetryEvent(
                event_id="evt-3",
                timestamp="2025-10-16T00:02:00Z",
                event_type="plan_created",
                actor={"id": "user-2", "role": "STUDENT", "surface": "cli"},
                run_id=None,
                action_id=None,
                session_id="sess-2",
                payload={
                    "run_id": "run-2",
                    "template_id": "template-2",
                    "template_name": "Empty Workflow",
                    "behavior_ids": [],
                    "baseline_tokens": 0,
                },
            ),
            TelemetryEvent(
                event_id="evt-4",
                timestamp="2025-10-16T00:03:00Z",
                event_type="execution_update",
                actor={"id": "system", "role": "SYSTEM", "surface": "api"},
                run_id=None,
                action_id=None,
                session_id="sess-2",
                payload={
                    "run_id": "run-2",
                    "template_id": "template-2",
                    "status": "FAILED",
                    "output_tokens": 1200,
                    "baseline_tokens": 0,
                    "token_savings_pct": None,
                    "behaviors_cited": [],
                },
            ),
            TelemetryEvent(
                event_id="evt-5",
                timestamp="2025-10-16T00:04:00Z",
                event_type="compliance_step_recorded",
                actor={"id": "auditor", "role": "TEACHER", "surface": "cli"},
                run_id="run-1",
                action_id="step-1",
                session_id="sess-3",
                payload={
                    "checklist_id": "check-1",
                    "step_id": "step-1",
                    "status": "COMPLETED",
                    "coverage_score": 0.8,
                    "related_run_id": "run-1",
                },
            ),
        ]

        projection = self.projector.project(events)

        self.assertEqual(projection.summary["total_runs"], 2)
        self.assertEqual(projection.summary["runs_with_behaviors"], 1)
        reuse_pct = projection.summary["behavior_reuse_pct"]
        self.assertIsNotNone(reuse_pct)
        assert isinstance(reuse_pct, (int, float))
        self.assertAlmostEqual(float(reuse_pct), 50.0)
        savings_pct = projection.summary["average_token_savings_pct"]
        self.assertIsNotNone(savings_pct)
        assert isinstance(savings_pct, (int, float))
        self.assertAlmostEqual(float(savings_pct), 40.0)
        self.assertEqual(projection.summary["completed_runs"], 1)
        self.assertEqual(projection.summary["terminal_runs"], 2)
        completion_rate = projection.summary["task_completion_rate_pct"]
        self.assertIsNotNone(completion_rate)
        assert isinstance(completion_rate, (int, float))
        self.assertAlmostEqual(float(completion_rate), 50.0)
        compliance_pct = projection.summary["average_compliance_coverage_pct"]
        self.assertIsNotNone(compliance_pct)
        assert isinstance(compliance_pct, (int, float))
        self.assertAlmostEqual(float(compliance_pct), 80.0)

        usage_facts = {fact["run_id"]: fact for fact in projection.fact_behavior_usage}
        self.assertEqual(len(usage_facts), 2)
        self.assertEqual(usage_facts["run-1"]["behavior_count"], 2)
        self.assertTrue(usage_facts["run-1"]["has_behaviors"])
        self.assertFalse(usage_facts["run-2"]["has_behaviors"])

        token_facts = {fact["run_id"]: fact for fact in projection.fact_token_savings}
        self.assertEqual(token_facts["run-1"]["token_savings_pct"], 0.4)
        self.assertIsNone(token_facts["run-2"]["token_savings_pct"])

        status_facts = {fact["run_id"]: fact for fact in projection.fact_execution_status}
        self.assertEqual(status_facts["run-1"]["status"], "COMPLETED")
        self.assertEqual(status_facts["run-2"]["status"], "FAILED")

        compliance_facts = [fact for fact in projection.fact_compliance_steps if fact["status"] != "BEHAVIOR_RETRIEVAL"]
        self.assertEqual(len(compliance_facts), 1)
        self.assertEqual(compliance_facts[0]["coverage_score"], 0.8)

        resource_facts_run1 = [fact for fact in projection.fact_resource_usage if fact["run_id"] == "run-1"]
        self.assertGreaterEqual(len(resource_facts_run1), 2)
        for fact in resource_facts_run1:
            self.assertIsInstance(fact["timestamp"], str)
            self.assertTrue(fact["timestamp"])
            self.assertIn(fact["service_name"], {"BehaviorService", "ActionService", "RunService", "ComplianceService"})
            self.assertIsInstance(fact["token_count"], int)
            token_value = cast(int, fact["token_count"])
            self.assertGreater(token_value, 0)

        cost_facts = {fact["run_id"]: fact for fact in projection.fact_cost_allocation}
        self.assertIn("run-1", cost_facts)
        run1_cost_fact = cost_facts["run-1"]
        self.assertIsInstance(run1_cost_fact["total_cost_usd"], float)
        run1_cost = cast(float, run1_cost_fact["total_cost_usd"])
        self.assertGreater(run1_cost, 0.0)
        service_costs_obj = run1_cost_fact["service_costs"]
        self.assertIsInstance(service_costs_obj, dict)
        service_costs = cast(Dict[str, float], service_costs_obj)
        self.assertTrue("BehaviorService" in service_costs)
        total_cost_summary_obj = projection.summary["total_cost_usd"]
        self.assertIsInstance(total_cost_summary_obj, (int, float))
        assert isinstance(total_cost_summary_obj, (int, float))
        total_cost_summary = float(total_cost_summary_obj)
        self.assertGreaterEqual(total_cost_summary, run1_cost)

    def test_accepts_raw_mapping_events(self) -> None:
        raw_events = [
            {
                "event_id": "evt-raw-1",
                "timestamp": "2025-10-16T00:05:00Z",
                "event_type": "plan_created",
                "actor": {"id": "user-3", "role": "STRATEGIST", "surface": "web"},
                "payload": {
                    "run_id": "run-raw",
                    "template_id": "template-raw",
                    "behavior_ids": ["behavior-x"],
                    "baseline_tokens": "1500",
                },
            },
            {
                "event_id": "evt-raw-2",
                "timestamp": "2025-10-16T00:06:00Z",
                "event_type": "execution_update",
                "payload": {
                    "run_id": "run-raw",
                    "template_id": "template-raw",
                    "status": "COMPLETED",
                    "output_tokens": 900,
                    "baseline_tokens": 1500,
                    "token_savings_pct": 0.4,
                    "behaviors_cited": ["behavior-x"],
                },
            },
        ]

        projection = self.projector.project(raw_events)

        self.assertEqual(projection.summary["total_runs"], 1)
        reuse_pct = projection.summary["behavior_reuse_pct"]
        self.assertIsNotNone(reuse_pct)
        assert isinstance(reuse_pct, (int, float))
        self.assertAlmostEqual(float(reuse_pct), 100.0)
        savings_pct = projection.summary["average_token_savings_pct"]
        self.assertIsNotNone(savings_pct)
        assert isinstance(savings_pct, (int, float))
        self.assertAlmostEqual(float(savings_pct), 40.0)
        usage_fact = projection.fact_behavior_usage[0]
        self.assertEqual(usage_fact["baseline_tokens"], 1500)
        self.assertEqual(usage_fact["behavior_ids"], ["behavior-x"])
        self.assertTrue(projection.fact_resource_usage)
        self.assertTrue(projection.fact_cost_allocation)
        total_cost_value = projection.summary["total_cost_usd"]
        self.assertIsInstance(total_cost_value, (int, float))
        assert isinstance(total_cost_value, (int, float))
        self.assertGreater(float(total_cost_value), 0)


if __name__ == "__main__":
    unittest.main()
