# Enterprise Module Migration Analysis

> **Date**: 2026-03-24 | **Status**: Planning | **Author**: Architecture Review

---

## Executive Summary

This analysis evaluates six candidate modules for enterprise/OSS repository split. The `multi_tenant` module is the most deeply coupled (27 external consumers, 11K LOC) and requires a hybrid approach. `billing` is already well-architected as a standalone package wrapper. `analytics`, `crypto`, and `research` are cleanly separable. `midnighter` is a thin wrapper with zero external consumers.

---

## Primary Enterprise Modules

### Module Inventory

| Module | Files | LOC | Key Classes / Functions | Migration Complexity |
|--------|------:|----:|------------------------|---------------------|
| `amprealize/billing/` | 4 | 1,764 | `AmprealizeBillingService`, `AmprealizeBillingHooks`, `create_billing_router`, `create_webhook_router`, `create_amprealize_webhook_router` | **Easy** |
| `amprealize/analytics/` | 3 | 962 | `AnalyticsWarehouse`, `TelemetryKPIProjector`, `TelemetryProjection` | **Easy** |
| `amprealize/multi_tenant/` | 11 | 11,048 | `OrganizationService`, `PermissionService`, `TenantContext`, `TenantMiddleware`, `InvitationService`, `SettingsService`, 30+ Pydantic contracts, Board contracts (enums, `WorkItem`, `Board`, `BoardColumn`), `create_org_routes`, `create_settings_routes` | **Hard** |

### Detailed Dependency Map

#### 1. `amprealize/billing/` — Stripe Billing Integration

| Attribute | Detail |
|-----------|--------|
| **Files** | `__init__.py`, `service.py`, `api.py`, `webhook_routes.py` |
| **LOC** | 1,764 |
| **Architecture** | Thin wrapper around standalone `packages/billing/` package. Core logic lives outside `amprealize/`. |
| **Internal Imports** | `amprealize.action_service` (ActionService, ActionCreateRequest, Actor, Action) · `amprealize.action_contracts` · `amprealize.compliance_service` (ComplianceService, RecordStepRequest) · `amprealize.metrics_service` (MetricsService) |
| **External Consumers** | `tests/billing/test_billing_service.py` (1 consumer) |
| **Standalone Package** | ✅ Already exists at `packages/billing/` — `amprealize/billing/` is only the integration glue |
| **Complexity** | **Easy** — Already follows standalone pattern. Only 1 test file consumes it. Wrapper imports 3 core services via hooks. |
| **Recommendation** | **Move to enterprise.** Keep `packages/billing/` as-is (provider-agnostic). Move `amprealize/billing/` wrapper to enterprise repo. OSS can stub billing checks or use a `NoOpBillingProvider`. |

#### 2. `amprealize/analytics/` — KPI Projector & Warehouse

| Attribute | Detail |
|-----------|--------|
| **Files** | `__init__.py`, `warehouse.py`, `telemetry_kpi_projector.py` |
| **LOC** | 962 |
| **Architecture** | DuckDB + Postgres/Timescale dual-backend warehouse. KPI projector transforms telemetry events into fact tables (Snowflake schema). |
| **Internal Imports** | `amprealize.telemetry.TelemetryEvent` · `amprealize.utils.dsn.apply_host_overrides` |
| **External Consumers** | `amprealize/cli.py` · `amprealize/metrics_service.py` · `tests/test_analytics_parity.py` · `tests/test_analytics_warehouse_parity.py` · `tests/test_telemetry_kpi_projector.py` (5 consumers) |
| **Complexity** | **Easy** — Only 2 internal imports, both utility-level. Consumers are CLI (optional), metrics service (can be feature-flagged), and tests. |
| **Recommendation** | **Move to enterprise.** Advanced analytics/KPI dashboards are enterprise features. OSS retains basic `TelemetryEvent` and `MetricsService`. Add a `analytics_enabled` feature flag to gate CLI commands and metrics integrations. |

#### 3. `amprealize/multi_tenant/` — Multi-Tenancy, Orgs, Permissions, Boards

| Attribute | Detail |
|-----------|--------|
| **Files** | `__init__.py`, `api.py`, `board_contracts.py`, `board_contracts_backup.py`, `context.py`, `contracts.py`, `invitation_service.py`, `organization_service.py`, `permissions.py`, `settings.py`, `settings_api.py` |
| **LOC** | 11,048 |
| **Architecture** | PostgreSQL RLS-based tenant isolation. Full RBAC permission system. Org/project/member CRUD. Board/WorkItem contracts used across the platform. |
| **Internal Imports** | `amprealize.storage.postgres_pool.PostgresPool` (6 files) · `amprealize.notify.AmprealizeNotifyService` · `amprealize.services.board_service.BoardService` |
| **External Consumers** | **27 files** across core, services, MCP, auth, API, and tests: |

<details>
<summary>Full consumer list (27 files)</summary>

| Layer | Files |
|-------|-------|
| **Core** | `amprealize/adapters.py`, `amprealize/api.py`, `amprealize/cli.py`, `amprealize/execution_worker.py`, `amprealize/migration.py`, `amprealize/projects_api.py`, `amprealize/research_service.py`, `amprealize/work_item_execution_service.py` |
| **Auth** | `amprealize/auth/middleware.py` |
| **MCP** | `amprealize/mcp/handlers/org_agent_handlers.py` |
| **Services** | `amprealize/services/assignment_service.py`, `amprealize/services/board_api_v2.py`, `amprealize/services/board_service.py`, `amprealize/services/board_service_backup.py`, `amprealize/services/work_item_assignment.py` |
| **Tests** | `tests/test_board_service.py`, `tests/test_execution_gateway.py`, `tests/test_invitation_service.py`, `tests/test_mcp_multi_tenant_handlers.py`, `tests/test_mcp_suggest_agent.py`, `tests/test_org_api_endpoints.py`, `tests/test_organization_service.py`, `tests/test_permission_integration.py`, `tests/test_permission_service.py`, `tests/test_settings_api.py`, `tests/unit/test_board_boards_rest_contract.py`, `tests/unit/test_board_labels_cross_surface.py`, `tests/unit/test_projects_api.py` |

</details>

| Attribute | Detail |
|-----------|--------|
| **Complexity** | **Hard** — 27 consumers across every layer. Board contracts are used by work item system (OSS-critical). Permission system is woven into auth middleware and API layer. RLS context is foundational to all multi-org queries. |
| **Recommendation** | **Hybrid.** See split strategy below. |

**Multi-Tenant Split Strategy:**

| Sub-module | Destination | Rationale |
|------------|-------------|-----------|
| `contracts.py` (base enums, `Organization`, `Project`, `MemberRole`, `ProjectRole`) | **OSS** | Needed as interface types everywhere |
| `board_contracts.py` (`WorkItem`, `Board`, `BoardColumn`, status enums) | **OSS** | Core work management types used across platform |
| `context.py` (`TenantContext`, `TenantMiddleware`) | **OSS** | Foundational infrastructure, needed for any multi-org support |
| `permissions.py` (`PermissionService`, RBAC enums) | **OSS** | Basic permission checking needed even in single-tenant mode |
| `organization_service.py` (full org CRUD, billing integration) | **Enterprise** | Advanced multi-org management, subscription tiers |
| `invitation_service.py` (email invitations, notification hooks) | **Enterprise** | Team management feature |
| `settings.py` + `settings_api.py` (org/project settings, branding, integrations) | **Enterprise** | Advanced configuration, branding, webhook management |
| `api.py` (REST routes for org management) | **Enterprise** | Full org management API |

---

## Additional Enterprise Candidates

| Module | Files | LOC | Internal Imports | External Consumers | Complexity | Recommendation |
|--------|------:|----:|-----------------|-------------------|------------|----------------|
| `amprealize/crypto/` | 2 | 475 | `amprealize.config.settings` (conditional) | `amprealize/services/audit_log_service.py`, `tests/test_s3_worm_storage.py` (2) | **Easy** | **Move to enterprise.** Ed25519 audit log signing is a compliance/enterprise feature. OSS can skip signature verification. |
| `amprealize/research/` | 9 | 2,097 | None (zero amprealize imports) | `amprealize/cli.py`, `amprealize/research_service.py` (2) | **Easy** | **Move to enterprise.** Research evaluation pipeline (PDF/URL ingestion, codebase analysis) is a premium feature. Zero coupling to core. |
| `amprealize/midnighter/` | 1 | 146 | `amprealize.behavior_service.BehaviorService` (TYPE_CHECKING only) | None (0 consumers) | **Easy** | **Move to enterprise.** BC-SFT training integration. Wraps standalone `packages/midnighter/`. No consumers — cleanest extraction possible. |

---

## Migration Complexity Summary

| Complexity | Module | LOC | Consumers | Action |
|:----------:|--------|----:|----------:|--------|
| 🟢 Easy | `billing/` | 1,764 | 1 | Move to enterprise (standalone pkg stays) |
| 🟢 Easy | `analytics/` | 962 | 5 | Move to enterprise, feature-flag CLI |
| 🟢 Easy | `crypto/` | 475 | 2 | Move to enterprise, stub signer in OSS |
| 🟢 Easy | `research/` | 2,097 | 2 | Move to enterprise, zero core deps |
| 🟢 Easy | `midnighter/` | 146 | 0 | Move to enterprise, no changes needed |
| 🔴 Hard | `multi_tenant/` | 11,048 | 27 | Hybrid split (contracts+context in OSS, services in enterprise) |
| | **Total** | **16,492** | | |

---

## Recommended Migration Order

| Phase | Module(s) | Risk | Notes |
|:-----:|-----------|------|-------|
| 1 | `midnighter/`, `research/` | Minimal | Zero or near-zero consumers. Safe first moves. |
| 2 | `crypto/`, `billing/` | Low | Few consumers, already well-isolated. Add OSS stubs. |
| 3 | `analytics/` | Low | Feature-flag gating in CLI and metrics_service. |
| 4 | `multi_tenant/` | High | Requires interface extraction, hybrid split, and consumer rewiring across 27 files. Plan 2-3 sprints. |

---

## Interface Stubs Required in OSS

After migration, these stubs/no-ops are needed in the OSS repo:

| Module | OSS Stub |
|--------|----------|
| `billing` | `NoOpBillingProvider` (already exists in `packages/billing/`) |
| `analytics` | Feature flag `analytics_enabled=false`; skip KPI projector initialization |
| `crypto` | `NoOpAuditSigner` returning empty signatures; skip verification |
| `multi_tenant` | Keep contracts + context + basic permissions in OSS; enterprise services behind `try/except ImportError` |
| `research` | CLI command hidden when module not installed |
| `midnighter` | No stub needed (zero consumers) |

---

## Infrastructure Files Analysis (A6-T9)

> **Total**: 70 files across Dockerfiles, compose configs, scripts, monitoring, docs

### Files Staying in OSS (`SandRiseStudio/amprealize`)

These support local development and basic self-hosted deployments:

| File | Purpose |
|------|---------|
| `infra/Dockerfile.core.simple` | Minimal single-stage build for local dev |
| `infra/docker-compose.test.yml` | Test infrastructure (Postgres, Redis) |
| `infra/docker-compose.postgres.yml` | Basic Postgres for local development |
| `infra/environments/local.env` | Local development environment variables |
| `infra/environments/dev.env.example` | Dev environment template |
| `infra/environments/postgres.env.example` | Postgres connection template |
| `infra/environments.yaml` | BreakerAmp environment definitions |
| `infra/scripts/entrypoint.sh` | Container entrypoint |
| `infra/QUICKSTART.md` | Getting started guide |
| `infra/README.md` | Infra overview |
| `infra/CONTAINER_COMPARISON.md` | Container runtime docs |
| `infra/CONTAINER_RUNTIME_DECISION.md` | Runtime decision docs |
| `infra/data/test-events/parity_test_events.json` | Test fixtures |
| `infra/requirements-verify.txt` | Verification requirements |

### Files Moving to Enterprise (`SandRiseStudio/amprealize-enterprise`)

Production, staging, scaling, and cloud deployment configs:

| Category | Files | Count |
|----------|-------|------:|
| **Dockerfiles (production)** | `Dockerfile.core`, `Dockerfile.mcp`, `Dockerfile.archive-audit`, `Dockerfile.verify-hash-chain` | 4 |
| **Compose (staging/prod)** | `docker-compose.staging.yml`, `docker-compose.streaming.yml`, `docker-compose.streaming-simple.yml`, `docker-compose.telemetry.yml`, `docker-compose.metrics.yml`, `docker-compose.analytics-dashboard.yml` | 6 |
| **Podman (scaling)** | `podman-compose-scaled.yml`, `podman-compose-staging.yml` | 2 |
| **Cloud Build** | `cloudbuild.verify-hash-chain.yaml` | 1 |
| **Environments (prod/staging)** | `environments/production.env`, `environments/staging.env.example`, `environments/prod.env.example`, `staging.env` | 4 |
| **Config (monitoring)** | `config/grafana/`, `config/prometheus/`, `config/prometheus-staging.yml`, `config/pgbouncer.*`, `config/pgadmin_servers.json`, `config/dr_monitoring.yml`, `config/telemetry.*.env`, `config/hybrid-flink.env` | 12 |
| **Flink** | `flink/telemetry_kpi_job.py` | 1 |
| **Grafana** | `grafana/README.md`, `grafana/embedding_optimization.json` | 2 |
| **Prometheus** | `prometheus/embedding_alerts.yml` | 1 |
| **Scripts (deploy/scale)** | `scripts/deploy-scaled-services.sh`, `scripts/hybrid-*.sh` (4), `scripts/init-warehouse.py`, `scripts/migrate-podman-to-k8s.sh`, `scripts/nginx-entrypoint.sh`, `scripts/scale-specific-services.sh*` (2) | 10 |
| **Docs (scaling/deploy)** | `CICD_DEPLOYMENT_GUIDE.md`, `CICD_TEST_STATUS.md`, `HORIZONTAL_SCALING_*.md` (3), `HYBRID_FLINK_*.md` (2), `HYBRID_KAFKA_*.md`, `PODMAN.md`, `PODMAN_SCALING_CONFIGURATION.md`, `SCALING_DEPLOYMENT_SCRIPTS.md`, `STAGING_DEPLOYMENT_GUIDE.md` | 13 |
| | **Total enterprise** | **56** |

### Summary

| Destination | Files | Purpose |
|------------|------:|---------|
| OSS | 14 | Local dev, test, basic self-hosted |
| Enterprise | 56 | Production, staging, scaling, monitoring, cloud |
