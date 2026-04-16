---
title: "Editions & Feature Matrix"
type: reference
last_updated: 2026-04-14
applies_to:
  - dev
  - test
  - staging
  - prod
tags:
  - editions
  - oss
  - enterprise
  - feature-matrix
  - licensing
---

# Editions & Feature Matrix

Amprealize ships in three editions. The OSS core is Apache 2.0 licensed;
enterprise features are proprietary add-ons.

## Edition Comparison

| Capability | OSS | Starter | Premium |
|---|:---:|:---:|:---:|
| Core behaviors, agents, runs, actions | ✓ | ✓ | ✓ |
| Compliance checklists & validation | ✓ | ✓ | ✓ |
| BCI (Behavior-Conditioned Inference) | ✓ | ✓ | ✓ |
| MCP server (64+ tools) | ✓ | ✓ | ✓ |
| CLI / REST API / VS Code / Web Console | ✓ | ✓ | ✓ |
| Knowledge packs (build, activate) | ✓ | ✓ | ✓ |
| Wiki system (4 domains) | ✓ | ✓ | ✓ |
| Org + multi-tenant (RLS, RBAC) | — | ✓ | ✓ |
| Billing (Stripe integration) | — | ✓ | ✓ |
| Analytics / KPI warehouse | — | ✓ | ✓ |
| Conversations (real-time chat) | — | ✓ | ✓ |
| Collaboration (shared editing) | — | ✓ | ✓ |
| Auto-reflection (behavior proposals) | — | ✓ | ✓ |
| Research module (codebase analysis) | — | ✓ | ✓ |
| Midnighter (BC-SFT training data) | — | ✓ | ✓ |
| SSO, audit signing, custom branding | — | — | ✓ |
| SLA support, self-improving agents | — | — | ✓ |

## Resource Caps (Starter Edition)

Enforced by `CapsEnforcer`:

| Resource | Starter Limit |
|----------|:-------------:|
| Projects | 10 |
| Boards per project | 5 |
| Work items | 2,000 |
| Agents | 3 |
| Behaviors | 100 |
| API calls / month | 50,000 |
| Storage | 10 GB |
| Team members | 15 |

OSS and Premium editions have no enforced caps.

## Repository Layout

```
/Users/nick/Main/
├── amprealize/                  # OSS (Apache 2.0)
│   └── amprealize/              # Core Python package
└── amprealize-enterprise/       # Proprietary
    ├── amprealize/              # Shared core (symlinked or identical)
    └── src/amprealize_enterprise/
        ├── multi_tenant/        # RLS, RBAC, org management
        ├── billing/             # Stripe integration
        ├── analytics/           # KPI warehouse
        ├── research/            # Codebase analysis
        ├── midnighter/          # BC-SFT training
        └── crypto/              # Audit signing
```

## Import Stub Patterns

OSS code compiles without enterprise dependencies using these patterns:

1. **None assignment**: `try: from enterprise import X except ImportError: X = None`
2. **No-op dataclass**: Stub with same shape, no-op methods
3. **Raise on call**: Function exists but raises `ImportError` when invoked
4. **Empty constants**: `FEATURE_FLAGS = {}` as fallback
5. **Boolean flag**: `HAS_ENTERPRISE = False` + conditional logic

## Version Coupling

Both repos track `.amprealize-version` (currently `0.1.0`). The OSS `pyproject.toml`
pins enterprise as `~=0.1.0` to ensure compatible releases.
