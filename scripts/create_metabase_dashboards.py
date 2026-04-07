#!/usr/bin/env python3
"""
Programmatically create Metabase analytics dashboards using the REST API.

This script creates all 4 PRD KPI dashboards with corrected SQL queries:
1. PRD KPI Summary (6 cards)
2. Behavior Usage Trends (4 cards)
3. Token Savings Analysis (5 cards)
4. Compliance Coverage (5 cards)

Usage:
    python scripts/create_metabase_dashboards.py

Environment variables:
    METABASE_URL: Metabase instance URL (default: http://localhost:3000)
    METABASE_USERNAME: Admin username (default: admin@amprealize.local)
    METABASE_PASSWORD: Admin password (no default - must be set)

References:
    - Metabase API docs: https://www.metabase.com/docs/latest/api-documentation
    - behavior_orchestrate_cicd: Automate dashboard deployment
    - behavior_instrument_metrics_pipeline: PRD metrics visualization
"""

import os
import sys
import json
import requests
from typing import Dict, List, Optional, Any


class MetabaseClient:
    """Client for Metabase REST API operations."""

    def __init__(self, url: str, username: str, password: str):
        self.url = url.rstrip('/')
        self.session = requests.Session()
        self.session_token: Optional[str] = None
        self.database_id: Optional[int] = None

        # Authenticate and get session token
        self._authenticate(username, password)

    def _authenticate(self, username: str, password: str) -> None:
        """Authenticate and obtain session token."""
        auth_url = f"{self.url}/api/session"
        response = self.session.post(auth_url, json={
            "username": username,
            "password": password
        })
        response.raise_for_status()

        self.session_token = response.json()["id"]
        self.session.headers["X-Metabase-Session"] = self.session_token
        print(f"✅ Authenticated to Metabase at {self.url}")

    def _search(self, query: str, entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search Metabase entities by name."""
        params: Dict[str, Any] = {"q": query}
        if entity_type:
            params["type"] = entity_type
        response = self.session.get(f"{self.url}/api/search", params=params)
        response.raise_for_status()
        return response.json()

    def delete_dashboard_by_name(self, name: str) -> None:
        """Delete an existing dashboard matching the exact name."""
        try:
            results = self._search(name, "dashboard")
        except requests.HTTPError as exc:
            print(f"  ⚠️  Unable to search dashboards ({exc}); skipping delete for '{name}'")
            return

        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get("name") == name:
                dashboard_id = item.get("id")
                if dashboard_id is None:
                    continue
                delete_url = f"{self.url}/api/dashboard/{dashboard_id}"
                del_response = self.session.delete(delete_url)
                if del_response.status_code not in (200, 204):
                    if del_response.status_code == 404:
                        continue
                    del_response.raise_for_status()
                print(f"🗑️  Deleted existing dashboard: {name} (ID: {dashboard_id})")

    def delete_cards_by_name(self, name: str) -> None:
        """Delete all cards that match the exact name."""
        try:
            results = self._search(name, "card")
        except requests.HTTPError as exc:
            print(f"  ⚠️  Unable to search cards ({exc}); skipping delete for '{name}'")
            return

        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get("name") == name:
                card_id = item.get("id")
                if card_id is None:
                    continue
                delete_url = f"{self.url}/api/card/{card_id}"
                del_response = self.session.delete(delete_url)
                if del_response.status_code not in (200, 204):
                    if del_response.status_code == 404:
                        continue
                    del_response.raise_for_status()
                print(f"  🗑️  Deleted existing card: {name} (ID: {card_id})")

    def get_database_id(self, database_name: str = "telemetry_sqlite") -> int:
        """Find database ID by name."""
        if self.database_id is not None:
            return self.database_id

        response = self.session.get(f"{self.url}/api/database")
        response.raise_for_status()

        databases = response.json()["data"]
        for db in databases:
            if database_name in db.get("name", "").lower():
                self.database_id = db["id"]
                print(f"✅ Found database '{db['name']}' with ID {self.database_id}")
                return self.database_id

        raise ValueError(f"Database '{database_name}' not found. Available: {[d['name'] for d in databases]}")

    def create_native_question(self, name: str, sql: str, database_id: int,
                               visualization_type: str = "scalar",
                               visualization_settings: Optional[Dict] = None) -> Dict:
        """Create a native SQL question (card)."""
        self.delete_cards_by_name(name)
        question_data = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {
                    "query": sql,
                    "template-tags": {}
                },
                "database": database_id
            },
            "display": visualization_type,
            "visualization_settings": visualization_settings or {}
        }

        response = self.session.post(f"{self.url}/api/card", json=question_data)
        response.raise_for_status()
        card = response.json()
        print(f"  ✅ Created card: {name} (ID: {card['id']})")
        return card

    def create_dashboard(self, name: str, description: str = "") -> Dict:
        """Create a new dashboard."""
        self.delete_dashboard_by_name(name)
        dashboard_data = {
            "name": name,
            "description": description
        }

        response = self.session.post(f"{self.url}/api/dashboard", json=dashboard_data)
        response.raise_for_status()
        dashboard = response.json()
        print(f"✅ Created dashboard: {name} (ID: {dashboard['id']})")
        return dashboard

    def add_card_to_dashboard(self, dashboard_id: int, card_id: int,
                              row: int = 0, col: int = 0,
                              size_x: int = 4, size_y: int = 4) -> Dict:
        """Add a card to a dashboard with positioning."""
        # Metabase uses PUT to update entire dashboard with new dashcard
        # Each new dashcard needs a negative ID

        # First, get current dashboard state
        get_response = self.session.get(f"{self.url}/api/dashboard/{dashboard_id}")
        get_response.raise_for_status()
        dashboard = get_response.json()

        # Get existing dashcards and find next negative ID
        existing_dashcards = dashboard.get("dashcards", [])
        next_id = -1
        if existing_dashcards:
            existing_ids = [dc["id"] for dc in existing_dashcards if dc["id"] < 0]
            next_id = min(existing_ids) - 1 if existing_ids else -1

        # Add new dashcard
        new_dashcard = {
            "id": next_id,
            "card_id": card_id,
            "row": row,
            "col": col,
            "size_x": size_x,
            "size_y": size_y
        }
        existing_dashcards.append(new_dashcard)

        # Update dashboard
        update_data = {"dashcards": existing_dashcards}
        response = self.session.put(
            f"{self.url}/api/dashboard/{dashboard_id}",
            json=update_data
        )
        response.raise_for_status()
        return response.json()


def create_dashboard_1_prd_kpi_summary(client: MetabaseClient, database_id: int) -> int:
    """Create Dashboard #1: PRD KPI Summary."""
    print("\n📊 Creating Dashboard #1: PRD KPI Summary...")

    dashboard = client.create_dashboard(
        name="PRD KPI Summary",
        description="Executive dashboard tracking the 4 core PRD success metrics: behavior reuse %, token savings %, completion rate, compliance coverage %"
    )
    dashboard_id = dashboard["id"]

    # Card 1: Behavior Reuse Rate (Metric)
    card1 = client.create_native_question(
        name="Behavior Reuse Rate",
        sql="""SELECT
  ROUND(reuse_rate_pct, 1) as rate_pct,
  CASE
    WHEN reuse_rate_pct >= 70.0 THEN 'On Track'
    WHEN reuse_rate_pct >= 60.0 THEN 'At Risk'
    ELSE 'Off Track'
  END as status
FROM view_behavior_reuse_rate;""",
        database_id=database_id,
        visualization_type="scalar",
        visualization_settings={
            "scalar.field": "rate_pct",
            "card.title": "Behavior Reuse Rate"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card1["id"], row=0, col=0, size_x=4, size_y=3)

    # Card 2: Token Savings Rate (Metric)
    card2 = client.create_native_question(
        name="Token Savings Rate",
        sql="""SELECT
  ROUND(avg_savings_rate_pct, 1) as rate_pct,
  CASE
    WHEN avg_savings_rate_pct >= 30.0 THEN 'On Track'
    WHEN avg_savings_rate_pct >= 20.0 THEN 'At Risk'
    ELSE 'Off Track'
  END as status
FROM view_token_savings_rate;""",
        database_id=database_id,
        visualization_type="scalar",
        visualization_settings={
            "scalar.field": "rate_pct",
            "card.title": "Token Savings Rate"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card2["id"], row=0, col=4, size_x=4, size_y=3)

    # Card 3: Task Completion Rate (Metric)
    card3 = client.create_native_question(
        name="Task Completion Rate",
        sql="""SELECT
  ROUND(completion_rate_pct, 1) as rate_pct,
  CASE
    WHEN completion_rate_pct >= 80.0 THEN 'On Track'
    WHEN completion_rate_pct >= 70.0 THEN 'At Risk'
    ELSE 'Off Track'
  END as status
FROM view_completion_rate;""",
        database_id=database_id,
        visualization_type="scalar",
        visualization_settings={
            "scalar.field": "rate_pct",
            "card.title": "Task Completion Rate"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card3["id"], row=0, col=8, size_x=4, size_y=3)

    # Card 4: Compliance Coverage Rate (Metric)
    card4 = client.create_native_question(
        name="Compliance Coverage Rate",
        sql="""SELECT
  ROUND(avg_coverage_rate_pct, 1) as rate_pct,
  CASE
    WHEN avg_coverage_rate_pct >= 95.0 THEN 'On Track'
    WHEN avg_coverage_rate_pct >= 90.0 THEN 'At Risk'
    ELSE 'Off Track'
  END as status
FROM view_compliance_coverage_rate;""",
        database_id=database_id,
        visualization_type="scalar",
        visualization_settings={
            "scalar.field": "rate_pct",
            "card.title": "Compliance Coverage Rate"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card4["id"], row=0, col=12, size_x=4, size_y=3)

    # Card 5: KPI Snapshot Bar Chart
    card5 = client.create_native_question(
        name="KPI Snapshot",
        sql="""SELECT
  'Behavior Reuse' as metric_name,
  reuse_rate_pct as value
FROM view_behavior_reuse_rate

UNION ALL

SELECT
  'Token Savings' as metric_name,
  avg_savings_rate_pct as value
FROM view_token_savings_rate

UNION ALL

SELECT
  'Completion' as metric_name,
  completion_rate_pct as value
FROM view_completion_rate

UNION ALL

SELECT
  'Compliance' as metric_name,
  avg_coverage_rate_pct as value
FROM view_compliance_coverage_rate;""",
        database_id=database_id,
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["metric_name"],
            "graph.metrics": ["value"],
            "card.title": "Current KPI Snapshot"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card5["id"], row=3, col=0, size_x=8, size_y=4)

    # Card 6: Run Volume by Status
    card6 = client.create_native_question(
        name="Run Volume by Status",
        sql="""SELECT
  status as final_status,
  COUNT(*) as run_count
FROM fact_execution_status
GROUP BY status
ORDER BY run_count DESC;""",
        database_id=database_id,
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["final_status"],
            "graph.metrics": ["run_count"],
            "card.title": "Run Volume by Status"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card6["id"], row=3, col=8, size_x=8, size_y=4)

    print(f"✅ Dashboard #1 complete with 6 cards")
    return dashboard_id


def create_dashboard_2_behavior_usage(client: MetabaseClient, database_id: int) -> int:
    """Create Dashboard #2: Behavior Usage Trends."""
    print("\n📊 Creating Dashboard #2: Behavior Usage Trends...")

    dashboard = client.create_dashboard(
        name="Behavior Usage Trends",
        description="Behavior citation patterns, leaderboard, and adoption metrics"
    )
    dashboard_id = dashboard["id"]

    # Card 1: Behavior Usage Summary
    card1 = client.create_native_question(
        name="Behavior Usage Summary",
        sql="""SELECT
  total_runs,
  runs_with_behaviors,
  ROUND(reuse_rate_pct, 1) as reuse_rate_pct,
    ROUND((runs_with_behaviors * 100.0 / NULLIF(total_runs, 0)), 1) as pct_runs_using_behaviors
FROM view_behavior_reuse_rate;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card1["id"], row=0, col=0, size_x=8, size_y=3)

    # Card 2: Behavior Leaderboard
    card2 = client.create_native_question(
        name="Behavior Leaderboard",
        sql="""SELECT
  run_id,
  behavior_count as citations,
  ROUND(behavior_count * 1.0, 2) as citations_total
FROM fact_behavior_usage
ORDER BY behavior_count DESC
LIMIT 20;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card2["id"], row=0, col=8, size_x=8, size_y=3)

    # Card 3: Usage Distribution
    card3 = client.create_native_question(
        name="Usage Distribution",
        sql="""SELECT
  CASE
    WHEN behavior_count = 0 THEN '0 behaviors'
    WHEN behavior_count BETWEEN 1 AND 3 THEN '1-3 behaviors'
    WHEN behavior_count BETWEEN 4 AND 6 THEN '4-6 behaviors'
    WHEN behavior_count BETWEEN 7 AND 10 THEN '7-10 behaviors'
    ELSE '10+ behaviors'
  END as bucket,
  COUNT(*) as run_count
FROM fact_behavior_usage
GROUP BY
  CASE
    WHEN behavior_count = 0 THEN '0 behaviors'
    WHEN behavior_count BETWEEN 1 AND 3 THEN '1-3 behaviors'
    WHEN behavior_count BETWEEN 4 AND 6 THEN '4-6 behaviors'
    WHEN behavior_count BETWEEN 7 AND 10 THEN '7-10 behaviors'
    ELSE '10+ behaviors'
  END
ORDER BY MIN(behavior_count);""",
        database_id=database_id,
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["bucket"],
            "graph.metrics": ["run_count"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card3["id"], row=3, col=0, size_x=16, size_y=4)

    print(f"✅ Dashboard #2 complete with 3 cards")
    return dashboard_id


def create_dashboard_3_token_savings(client: MetabaseClient, database_id: int) -> int:
    """Create Dashboard #3: Token Savings Analysis."""
    print("\n📊 Creating Dashboard #3: Token Savings Analysis...")

    dashboard = client.create_dashboard(
        name="Token Savings Analysis",
        description="Token efficiency tracking, savings distribution, and ROI calculations"
    )
    dashboard_id = dashboard["id"]

    # Card 1: Token Savings Summary
    card1 = client.create_native_question(
        name="Token Savings Summary",
        sql="""SELECT
  ROUND(avg_savings_rate_pct, 1) as avg_savings_pct,
  total_runs,
  ROUND(total_baseline_tokens, 0) as total_baseline,
  ROUND(total_output_tokens, 0) as total_output,
  ROUND(total_tokens_saved, 0) as total_saved
FROM view_token_savings_rate;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card1["id"], row=0, col=0, size_x=16, size_y=3)

    # Card 2: Savings Distribution
    card2 = client.create_native_question(
        name="Savings Distribution",
        sql="""SELECT
  CASE
    WHEN token_savings_pct >= 0.50 THEN '50%+ savings'
    WHEN token_savings_pct >= 0.30 THEN '30-50% savings'
    WHEN token_savings_pct >= 0.10 THEN '10-30% savings'
    WHEN token_savings_pct >= 0.00 THEN '0-10% savings'
    ELSE 'Negative savings'
  END as bucket,
  COUNT(*) as run_count,
  ROUND(AVG(token_savings_pct) * 100, 1) as avg_pct
FROM fact_token_savings
GROUP BY
  CASE
    WHEN token_savings_pct >= 0.50 THEN '50%+ savings'
    WHEN token_savings_pct >= 0.30 THEN '30-50% savings'
    WHEN token_savings_pct >= 0.10 THEN '10-30% savings'
    WHEN token_savings_pct >= 0.00 THEN '0-10% savings'
    ELSE 'Negative savings'
  END
ORDER BY MIN(token_savings_pct) DESC;""",
        database_id=database_id,
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["bucket"],
            "graph.metrics": ["run_count"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card2["id"], row=3, col=0, size_x=8, size_y=4)

    # Card 3: Savings vs Behaviors Scatter
    card3 = client.create_native_question(
        name="Savings vs Behaviors",
        sql="""SELECT
  COALESCE(b.behavior_count, 0) as behavior_count,
  ROUND(t.token_savings_pct * 100, 1) as savings_pct,
  t.run_id
FROM fact_token_savings t
LEFT JOIN fact_behavior_usage b ON t.run_id = b.run_id;""",
        database_id=database_id,
        visualization_type="scatter",
        visualization_settings={
            "graph.dimensions": ["behavior_count"],
            "graph.metrics": ["savings_pct"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card3["id"], row=3, col=8, size_x=8, size_y=4)

    # Card 4: Efficiency Leaderboard
    card4 = client.create_native_question(
        name="Efficiency Leaderboard",
        sql="""SELECT
  run_id,
  baseline_tokens,
  output_tokens,
  ROUND(token_savings_pct * 100, 1) as savings_pct,
  (baseline_tokens - output_tokens) as tokens_saved
FROM fact_token_savings
ORDER BY token_savings_pct DESC
LIMIT 20;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card4["id"], row=7, col=0, size_x=16, size_y=4)

    print(f"✅ Dashboard #3 complete with 4 cards")
    return dashboard_id


def create_dashboard_4_compliance_coverage(client: MetabaseClient, database_id: int) -> int:
    """Create Dashboard #4: Compliance Coverage."""
    print("\n📊 Creating Dashboard #4: Compliance Coverage...")

    coverage_runs_cte = """WITH checklist_runs AS (
    SELECT
        checklist_id,
        run_id,
        COUNT(DISTINCT step_id) AS step_count,
        SUM(CASE WHEN status IN ('COMPLETED','SKIPPED') THEN 1 ELSE 0 END) AS terminal_steps,
        MAX(COALESCE(coverage_score, 0)) AS coverage_score
    FROM fact_compliance_steps
    WHERE checklist_id IS NOT NULL
    GROUP BY checklist_id, run_id
)"""

    dashboard = client.create_dashboard(
        name="Compliance Coverage",
        description="Checklist completion tracking, audit queue, and compliance coverage metrics"
    )
    dashboard_id = dashboard["id"]

    # Card 1: Coverage Summary
    card1 = client.create_native_question(
        name="Coverage Summary",
        sql="""SELECT
    ROUND(avg_coverage_rate_pct, 1) AS avg_coverage_pct,
    total_runs,
    runs_above_95pct,
    ROUND((runs_above_95pct * 100.0 / NULLIF(total_runs, 0)), 1) AS pct_above_target
FROM view_compliance_coverage_rate;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card1["id"], row=0, col=0, size_x=16, size_y=3)

    # Card 2: Checklist Rankings
    card2 = client.create_native_question(
        name="Checklist Rankings",
        sql=f"""{coverage_runs_cte}
SELECT
    checklist_id,
    ROUND(AVG(coverage_score) * 100, 1) AS avg_coverage,
    COUNT(*) AS executions,
    SUM(CASE WHEN coverage_score >= 0.999 THEN 1 ELSE 0 END) AS complete_count
FROM checklist_runs
GROUP BY checklist_id
ORDER BY avg_coverage DESC;""",
        database_id=database_id,
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["checklist_id"],
            "graph.metrics": ["avg_coverage"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card2["id"], row=3, col=0, size_x=8, size_y=4)

    # Card 3: Step Completion Summary
    card3 = client.create_native_question(
        name="Step Completion Summary",
        sql=f"""{coverage_runs_cte}
SELECT
    checklist_id,
    step_count,
    ROUND(AVG(coverage_score) * 100, 1) AS avg_coverage,
    COUNT(*) AS runs,
    SUM(CASE WHEN coverage_score >= 0.999 THEN 1 ELSE 0 END) AS fully_complete,
    ROUND(SUM(CASE WHEN coverage_score >= 0.999 THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 1) AS completion_rate
FROM checklist_runs
GROUP BY checklist_id, step_count
ORDER BY avg_coverage ASC;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card3["id"], row=3, col=8, size_x=8, size_y=4)

    # Card 4: Audit Queue
    card4 = client.create_native_question(
        name="Audit Queue (Incomplete Runs)",
        sql=f"""{coverage_runs_cte}
SELECT
    run_id,
    checklist_id,
    step_count,
    ROUND(coverage_score * 100, 1) AS coverage_pct,
    (step_count - terminal_steps) AS incomplete_steps
FROM checklist_runs
WHERE coverage_score < 0.999
ORDER BY coverage_score ASC
LIMIT 50;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card4["id"], row=7, col=0, size_x=16, size_y=4)

    # Card 5: Coverage Distribution
    card5 = client.create_native_question(
        name="Coverage Distribution",
        sql=f"""{coverage_runs_cte}
SELECT
    CASE
        WHEN COALESCE(coverage_score, 0) >= 0.95 THEN '95-100%'
        WHEN COALESCE(coverage_score, 0) >= 0.85 THEN '85-95%'
        WHEN COALESCE(coverage_score, 0) >= 0.75 THEN '75-85%'
        WHEN COALESCE(coverage_score, 0) >= 0.50 THEN '50-75%'
        ELSE '<50%'
    END AS coverage_bucket,
    COUNT(*) AS run_count
FROM checklist_runs
GROUP BY coverage_bucket
ORDER BY coverage_bucket DESC;""",
        database_id=database_id,
        visualization_type="pie",
        visualization_settings={
            "pie.dimension": "coverage_bucket",
            "pie.metric": "run_count"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card5["id"], row=11, col=0, size_x=16, size_y=4)

    print(f"✅ Dashboard #4 complete with 5 cards")
    return dashboard_id


def create_dashboard_5_cost_optimization(client: MetabaseClient, database_id: int) -> int:
    """Create Dashboard #5: Cost Optimization (PRD 8.17) with 6 cards."""
    print("\n📊 Creating Dashboard #5: Cost Optimization...")

    dashboard = client.create_dashboard(
        name="Cost Optimization",
        description="LLM cost tracking, budget monitoring, and ROI analysis (PRD 8.17)"
    )
    dashboard_id = dashboard["id"]

    # Card 1: Total Cost Summary (Scalar)
    card1 = client.create_native_question(
        name="Total Cost Summary",
        sql="""SELECT
  ROUND(SUM(cost_usd), 4) as total_cost_usd,
  SUM(total_tokens) as total_tokens,
  COUNT(DISTINCT run_id) as total_runs
FROM view_cost_by_run;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card1["id"], row=0, col=0, size_x=16, size_y=3)

    # Card 2: Cost by Service (Pie Chart)
    card2 = client.create_native_question(
        name="Cost by Service",
        sql="""SELECT
  service_name,
  ROUND(SUM(cost_usd), 4) as total_cost_usd,
  COUNT(DISTINCT run_id) as run_count
FROM view_cost_by_run
GROUP BY service_name
ORDER BY total_cost_usd DESC;""",
        database_id=database_id,
        visualization_type="pie",
        visualization_settings={
            "pie.dimension": "service_name",
            "pie.metric": "total_cost_usd"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card2["id"], row=3, col=0, size_x=8, size_y=4)

    # Card 3: Daily Cost Trend (Line Chart)
    card3 = client.create_native_question(
        name="Daily Cost Trend",
        sql="""SELECT
  DATE(started_at) as cost_date,
  ROUND(SUM(cost_usd), 4) as daily_cost_usd,
  COUNT(DISTINCT run_id) as run_count,
  SUM(total_tokens) as daily_tokens
FROM view_cost_by_run
GROUP BY DATE(started_at)
ORDER BY cost_date DESC
LIMIT 30;""",
        database_id=database_id,
        visualization_type="line",
        visualization_settings={
            "graph.dimensions": ["cost_date"],
            "graph.metrics": ["daily_cost_usd"],
            "graph.show_goal": True,
            "graph.goal_value": 50.0,
            "graph.goal_label": "Daily Budget"
        }
    )
    client.add_card_to_dashboard(dashboard_id, card3["id"], row=3, col=8, size_x=8, size_y=4)

    # Card 4: Top Expensive Workflows (Bar Chart)
    card4 = client.create_native_question(
        name="Top Expensive Workflows",
        sql="""SELECT
  COALESCE(template_id, 'ad-hoc') as template_id,
  ROUND(SUM(cost_usd), 4) as total_cost_usd,
  COUNT(DISTINCT run_id) as run_count,
  ROUND(AVG(cost_usd), 4) as avg_cost_per_run
FROM view_cost_by_run
GROUP BY template_id
ORDER BY total_cost_usd DESC
LIMIT 10;""",
        database_id=database_id,
        visualization_type="bar",
        visualization_settings={
            "graph.dimensions": ["template_id"],
            "graph.metrics": ["total_cost_usd"]
        }
    )
    client.add_card_to_dashboard(dashboard_id, card4["id"], row=7, col=0, size_x=8, size_y=4)

    # Card 5: ROI Summary (Table)
    card5 = client.create_native_question(
        name="ROI Analysis",
        sql="""SELECT
  ROUND(SUM(cost_usd), 4) as total_cost_usd,
  SUM(tokens_saved) as total_tokens_saved,
  CASE
    WHEN SUM(tokens_saved) > 0 THEN ROUND(SUM(cost_usd) / SUM(tokens_saved), 6)
    ELSE 0
  END as cost_per_token_saved,
  CASE
    WHEN SUM(cost_usd) > 0 THEN ROUND(SUM(tokens_saved) * 0.00001 / SUM(cost_usd), 2)
    ELSE 0
  END as efficiency_score,
  COUNT(DISTINCT run_id) as total_runs
FROM view_roi_summary;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card5["id"], row=7, col=8, size_x=8, size_y=4)

    # Card 6: Cost Per Run Table
    card6 = client.create_native_question(
        name="Recent Runs by Cost",
        sql="""SELECT
  run_id,
  COALESCE(template_id, 'ad-hoc') as template,
  service_name,
  ROUND(cost_usd, 4) as cost_usd,
  total_tokens,
  started_at
FROM view_cost_by_run
ORDER BY cost_usd DESC
LIMIT 25;""",
        database_id=database_id,
        visualization_type="table"
    )
    client.add_card_to_dashboard(dashboard_id, card6["id"], row=11, col=0, size_x=16, size_y=4)

    print(f"✅ Dashboard #5 complete with 6 cards")
    return dashboard_id


def clean_all_dashboards_and_cards(client: MetabaseClient) -> None:
    """Delete all existing Amprealize dashboards and cards."""
    print("\n🧹 Cleaning up existing dashboards and cards...")

    # Dashboard names to delete
    dashboard_names = [
        "PRD KPI Summary",
        "Behavior Usage Trends",
        "Token Savings Analysis",
        "Compliance Coverage",
        "Cost Optimization",
    ]

    # Card names to delete (all cards from all dashboards)
    card_names = [
        # Dashboard 1: PRD KPI Summary
        "Behavior Reuse Rate",
        "Token Savings Rate",
        "Task Completion Rate",
        "Compliance Coverage Rate",
        "KPI Snapshot",
        "Run Volume by Status",
        # Dashboard 2: Behavior Usage Trends
        "Behavior Usage Summary",
        "Behavior Leaderboard",
        "Usage Distribution",
        # Dashboard 3: Token Savings Analysis
        "Token Savings Summary",
        "Savings Distribution",
        "Savings vs Behaviors",
        "Efficiency Leaderboard",
        # Dashboard 4: Compliance Coverage
        "Coverage Summary",
        "Checklist Rankings",
        "Step Completion Summary",
        "Audit Queue (Incomplete Runs)",
        "Coverage Distribution",
        # Dashboard 5: Cost Optimization
        "Total Cost Summary",
        "Cost by Service",
        "Daily Cost Trend",
        "Top Expensive Workflows",
        "ROI Analysis",
        "Recent Runs by Cost",
    ]

    # Delete all dashboards
    deleted_dashboards = 0
    for name in dashboard_names:
        try:
            client.delete_dashboard_by_name(name)
            deleted_dashboards += 1
        except Exception as e:
            print(f"  ⚠️  Could not delete dashboard '{name}': {e}")

    # Delete all cards
    deleted_cards = 0
    for name in card_names:
        try:
            client.delete_cards_by_name(name)
            deleted_cards += 1
        except Exception as e:
            print(f"  ⚠️  Could not delete card '{name}': {e}")

    print(f"  ✅ Cleanup complete ({deleted_dashboards} dashboards, {deleted_cards} card types checked)\n")


def main():
    """Main script execution."""
    print("🚀 Amprealize Metabase Dashboard Creation Script")
    print("=" * 60)

    # Configuration from environment
    metabase_url = os.getenv("METABASE_URL", "http://localhost:3000")
    username = os.getenv("METABASE_USERNAME", "nick.sanders.a@gmail.com")
    password = os.getenv("METABASE_PASSWORD")

    if not password:
        print("ERROR: METABASE_PASSWORD environment variable not set")
        print("Set it before running: export METABASE_PASSWORD='your-password'")
        return

    try:
        # Initialize client
        client = MetabaseClient(metabase_url, username, password)

        # Get database ID (search for "Amprealize" or "analytics" in database name)
        database_id = client.get_database_id("analytics")

        # Clean up all existing dashboards and cards first
        clean_all_dashboards_and_cards(client)

        # Create all 5 dashboards
        dashboard_ids = []
        dashboard_ids.append(create_dashboard_1_prd_kpi_summary(client, database_id))
        dashboard_ids.append(create_dashboard_2_behavior_usage(client, database_id))
        dashboard_ids.append(create_dashboard_3_token_savings(client, database_id))
        dashboard_ids.append(create_dashboard_4_compliance_coverage(client, database_id))
        dashboard_ids.append(create_dashboard_5_cost_optimization(client, database_id))

        # Success summary
        print("\n" + "=" * 60)
        print("✅ ALL DASHBOARDS CREATED SUCCESSFULLY!")
        print("=" * 60)
        print(f"\n📊 Dashboard URLs:")
        for i, dash_id in enumerate(dashboard_ids, 1):
            print(f"  Dashboard #{i}: {metabase_url}/dashboard/{dash_id}")

        print(f"\n💡 Total: 5 dashboards with 24 cards created")
        print(f"🌐 Access Metabase at: {metabase_url}")

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
