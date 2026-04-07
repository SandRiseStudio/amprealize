# Consent & MFA Telemetry Snapshot

This snapshot aggregates the latest consent instrumentation across Web, CLI, and VS Code surfaces. Values are derived from synthetic test runs collected after the new telemetry hooks were deployed.

| Surface | Prompts | Approvals | Denials | Snoozes | MFA Required | MFA Completed | Avg Decision Latency (s) | p95 Decision Latency (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| web | 32 | 27 | 2 | 3 | 12 | 11 | 4.6 | 9.8 |
| cli | 19 | 14 | 3 | 2 | 19 | 17 | 6.1 | 11.4 |
| vscode | 15 | 12 | 1 | 2 | 10 | 9 | 5.2 | 10.7 |

> _Updated: 2025-10-15_

## Observations
- CLI prompts exhibit the highest MFA volume; iterative UX tests should focus on shortening device-code approval steps.
- Web surface shows quickest decision times thanks to inline modals, but snooze usage indicates opportunity to improve context copy.
- VS Code approvals trend positive; integrate badge reminders for pending MFA to avoid stale prompts.

## Telemetry event hooks
- `consent.snapshot` — emitted by the dashboard to seed metrics with the latest snapshot payload (`surface`, counts, latency stats, `updated_at`).
- `consent.prompt_finished` — emitted by live surfaces whenever a consent decision resolves; payload must include `surface`, `decision`, `latency_seconds`, `mfa_required`, `mfa_completed`.
- Downstream analytics aggregate these events to refresh the dashboard in real time and to back the PRD adoption metrics.
