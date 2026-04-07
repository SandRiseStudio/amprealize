# Secrets Management Plan (CLI & SDK Integrations)

## Goals
- Enforce `behavior_externalize_configuration` and compliance checklist requirements for secrets handling.
- Provide consistent guidance for CLI users, SDK consumers, and platform services.
- Ensure secrets are never stored in source control or plaintext logs, with auditable rotation procedures.

## Secret Types
| Secret | Examples | Storage Location |
| --- | --- | --- |
| API tokens | `AMPREALIZE_API_TOKEN`, MCP client creds | Managed secret manager (AWS Secrets Manager, GCP Secret Manager) |
| CLI auth tokens | Device codes, refresh tokens | Local OS keychain (macOS Keychain, Windows Credential Manager) |
| SDK credentials | Service accounts for automation | Vault namespace per environment |
| Third-party connectors | LLM provider keys, embedding API keys | Secret manager with strict IAM policies |

## CLI Handling
- CLI performs device login (`amprealize auth login`) to exchange for short-lived access + refresh tokens.
- Tokens stored via `keyring` integration (platform-specific secure storage); fallback requires explicit `--allow-plaintext` flag (disabled by default).
- Commands log token scope changes using `amprealize record-action` for compliance traceability.
- `amprealize scan-secrets` shells out to the shared Gitleaks hook (`pre-commit run gitleaks --all-files`) and emits a JSON/table report that is archived under `security/scan_reports/` when `--output` is provided.
- Auto-rotation: refresh tokens valid 7 days; CLI prompts rotation on expiry.

## SDK Guidelines
- Language SDKs load credentials from environment variables pointing to secret-manager mounts (e.g., `/var/run/secrets/amprealize/token`).
- SDK initialization requires explicit `credentials_provider` parameter; defaults to Vault fetcher.
- Rotations triggered by platform events (e.g., secret revoke) propagate via webhook; SDK caches refresh if token expiration < 5 minutes.

## Platform/API Policies
- Secrets never written to telemetry payloads or audit logs (fields marked as redacted, hashed).
- Configuration updates require dual-approval workflow (Strategist + Compliance) logged via ActionService.
- Rotation runbook stored in `docs/runbooks/secret_rotation.md` with step-by-step instructions.
- **Gateway header stripping**: Nginx strips client-supplied `X-Tenant-Id` and `X-User-Id` at all proxy locations to prevent identity spoofing. Only `AuthMiddleware` and `TenantMiddleware` may set these headers after token validation. See `docs/GATEWAY_ARCHITECTURE.md`.

## Source Control Guardrails
- Pre-commit hook (`.pre-commit-config.yaml`) runs Gitleaks with redaction and whitespace fixers; developers must run `pre-commit install` before committing.
- `scripts/scan_secrets.sh` provides a deterministic wrapper used by CI (`amprealize scan-secrets`) and local workflows; exit status blocks merges if any findings remain.
- MCP adapters call `security.scanSecrets` to enforce the same guardrail inside IDE integrations; requests must include the invoking surface so telemetry can attribute remediation SLAs.
- MCP tool contract (`mcp/tools/security.scanSecrets.json`) mirrors the CLI inputs/outputs so IDEs can persist audit-ready reports alongside ActionService entries.
- Suppression requires Compliance approval and an audit note referencing the remediation action logged via ActionService.
- `.gitignore` tracks secret-prone files (`.env`, `.venv`, generated logs); additions must cite `behavior_prevent_secret_leaks`.

## Compliance & Monitoring
- Metrics: `secret_rotation_success_total`, `secret_rotation_failure_total`, `cli_plaintext_storage_attempts_total`.
- Alerts when plaintext flag used more than once per user per day or when rotations fail.
- Quarterly review of secret access logs by Compliance agent; findings logged in `PRD_ALIGNMENT_LOG.md`.

## Implementation Tasks
- Integrate CLI with OS keychain using `keyring` (Python) or native APIs.
- Implement device code flow for MCP/REST authentication (`/v1/auth/device`).
- Provide SDK helper libs (`@amprealize/auth`) to wrap rotations and secret fetch.
- Document integration steps in `docs/authentication/README.md` and reference in onboarding guides.

## Behaviors & Playbooks
- Reference `behavior_externalize_configuration`, `behavior_rotate_leaked_credentials`, and update agent playbooks to ensure checks focus on secret hygiene.
- Add checklist step to confirm `amprealize record-action` logged after each rotation or secret scope change.
