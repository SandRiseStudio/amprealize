# Amprealize Onboarding Quickstarts

> Mission: reduce time-to-first-behavior for every surface and capture telemetry needed to prove adoption targets (70% behavior reuse, 30% token savings, 80% task completion, 95% compliance coverage).

## How to use this guide
1. Pick the surface your team is onboarding (Web console, REST API, CLI, or VS Code).
2. Follow the numbered quickstart to launch your first guided run **and** record at least one action via `amprealize record-action`.
3. Confirm telemetry landed by checking the "Onboarding KPI" section at the end of the quickstart.
4. Log the activity via `amprealize record-action` so the RunService, telemetry pipeline, and audit trail stay aligned.

Each quickstart maps to the Strategist → Teacher → Student workflow:
- **Strategist**: chooses the persona template and retrieves relevant handbook behaviors.
- **Teacher**: explains the plan to stakeholders, citing behaviors and success metrics.
- **Student**: executes the run, captures evidence, and validates telemetry/CI signals.

## Web Console Quickstart
**Goal:** Get a Strategist plan running in the web dashboard and verify telemetry ingestion.

1. Sign in with an approved agent account and open the **Progress Overview** dashboard.
2. Click **Start Guided Run** → choose the "Behavior Adoption" template.
3. Attach the latest behaviors from the handbook search (e.g., `behavior_unify_execution_records`).
4. Launch the run and monitor milestones on the `Timeline` component.
5. When a step completes, use the in-app "Record Action" button to capture the evidence.
6. Open the **Consent & MFA** widget to confirm grant status; approve scopes if prompted.
7. Navigate to **Alignment Updates** and verify the run summary appears with the linked action ID.
8. Capture telemetry:
   - Ensure the dashboard shows a new event in the "Onboarding KPI" sparkline.
   - In the backend (optional), query `GET /v1/analytics/adoption` and verify `surface="web"` incremented.
9. Run the post-action checklist (`amprealize compliance record-step --checklist onboarding-web`).

**Telemetry success:** `analytics.onboarding` event with `surface="web"`, `timeToFirstBehavior` <= 15 minutes, linked `action_id` stored in ActionService.

## REST API Quickstart
**Goal:** Trigger a run and record actions programmatically via REST while keeping telemetry/audit parity.

1. Retrieve an access token via the AgentAuth device flow (`POST /v1/auth/device/start`).
2. Create a run: `POST /v1/runs` with payload `{ "persona": "strategist", "template": "behavior_adoption" }`.
3. Attach behaviors: `POST /v1/runs/{id}/behaviors` with IDs returned from `GET /v1/behaviors?tags=onboarding`.
4. Update run status as milestones complete: `PATCH /v1/runs/{id}/status`.
5. Record an action once a milestone finishes:

```bash
curl -X POST https://api.amprealize.dev/v1/actions \
  -H "Authorization: Bearer $AMPREALIZE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "run_id": "<RUN_ID>",
        "summary": "Enable onboarding telemetry",
        "artifacts": ["docs/ONBOARDING_QUICKSTARTS.md"]
      }'
```

6. Replay (optional) to validate reproducibility: `POST /v1/actions:replay` with the action ID.
7. Confirm telemetry: poll `GET /v1/analytics/onboarding?surface=api`.
8. Log the checklist step: `amprealize compliance record-step --checklist onboarding-api`.

**Telemetry success:** `analytics.onboarding` event with `surface="api"`, replay checksum recorded, compliance checklist step marked complete.

## CLI Quickstart
**Goal:** Use the `amprealize` CLI to run the strategist workflow end-to-end and enforce secret scanning.

1. Install the CLI (`pip install amprealize` or `pipx install amprealize`).
2. Authenticate: `amprealize auth login` and approve required scopes (`actions.write`, `runs.manage`).
3. Bootstrap behaviors locally:

```bash
amprealize behaviors search --tag onboarding --limit 3 > behaviors.json
```

4. Launch a run referencing the behavior set:

```bash
amprealize run start --template behavior_adoption --behaviors behaviors.json --output run.json
```

5. Stream progress:

```bash
amprealize status --run $(jq -r '.run_id' run.json) --watch
```

6. Record an action when you complete a milestone:

```bash
amprealize record-action --artifact docs/ONBOARDING_QUICKSTARTS.md \
  --summary "CLI onboarding complete" \
  --behaviors behavior_update_docs_after_changes behavior_wire_cli_to_orchestrator
```

7. Enforce guardrails before committing changes:

```bash
./scripts/install_hooks.sh
pre-commit run --all-files
```

8. Verify telemetry via the CLI analytics command:

```bash
amprealize analytics metrics --metric onboarding --surface cli
```

9. Complete the compliance checklist step:

```bash
amprealize compliance record-step --checklist onboarding-cli
```

**Telemetry success:** `analytics.onboarding` event with `surface="cli"`, pre-commit secret scan logged, action recorded against run ID.

## VS Code Extension Quickstart (Preview)
**Goal:** Validate IDE parity by running the onboarding flow inside VS Code.

1. Install the Amprealize preview extension (`.vsix` from internal channel).
2. In VS Code, open the **Amprealize** view container and sign in via the device flow panel.
3. From the **Playbooks** tab, select "Behavior Adoption" and insert recommended behaviors.
4. Use the inline plan editor to refine the Strategist plan; cite behaviors in comments for auditability.
5. Click **Start Run** to dispatch the workflow via the MCP transport; watch progress in the sidebar timeline.
6. Use the embedded **Record Action** command (command palette: `Amprealize: Record Action`) when a milestone completes.
7. Confirm the extension emits telemetry (developer tools console logs `analytics.onboarding` event) and that the same event is visible via `amprealize analytics metrics --surface ide`.
8. Run the IDE-specific compliance step: `amprealize compliance record-step --checklist onboarding-ide` (CLI) or the extension equivalent once shipped.
9. File a feedback note via `amprealize agents review --scope dx --artifact docs/ONBOARDING_QUICKSTARTS.md` to capture DX insights.

**Telemetry success:** `analytics.onboarding` event with `surface="ide"`, MCP transport logs stored, feedback action recorded.

## Onboarding KPI Reference
| Surface | KPI Target | Telemetry Signal | Verification Command |
| --- | --- | --- | --- |
| Web | Run launched + action recorded in < 15 minutes | `analytics.onboarding` (`surface="web"`) | `GET /v1/analytics/onboarding?surface=web` |
| REST API | Replay-ready action with checksum match | `analytics.onboarding` (`surface="api"`) | `amprealize analytics metrics --metric onboarding --surface api` |
| CLI | Secret scan + action log before commit | `analytics.onboarding` (`surface="cli"`) | `amprealize analytics metrics --metric onboarding --surface cli` |
| VS Code | MCP run reflection + action log | `analytics.onboarding` (`surface="ide"`) | `amprealize analytics metrics --metric onboarding --surface ide` |

## Next steps
- Keep this guide updated as new onboarding templates ship.
- Attach onboarding telemetry dashboards to the Milestone 1 analytics deliverable.
- Add parity tests ensuring each surface emits the `analytics.onboarding` event before GA.
