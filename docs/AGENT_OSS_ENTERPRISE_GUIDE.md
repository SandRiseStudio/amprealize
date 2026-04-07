# Agent Guide: OSS vs Enterprise Boundary

> **Audience**: AI agents developing the Amprealize platform.
> **Last verified against code**: `main` branch, commit `65d2f45`.

---

## Architecture Overview

Amprealize ships as two Python packages:

| Package | Repo | License | PyPI |
|---------|------|---------|------|
| `amprealize` | `SandRiseStudio/amprealize` (public) | Apache-2.0 | `amprealize==0.1.0` |
| `amprealize-enterprise` | private | proprietary | not yet published |

The OSS package **always works without enterprise installed**. Enterprise
features degrade gracefully via stub patterns at every import site.

### Version Coupling

Both packages use **PEP 440 compatible-release** (`~=0.1.0`) — meaning
`>=0.1.0, <0.2.0`. A patch bump on either side is automatically
compatible; a minor bump is a breaking boundary.

- **Pin file**: `.amprealize-version` (root) — single source of truth, currently `0.1.0`
- **OSS pyproject.toml**: `enterprise = ["amprealize-enterprise~=0.1.0"]`
- **CI validation**: `scripts/check_oss_version.py` runs in CI to enforce coupling
- **Full details**: `docs/ENTERPRISE_OSS_COUPLING.md`

---

## The Import Pattern

Every enterprise-gated module follows this structure:

```python
"""Module docstring — OSS Stub. Full implementation in amprealize-enterprise."""

try:
    from amprealize_enterprise.module.path import RealThing
except ImportError:
    # One of five stub patterns (see below)
    RealThing = None  # or no-op class, or raise ImportError on call
```

### Root Detection

`amprealize/__init__.py` (line 17) exposes a global flag:

```python
try:
    import amprealize_enterprise as _enterprise
    HAS_ENTERPRISE = True
except ImportError:
    HAS_ENTERPRISE = False
```

Consumers can check `amprealize.HAS_ENTERPRISE` at runtime.

---

## Five Stub Patterns

The codebase uses exactly five fallback patterns. When adding new
enterprise-gated code, use the pattern that matches your use case.

### Pattern 1: `None` Assignment

**Used when**: The feature is entirely absent in OSS and callers check
for `None` before use.

```python
try:
    from amprealize_enterprise.multi_tenant.organization_service import OrganizationService
except ImportError:
    OrganizationService = None
```

**Files using this pattern**:
- `multi_tenant/organization_service.py` → `OrganizationService = None`
- `multi_tenant/invitation_service.py` → `InvitationService = None`
- `multi_tenant/settings.py` → `SettingsService = None`, `OrgSettings = None`, plus 8 more models
- `analytics/warehouse.py` → `AnalyticsWarehouse = None`
- `billing/service.py` → `AmprealizeBillingService = None`, `AmprealizeBillingHooks = None`
- `billing/api.py` → `create_billing_router = None`
- `billing/webhook_routes.py` → `create_webhook_router = None`, etc.
- `billing/__init__.py` → `BillingService = None`, `create_billing_router = None`, etc.
- `research/codebase_analyzer.py` → `CodebaseAnalyzer = None`, `CodebaseSnapshot = None`, etc.
- `research/ingesters/*.py` → All ingester classes set to `None`
- `research/__init__.py` → `CodebaseAnalyzer = None`, formatter functions = `None`, etc.
- `midnighter/__init__.py` → `MidnighterService = None`, `MidnighterHooks = None`

**Caller convention**: Always check `if SomeClass is not None:` before instantiating.

### Pattern 2: No-Op Dataclass / Class

**Used when**: OSS callers need a working object (not `None`), but the
object should do nothing.

```python
except ImportError:
    @dataclass
    class TelemetryProjection:
        summary: Dict[str, Any] = field(default_factory=dict)
        fact_behavior_usage: List[Dict[str, Any]] = field(default_factory=list)
        # ...

    class TelemetryKPIProjector:
        def project(self, events=None, **kwargs):
            return TelemetryProjection()
```

**Files using this pattern**:
- `analytics/telemetry_kpi_projector.py` → `TelemetryKPIProjector` returns empty `TelemetryProjection`
- `crypto/__init__.py` → `AuditSigner` with `is_loaded=False`, `sign_record()` returns empty `SignatureMetadata`, `verify_record()` always returns `True`

### Pattern 3: Raise `ImportError` on Call

**Used when**: The feature cannot degrade gracefully — calling it without
enterprise should fail loudly and tell the user what to install.

```python
except ImportError:
    def create_midnighter_service(**kwargs):
        raise ImportError(
            "Midnighter integration requires amprealize-enterprise. "
            "Install with: pip install amprealize-enterprise[midnighter]"
        )
```

**Files using this pattern**:
- `midnighter/__init__.py` → `create_midnighter_service()` raises
- `crypto/__init__.py` → `generate_signing_key()` raises
- `research/report.py` → `render_report()` raises
- `research/prompts.py` → `format_*_prompt()` functions raise
- `multi_tenant/api.py` → `create_org_routes()` raises (when called directly)
- `multi_tenant/settings_api.py` → `create_settings_routes()` raises (when called directly)

### Pattern 4: Empty String / Empty Dict Constants

**Used when**: Code reads string constants or config dicts that can
safely be empty.

```python
except ImportError:
    _ENTERPRISE_AVAILABLE = False
    COMPREHENSION_SYSTEM_PROMPT = ""
    EVALUATION_SYSTEM_PROMPT = ""
    TOKEN_BUDGETS = {}
```

**Files using this pattern**:
- `research/__init__.py` → All prompt strings = `""`, `TOKEN_BUDGETS = {}`

### Pattern 5: Boolean Availability Flag + No-Op Function

**Used when**: API routes are conditionally mounted. The flag controls
whether the route family appears; the function raises only if called
directly without checking the flag first.

```python
try:
    from amprealize_enterprise.multi_tenant.api import create_org_routes
    ORG_ROUTES_AVAILABLE = True
except ImportError:
    ORG_ROUTES_AVAILABLE = False
    def create_org_routes(*args, **kwargs):
        raise ImportError("Organization management API requires amprealize-enterprise.")
```

**Files using this pattern**:
- `multi_tenant/api.py` → `ORG_ROUTES_AVAILABLE`
- `multi_tenant/settings_api.py` → `SETTINGS_ROUTES_AVAILABLE`

**How the API uses them**: `amprealize/api.py` checks these flags in
`AmprealizeContainer.__init__()` and only mounts route families when all
flags are `True` AND a PostgreSQL DSN is configured.

---

## Enterprise-Gated Modules: Complete Map

### `amprealize/analytics/`
| File | Enterprise Import | Stub Pattern | OSS Behavior |
|------|-------------------|-------------|--------------|
| `telemetry_kpi_projector.py` | `.analytics.telemetry_kpi_projector` | No-op dataclass | Returns empty projections |
| `warehouse.py` | `.analytics.warehouse` | `None` | Feature absent |

### `amprealize/billing/`

**Hybrid module** — standalone `packages/billing/` stays in OSS; enterprise
wrappers (`AmprealizeBillingService`, API routes, webhooks) are enterprise-only.

| File | Enterprise Import | Stub Pattern | OSS Behavior |
|------|-------------------|-------------|--------------|
| `__init__.py` | `.billing.service`, `.billing.webhook_routes`, `.billing.api` | `None` | Standalone billing pkg available; enterprise wrappers absent |
| `service.py` | `.billing.service` | `None` | Feature absent |
| `api.py` | `.billing.api` | `None` | Feature absent |
| `webhook_routes.py` | `.billing.webhook_routes` | `None` | Feature absent |

### `amprealize/crypto/`
| File | Enterprise Import | Stub Pattern | OSS Behavior |
|------|-------------------|-------------|--------------|
| `__init__.py` | `.crypto.signing` | No-op class + raise on keygen | `AuditSigner` does nothing; `generate_signing_key()` raises; exception classes stay in OSS |

### `amprealize/midnighter/`
| File | Enterprise Import | Stub Pattern | OSS Behavior |
|------|-------------------|-------------|--------------|
| `__init__.py` | `.midnighter` | `None` + raise on factory | `create_midnighter_service()` raises; classes are `None` |

### `amprealize/multi_tenant/`

**Partial OSS** — contracts, context, permissions, and OSS project service
stay in OSS. Organization/invitation/settings services are enterprise-only.

| File | Enterprise? | Notes |
|------|------------|-------|
| `contracts.py` | **No — OSS** | Pydantic models, shared interface types |
| `board_contracts.py` | **No — OSS** | Board-related models |
| `context.py` | **No — OSS** | `TenantContext` for RLS, tenant middleware |
| `permissions.py` | **No — OSS** | RBAC permission system, decorators |
| `oss_project_service.py` | **No — OSS** | Lightweight fallback for personal projects |
| `organization_service.py` | **Yes** | `OrganizationService = None` |
| `invitation_service.py` | **Yes** | `InvitationService = None` |
| `settings.py` | **Partial** | `ExecutionMode` enum + surface constants are OSS; `SettingsService` + all Pydantic settings models are enterprise |
| `api.py` | **Yes** | `create_org_routes()` + `ORG_ROUTES_AVAILABLE` flag |
| `settings_api.py` | **Yes** | `create_settings_routes()` + `SETTINGS_ROUTES_AVAILABLE` flag |

### `amprealize/research/`
| File | Enterprise Import | Stub Pattern | OSS Behavior |
|------|-------------------|-------------|--------------|
| `__init__.py` | `.research.prompts`, `.research.codebase_analyzer` | Empty strings + `None` | `_ENTERPRISE_AVAILABLE = False`; prompts are `""` |
| `prompts.py` | `.research.prompts` | Empty strings + raise on format | Format functions raise |
| `codebase_analyzer.py` | `.research.codebase_analyzer` | `None` | Feature absent |
| `report.py` | `.research.report` | Raise on call | `render_report()` raises |
| `ingesters/__init__.py` | `.research.ingesters` | `None` | All ingesters are `None` |
| `ingesters/base.py` | `.research.ingesters.base` | `None` | Utilities are `None` |
| `ingesters/markdown_ingester.py` | `.research.ingesters.markdown_ingester` | `None` | Feature absent |
| `ingesters/url_ingester.py` | `.research.ingesters.url_ingester` | `None` | Feature absent |
| `ingesters/pdf_ingester.py` | `.research.ingesters.pdf_ingester` | `None` | Feature absent |

---

## API Capability Gating

The FastAPI app in `amprealize/api.py` uses _capability gating_ to
dynamically enable/disable route families based on what's installed.

### How It Works

`AmprealizeContainer.__init__()` checks a chain of conditions:

```python
enterprise_org_routes_available = bool(
    MULTI_TENANT_AVAILABLE        # OrganizationService is not None
    and ORG_ROUTES_AVAILABLE      # create_org_routes imported successfully
    and SETTINGS_ROUTES_AVAILABLE # create_settings_routes imported successfully
    and create_org_routes is not None
    and create_settings_routes is not None
)
```

When enterprise is missing, the container falls back to `OSSProjectService`:

```python
if enterprise_org_routes_available and org_dsn:
    self.org_service = OrganizationService(dsn=org_dsn, ...)
elif org_dsn:
    self.org_service = OSSProjectService(dsn=org_dsn)
```

The final capability report is exposed at runtime via
`ApiCapabilitiesResponse`:

```python
self.api_capabilities = ApiCapabilitiesResponse(
    routes=RouteCapabilitiesResponse(
        projects=self.project_service_available,
        orgs=self.org_routes_available,          # False in OSS
        settings=self.settings_routes_available, # False in OSS
        executions=self.execution_service_available,
    ),
    ...
)
```

### What This Means for Agents

- **Never assume a route family exists.** Check `api_capabilities` first.
- **`/orgs/*` and `/settings/*` routes only mount with enterprise.**
- **`/projects/*` routes always work** — `OSSProjectService` handles personal projects.

---

## Standalone Packages in `packages/`

Some enterprise-adjacent functionality lives in standalone packages that
are **not** enterprise-gated:

| Package | Path | Relation to Enterprise |
|---------|------|----------------------|
| `billing` | `packages/billing/` | OSS — provider-agnostic billing models/service. Enterprise adds `AmprealizeBillingService` wrapper. |
| `raze` | `packages/raze/` | OSS — structured logging. Used by both editions. |
| `breakeramp` | `packages/breakeramp/` | OSS — environment orchestration. Used by both editions. |
| `midnighter` | `packages/midnighter/` | OSS standalone package. Enterprise adds `create_midnighter_service` integration. |

---

## Rules for Adding New Enterprise-Gated Code

### 1. Choose the Right Stub Pattern

| Scenario | Pattern | Example |
|----------|---------|---------|
| Callers check before use | `= None` | `OrganizationService = None` |
| Callers need a working object that does nothing | No-op class | `AuditSigner` |
| Feature should fail loudly | `raise ImportError(...)` | `create_midnighter_service()` |
| Config constants/strings | Empty string / empty dict | `PROMPT = ""` |
| API route conditionally mounted | Boolean flag + raise | `ORG_ROUTES_AVAILABLE` |

### 2. File Structure

```python
"""One-line description — OSS Stub. Full implementation in amprealize-enterprise."""

try:
    from amprealize_enterprise.module.submodule import Thing
except ImportError:
    Thing = None  # or no-op class, or raise

__all__ = ["Thing"]
```

### 3. Keep Shared Types in OSS

Contracts (Pydantic models), enums, exception classes, and protocol
definitions that both OSS and enterprise code import **must stay in OSS**.

Examples:
- `multi_tenant/contracts.py` — all org/project Pydantic models
- `multi_tenant/context.py` — `TenantContext` and RLS middleware
- `multi_tenant/permissions.py` — RBAC system
- `crypto/__init__.py` — `SigningError`, `KeyNotLoadedError`, `InvalidSignatureError`, `SignatureMetadata`
- `multi_tenant/settings.py` — `ExecutionMode` enum, `LOCAL_CAPABLE_SURFACES`, `REMOTE_ONLY_SURFACES`

### 4. Wire Into API Capability Gating

If your enterprise feature adds API routes:

1. Add a `YOUR_ROUTES_AVAILABLE: bool` flag in the OSS stub module
2. Import and check it in `amprealize/api.py` inside `AmprealizeContainer.__init__()`
3. Add a field to `RouteCapabilitiesResponse` or `ServiceCapabilitiesResponse`
4. Only mount routes when the flag is `True` AND required services are instantiated

### 5. Add `__all__` Exports

Always export all names (real or stub) via `__all__` so that
`from amprealize.module import *` works identically in both editions.

### 6. Update These Files

When adding a new enterprise-gated module:

- [ ] Create the OSS stub file under `amprealize/` with the correct pattern
- [ ] Add `__all__` listing all exported names
- [ ] If API routes: add availability flag + update `api.py` gating
- [ ] Update `docs/ENTERPRISE_OSS_COUPLING.md` if coupling rules change
- [ ] Update this file (`docs/AGENT_OSS_ENTERPRISE_GUIDE.md`) with the new module
- [ ] Add test in `tests/unit/test_api_capability_gating.py` if applicable
- [ ] Ensure `import amprealize` still works without enterprise installed

---

## Testing Without Enterprise

Since `amprealize-enterprise` is not published yet, **all CI runs in pure
OSS mode**. Every stub path is exercised by default.

To simulate enterprise being available in tests, monkeypatch the flags:

```python
# tests/unit/test_api_capability_gating.py
monkeypatch.setattr(api_module, "ORG_ROUTES_AVAILABLE", True)
monkeypatch.setattr(api_module, "SETTINGS_ROUTES_AVAILABLE", True)
```

Or check an enterprise feature is properly gated:

```python
from amprealize import HAS_ENTERPRISE
assert not HAS_ENTERPRISE  # Should be False in CI

from amprealize.crypto import AuditSigner
signer = AuditSigner()
assert not signer.is_loaded  # No-op stub
```

---

## Quick Reference: What Lives Where

| Layer | OSS (`amprealize`) | Enterprise (`amprealize-enterprise`) |
|-------|-----------------|----------------------------------|
| **Core services** | ActionService, RunService, BehaviorService, BCIService | — |
| **Multi-tenant contracts** | Pydantic models, enums, permissions, RLS context | — |
| **Multi-tenant services** | `OSSProjectService` (personal projects only) | `OrganizationService`, `InvitationService`, `SettingsService` |
| **Multi-tenant API routes** | `/projects/*` (via OSS fallback) | `/orgs/*`, `/settings/*` |
| **Billing models** | `packages/billing/` (provider-agnostic) | `AmprealizeBillingService`, billing API/webhook routes |
| **Crypto** | Exception classes, `SignatureMetadata`, no-op `AuditSigner` | Real Ed25519 `AuditSigner`, `generate_signing_key` |
| **Analytics** | No-op `TelemetryKPIProjector` | Real projector, `AnalyticsWarehouse` |
| **Research** | Empty prompt strings, `None` analyzers/ingesters | Full pipeline: prompts, codebase analyzer, PDF/URL/MD ingesters |
| **Midnighter** | Factory raises `ImportError` | `MidnighterService` for BC-SFT training |
| **Logging** | `packages/raze/` | — (shared) |
| **Environments** | `packages/breakeramp/` | — (shared) |
| **VS Code extension** | `extension/` | — (shared) |
| **MCP server** | `mcp/` | — (shared) |

---

_Verified by scanning all `from amprealize_enterprise` and `import amprealize_enterprise`
patterns across 26 import sites in the `amprealize/` source tree._
