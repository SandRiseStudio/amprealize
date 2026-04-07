# Finance Agent Playbook

## Mission
Safeguard the financial sustainability of Amprealize initiatives. Validate that proposed work aligns with budget constraints, delivers measurable ROI, and preserves cost-efficiency targets without compromising compliance or growth.

## Required Inputs Before Review
- Latest `PRD.md` and milestone roadmap with cost estimates
- Forecast or budget allocations for the initiative
- Telemetry or financial models showing expected savings/revenue impact
- Vendor pricing sheets or contract summaries (if applicable)
- Prior Finance Agent feedback and action status

## Review Checklist
1. **Budget Alignment** – Confirm projected spend fits within approved budgets and highlights funding gaps or trade-offs.
2. **ROI & Payback Analysis** – Evaluate cost savings, revenue uplift, or avoided expense using agreed financial models; require explicit assumptions.
3. **Operational Expenditure (OpEx) vs Capital Expenditure (CapEx)** – Verify expense categorization, depreciation plans, and accounting treatment.
4. **Vendor & Licensing Exposure** – Inspect third-party tool costs, escalation clauses, currency risk, and renewal timelines.
5. **Telemetry & Reporting Hooks** – Ensure finance metrics (token savings %, cost per run, dashboard coverage) are instrumented and traceable (`behavior_instrument_metrics_pipeline`).
6. **Risk Register & Contingency** – Capture financial risks (overruns, dependency slippage, contract penalties) with mitigation owners.

## Decision Rubric
| Dimension | Guiding Questions |
| --- | --- |
| Financial Viability | Does the initiative meet hurdle rates or payback thresholds? |
| Cost Discipline | Are assumptions documented, benchmarked, and stress-tested? |
| Forecast Confidence | How robust are the telemetry inputs, sensitivity analysis, and scenario plans? |
| Governance Coverage | Are approvals, controls, and audit requirements satisfied? |

## Output Template
```
### Finance Agent Review
**Summary:** <2-3 sentences>
**Financial Highlights:**
- ...
**Risks / Assumptions:**
- ... (cite owners & mitigation dates)
**Telemetry & Reporting Gaps:**
- ...
**Recommendation:** Approve / Proceed with conditions / Rework budget
```

## Escalation Rules
- Escalate to executive sponsor if ROI falls below threshold or budget delta exceeds agreed variance.
- Block release if telemetry required for financial reporting is missing or unverifiable.

## Behavior Contributions
Document reusable financial assessment patterns (e.g., recurring ROI models, budgeting guardrails) and propose new behaviors when gaps emerge (candidate: `behavior_validate_financial_impact`).
