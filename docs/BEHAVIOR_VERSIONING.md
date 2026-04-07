# Behavior Versioning & Migration Strategy

## Mission
Guarantee that every behavior change is traceable, reproducible, and backwards-compatible across Web, REST API, CLI, and MCP surfaces. This document supplements the Data Model section of the PRD and the contracts in `contracts/MCP_SERVER_DESIGN.md` and `contracts/ACTION_REGISTRY_SPEC.md`.

## Versioning model
- **Identifier:** `behavior_id` remains immutable (UUID).
- **Version field:** `version` follows `MAJOR.MINOR.PATCH` semantics (`major` promotes breaking prompt/instruction changes, `minor` for additive metadata, `patch` for typo fixes).
- **Status lifecycle:** `draft → in_review → approved → deprecated`. Version bumps always start in `draft` and must pass compliance checks prior to approval.
- **Effective ranges:**
  - Each version carries `effective_from` (timestamp) and optional `effective_to` (null if active).
  - Runs reference `(behavior_id, version)` at execution time; replaying a run rehydrates the exact version.

### When to bump
| Change type | Example | Version increment | Checklist |
| --- | --- | --- | --- |
| Breaking instruction change | Altering validation steps or role guidance | **MAJOR** | Requires Strategist + Compliance approval, replay tests |
| Additive metadata | New trigger keyword, tag, or example | **MINOR** | Requires Strategist review, updated retrieval tests |
| Non-functional fix | Grammar correction, hyperlink update | **PATCH** | Teacher sign-off, smoke test |
| Deprecation | Behavior superseded by another | No increment; set `status=deprecated` with `effective_to` | Notify Strategist + update retrieval index |

## Storage schema
```sql
CREATE TABLE behaviors (
  behavior_id UUID PRIMARY KEY,
  latest_version INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  tags TEXT[] DEFAULT '{}',
  embedding vector(1024)
);

CREATE TABLE behavior_versions (
  behavior_id UUID NOT NULL REFERENCES behaviors(behavior_id),
  version_semver TEXT NOT NULL,
  major SMALLINT NOT NULL,
  minor SMALLINT NOT NULL,
  patch SMALLINT NOT NULL,
  status behavior_status NOT NULL,
  instruction TEXT NOT NULL,
  metadata JSONB DEFAULT '{}',
  effective_from TIMESTAMPTZ NOT NULL,
  effective_to TIMESTAMPTZ,
  approval_action_id UUID,
  created_by UUID NOT NULL,
  PRIMARY KEY (behavior_id, version_semver)
);

CREATE INDEX behavior_versions_active_idx
  ON behavior_versions (behavior_id)
  WHERE status = 'approved' AND effective_to IS NULL;
```

## API & contract updates
- **REST (`GET /v1/behaviors/:id`):** returns `versions[]` with fields above and `latest` pointer.
- **REST (`POST /v1/behaviors`):** accepts optional `base_version` to clone metadata when drafting updates.
- **REST (`PATCH /v1/behaviors/:id`):** only updates `draft` versions; approval endpoint (`POST /v1/behaviors/:id/approve`) transitions to `approved`.
- **CLI (`amprealize behaviors get <id>`):** default output now includes `version`, `status`, and `effective_from`. `--version` flag requests an exact version.
- **MCP (`behaviors.get`):** request schema gains optional `version` field; response includes the same version metadata.
- **Telemetry:** emit `behaviors.version_published` with labels `{behavior_id, version, major_change=<bool>}` and `behaviors.version_deprecated` when `effective_to` set.

## Migration workflow
1. **Draft new version:** Strategist duplicates prior version via `base_version`; run `amprealize behaviors edit` (future command) or REST PATCH.
2. **Unit tests:**
   - Run `pytest tests/test_behavior_versioning.py` (new suite) validating serialization and replay compatibility.
   - Execute retriever regression: `python -m tests.retriever.test_ranker --behaviors behavior_id` (ensures embeddings unaffected when not changed).
3. **Approval:** Teacher + Compliance review; approval logs `approval_action_id` via `amprealize record-action --summary "Approve behavior <id> vX.Y.Z"`.
4. **Data migration:** A simple `INSERT` into `behavior_versions` with bumped semver; `behaviors.latest_version` increments atomically.
5. **Retrieval sync:** Trigger BehaviorService indexer to refresh vector store for updated instructions.
6. **Deprecation:** When replacing a behavior, set `effective_to` on prior version and emit `behaviors.version_deprecated` telemetry. Add alias link pointing to successor behavior.
7. **Rollback:** If regression detected, set `effective_to` on offending version and promote previous version by clearing its `effective_to`.

### Backfill plan
- For legacy records lacking `version`: default to `1.0.0`, log remediation action (`amprealize record-action --summary "Backfill behavior versions"`).
- Replay historical runs to ensure `(behavior_id, version)` references resolve.
- Add migration script `alembic upgrade head` (TBD) to create tables above and populate with existing behaviors.

## Testing & validation
- **Unit:** `tests/test_behavior_versioning.py` (to be added) covers serialization, lifecycle transitions, and invalid state guards.
- **Integration:** Extend `tests/test_action_service_parity.py` to ensure behavior version metadata is exposed identically via REST, CLI, MCP.
- **UI smoke:** Add Playwright scenario verifying version dropdown in behavior detail view.
- **Data quality:** SQL check ensuring only one `approved` version lacks `effective_to` per behavior.

## Deployment considerations
- Version schema must deploy before clients expecting the new fields. Sequence: run migrations → deploy BehaviorService → update CLI/SDK → update web/IDE.
- Feature flag `behavior.versioning` gates UI display until migrations verified.
- Telemetry dashboards should graph version churn and recall rates (versions referenced/run).

## Governance & documentation
- Update `AGENTS.md` when new workflows emerge (e.g., behavior editing playbooks).
- Record action IDs for migrations in `BUILD_TIMELINE.md` and `PRD_ALIGNMENT_LOG.md`.
- Compliance requires retaining deprecated versions for ≥ 1 year; do not delete records without legal sign-off.

## Open questions
- Should we allow semantic version skipping (e.g., jump from 1.0.0 to 2.0.0)? Default policy: no gaps.
- Do we automatically archive embeddings for deprecated versions? TBD (track in retriever backlog).
- Should Strategist or Teacher own version bump request templates? Pending DX decision.
