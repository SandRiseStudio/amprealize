# Pytest “not yet implemented” and parity-gap inventory

**Purpose:** Track product work behind intentional skips (not env/enterprise/load).
**Board goal:** **guideai-1182** — *Close pytest not-yet-implemented gaps across surfaces* (GuideAI project `proj-b575d734aa37`, GuideAI Board).
**Child features (remaining gaps):** **guideai-1183**–**guideai-1188** (see Cross-surface / Enterprise / Runtime tables below).
**Canonical tables + MCP recipe:** this file.
**Last reviewed:** 2026-04-30

## Create the GuideAI goal via Amprealize MCP (recommended)

Tool names are the MCP identifiers (e.g. `auth_devicelogin`, `workitems_create`).

1. **`auth_authstatus`** — If `needs_login` is true, continue.
2. **`auth_devicelogin`** — Typical arguments:
   - `client_id`: `"amprealize-mcp-client"` (or the client your workspace uses)
   - `scopes`: `["read", "write"]` (expand if your tenant requires board/work-item scopes)
   - `store_tokens`: `true`
   - `wait_for_authorization`: `true` and `timeout`: `300` so the tool blocks until approval completes (Amprealize agent environments often auto-approve after the tool call).
   - If `wait_for_authorization` is false, call **`auth_devicepoll`** with the returned `device_code` until the flow completes.
3. **`projects_list`** — Find the **GuideAI** project and copy its **`project_id`** (UUID-style id, not only the slug).
4. **`boards_list`** — Pass that `project_id`; copy the **`board_id`** for the board where the goal should live.
5. **`workitems_create`** — Create one **goal** (GWS title: imperative phrase). Example fields:

| Field | Value |
|--------|--------|
| `item_type` | `goal` |
| `project_id` | From step 3 |
| `board_id` | From step 4 (optional if your server infers a default board) |
| `title` | `Close pytest not-yet-implemented gaps across surfaces` |
| `description` | Paste the **markdown body of this file** (stays under the 10k MCP limit) |
| `priority` | `high` |
| `labels` | `["skip-backlog", "parity", "pytest", "guideai"]` |

If device login returns **`invalid_device_code`** on poll, the MCP server’s auth base URL and the **`verification_uri`** host are usually mismatched, or the code expired—fix MCP/API alignment, then retry `auth_devicelogin`.

## Cross-surface parity — adapters missing

| Area | Location | Skip / condition | Board tracking |
|------|-----------|------------------|----------------|
| ~~Agent registry CLI + MCP~~ | `tests/test_agent_registry_parity.py` | ~~Module-level import skip~~ — **implemented** (`CLIAgentRegistryAdapter`, `MCPAgentRegistryAdapter`; REST create/search/publish/deprecate shapes aligned). | Run with `AMPREALIZE_POSTGRES_DSN` / `AMPREALIZE_BEHAVIOR_PG_DSN`. |
| ~~MCP task assignment suggest~~ | `tests/test_mcp_suggest_agent.py` | ~~`MCPTaskAssignmentAdapter.suggest_agent`~~ — **implemented** | — |
| ~~CLI task assignment surface~~ | `tests/test_mcp_suggest_agent.py` | ~~`CLITaskAssignmentAdapter.surface`~~ — **implemented** (`surface = "cli"`) | — |
| ~~CLI suggest-agent command~~ | `tests/test_cli_suggest_agent.py` | ~~`suggest-agent` not registered~~ — **implemented** | — |
| MCP permission enforcement | `tests/test_permission_integration.py` | **Shipped (guideai-1183):** `MCPServiceRegistry.permission_service()`, `MCPServer._check_permission`, `mcp_permission_registry` | **guideai-1183** ✅ |
| Agent performance MCP | `tests/test_mcp_agent_performance_tools.py` | `recordStatusChange` MCP tool not implemented (service exists) | **guideai-1184** |

## Enterprise-only service gaps

| Area | Location | Skip / condition | Board tracking |
|------|-----------|------------------|----------------|
| OrganizationService | `tests/test_organization_service.py` | `Not yet implemented in amprealize-enterprise OrganizationService` (specific test) | **guideai-1185** |

## Runtime / conditional skips (implementation or wiring)

| Area | Location | Message / trigger | Board tracking |
|------|-----------|-------------------|----------------|
| Analytics CLI parity | `tests/test_analytics_parity.py` | `CLI command not yet implemented or not in PATH` | **guideai-1186** |
| BreakerAmp load harness | `tests/load/test_breakeramp_load.py` | `_get_current_resource_usage` not implemented (not pytest `not yet` string; same class of “stub”) | **guideai-1187** |

## Config / fixture debt (not product features)

| Area | Location | Note | Board tracking |
|------|-----------|------|----------------|
| Production env fixture | `tests/test_settings_integration.py` | `production.env not yet created` — add or relax test when `deployment/environments/production.env` exists | **guideai-1188** |

## Large stub surfaces (outside pytest skip list)

These are **NotImplementedError** or stubs in product code; they may not map 1:1 to a single test skip but belong in the same **delivery** conversation as the goal:

- `amprealize/research/` — PDF ingester, codebase analyzer, report render
- `amprealize/packages/billing/.../stripe.py` — many Stripe methods stubbed
- `amprealize/config/secrets.py` — GCP Secret Manager, Azure Key Vault, secret write paths
- `amprealize/cli_dr.py` — restore / automated failover messaging

## Suggested child features (for board breakdown)

Parent **guideai-1182** now has tracked **features** **guideai-1183**–**guideai-1188** for remaining gaps. Historical suggestions (superseded where shipped):

1. ~~Ship **CLI + MCP agent registry adapters** and unskip `test_agent_registry_parity.py`.~~ **Done** in OSS (`CLIAgentRegistryAdapter`, `MCPAgentRegistryAdapter`, REST shape fixes).
2. ~~Wire **suggest_agent** through CLI registration + `MCPTaskAssignmentAdapter` + `CLITaskAssignmentAdapter.surface`.~~ **Done**.
3. ~~Implement **MCP permission** registry + `_check_permission` and unskip permission integration — **guideai-1183**.~~ **Done** (`mcp_permission_registry.py`, `MCPServiceRegistry.permission_service`, `MCPServer._check_permission`).
4. Expose **agentPerformance.recordStatusChange** (or equivalent) as MCP tool — **guideai-1184**.
5. Complete **enterprise OrganizationService** behaviors covered by skipped tests — **guideai-1185**.
6. **Analytics / CLI** parity for commands referenced in `test_analytics_parity.py` — **guideai-1186**.

## Related docs

- [CI_ENTERPRISE.md](../CI_ENTERPRISE.md) — skip catalog and optional CI
- [TESTING_GUIDE.md](../TESTING_GUIDE.md) — item 6, enterprise / load / parity
- [WORK_MANAGEMENT_GUIDE.md](../WORK_MANAGEMENT_GUIDE.md) — work item API and MCP `workItems.create`
