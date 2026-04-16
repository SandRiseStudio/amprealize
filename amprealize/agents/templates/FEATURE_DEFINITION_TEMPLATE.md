## Feature Definition: {Feature Name}

**Date**: {YYYY-MM-DD}
**Author**: {author}
**Status**: Draft
**Version**: 1.0

---

### Summary

{1-2 sentence elevator pitch: What does this feature do? Who is it for? Why does it matter?}

---

### Distribution

| Attribute | Value |
|-----------|-------|
| Edition | {OSS / Enterprise Starter / Enterprise Premium} |
| Feature Flag | {flag name or "None — ship fully"} |
| Rollout Strategy | {percentage / user-list / full-launch / no-flag} |
| Starter Tier Cap | {limit or "N/A"} |
| OSS Stub Pattern | {None / No-Op / Raise / Empty / Conditional — or "N/A" if OSS} |

---

### Surface Coverage

| Surface | Day One | Follow-Up | Notes |
|---------|---------|-----------|-------|
| MCP Tools | ✅ / ❌ | ✅ / ❌ | {new tool schemas, tool names} |
| REST API | ✅ / ❌ | ✅ / ❌ | {new endpoints, OpenAPI changes} |
| CLI (Click) | ✅ / ❌ | ✅ / ❌ | {new commands/subcommands} |
| Web Console | ✅ / ❌ | ✅ / ❌ | {new views, components, routes} |
| VS Code Extension | ✅ / ❌ | ✅ / ❌ | {new panels, commands, webviews} |

**Cross-Surface Parity**: {strict parity / surface-appropriate variations — describe}

---

### Architecture & Services

**Services Impacted:**

| Service | Impact Type | Description |
|---------|------------|-------------|
| {ServiceName} | New / Modified / Depends | {what changes and why} |

**New Service**: {Yes — standalone package under `packages/`? / No}

**Data Model Changes:**

| Table / Collection | Change Type | Migration |
|-------------------|-------------|-----------|
| {table_name} | New / Alter / Drop | {alembic revision name} |

**Storage Adapters**: {SQLite / Postgres / Firestore — which need support?}

**Configuration:**

| Env Var / Setting | Purpose | Default |
|-------------------|---------|---------|
| {VAR_NAME} | {purpose} | {default value} |

---

### Behavioral Context

**Existing Behaviors That Apply:**
- `{behavior_name}` — {how it relates}

**New Behaviors Proposed:**
- `{behavior_name}` — {when triggered, what it does}

**Primary Role**: {Student / Teacher / Strategist}

**AGENTS.md Updates:**
- Quick Trigger: {keywords} → `{behavior_name}` | {role}
- Behavior Definition: {new behavior section if needed}

---

### Feature Interactions

**Depends On:**
- {Feature/Service} — {why this dependency exists}

**Impacts (Existing Features Affected):**
- {Feature/Service} — {how it's affected}

**API Contract Changes**: {Breaking / Non-Breaking / Additive-Only}
- {details of what changes}

**Backward Compatibility**: {Yes / No — details}

**Migration Path**: {How existing users/data transition to the new behavior}

---

### Security & Compliance

| Attribute | Value |
|-----------|-------|
| Auth Level | {Public / Authenticated / Project-Scoped / Org-Scoped / Admin-Only} |
| New RBAC Permissions | {scope names or "None"} |
| Audit Logging | {which mutations to log, append-only or mutable} |
| Data Sensitivity | {Public / Internal / Confidential / Restricted} |
| Rate Limiting | {specific limits or "Default"} |
| Compliance Items | {SOC2 / GDPR / HIPAA considerations or "None"} |
| CORS/Security Surface Changes | {changes or "None"} |

---

### Success Criteria

**Acceptance Criteria:**
1. Given {context}, when {action}, then {expected outcome}
2. Given {context}, when {action}, then {expected outcome}
3. {add more as needed}

**Metrics:**

| Metric | Target | Telemetry Event |
|--------|--------|-----------------|
| {metric_name} | {target_value} | {event_name} |

**Testing Requirements:**

| Type | Scope | Target |
|------|-------|--------|
| Parity | {day-one surfaces} | 100% |
| Unit | Core logic | >90% |
| Integration | Service boundaries | Key paths |
| Performance | {benchmark description} | {threshold} |

---

### Documentation Updates

- [ ] PRD.md
- [ ] README.md
- [ ] BUILD_TIMELINE.md
- [ ] capability_matrix.md
- [ ] MCP_SERVER_DESIGN.md
- [ ] AGENTS.md
- [ ] API contract docs
- [ ] {other relevant docs}

---

### Open Questions

1. {Unresolved item — who needs to answer, by when}
2. {Unresolved item}
