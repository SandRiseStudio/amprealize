# Code Style and Conventions

## General
- **Behaviors**: Follow the "behaviors" defined in `AGENTS.md`. This is the core philosophy of the project.
- **Roles**: Adhere to the Strategist -> Teacher -> Student workflow.
- **Documentation**: Keep `PRD.md`, `BUILD_TIMELINE.md`, and `PROGRESS_TRACKER.md` up to date.

## Python
- **Type Hints**: Use type annotations extensively.
- **Testing**: Use `pytest`. Ensure tests cover CLI, REST, and MCP parity.
- **Linting**: Use `pre-commit` hooks (likely includes `black`, `isort`, `flake8` or `ruff`).

## TypeScript (Extension)
- **Linting**: ESLint.
- **Style**: Standard TypeScript conventions.

## Agent Etiquette (from AGENTS.md)
- **Testing**: Run relevant checks after changes.
- **Environment**: No hardcoded secrets; use env vars.
- **Logging**: Structured logging with run IDs.
- **Metrics**: Instrument telemetry for success targets.
