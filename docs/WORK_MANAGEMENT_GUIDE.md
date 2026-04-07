# WORK_MANAGEMENT_GUIDE.md

This document defines how AI agents use the Amprealize platform to plan and manage the development of Amprealize itself.

> **Last validated**: 2026-03-10 against local Amprealize dev instance.

## 1. Purpose
- Make Amprealize platform development work tracking deterministic and replayable.
- Standardize backlog seeding and day-to-day execution for agents working on Amprealize.
- Ensure all non-trivial implementation work is visible in Amprealize's own project tracking.
- Dogfood the platform: Amprealize tracks its own development, exposing real bugs and UX gaps.

## 2. Required Rules
- Use only `goal`, `feature`, and `task` item types (previously called `epic` and `story`).
- The `bug` type is also available for defect tracking.
- All implementation work must be tracked in Amprealize, except trivial fixes under 30 minutes.
- If a trivial fix exceeds 30 minutes, create a Amprealize item immediately.
- Platform bugs discovered during development must be tracked as items on the Amprealize Platform Issues board (see §3.1).
- Reference `AGENTS.md` behaviors in all work — cite `behavior_<name>` and your declared role.
-If you find a bug/issue with the Amprealize platform itself, check if it’s already tracked on the Amprealize Board. If not, create a new work item with the appropriate labels and metadata.- Follow GWS v1.0 naming conventions (see §2.1 below).

### 2.1 GWS v1.0 — Work Item Naming Standard

All work item titles must follow the Amprealize Work Item Standard (GWS):

- **Uppercase start**: Titles begin with a capital letter
- **Imperative verb phrases**: "Add X", "Implement Y", "Fix Z"
- **5-120 characters**: Letters, numbers, spaces, basic punctuation
- **Hierarchy**: goal → feature → task/bug (set `parent_id` accordingly)
- **Sizing**: Use `points` (not `story_points`)
- **Depth levels**: `goal_only` | `goal_and_features` | `full`

**Forbidden patterns** (enforced by MCP and REST API):
| Pattern | Example | Use Instead |
|---------|---------|-------------|
| Phase/Sprint/Track numbering | "Phase 1: Work Items" | `labels: ["phase:1"]` |
| Type-number prefix | "EPIC-001 Foo" | system-assigned IDs |
| Manual numbering | "1. Do X" | `position` field |
| Status prefix | "TODO: Fix Y" | `status` field |

**Source**: `amprealize/agents/work_item_planner/prompts.py` (single source of truth)
**Behavior**: `behavior_standardize_work_items` in `AGENTS.md`
**Skill**: `skills/work-item-planner/SKILL.md`
## 3. Canonical Names for Amprealize Tracking

### 3.1 Amprealize Platform Development
- Project name: `Amprealize` / slug: `amprealize`
- Project ID (current): `proj-b575d734aa37`
- Board name: `Amprealize Board`
- Board ID (current): `523b3a4f-4157-4fd1-b5e9-93437eca6009`
- Owner: `nick.sanders.a@gmail.com` (user ID `112316240869466547718`)

> **⚠️ Volatile IDs**: Board IDs, container names, and other infrastructure identifiers **change after every `breakeramp fresh` run**. The IDs listed in this document are examples from the last validated run. Before any operation that uses a board ID or container name, agents **must** resolve the current values dynamically:
> - **Board IDs**: Query `board.boards` via `podman exec <db-container> psql ...` or use `GET /api/v1/boards?project_id=<id>`.
> - **Container names**: Run `podman ps --format '{{.Names}}' | grep <service>` to find the current BreakerAmp-prefixed name.
> - **Project IDs**: These are stable across `breakeramp fresh` runs (stored in PostgreSQL). Use `GET /api/v1/projects` or `mcp_amprealize_projects_list`.
>
> Never hardcode container names or board IDs in scripts — always resolve them at runtime.

### 3.2 Relationship to WORK_STRUCTURE.md
`WORK_STRUCTURE.md` is the definitive goal/feature/task inventory for the Amprealize platform (14 goals, 150+ features). When creating work items in Amprealize, reference the corresponding goal/feature numbers from `WORK_STRUCTURE.md` in the `metadata.seed_key` field (e.g., `"seed_key": "E8"` for Goal 8: Infrastructure & Staging Readiness). Note: `WORK_STRUCTURE.md` may still use "Epic" labels — these map to the `goal` work item type.

### 3.3 Relationship to BUILD_TIMELINE.md
`BUILD_TIMELINE.md` is the chronological audit log of completed work (170+ entries). After completing any work item, add an entry to `BUILD_TIMELINE.md` documenting what was done, files modified, and test results.

## 4. Surface Priority (Strict Order)

### 4.1 MCP-first (Preferred)
Amprealize MCP tools work natively in VS Code Copilot Chat. **Always prefer MCP tools when available.**

```
# List projects
mcp_amprealize_projects_list

# Get behaviors for a task
mcp_amprealize_behaviors_getfortask(task_description="...", role="Student")

# Create work items
mcp_amprealize_workitems_create(item_type="task", project_id="proj-b575d734aa37", title="...")

# List work items
mcp_amprealize_workitems_list(project_id="proj-b575d734aa37")
```

### 4.2 API (Fallback)
Use the REST API when MCP tools are unavailable or need fine-grained control.

### 4.3 CLI/Script (Fallback)
Use CLI or scripts when API calls need retry logic, state caching, or batch operations.

### 4.4 UI (Last Resort)
Use the web console UI only when all programmatic paths are blocked.

## 5. Infrastructure and Runtime Preflight

### 5.1 Container Runtime
Amprealize runs on **Podman** (not Docker). The Podman VM is named `amprealize-dev`.

All infrastructure is managed through the **BreakerAmp** standalone package (`packages/breakeramp/`). BreakerAmp provides a Terraform-like workflow (`plan → apply → destroy`) for containerized environments.

> **⚠️ Container names are volatile.** Every `breakeramp fresh` run generates a new UUID prefix (e.g., `amp-845682e9-...`). Always discover current names with:
> ```bash
> podman ps --format '{{.Names}}' | sort
> ```

#### Starting the environment
Use BreakerAmp CLI commands instead of manual `podman start` chains:

```bash
# Bring up the full development environment (plan + apply in one step)
breakeramp up

# Or with a specific blueprint
breakeramp up development -b local-test-suite
```

#### After a machine reboot
```bash
# Restart all containers in the most recent environment
breakeramp restart --all

# Or restart only unhealthy containers (default)
breakeramp restart
```

#### Full environment rebuild (clean slate)

> **Auto-backup**: Both `nuke` and `fresh` automatically back up all running PostgreSQL databases before destroying anything. Backups are saved to `~/.amprealize/backups/` with the tag `pre-nuke`. The last 5 auto-backups are kept. Use `--skip-backup` to opt out.

```bash
# Nuke everything and bring up fresh (nuke + up combined)
breakeramp fresh

# With volume cleanup (WARNING: data loss — but databases are auto-backed-up first)
breakeramp fresh -v

# Skip confirmation prompt
breakeramp fresh --force

# Skip the automatic pre-destruction database backup
breakeramp fresh --skip-backup
```

The API container reinstalls Python dependencies on startup. This can take 30–60 seconds. Poll the health endpoint before proceeding.

### 5.2 Health Checks

> **Canonical entry point**: all client traffic should go through the gateway on `:8080` (HTTP) or `:8443` (HTTPS). Direct service ports (`:8000` API, `:5173` web console) are available in dev but non-canonical.

```bash
# Gateway (reverse proxy) — canonical entry point
curl -sS -m 5 http://localhost:8080/health

# API (direct, non-canonical in production)
curl -sS -m 5 http://localhost:8000/health
```

Wait until both return HTTP 200 before making API calls. The gateway may return 502 while the API is still starting.

### 5.3 Database Access
Direct PostgreSQL access for debugging and workarounds:
```bash
podman exec amp-845682e9-f6ad-49a7-80e5-bb29b2155cdf-amprealize-db \
  psql -U amprealize -d amprealize -c "<SQL>"
```

- **User**: `amprealize`
- **Password**: `amprealize_dev`
- **Database**: `amprealize`
- **Schemas**: `auth`, `board`, `execution`, `behavior`, `workflow`, `consent`, `audit`, `credentials`

Key tables:
- `auth.projects` — PK is `project_id` (varchar), has `owner_id` FK
- `auth.users` — PK is `id` (varchar)
- `board.boards` — PK is `id` (uuid), has `board_id` in API responses
- `board.work_items` — PK is `id` (uuid), has `item_id` in API responses, `parent_id` for hierarchy
- `behavior.behaviors` — PK is `id`, stores the behavior handbook entries
- `execution.runs` — PK is `run_id`, tracks agent execution runs
- `auth.device_sessions` — PK is `device_code`, stores OAuth device flow sessions

### 5.4 Alembic Migrations
Amprealize uses three isolated Alembic environments:

```bash
# Main amprealize database
alembic upgrade head

# Workflow database
alembic -c alembic.workflow.ini upgrade head

# Telemetry database (TimescaleDB)
alembic -c alembic.telemetry.ini upgrade head
```

Verify migration state with:
```bash
alembic heads    # Must show exactly ONE head
alembic current  # Shows current revision
```

> **Note**: BreakerAmp can run migrations automatically on `breakeramp apply` when `migrations.auto_run: true` is set in `environments.yaml` (see §5.5).

Refer to `docs/MIGRATION_GUIDE.md` and `behavior_migrate_postgres_schema` for migration procedures.

### 5.5 BreakerAmp Environment Management

BreakerAmp is a standalone package (`packages/breakeramp/`) that provides blueprint-driven container orchestration for Amprealize infrastructure. It is the **primary tool** for managing the local development stack.

#### Installation
```bash
# Install with CLI support (from repo root)
pip install -e ./packages/breakeramp[cli]

# Verify installation
breakeramp version
```

#### Configuration
BreakerAmp reads environment definitions from `environments.yaml` at the project root. This file defines:
- **Runtime config**: Podman machine name, resource limits, auto-start behavior
- **Infrastructure config**: Blueprint ID, teardown policy
- **Migrations**: Alembic configs to auto-run after containers are healthy
- **Variables**: Environment variables passed to containers (DB DSNs, ports, OAuth credentials)

Validate your configuration:
```bash
breakeramp validate environments.yaml
```

#### Blueprints
Blueprints define the services in each environment. They live in `packages/breakeramp/src/breakeramp/blueprints/`.

| Blueprint | Purpose |
|---|---|
| `local-test-suite` | Full local dev stack (DB, Redis, API, gateway, web-console, workers) |
| `core-data-plane` | Core data stores only (PostgreSQL, TimescaleDB, Redis) |
| `ci-test-stack` | Minimal stack for CI pipelines |
| `test-aware-stack` | Stack with test analysis capabilities |
| `agent-workspace` | Isolated agent execution workspace |
| `streaming-simple` | Kafka streaming (minimal) |
| `staging` | Staging environment configuration |
| `production` | Production environment configuration |

The default blueprint for development is `local-test-suite`, which includes these modules:
- **core**: PostgreSQL (schema-routed), TimescaleDB, Redis
- **console**: Amprealize API, gateway (nginx), web-console
- **agents**: Execution workers, Podman socket proxy

#### CLI Quick Reference

| Command | Description |
|---|---|
| `breakeramp up` | Plan + apply in one step (idempotent; reuses existing env) |
| `breakeramp plan <env>` | Preview resource requirements before provisioning |
| `breakeramp apply --plan-id <id>` | Provision the planned environment |
| `breakeramp status [<run-id>]` | Check status and health of running environment |
| `breakeramp restart [--all]` | Restart containers (unhealthy only, or all) |
| `breakeramp stop` | Stop containers without removing them |
| `breakeramp destroy <run-id>` | Tear down a specific environment |
| `breakeramp fresh` | Nuke everything + bring up clean environment |
| `breakeramp nuke` | Remove all containers, networks, processes |
| `breakeramp list` | List all tracked environments |
| `breakeramp blueprints` | List available blueprints |
| `breakeramp validate [<path>]` | Validate environments.yaml configuration |
| `breakeramp resources` | Show resource usage of running environment |
| `breakeramp cleanup` | Clean up stale/orphaned resources |
| `breakeramp backup [--tag TAG]` | Back up all running PostgreSQL databases to `~/.amprealize/backups/` |
| `breakeramp restore [BACKUP_NAME]` | Restore databases from a backup (latest if omitted) |
| `breakeramp backups` | List all available database backups |
| `breakeramp plan-for-tests` | Plan an environment optimized for test runs |
| `breakeramp run-tests` | Run tests in an BreakerAmp-managed environment |

#### Common Workflows

**First-time setup:**
```bash
pip install -e ./packages/breakeramp[cli]
breakeramp up
# Wait for health checks to pass, then verify:
curl -sS -m 5 http://localhost:8080/health
curl -sS -m 5 http://localhost:8000/health
```

**Day-to-day development:**
```bash
breakeramp restart          # Restart unhealthy containers after reboot
breakeramp status           # Check what's running and health status
breakeramp resources        # Monitor resource usage
```

**Debugging infra issues:**
```bash
breakeramp status           # See which containers are unhealthy
breakeramp restart -s amprealize-api  # Restart specific service
breakeramp fresh            # Nuclear option: rebuild everything
```

**Database backup & restore:**
```bash
breakeramp backup                     # Back up all DBs (tag: "manual")
breakeramp backup --tag before-migration  # Back up with a custom tag
breakeramp backups                    # List all saved backups
breakeramp restore                    # Restore from the latest backup
breakeramp restore 2026-03-11T10-03-14  # Restore a specific backup
```

**Running tests with BreakerAmp:**
```bash
./scripts/run_tests.sh --breakeramp  # Uses breakeramp to manage test infra
breakeramp run-tests                  # Or use CLI directly
```

#### Volatile IDs and Dynamic Resolution
BreakerAmp generates UUID-prefixed container names on each `fresh` or `up --force` run. **Never hardcode container names or board IDs in scripts.** Always resolve dynamically:

```bash
# Discover current container names
podman ps --format '{{.Names}}' | sort

# Get the DB container name
DB_CONTAINER=$(podman ps --format '{{.Names}}' | grep amprealize-db)

# Use breakeramp status for structured info
breakeramp status --json
```

## 6. Authentication

### 6.1 Working Auth Method: Device Authorization Flow
This is the **only reliable auth method** in the current build. Service Principal tokens are broken (see §14).

Three-step flow:
```bash
# Step 1: Request device code
curl -X POST http://localhost:8080/api/v1/auth/device/authorize \
  -H "Content-Type: application/json" \
  -d '{"client_id": "amprealize-agent-cli", "scopes": ["read", "write"]}'
# Returns: {"device_code": "...", "user_code": "XXXX-YYYY", ...}

# Step 2: Approve (self-approve for local dev)
curl -X POST http://localhost:8080/api/v1/auth/device/approve \
  -H "Content-Type: application/json" \
  -d '{"user_code": "XXXX-YYYY", "approver": "amprealize-agent"}'

# Step 3: Exchange for access token
curl -X POST http://localhost:8080/api/v1/auth/device/token \
  -H "Content-Type: application/json" \
  -d '{"device_code": "...", "client_id": "amprealize-agent-cli"}'
# Returns: {"access_token": "ga_...", "scope": "read write", ...}
```

Use the token in all subsequent requests:
```bash
curl -H "Authorization: Bearer ga_..." -H "Content-Type: application/json" \
  http://localhost:8080/api/v1/projects
```

Token TTL is approximately 1 hour. Scripts should re-authenticate each run.

### 6.2 MCP Device Authorization
MCP tools can also initiate device auth:
```
mcp_amprealize_auth_deviceinit(client_id="amprealize-agent-mcp", scopes=["read", "write"])
mcp_amprealize_auth_devicepoll(device_code="...", client_id="amprealize-agent-mcp")
```

### 6.3 Broken Auth Method: Service Principal (DO NOT USE)
`POST /api/v1/auth/sp/token` returns a valid-looking `ga_` token, but this token is rejected with 401 on all non-auth endpoints. This is a known platform bug tracked as GS2.1 on the Amprealize Platform Issues board.

## 7. API Reference (Actual Behavior)

### 7.1 Important: Response Envelope Inconsistency
**Different endpoints use different response wrappers.** This is a known platform issue (GS3.2). Always handle both wrapped and unwrapped formats defensively.

| Endpoint | Create Response | List Response | ID Field |
|---|---|---|---|
| Projects | `{"id": "proj-..."}` (flat) | `{"items": [...]}` | `id` |
| Boards | `{"board": {"board_id": "..."}}` | `{"boards": [...]}` | `board_id` |
| Work Items | `{"item": {"item_id": "..."}}` | `{"items": [...]}` | `item_id` |

Defensive parsing pattern:
```python
# For boards
resp = api("POST", "/api/v1/boards", payload, headers)
board = resp.get("board", resp)
bid = board.get("board_id", board.get("id"))

# For work items
resp = api("POST", "/api/v1/work-items", payload, headers)
item = resp.get("item", resp)
iid = item.get("item_id", item.get("id"))
```

### 7.2 Endpoints

#### Projects
- `POST /api/v1/projects` — Create project
- `GET /api/v1/projects` — List projects (may not show projects from other auth sessions)
- `GET /api/v1/projects/<project_id>` — Get project by ID

#### Boards
- `POST /api/v1/boards` — Create board (set `create_default_columns: true` for default columns)
- `GET /api/v1/boards?project_id=<id>` — List boards for project
- `GET /api/v1/boards/<board_id>` — Get board by ID
- `PATCH /api/v1/boards/<board_id>` — Update board
- `DELETE /api/v1/boards/<board_id>` — Delete board

#### Work Items
- `POST /api/v1/work-items` — Create work item
- `GET /api/v1/work-items?board_id=<id>&limit=<n>` — List work items (supports filters: `project_id`, `board_id`, `item_type`, `parent_id`, `status`, `assignee_id`, `labels`, `limit`, `offset`)
- `GET /api/v1/work-items/<item_id>` — Get work item by ID
- `PATCH /api/v1/work-items/<item_id>` — Update work item
- `POST /api/v1/work-items/<item_id>/move` — Move work item to column
- `DELETE /api/v1/work-items/<item_id>` — Delete work item

#### Behaviors
- `GET /api/v1/behaviors` — List behaviors
- `POST /api/v1/behaviors` — Create behavior
- `POST /api/v1/behaviors:search` — Search behaviors
- `GET /api/v1/behaviors/<behavior_id>` — Get behavior by ID
- `POST /api/v1/behaviors/<behavior_id>:approve` — Approve behavior
- `POST /api/v1/behaviors/<behavior_id>:deprecate` — Deprecate behavior

#### Agents
- `GET /api/v1/agents` — List agents
- `POST /api/v1/agents` — Create agent
- `GET /api/v1/agents/<agent_id>` — Get agent by ID
- `POST /api/v1/agents/<agent_id>:publish` — Publish agent
- `POST /api/v1/agents/<agent_id>:deprecate` — Deprecate agent

#### Actions
- `POST /api/v1/actions` — Record action
- `GET /api/v1/actions` — List actions
- `GET /api/v1/actions/<action_id>` — Get action by ID
- `POST /api/v1/actions:replay` — Replay an action

### 7.3 Create Project
```json
{
  "name": "Amprealize",
  "slug": "amprealize",
  "description": "Amprealize Metacognitive Behavior Handbook Platform",
  "visibility": "private"
}
```

### 7.4 Create Board
```json
{
  "project_id": "proj-b575d734aa37",
  "name": "Amprealize Platform Issues",
  "description": "Platform development and issue tracking",
  "create_default_columns": true
}
```

### 7.5 Create Work Items

`goal` (previously called `epic`; maps to WORK_STRUCTURE.md epics):
```json
{
  "item_type": "goal",
  "project_id": "proj-b575d734aa37",
  "board_id": "523b3a4f-4157-4fd1-b5e9-93437eca6009",
  "title": "Infrastructure & Staging Readiness",
  "description": "Complete infrastructure hardening for staging deployment",
  "priority": "high",
  "labels": ["amprealize", "platform", "infrastructure"],
  "metadata": {
    "seed_source": "amprealize-platform-v1",
    "seed_key": "E8",
    "seed_version": "2026-02-09",
    "work_structure_ref": "Epic 8"
  }
}
```

`feature` (previously called `story`; with parent):
```json
{
  "item_type": "feature",
  "project_id": "proj-b575d734aa37",
  "board_id": "523b3a4f-4157-4fd1-b5e9-93437eca6009",
  "parent_id": "<goal_item_id>",
  "title": "Fix Service Principal token validation",
  "description": "SP tokens from POST /api/v1/auth/sp/token are rejected with 401 on non-auth endpoints",
  "priority": "high",
  "labels": ["amprealize", "platform", "auth", "bug"],
  "metadata": {
    "seed_source": "amprealize-platform-v1",
    "seed_key": "GS2.1",
    "seed_version": "2026-02-09",
    "bug_id": "GS2.1"
  }
}
```

`task` (with parent):
```json
{
  "item_type": "task",
  "project_id": "proj-b575d734aa37",
  "board_id": "523b3a4f-4157-4fd1-b5e9-93437eca6009",
  "parent_id": "<feature_item_id>",
  "title": "Debug SP token middleware in api.py to find 401 root cause",
  "description": "Trace the token validation path for SP tokens and fix the rejection logic",
  "priority": "medium",
  "labels": ["amprealize", "platform", "auth"],
  "metadata": {
    "seed_source": "amprealize-platform-v1",
    "seed_key": "GS2.1-T1",
    "seed_version": "2026-02-09"
  }
}
```

## 8. MCP Tools for Self-Management

Amprealize MCP tools are available directly in VS Code Copilot Chat. Key tools for platform self-management:

### 8.1 Work Item Management
| Tool | Purpose |
|------|---------|
| `mcp_amprealize_workitems_create` | Create goals, features, tasks |
| `mcp_amprealize_workitems_list` | List and filter work items |
| `mcp_amprealize_workitems_execute` | Execute a work item via GEP |
| `mcp_amprealize_workitem_executewithtracking` | Execute with progress tracking |

### 8.2 Behavior Management
| Tool | Purpose |
|------|---------|
| `mcp_amprealize_behaviors_getfortask` | Retrieve behaviors before starting any task |
| `mcp_amprealize_behaviors_list` | List all behaviors in the handbook |
| `mcp_amprealize_behaviors_create` | Create a new behavior draft |
| `mcp_amprealize_behavior_analyzeandretrieve` | Analyze task and retrieve behaviors + recommendations |

### 8.3 Project & Compliance
| Tool | Purpose |
|------|---------|
| `mcp_amprealize_context_getcontext` | Get current tenant context and auth state |
| `mcp_amprealize_compliance_fullvalidation` | Validate compliance policies and audit trail |
| `mcp_amprealize_project_setupcomplete` | Set up a complete project with board |

## 9. Idempotent Seeding Rules
- Resolve project and board by name/slug before create.
- Use `metadata.seed_key` + `metadata.seed_version` to detect duplicate seeds.
- Re-runs must update or skip existing items; never create duplicate hierarchy.
- Use a local state cache file (e.g., `.amprealize_seed_state.json`) to track created IDs across runs, since device auth sessions may not share project list visibility.

## 10. Ongoing Agent Workflow

### 10.1 Before Starting Any Task
1. Retrieve behaviors: `mcp_amprealize_behaviors_getfortask(task_description="...", role="Student")`
2. Declare your role per `AGENTS.md` Role Declaration Protocol.
3. Select or create a Amprealize work item for the task.

### 10.2 During Execution
1. Set item to `in_progress` at start.
2. Keep item notes current with implementation evidence.
3. Cite behaviors and role in all work output: `Following behavior_xyz (Student): ...`
4. Run the smallest relevant automated check after each change (`pytest`, `npm run build`, lint).
5. Record command and outcome.

### 10.3 Completing Work
1. Move item to `in_review` when tests and docs are ready.
2. Move to `done` only when code, tests, docs, and acceptance checks are complete.
3. Add entry to `BUILD_TIMELINE.md` documenting the work.
4. Update `WORK_STRUCTURE.md` if goal/feature status changed.
5. If pattern repeated 3+ times, escalate to Strategist for behavior proposal.

### 10.4 Testing & Validation
```bash
# Run unit tests (no infrastructure required)
pytest -q tests/unit

# Run full test suite (requires Podman containers)
./scripts/run_tests.sh

# Run with BreakerAmp-managed environment
./scripts/run_tests.sh --breakeramp

# Plan and run tests via BreakerAmp CLI directly
breakeramp plan-for-tests
breakeramp run-tests

# Compile VS Code extension
cd extension && npm run compile

# Run pre-commit hooks
pre-commit run --all-files
```

## 11. CLI/Script Fallback
When MCP and API paths are blocked, use CLI commands:

```bash
# Behavior retrieval
amprealize behaviors get-for-task "describe your task" --role Student

# List behaviors
amprealize behaviors list

# Create a behavior draft
amprealize behaviors create --name behavior_xyz --description "..." --instruction "..."
```

## 12. UI Fallback
Use Web Console UI only when API, MCP, and CLI paths are blocked.

UI paths (default: `http://localhost:5173`):
- `/projects/new` for project creation
- Project page for board creation
- Board page for goal/feature/task creation

After UI fallback:
- Run the same verification checks (counts, hierarchy, status).
- Backfill seed metadata where supported.

## 13. Handling Platform Bugs Discovered During Development
Since Amprealize tracks its own development, platform bugs are first-class work items:

1. Check if bug already exists on the Amprealize Board (`board_id: 523b3a4f-4157-4fd1-b5e9-93437eca6009` — resolve dynamically, see §3.1).
2. If not, create a feature (previously called story) with `labels: ["amprealize", "platform", "bug"]` and a `metadata.bug_id` field (e.g., `GS4.1`).
3. Include repro steps, expected behavior, observed behavior, and workaround status in the description.
4. If the bug blocks current work, add the workaround to §14 of this document.
5. When the bug is fixed, update the work item to `done` and note in §14 that the workaround is no longer needed.

If Amprealize cannot self-track (e.g., API is completely down):
- Document blockers in this file as temporary fallback.
- Backfill Amprealize items after platform recovery.

## 14. Known Platform Bugs and Workarounds (as of 2026-03-10)
These are tracked on the Amprealize Board. Agents **must** apply these workarounds until the bugs are fixed.

### 14.1 Project Creation Does Not Persist to `auth.projects` (GS1.1)
**Bug**: `POST /api/v1/projects` returns 201 but does not write to `auth.projects` in PostgreSQL. Boards and work items that FK-reference the project will fail.

**Workaround**: After creating a project via API, insert the row directly:
```bash
# Resolve current DB container name first:
# DB_CONTAINER=$(podman ps --format '{{.Names}}' | grep amprealize-db)
podman exec $DB_CONTAINER \
  psql -U amprealize -d amprealize -c \
  "INSERT INTO auth.projects (project_id, name, slug, description, visibility, created_by, owner_id)
   VALUES ('<project_id>', '<name>', '<slug>', '<desc>', 'private', '<user_id>', '<user_id>')
   ON CONFLICT (project_id) DO NOTHING;"
```
Note: `auth.projects` has a check constraint requiring either `org_id` or `owner_id` to be non-null.

### 14.2 Missing `parent_id` Column on `board.work_items` (GS1.2)
**Bug**: The API accepts `parent_id` in work item payloads but the DB migration did not create the column.

**Workaround**: Add the column manually (only needed once):
```bash
DB_CONTAINER=$(podman ps --format '{{.Names}}' | grep amprealize-db)
podman exec $DB_CONTAINER \
  psql -U amprealize -d amprealize -c \
  "ALTER TABLE board.work_items ADD COLUMN IF NOT EXISTS parent_id uuid
   REFERENCES board.work_items(id) ON DELETE SET NULL;"
```

### 14.3 Missing Default Users in `auth.users` (GS1.3)
**Bug**: Board creation sets `created_by = 'anonymous'` but no such user exists, causing FK violations.

**Workaround**: Insert default users (only needed once):
```bash
DB_CONTAINER=$(podman ps --format '{{.Names}}' | grep amprealize-db)
podman exec $DB_CONTAINER \
  psql -U amprealize -d amprealize -c \
  "INSERT INTO auth.users (id, email, display_name, auth_provider)
   VALUES ('anonymous', 'anonymous@system', 'Anonymous', 'system'),
          ('amprealize-agent', 'amprealize-agent@system', 'Amprealize Agent', 'system')
   ON CONFLICT (id) DO NOTHING;"
```

### 14.4 Service Principal Tokens Rejected on Non-Auth Endpoints (GS2.1)
**Bug**: Tokens from `POST /api/v1/auth/sp/token` return 401 on projects, boards, and work-items endpoints.

**Workaround**: Use the device authorization flow exclusively (see §6.1).

### 14.5 Board Service Returns 503 on FK Failures (GS3.1)
**Bug**: When a board creation fails due to FK constraint violation, the service returns HTTP 503 with no error body.

**Workaround**: Ensure the project row exists in `auth.projects` (§14.1) and default users exist (§14.3) before creating boards.

### 14.6 Inconsistent Response Envelopes (GS3.2)
**Bug**: Projects return flat `{"id": ...}`, boards wrap in `{"board": {"board_id": ...}}`, work items wrap in `{"item": {"item_id": ...}}`.

**Workaround**: Use defensive parsing that handles both wrapped and unwrapped formats (see §7.1).

## 15. Verification
After any seed run or batch of work item operations, verify counts directly in the database:
```bash
DB_CONTAINER=$(podman ps --format '{{.Names}}' | grep amprealize-db)
podman exec $DB_CONTAINER \
  psql -U amprealize -d amprealize -c \
  "SELECT item_type, count(*) FROM board.work_items
   WHERE metadata->>'seed_source' = 'amprealize-platform-v1'
   GROUP BY item_type ORDER BY item_type;"
```

For verifying work item hierarchy:
```bash
podman exec $DB_CONTAINER \
  psql -U amprealize -d amprealize -c \
  "SELECT wi.item_type, wi.title, wi.status, p.title AS parent_title
   FROM board.work_items wi
   LEFT JOIN board.work_items p ON wi.parent_id = p.id
   WHERE wi.metadata->>'seed_source' = 'amprealize-platform-v1'
   ORDER BY wi.item_type, wi.title;"
```

## 16. Key Source Files

### Platform Core
| File | Purpose |
|------|---------|
| `amprealize/api.py` | FastAPI application with all REST endpoints |
| `amprealize/mcp_server.py` | MCP server (220 tools) |
| `amprealize/services/board_api_v2.py` | Board and work item REST routes |
| `amprealize/projects_api.py` | Project REST routes |
| `amprealize/behavior_service.py` | Behavior CRUD and lifecycle |
| `amprealize/bci_service.py` | Behavior-Conditioned Inference |
| `amprealize/run_service.py` | Run orchestration |
| `amprealize/task_cycle_service.py` | GEP 8-phase execution |
| `amprealize/work_item_execution_service.py` | Work item execution wiring |

### Auth
| File | Purpose |
|------|---------|
| `amprealize/auth/` | Auth services directory |
| `amprealize/auth/postgres_device_flow.py` | PostgreSQL-backed device flow |
| `amprealize/auth/consent_service.py` | JIT consent service |
| `amprealize/auth/user_service_postgres.py` | User management |

### Infrastructure
| File | Purpose |
|------|---------|
| `environments.yaml` | BreakerAmp environment configuration (runtime, blueprints, migrations, variables) |
| `alembic.ini` | Main database migration config |
| `migrations/versions/` | Alembic migration scripts |
| `packages/breakeramp/` | Standalone container orchestration package (plan/apply/destroy workflow) |
| `packages/breakeramp/src/breakeramp/cli.py` | BreakerAmp CLI (21 commands: up, fresh, nuke, backup, restore, backups, plan, apply, status, etc.) |
| `packages/breakeramp/src/breakeramp/backup.py` | Database backup/restore via `pg_dump`/`psql` in containers |
| `packages/breakeramp/src/breakeramp/blueprints/` | Blueprint YAML definitions (local-test-suite, core-data-plane, ci-test-stack, etc.) |
| `packages/breakeramp/src/breakeramp/service.py` | BreakerAmpService core (plan/apply/destroy orchestration) |
| `packages/breakeramp/src/breakeramp/executors/` | Container runtime executors (PodmanExecutor) |
| `packages/breakeramp/src/breakeramp/hooks.py` | BreakerAmpHooks for ActionService/ComplianceService integration |
| `packages/raze/` | Structured logging package |

### Extension
| File | Purpose |
|------|---------|
| `extension/src/extension.ts` | VS Code extension entry point |
| `extension/src/client/McpClient.ts` | MCP client for extension |
| `extension/src/client/RazeClient.ts` | Raze logging client |

### Documentation
| File | Purpose |
|------|---------|
| `AGENTS.md` | Agent behavior handbook (33 behaviors) |
| `WORK_STRUCTURE.md` | Full goal/feature/task inventory |
| `BUILD_TIMELINE.md` | Chronological audit log |
| `PRD.md` | Product requirements document |
| `contracts/MCP_SERVER_DESIGN.md` | MCP server architecture |
| `docs/MIGRATION_GUIDE.md` | Database migration procedures |
| `docs/TESTING_GUIDE.md` | Testing strategy and procedures |

## 17. Source Documents
- `AGENTS.md` — Behavior handbook and agent roles
- `WORK_STRUCTURE.md` — Full platform work inventory (14 goals)
- `BUILD_TIMELINE.md` — Chronological build audit log
- `PRD.md` — Product requirements
- `contracts/MCP_SERVER_DESIGN.md` — MCP server architecture (220 tools)
- `environments.yaml` — BreakerAmp environment configuration
- `packages/breakeramp/README.md` — BreakerAmp standalone package documentation
- `packages/breakeramp/src/breakeramp/blueprints/local-test-suite.yaml` — Development blueprint
- `docs/MIGRATION_GUIDE.md` — Database migration procedures
- `docs/TESTING_GUIDE.md` — Testing strategy
- `.github/copilot-instructions.md` — Copilot quick triggers
