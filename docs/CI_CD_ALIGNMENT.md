# CI/CD Alignment with Local Test Infrastructure

**Status**: ✅ Complete
**Date**: 2025-01-XX
**Behaviors**: `behavior_orchestrate_cicd`, `behavior_align_storage_layers`, `behavior_prevent_secret_leaks`

## Changes Made

### 1. Port Mappings (5433-5437 → 6433-6438)
Updated `.github/workflows/ci.yml` to match local test infrastructure:

| Service | Old Port | New Port | Container Port |
|---------|----------|----------|----------------|
| postgres-behavior | 5433 | **6433** | 5432 |
| postgres-workflow | 5434 | **6434** | 5432 |
| postgres-action | 5435 | **6435** | 5432 |
| postgres-run | 5436 | **6436** | 5432 |
| postgres-compliance | 5437 | **6437** | 5432 |
| postgres-telemetry | 5432 | **6438** | 5432 |
| redis | 6379 | **6479** | 6379 |

**Rationale**: Avoids conflicts with local dev databases running on 5433-5437.

### 2. Memory Limits
Added memory limits to all service containers:
- PostgreSQL services: 256MB each
- Redis: 128MB

**Rationale**: Prevents memory exhaustion that crashed local testing at ~22% completion. GitHub Actions runners have 7GB RAM, so these limits are conservative and prevent runaway resource usage.

### 3. Database Name Environment Variables
Added missing `AMPREALIZE_PG_DB_*` environment variables for all 6 database services:
- `AMPREALIZE_PG_DB_BEHAVIOR: amprealize_behavior`
- `AMPREALIZE_PG_DB_WORKFLOW: amprealize_workflow`
- `AMPREALIZE_PG_DB_ACTION: amprealize_action`
- `AMPREALIZE_PG_DB_RUN: amprealize_run`
- `AMPREALIZE_PG_DB_COMPLIANCE: amprealize_compliance`
- `AMPREALIZE_PG_DB_TELEMETRY: amprealize_telemetry`

**Rationale**: These variables are required by the PostgresPool connection logic and were previously missing from CI configuration.

### 4. Health Check Port Updates
Updated service readiness wait loop to check new ports:
```bash
for port in 6433 6434 6435 6436 6437 6438; do
  timeout 30 bash -c "until pg_isready -h localhost -p $port; do sleep 1; done" || exit 1
done
```

Redis health check updated to port 6479:
```bash
timeout 30 bash -c "until redis-cli -h localhost -p 6479 ping; do sleep 1; done" || exit 1
```

## What Stays Different: Parallel vs Serial Execution

**CI**: `pytest -n auto` (parallel execution for speed)
**Local**: `pytest` (serial execution with 60s timeout for stability)

**Decision**: Keep this difference.
- CI runners have 7GB RAM and can handle parallel execution safely with session-scoped mocks
- Local serial execution provides better debugging experience and timeout enforcement
- Session-scoped `mock_sentence_transformer` fixture in `tests/conftest.py` is autouse and applies to all tests regardless of execution mode

## Pre-Commit Integration

Both CI and local use `.pre-commit-config.yaml`:
- **Local**: Run via `./scripts/install_hooks.sh` → `pre-commit install`
- **CI**: Runs via dedicated `pre-commit` job in workflow

Secret scanning integrated via:
- `./scripts/scan_secrets.sh` (wraps gitleaks)
- Pre-commit hook catches leaks before commit
- CI runs full scan on all files

## Validation Checklist

Before merging these changes:

- [ ] Verify CI workflow syntax is valid
- [ ] Confirm all port references updated (6433-6438, 6479)
- [ ] Ensure all `AMPREALIZE_PG_DB_*` variables present
- [ ] Check memory limits don't cause OOM in CI
- [ ] Run local tests to confirm no regressions
- [ ] Trigger CI workflow and verify services start correctly
- [ ] Confirm session-scoped mocks work in parallel CI execution
- [ ] Validate test results match local outcomes

## Rollback Plan

If CI fails after these changes:

1. **Port conflicts**: Check if GitHub Actions runners have conflicting services on 6433-6438
2. **Memory limits too strict**: Remove `--memory` options or increase limits
3. **Parallel execution issues**: Change `pytest -n auto` → `pytest` (serial)
4. **Database connection failures**: Verify `AMPREALIZE_PG_DB_*` env vars are correct

## References

- Local test infrastructure: `docker-compose.test.yml`
- Test runner script: `scripts/run_tests.sh`
- Model mocking: `tests/conftest.py` lines 26-50
- Storage layer fixes: `amprealize/storage/postgres_pool.py` lines 95-114
- Search bug fix: `amprealize/behavior_service.py` lines 750-822
- Safe test commands: `SAFE_TEST_COMMANDS.md`
- Git strategy: `docs/GIT_STRATEGY.md`
- Secrets management: `SECRETS_MANAGEMENT_PLAN.md`

## Next Steps

1. **Commit changes**: `git add .github/workflows/ci.yml CI_CD_ALIGNMENT.md`
2. **Run pre-commit**: `pre-commit run --all-files` (verify gitleaks passes)
3. **Push to feature branch**: Test CI on non-main branch first
4. **Monitor CI run**: Check GitHub Actions logs for service startup, port binding, test execution
5. **Verify test parity**: Ensure CI test results match local (9/9 core CLI tests passing)
6. **Document outcomes**: Update `PROGRESS_TRACKER.md` and `PRD_ALIGNMENT_LOG.md`

---

**Compliance**: This change satisfies `behavior_orchestrate_cicd` by aligning CI configuration with validated local test infrastructure, and `behavior_prevent_secret_leaks` by maintaining pre-commit integration across both environments.
