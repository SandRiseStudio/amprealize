# Midnighter Production Deployment Checklist

> Complete this checklist before deploying Midnighter to production.

## 🔐 Security & Secrets

- [ ] **OpenAI API Key**
  - [ ] Stored in secrets manager (not environment variable in code)
  - [ ] Key has appropriate rate limits and spending caps set in OpenAI dashboard
  - [ ] Separate keys for staging vs production
  - [ ] Key rotation schedule documented

- [ ] **Slack Webhook (if using cost alerts)**
  - [ ] Webhook URL stored in secrets manager
  - [ ] Test webhook with sample alert
  - [ ] Alert channel is monitored

- [ ] **Access Control**
  - [ ] API endpoints require authentication
  - [ ] Role-based access for corpus/job management
  - [ ] Audit logging enabled for all mutations

## 💰 Cost Controls

- [ ] **Budget Limits**
  - [ ] Monthly budget cap set in OpenAI dashboard
  - [ ] Cost alerts configured (see below)
  - [ ] Escalation path documented for budget overruns

- [ ] **Cost Alerting Setup**
  ```python
  from mdnt.integrations import create_raze_hooks

  hooks = create_raze_hooks(
      slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
      slack_channel="#ml-costs",
      cost_threshold_usd=50.0,  # Adjust based on expected costs
  )
  ```

- [ ] **Cost Thresholds Configured**
  | Alert Level | Threshold | Action |
  |-------------|-----------|--------|
  | Warning | $25 | Slack notification |
  | Critical | $100 | Slack + PagerDuty |
  | Emergency | $500 | Auto-pause training |

## 🔄 Rate Limiting & Resilience

- [ ] **OpenAI Client Retry Configuration**
  - [ ] `max_retries` set appropriately (default: 5)
  - [ ] Exponential backoff configured
  - [ ] Rate limit headers monitored

- [ ] **API Rate Limits**
  - [ ] Training API endpoints rate-limited
  - [ ] Corpus generation has concurrency limits
  - [ ] Batch size limits enforced

- [ ] **Circuit Breaker**
  - [ ] Failures don't cascade
  - [ ] Graceful degradation for non-critical features

## 📊 Monitoring & Observability

- [ ] **Structured Logging (Raze)**
  - [ ] All operations log to Raze
  - [ ] Log retention configured
  - [ ] Log queries tested

- [ ] **Metrics Dashboard**
  - [ ] Training job success/failure rates
  - [ ] Average training duration
  - [ ] Cost per job
  - [ ] Corpus quality scores

- [ ] **Alerting**
  | Metric | Threshold | Alert |
  |--------|-----------|-------|
  | Job failure rate | > 10% | Warning |
  | Training duration | > 2h | Warning |
  | Cost per job | > $50 | Critical |
  | API error rate | > 5% | Critical |

## 🧪 Validation

- [ ] **Pre-deployment Tests**
  ```bash
  # Run full test suite
  pytest tests/ -v

  # Test OpenAI integration
  pytest tests/test_openai_integration.py -v

  # Test CLI
  mdnt --help
  mdnt corpus list
  ```

- [ ] **Evaluation Benchmarks**
  - [ ] Baseline model performance recorded
  - [ ] Fine-tuned model meets quality thresholds
  - [ ] Behavior adherence score > 80%

- [ ] **Load Testing**
  - [ ] API can handle expected concurrent requests
  - [ ] Training queue handles burst load

## 🔙 Rollback Procedures

- [ ] **Model Rollback**
  ```bash
  # List available models
  mdnt model list

  # Rollback to previous model (update your inference config)
  # Previous model ID: ft:gpt-4o-mini:org::previous_id
  ```

- [ ] **Corpus Rollback**
  - [ ] Previous corpus versions archived
  - [ ] Can regenerate corpus from behavior snapshots

- [ ] **Configuration Rollback**
  - [ ] Configuration changes are versioned
  - [ ] Can restore previous configuration

## 📋 Documentation

- [ ] **Runbook**
  - [ ] Common issues and resolutions documented
  - [ ] On-call procedures defined
  - [ ] Escalation paths clear

- [ ] **API Documentation**
  - [ ] OpenAPI spec generated
  - [ ] Examples for all endpoints
  - [ ] Error codes documented

## 🚀 Deployment Steps

### Pre-deployment

1. [ ] Merge to main branch
2. [ ] All tests passing in CI
3. [ ] Security scan completed
4. [ ] Cost estimates approved

### Deployment

1. [ ] Deploy to staging environment
2. [ ] Run smoke tests on staging
3. [ ] Verify cost alerts working
4. [ ] Deploy to production
5. [ ] Monitor for 30 minutes

### Post-deployment

1. [ ] Verify metrics flowing
2. [ ] Test one training job (small corpus)
3. [ ] Confirm alerts working
4. [ ] Update BUILD_TIMELINE.md

## 🆘 Emergency Procedures

### Training Job Runaway

```bash
# Cancel all running jobs
mdnt job list --format json | jq -r '.[] | select(.status=="running") | .job_id' | xargs -I {} mdnt job cancel {}
```

### Cost Overrun

1. Check OpenAI dashboard for spending
2. Cancel running jobs (above)
3. Review recent job history for anomalies
4. Notify stakeholders

### API Outage

1. Check OpenAI status page
2. Review error logs: `mdnt job events <job_id>`
3. Switch to backup API key if available
4. Enable circuit breaker

---

## Sign-off

| Role | Name | Date | Approved |
|------|------|------|----------|
| Engineering Lead | | | [ ] |
| Security | | | [ ] |
| DevOps | | | [ ] |
| Product | | | [ ] |

---

_Last updated: December 2025_
