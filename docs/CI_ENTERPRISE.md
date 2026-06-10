# Enterprise overlay CI and skip remediation

This document complements [TESTING_GUIDE.md](./TESTING_GUIDE.md). It describes **optional** GitHub Actions workflows that reduce skips for enterprise-gated tests, load tests, and parity jobs that need real Postgres/Redis.

## Enterprise overlay workflow

**File:** `.github/workflows/ci-enterprise.yml`

**Purpose:** Install `amprealize-enterprise` **on top of** the OSS `amprealize` editable install, then run a **curated** pytest list. The full OSS suite is **not** run here: many tests assert `HAS_ENTERPRISE is False` and would fail once the enterprise package overlays the `amprealize` namespace.

**Curated targets:** [`scripts/enterprise_gated_pytest_files.txt`](../scripts/enterprise_gated_pytest_files.txt) (one test module path per line).

**Triggers:**

- `workflow_dispatch` (manual), with optional inputs `enterprise_repo` and `enterprise_ref`
- Weekly schedule (Monday 06:00 UTC)
- Push to `main` when this workflow or the curated file changes

**Secrets:**

- `AMPREALIZE_ENTERPRISE_CHECKOUT_PAT` (optional): fine-grained PAT with `contents: read` on `amprealize-enterprise` if `GITHUB_TOKEN` cannot access that repo (private repo or different org).

**Local reproduction (aligned with CI):**

```bash
cd /path/to/amprealize
# One-shot: test stack + guard + pip installs + curated pytest (same order as ci-enterprise.yml)
./scripts/run_tests.sh --breakeramp --env test --enterprise
```

Or step-by-step with your own venv:

```bash
# From sibling checkouts (same layout as CI)
cd /path/to/amprealize
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,postgres,telemetry,semantic]"
pip install -e "../amprealize-enterprise[dev,postgres,telemetry,semantic,crypto]"
# Start Postgres + Redis (e.g. ./scripts/run_tests.sh --breakeramp --env test --check-only)
export AMPREALIZE_BEHAVIOR_PG_DSN=postgresql://...
pytest $(grep -v '^#' scripts/enterprise_gated_pytest_files.txt | grep -v '^$')
```

Override the enterprise checkout path shown in MCP guidance copy with:

```bash
export AMPREALIZE_ENTERPRISE_REPO_PATH=/absolute/path/to/amprealize-enterprise
```

## Load tests (opt-in)

**File:** `.github/workflows/ci-load-opt-in.yml`

Sets `AMPREALIZE_RUN_LOAD_TESTS=1` and `AMPREALIZE_LOAD_RELAXED=1`, brings up Postgres + Redis + telemetry (same ports as main CI), runs Alembic, then `pytest tests/load/`. Many cases still skip without Kafka, Podman, or a live API—see `tests/load/conftest.py`.

**Triggers:** `workflow_dispatch` and weekly Sunday 07:00 UTC.

## Service parity job (main CI)

**File:** `.github/workflows/ci.yml` — job `test-parity`

This job now uses **Postgres (behavior + telemetry + metrics), Redis**, `pip install -e ".[dev,postgres,telemetry,semantic]"`, and **Alembic migrations** before parity pytest, so fewer tests skip for missing `AMPREALIZE_*_PG_DSN` / DB reachability.

## Skip catalog (high level)

| Category | Typical cause | Mitigation |
|----------|---------------|------------|
| Enterprise-only services | `OrganizationService` / `SettingsService` / etc. are absent without `amprealize-enterprise` | Enterprise workflow + local second install |
| Load / soak | `tests/load/*` skipped unless `AMPREALIZE_RUN_LOAD_TESTS=1` | Load workflow or export var locally |
| Per-service DSN | Parity/integration skips when env DSN unset | `run_tests.sh`, BreakerAmp `--env test`, or CI service env block |
| Optional Python deps | e.g. `sentence-transformers`, `scikit-learn`, `prometheus_client` | `pip install -e ".[dev,postgres,telemetry,semantic]"` (see `pyproject.toml` optional deps) |
| Staging / manual | OAuth, stored tokens, gateway not up | Configure secrets + stack per skip message |
| Not yet implemented | Skip message says adapter or CLI not implemented | Product work: [skip inventory + MCP goal steps](./testing/NOT_YET_IMPLEMENTED_SKIP_INVENTORY.md) |

## Optional dependency audit (CI defaults)

Main Python CI uses `pip install -e ".[dev,postgres,telemetry,semantic]"`, which pulls:

- **postgres**: SQLAlchemy, psycopg2, Alembic, prometheus_client
- **telemetry**: kafka-python, duckdb, psycopg2, pytz
- **semantic**: sentence-transformers, faiss-cpu

Heavy **torch/scipy** remain under `[ml]` only—retrieval-quality tests that need live models may still skip without `[ml]`.
