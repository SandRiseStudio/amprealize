# SDK Scope & Distribution Plan

## Goal
Define the cross-surface SDK strategy so client teams (Web, CLI, VS Code, automation) and partners know exactly which languages, packages, and release cadences to expect before Milestone 1. This document ties back to the integration expectations in `PRD.md` and ensures the SDK roadmap stays in lockstep with AgentAuth and ActionService contracts.

## Supported Languages
| Language | Package Name | Status | Planned Milestone | Primary Consumers |
| --- | --- | --- | --- | --- |
| Python | `amprealize` (monorepo package) | ✅ Available (service stubs, auth, telemetry) | Milestone 0 | CLI, automation scripts, backend services |
| TypeScript / JavaScript | `@amprealize/sdk` | 🚧 In progress (API client + IDE helpers) | Milestone 1 (Internal Alpha) | VS Code extension, web console, partner integrations |
| Go | `github.com/amprealize/sdk-go` | 🔍 Exploration | Milestone 2 (External Beta) | Infrastructure automation, self-hosted agents |
| REST / MCP | OpenAPI + MCP tool schemas | ✅ Published | Milestone 0 | Any language via generated clients |

> Future languages inherit the same contract surfaces (ActionService, BehaviorService, AgentAuthService) and must satisfy parity requirements in `docs/capability_matrix.md`.

## Versioning & Release Cadence
- **Semantic Versioning (`MAJOR.MINOR.PATCH`)** governs all SDKs.
  - Pre-1.0 releases use `0.x.y` with breaking changes allowed but documented in release notes.
  - Once Milestone 2 stabilizes, bump to `1.0.0` for GA parity across surfaces.
- **Release Channels**
  - Python: tagged Git commits mirrored to PyPI (`amprealize`), with `python -m build` + `twine upload` pipeline (CI task targeted for Milestone 1).
  - TypeScript: npm package `@amprealize/sdk`, using `pnpm publish --access public` once IDE preview ships.
  - Go: module tags pushed to Git, consumed via `go get`.
- **Compatibility Policy**
  - SDKs maintain compatibility with at least the last **two** minor versions of ActionService and AgentAuthService schemas.
  - Breaking auth or telemetry changes require synchronized releases across all languages and must be announced ≥2 weeks ahead of rollout.

## Distribution & Packaging
- **Artifact Registry**: Use organization accounts on PyPI and npm; Go module served from the repo (backed by GitHub/GitLab mirror).
- **Build Metadata**: Each publish embeds commit SHA, ActionService schema version, and telemetry schema checksum for traceability.
- **Automated Pipelines**:
  - Add `sdk-release` workflow invoking `amprealize record-action` with release metadata once CI completes.
  - Store package checksums and changelogs in `docs/releases/<version>.md` (to be created during first publish).

## Integration Alignment
- **CLI**: continues bundling the Python `amprealize` package; CLI releases are locked to the SDK minor version (e.g., CLI `0.4.x` requires SDK `0.4.x`).
- **Web App**: consumes REST endpoints plus the upcoming `@amprealize/sdk` for shared auth helpers; TypeScript SDK provides Node/browser builds with tree-shaking.
- **VS Code Extension**: depends on `@amprealize/sdk` with MCP adapters; extension preview uses beta tags (`0.x`) until parity tests pass.
- **Automation & Partners**: REST/MCP specs remain the fallback; once Go SDK reaches beta, infra teams can adopt it for replay automation.

## Documentation & Samples
- Host language-specific quickstarts under `docs/sdk/examples/<language>/` (to be populated alongside releases).
- Update `docs/capability_matrix.md` and `PROGRESS_TRACKER.md` whenever a new SDK reaches preview/GA.
- Tie release announcements to the action registry: `amprealize record-action --artifact docs/releases/<version>.md ...` with behaviors `behavior_update_docs_after_changes`, `behavior_git_governance`.

## Open Follow-Ups
- Set up PyPI/npm publishing credentials via `SECRETS_MANAGEMENT_PLAN.md` workflows (Milestone 1).
- Author TypeScript SDK design doc covering MCP wrappers and fetch layers.
- Define automated contract validation ensuring SDK clients stay in sync with proto/JSON schemas.

_Last updated: 2025-10-15_
