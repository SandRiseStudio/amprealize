# Contributing to Amprealize

Thanks for contributing to Amprealize.

This repository is the open-source home for the Amprealize platform and follows a **behavior-driven development workflow**. Before making substantial changes, please review the project handbook in [`AGENTS.md`](../AGENTS.md).

## Before You Start

- Read [`AGENTS.md`](../AGENTS.md) for role selection, behavior usage, and workflow expectations
- Review relevant architecture and contract documents before changing APIs or core workflows
- Never hardcode secrets or credentials
- Run secret scanning and tests before opening a pull request
- Keep changes focused and well-scoped

## Development Setup

### Prerequisites

- Python 3.10+
- `pip` or `pipx`
- Git
- Recommended: virtual environment support

### Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/install_hooks.sh
```

### Running the Project

```bash
uvicorn amprealize.api:app --reload
```

### Running Tests

```bash
pytest
```

### Running Secret Scans

```bash
bash scripts/scan_secrets.sh
```

### MCP tool manifests (release / PyPI)

Canonical MCP tool JSON lives in `mcp/tools/`. The Python wheel also bundles copies under `amprealize/mcp_tool_manifests/` so `pip install amprealize` works without the full monorepo. After you add or edit manifests in `mcp/tools/`, run:

```bash
python scripts/sync_mcp_tool_manifests.py
```

CI runs `scripts/verify_mcp_manifests_sync.py` to ensure the two trees match.

## Workflow Expectations

### 1. Follow the Behavior Handbook

Amprealize uses role-based execution:

- **Student** — routine implementation using existing behaviors
- **Teacher** — documentation, examples, review, and validation
- **Metacognitive Strategist** — pattern extraction, architecture, and new behaviors

When applicable, cite behaviors used during implementation, review, or documentation work.

### 2. Keep Cross-Surface Consistency

Many Amprealize capabilities exist across multiple surfaces:

- CLI
- REST API
- MCP tools
- Web UI
- VS Code extension

When changing shared functionality, consider parity impacts and add or update tests accordingly.

### 3. Prefer Small, Reviewable Changes

Please avoid mixing unrelated refactors with feature work. Small diffs are easier to review, test, and revert.

## Pull Request Process

1. Fork or branch from the latest default branch
2. Make focused changes
3. Run relevant tests locally
4. Run secret scanning
5. Update documentation when behavior, APIs, or workflows change
6. Open a pull request using the PR template
7. Reference relevant issues, stories, or tasks

## Commit Guidance

Use clear, descriptive commit messages. Conventional commits are encouraged, for example:

- `feat: add behavior retrieval summary to CLI`
- `fix: align auth session handling in MCP tools`
- `docs: add OSS quick start to README`

## Documentation Expectations

Update documentation when you change:

- public APIs
- developer workflows
- setup instructions
- behavior or governance expectations
- cross-surface capabilities

Common files to review include:

- [`README.md`](../README.md)
- [`AGENTS.md`](../AGENTS.md)
- [`BUILD_TIMELINE.md`](../BUILD_TIMELINE.md)
- service contract documents in the repo root

## Security

If you discover a vulnerability, do **not** open a public issue. Please follow the process in [`SECURITY.md`](../SECURITY.md).

## Code of Conduct

By participating in this project, you agree to follow the standards in [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md).
