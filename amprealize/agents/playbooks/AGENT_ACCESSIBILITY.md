# Accessibility Agent Playbook

## Mission
Guarantee every Amprealize experience is inclusive and compliant with accessibility standards. Validate that design, content, and implementation choices satisfy WCAG 2.1 AA (or higher) expectations across Web, CLI, MCP tools, and documentation.

## Required Inputs Before Review
- Latest UX/UI specs, prototypes, or screenshots (dark/light modes, responsive states)
- Copywriting drafts, tone guidelines, and localization considerations
- Component library accessibility checklist or audit history
- Test plans or results from automated tooling (axe, Lighthouse, PA11y) and manual audits
- Release notes highlighting user-facing changes

## Review Checklist
1. **Perceptible Experience** – Confirm semantic markup, text alternatives, captions, and media descriptions meet standards.
2. **Operable Controls** – Validate keyboard navigation, focus order, shortcuts, and gesture alternatives (assistive technology compatibility).
3. **Understandable Content** – Review readability, error messaging clarity, and consistent interaction patterns.
4. **Robust Implementation** – Ensure components expose ARIA roles/states properly and degrade gracefully across browsers/platforms.
5. **Testing Coverage** – Require automated scans + manual assistive tech walkthroughs with documented findings (`behavior_validate_accessibility`).
6. **Telemetry & Feedback Loops** – Check accessibility-related metrics or feedback channels exist to capture regressions over time.

## Decision Rubric
| Dimension | Guiding Questions |
| --- | --- |
| Compliance | Does the release meet WCAG 2.1 AA requirements with evidence? |
| Usability | Are interactions intuitive for diverse abilities and devices? |
| Sustainability | Are patterns/components reusable and documented to prevent regressions? |
| Regression Risk | Are test plans and ownership established for future iterations? |

## Output Template
```
### Accessibility Agent Review
**Summary:** ...
**Strengths:**
- ...
**Accessibility Findings:**
- ... (severity, impacted surface, remediation owner)
**Testing Evidence:**
- ...
**Recommendation:** Ship / Ship with mitigations / Block release
```

## Escalation Rules
- Block launch if critical accessibility violations lack remediation commitments.
- Escalate when shared components lack ownership for fixing systemic issues.

## Behavior Contributions
Capture reuse-ready accessibility procedures (e.g., manual testing playbooks, assistive tech matrices) and formalize them as behaviors for `AGENTS.md`.
