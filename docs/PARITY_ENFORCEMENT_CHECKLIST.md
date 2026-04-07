# Cross-Surface Parity Enforcement Checklist

> **Purpose:** Ensure every control-plane capability achieves parity across CLI, REST API, and MCP surfaces as required by `contracts/MCP_SERVER_DESIGN.md` and `contracts/ACTION_SERVICE_CONTRACT.md`.

## Context

The amprealize platform requires **cross-surface parity**: every capability exposed via CLI must also be available through REST API and MCP tools with equivalent semantics and consistent return structures. This document provides checklists to prevent parity gaps during development and review.

## Pre-Implementation Checklist

Before implementing any new service or capability, verify:

- [ ] **Service Contract Defined** – Create `<SERVICE>_CONTRACT.md` documenting:
  - Request/response schemas for all operations
  - CRUD operations and lifecycle methods
  - Expected return structures (nested vs flat)
  - Error handling behavior and exception types
  - RBAC scopes required for each operation
  - Telemetry events emitted

- [ ] **Three Adapters Planned** – Design adapters for all three surfaces:
  - [ ] `CLI<Service>Adapter` – Command-line interface with keyword arguments
  - [ ] `Rest<Service>Adapter` – REST API with JSON payloads
  - [ ] `MCP<Service>Adapter` – MCP tool invocation with payload dicts

- [ ] **MCP Tool Manifests Planned** – Enumerate required MCP tools:
  - List all operations (CRUD: create/list/get/update/delete)
  - Include lifecycle operations (submit/approve/deprecate)
  - Include search/query operations if applicable
  - Count: typically 5-12 tools per service

## Implementation Checklist

### 1. Service Implementation

- [ ] **Service Runtime** – Implement core service in `amprealize/<service>_service.py`:
  - [ ] Define request/response dataclasses
  - [ ] Implement CRUD methods
  - [ ] Add telemetry instrumentation via `TelemetryClient`
  - [ ] Document return structures (nested objects vs flat dicts)
  - [ ] Define custom exception types (inherit from `<Service>Error`)

### 2. Adapter Implementation

- [ ] **CLI Adapter** (`amprealize/adapters.py`):
  - [ ] Inherit from `<Service>AdapterBase` if shared logic exists
  - [ ] Implement all service operations with keyword arguments
  - [ ] Use `Actor(id=actor_id, role=actor_role, surface="CLI")`
  - [ ] Return service responses unchanged or via `_<entity>_detail()` helper

- [ ] **REST Adapter** (`amprealize/adapters.py`):
  - [ ] Inherit from `<Service>AdapterBase`
  - [ ] Implement all service operations accepting `payload: Dict[str, Any]`
  - [ ] Extract `actor` from payload: `actor = self._build_actor(payload.get("actor", {}))`
  - [ ] Use `surface="REST_API"`
  - [ ] Return same structures as CLI adapter

- [ ] **MCP Adapter** (`amprealize/adapters.py`):
  - [ ] Inherit from `<Service>AdapterBase`
  - [ ] Implement all service operations accepting `payload: Dict[str, Any]`
  - [ ] Extract `actor` from payload: `actor = self._build_actor(payload.get("actor", {}))`
  - [ ] Use `surface="MCP"`
  - [ ] Return same structures as CLI/REST adapters

### 3. MCP Tool Manifests

For each service operation, create `mcp/tools/<service>.<operation>.json`:

- [ ] **Required Fields**:
  ```json
  {
    "name": "<service>.<operation>",
    "description": "One-line description of what this tool does",
    "inputSchema": {
      "type": "object",
      "properties": {
        // All parameters including actor
      },
      "required": ["param1", "param2", "actor"]
    },
    "outputSchema": {
      "type": "object",
      "properties": {
        // Match actual service return structure
      }
    }
  }
  ```

- [ ] **Input Schema Completeness**:
  - [ ] All required parameters listed in `required` array
  - [ ] All optional parameters documented with descriptions
  - [ ] `actor` object with `id`, `role`, `surface` fields
  - [ ] Parameter types match service contract (string, array, object)

- [ ] **Output Schema Accuracy**:
  - [ ] Match actual return structure from service
  - [ ] Document nested objects (`{"behavior": {...}, "versions": [...]}`)
  - [ ] Document list vs object returns
  - [ ] Include metadata fields (`behavior_id`, `created_at`, etc.)

- [ ] **Tool Count Validation**:
  - [ ] CRUD: create, list/search, get, update, delete (5 minimum)
  - [ ] Lifecycle: submit, approve, deprecate (+3 typical)
  - [ ] Query: search with filters (+1 typical)
  - [ ] **Total: 5-12 tools per service**

### 4. Parity Test Suite

Create `tests/test_<service>_parity.py` with comprehensive coverage:

- [ ] **Test Structure**:
  ```python
  class TestCreate<Entity>Parity:
      def test_cli_create(self, cli_adapter): ...
      def test_rest_create(self, rest_adapter): ...
      def test_mcp_create(self, mcp_adapter): ...
      def test_surface_parity_create(self, cli_adapter, rest_adapter, mcp_adapter):
          """Verify all three surfaces produce identical structures"""
  ```

- [ ] **Test Coverage Requirements**:
  - [ ] **TestCreate<Entity>Parity** (4 tests) – create via each surface + cross-surface comparison
  - [ ] **TestList<Entity>sParity** (4 tests) – list via each surface + filtering tests
  - [ ] **TestSearch<Entity>sParity** (3 tests) – search via each surface
  - [ ] **TestLifecycleParity** (4 tests) – submit/approve/deprecate operations
  - [ ] **TestUpdate<Entity>Parity** (3 tests) – update via each surface
  - [ ] **TestErrorHandlingParity** (4 tests) – get nonexistent, update nonexistent
  - [ ] **TestDelete<Entity>Parity** (3 tests) – delete draft via each surface
  - [ ] **Target: 20-30 tests total**

- [ ] **Assertion Best Practices**:
  - [ ] Check nested structure: `assert "behavior" in result` and `assert "versions" in result`
  - [ ] Access nested fields: `result["behavior"]["name"]` not `result["name"]`
  - [ ] Verify list structures: `[{"behavior": {...}, "active_version": {...}}]`
  - [ ] Test exception types: `pytest.raises(BehaviorNotFoundError)` not `assert result is None`
  - [ ] Validate metadata presence: `assert "behavior_id" in result["behavior"]`

### 5. CLI Integration

- [ ] **Command Registration** (`amprealize/cli.py`):
  - [ ] Add `<service>` command group: `@cli.group()`
  - [ ] Register subcommands for all operations
  - [ ] Use adapter methods: `adapter = CLI<Service>Adapter(service)`
  - [ ] Format output with `json.dumps(result, indent=2)`
  - [ ] Handle exceptions and print error messages

- [ ] **Example Commands**:
  ```bash
  amprealize <service> create --name "..." --description "..."
  amprealize <service> list --status DRAFT
  amprealize <service> get <id>
  amprealize <service> update <id> --instruction "..."
  amprealize <service> delete <id>
  ```

## Pull Request Review Checklist

Before merging any new service or capability:

- [ ] **Contract Documentation**:
  - [ ] `<SERVICE>_CONTRACT.md` exists and is complete
  - [ ] All request/response schemas documented
  - [ ] Return structures clearly specified
  - [ ] Exception types documented

- [ ] **Implementation Completeness**:
  - [ ] Service runtime exists in `amprealize/<service>_service.py`
  - [ ] Three adapters exist in `amprealize/adapters.py` (CLI, REST, MCP)
  - [ ] All adapters return consistent structures
  - [ ] Telemetry instrumentation present

- [ ] **MCP Tool Manifests**:
  - [ ] All tools exist in `mcp/tools/<service>.*.json`
  - [ ] Tool count matches operations (5-12 typical)
  - [ ] Input schemas complete with actor object
  - [ ] Output schemas match actual return structures

- [ ] **Parity Test Suite**:
  - [ ] `tests/test_<service>_parity.py` exists
  - [ ] 20-30 tests covering all surfaces
  - [ ] All tests passing: `pytest tests/test_<service>_parity.py -v`
  - [ ] Cross-surface comparison tests included

- [ ] **CLI Integration**:
  - [ ] Commands registered in `amprealize/cli.py`
  - [ ] Manual testing: `amprealize <service> <operation> --help`
  - [ ] Error handling validated

- [ ] **Documentation Updates**:
  - [ ] `docs/capability_matrix.md` updated with MCP tool links
  - [ ] Test counts recorded
  - [ ] Parity status marked complete

## Capability Matrix Update Template

After completing parity implementation, update `docs/capability_matrix.md`:

```markdown
### <ServiceName>

**Status:** ✅ Full Cross-Surface Parity Complete

**Evidence:**
- Service Contract: `<SERVICE>_CONTRACT.md`
- Service Runtime: `amprealize/<service>_service.py` (~XXX lines)
- Adapters: CLI/REST/MCP in `amprealize/adapters.py`
- MCP Tools: `mcp/tools/<service>.*.json` (N tools)
- Parity Tests: `tests/test_<service>_parity.py` (N passing tests)

**Operations:**
| Operation | CLI Command | REST Endpoint | MCP Tool | Parity Test |
|-----------|-------------|---------------|----------|-------------|
| Create | `amprealize <service> create` | `POST /v1/<service>` | `<service>.create` | ✅ 4 tests |
| List | `amprealize <service> list` | `GET /v1/<service>` | `<service>.list` | ✅ 4 tests |
| Get | `amprealize <service> get <id>` | `GET /v1/<service>/<id>` | `<service>.get` | ✅ 3 tests |
| Update | `amprealize <service> update <id>` | `PATCH /v1/<service>/<id>` | `<service>.update` | ✅ 3 tests |
| Delete | `amprealize <service> delete <id>` | `DELETE /v1/<service>/<id>` | `<service>.delete` | ✅ 3 tests |
```

## Common Pitfalls & Solutions

### Pitfall 1: Missing MCP Tool Manifests
**Symptom:** Adapters exist but MCP tools not callable from IDE agents.
**Solution:** Create JSON manifests in `mcp/tools/` following `tasks.listAssignments.json` pattern.

### Pitfall 2: Inconsistent Return Structures
**Symptom:** CLI returns `{"name": "..."}` but REST returns `{"behavior": {"name": "..."}`.
**Solution:** Use shared helper methods like `_behavior_detail()` in adapter base class.

### Pitfall 3: Missing Parity Tests
**Symptom:** Adapters work individually but cross-surface consistency unvalidated.
**Solution:** Create `test_surface_parity_<operation>` tests comparing all three surfaces.

### Pitfall 4: Wrong Exception Types in Tests
**Symptom:** Tests use `assert result is None` but service raises `BehaviorNotFoundError`.
**Solution:** Use `with pytest.raises(BehaviorNotFoundError)` to test exceptions.

### Pitfall 5: Nested Structure Misunderstandings
**Symptom:** Tests access `result["name"]` but service returns `{"behavior": {"name": "..."}}`.
**Solution:** Read service code to understand actual return structure before writing tests.

## Governance

**Enforcement:** This checklist is mandatory for all new services. PRs missing parity components will be rejected.

**Updates:** Maintain this checklist as new patterns emerge. Log changes in `PRD_ALIGNMENT_LOG.md`.

**Audit:** Run quarterly parity audits: `grep -r "class.*ServiceAdapter" amprealize/adapters.py` and verify MCP tools + tests exist for each.

---

**Last Updated:** 2025-10-15
**Owner:** Agent Engineering (see `AGENT_ENGINEERING.md`)
**Related:** `contracts/MCP_SERVER_DESIGN.md`, `contracts/ACTION_SERVICE_CONTRACT.md`, `PRD.md` (Milestone 1 requirements)
