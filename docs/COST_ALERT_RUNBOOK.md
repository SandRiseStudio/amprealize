# Cost Alert Runbook

**Status**: ✅ Production
**Last Updated**: 2025-11-26
**Related Docs**: [COST_MODEL.md](./COST_MODEL.md), [EPIC_8_12_COST_OPTIMIZATION.md](./EPIC_8_12_COST_OPTIMIZATION.md)

## Overview

This runbook provides operational procedures for responding to Amprealize cost alerts. Alerts are triggered by Grafana based on configurable budget thresholds.

## Alert Types

| Alert | Severity | Threshold | Check Interval |
|-------|----------|-----------|----------------|
| Daily Budget Warning | Warning | 80% of $80 = $64 | 1 hour |
| Daily Budget Exceeded | Critical | 100% of $80 | 1 hour |
| Monthly Budget Warning | Warning | 80% of $2000 = $1600 | 6 hours |
| Monthly Budget Exceeded | Critical | 100% of $2000 | 6 hours |
| Hourly Cost Spike | Warning | >50% increase vs prev hour | 15 minutes |

## Alert Routing

| Channel | Alert Types | Recipients |
|---------|-------------|------------|
| Slack #ops-alerts | All cost alerts | On-call engineer |
| Email | Critical alerts | finance@amprealize.local, eng-leads@amprealize.local |
| PagerDuty | Monthly Budget Exceeded only | On-call rotation |

## Response Procedures

### Alert: Daily Budget Warning (80%)

**Severity**: Warning
**Response Time**: 4 hours
**Escalation**: None initially

#### Investigation Steps

1. **Check current daily spend**:
   ```bash
   amprealize analytics daily-costs --start-date $(date +%Y-%m-%d) --format table
   ```

2. **Identify cost drivers**:
   ```bash
   amprealize analytics cost-by-service --start-date $(date +%Y-%m-%d) --format table
   ```

3. **Review expensive workflows**:
   ```bash
   amprealize analytics top-expensive --start-date $(date +%Y-%m-%d) --limit 10 --format table
   ```

4. **Check for anomalies**:
   - Unusually high token consumption per run
   - Spike in number of runs
   - Inefficient behavior conditioning

#### Actions

| Finding | Action |
|---------|--------|
| High token usage | Review behavior retrieval quality; ensure BCI is reducing tokens |
| Many small runs | Investigate automated triggers; check for retry loops |
| One expensive workflow | Optimize specific template; consider caching |
| Normal growth | Monitor; no action required |

---

### Alert: Daily Budget Exceeded (100%)

**Severity**: Critical
**Response Time**: 1 hour
**Escalation**: Engineering lead if unresolved in 2 hours

#### Investigation Steps

1. All steps from Daily Budget Warning, plus:

2. **Check real-time run activity**:
   ```bash
   amprealize runs list --status running --format table
   ```

3. **Review recent completed runs**:
   ```bash
   amprealize runs list --status completed --limit 50 --format table
   ```

4. **Check Grafana dashboard**:
   - Navigate to Cost Optimization Dashboard
   - Review "Hourly Cost Rate" panel for spike timing
   - Cross-reference with "Token Usage by Service"

#### Actions

| Finding | Action |
|---------|--------|
| Runaway automation | Pause automated triggers via `amprealize automation pause` |
| External attack/abuse | Enable rate limiting; review API keys |
| Legitimate growth | Document; request budget increase |
| Bug in cost calculation | File bug; verify projector logic |

#### Escalation

If daily budget exceeded by >20% ($96+), escalate to:
1. Engineering lead (Slack DM)
2. Finance team (email)
3. Create incident ticket in Jira

---

### Alert: Monthly Budget Warning (80%)

**Severity**: Warning
**Response Time**: 24 hours
**Escalation**: Finance review

#### Investigation Steps

1. **Review monthly trend**:
   ```bash
   amprealize analytics daily-costs --start-date $(date -d "30 days ago" +%Y-%m-%d) --format table
   ```

2. **Calculate run rate**:
   ```
   Current Month Spend: $X
   Days Elapsed: Y
   Daily Average: $X/Y
   Projected Month End: (Daily Average × 30)
   ```

3. **Compare with previous months**:
   ```bash
   amprealize analytics roi-summary --format json
   ```

#### Actions

| Finding | Action |
|---------|--------|
| Growth trajectory | Forecast EOM spend; notify Finance |
| One-time spike | Document cause; no action |
| Sustained high usage | Plan optimization sprint |

---

### Alert: Monthly Budget Exceeded (100%)

**Severity**: Critical
**Response Time**: 2 hours
**Escalation**: Finance + Engineering lead

#### Immediate Actions

1. **Notify stakeholders**:
   - Slack message to #cost-alerts with current spend
   - Email to finance@amprealize.local

2. **Document the exceedance**:
   - Total spend vs budget
   - Primary cost drivers
   - Root cause if known

3. **Determine response**:
   | Scenario | Response |
   |----------|----------|
   | Expected growth | Request budget increase; update `AMPREALIZE_COST_MONTHLY_BUDGET_USD` |
   | Unexpected spike | Implement cost controls (see below) |
   | Billing error | Contact provider; dispute charges |

#### Cost Control Options

| Control | Impact | Implementation |
|---------|--------|----------------|
| Rate limit API | Medium | Update nginx/API gateway |
| Pause non-critical workflows | High | `amprealize templates disable <id>` |
| Switch to cheaper model | Medium | Update `dim_cost_model` pricing |
| Reduce behavior retrieval K | Low | Update `BCI_TOP_K` setting |

---

### Alert: Hourly Cost Spike (>50%)

**Severity**: Warning
**Response Time**: 30 minutes
**Escalation**: None initially

#### Investigation Steps

1. **Identify spike timing**:
   - Check Grafana "Hourly Cost Rate" panel
   - Note exact time of spike

2. **Correlate with events**:
   - Deployment? (`git log --since="2 hours ago"`)
   - Traffic spike? (check request counts)
   - New customer onboarding?

3. **Check specific runs**:
   ```bash
   amprealize analytics cost-per-run --start-date $(date -d "2 hours ago" +%Y-%m-%d) --format table
   ```

#### Actions

If spike is:
- **Expected**: Document and close
- **Unexpected**: Continue investigation; check for bugs
- **Sustained**: Escalate to Daily Budget Warning procedures

---

## Preventive Measures

### Daily Operations

| Task | Frequency | Owner |
|------|-----------|-------|
| Review daily cost dashboard | Daily | On-call engineer |
| Check budget burn rate | Weekly | Finance |
| Review top expensive workflows | Weekly | Product |
| Update cost model rates | Monthly | Engineering |

### Optimization Opportunities

1. **Behavior Conditioning Efficiency**
   - Target: 30% token savings rate
   - Monitor via Token Savings Analysis dashboard
   - Low savings → Review behavior handbook quality

2. **Caching Layer**
   - Cache behavior embeddings
   - Cache compliance policy evaluations
   - Reduce redundant LLM calls

3. **Model Selection**
   - Use smaller models for simple tasks
   - Reserve GPT-4/Claude-Opus for complex reasoning
   - Implement model routing based on task complexity

4. **Request Batching**
   - Batch similar operations
   - Reduce API call overhead
   - Combine sequential behavior retrievals

---

## Dashboard Quick Access

| Dashboard | URL | Purpose |
|-----------|-----|---------|
| Grafana Cost Alerts | http://localhost:3001/d/cost-optimization | Real-time cost monitoring |
| Metabase Cost Optimization | http://localhost:3000/dashboard/5 | Historical analysis |
| VS Code Cost Tracker | Command: `Amprealize: Focus on Cost Tracker` | Customer-facing |

---

## Updating Thresholds

To update budget thresholds:

1. **Environment Variables** (recommended for quick changes):
   ```bash
   export AMPREALIZE_COST_DAILY_BUDGET_USD=100.0
   export AMPREALIZE_COST_MONTHLY_BUDGET_USD=2500.0
   export AMPREALIZE_COST_ALERT_THRESHOLD_PCT=0.75
   ```

2. **Settings File** (for permanent changes):
   Update `amprealize/config/settings.py`:
   ```python
   class CostOptimizationConfig(BaseSettings):
       daily_budget_usd: float = 100.0
       monthly_budget_usd: float = 2500.0
       alert_threshold_pct: float = 0.75
   ```

3. **Grafana Alerts** (for alert thresholds):
   - Edit `web-console/dashboard/grafana/cost-optimization-dashboard.json`
   - Update `threshold` values in panel definitions
   - Restart Grafana or reload dashboard

---

## Contact List

| Role | Contact | Escalation Path |
|------|---------|-----------------|
| On-call Engineer | PagerDuty rotation | First responder |
| Engineering Lead | @eng-lead in Slack | 2-hour escalation |
| Finance | finance@amprealize.local | Budget decisions |
| Product | @product in Slack | Workflow optimization |

---

**Behaviors Referenced**: `behavior_orchestrate_cicd`, `behavior_externalize_configuration`, `behavior_update_docs_after_changes`
