# Git Strategy & Guardrails

## Purpose
Establish a platform-agnostic Git operating model for Strategist → Teacher → Student agents so the amprealize project (and anything built with it) ships with reproducible history, secret hygiene, and consistent review practices—regardless of whether the remote lives on GitHub, GitLab, Bitbucket, or self-hosted Git.

## Pillars
1. **Predictable history** – Main stays releasable; feature branches capture isolated work; merge strategies remain consistent across hosting providers.
2. **Auditable changes** – Every commit references an action log entry and behaviors, echoing `contracts/ACTION_REGISTRY_SPEC.md` and `PROGRESS_TRACKER.md` requirements.
3. **Secret & env hygiene** – Enforce `behavior_prevent_secret_leaks` and `behavior_rotate_leaked_credentials` with automated scans and documented remediation.
4. **Cross-surface parity** – CLI, UI, MCP tools, and automation (CI/CD) apply the same rules for branch naming, reviews, and guardrails.

## Branching Model
- **`main`** (or host-specific default) is protected, fast-forward merges only via approved reviews, and must pass tests + secret scans.
- **Feature branches** follow `role/short-slug` (e.g., `student/mfa-dashboard`, `strategist/git-strategy-doc`). Keep them short-lived; delete after merge.
- **Release branches** (optional) use `release/YYYY-MM-DD` and capture stabilization work. Tag releases with semantic version or milestone ID.
- **Hotfix branches** derive from latest release tag (`hotfix/<issue>`), cherry-pick into `main` after verification.

## Commit Workflow
1. Run `pre-commit install` once per clone; hooks enforce gitleaks, whitespace, and formatting. CLIs must fail the commit if the hook exits non-zero.
2. Before committing:
   - `scripts/scan_secrets.sh` (or `pre-commit run --all-files`) for manual assurance.
   - `git status` to confirm only intentional files staged.
3. Craft commit messages as `type(scope): summary` or `Summary sentence`. Include ActionService action ID in body when available (e.g., `Action: act_12345`).
4. Reference behaviors in the summary or body (e.g., `Behaviors: behavior_prevent_secret_leaks, behavior_update_docs_after_changes`).
5. Push with `git push origin <branch>`; hosting differences (GitHub/GitLab/Bitbucket) shift only in remote URL format.

## Pull / Merge Requests
- Require at least one reviewer from a different role (Strategist, Teacher, Student) to ensure cross-discipline alignment.
- CI pipeline runs:
  - `pre-commit run gitleaks --all-files --hook-stage manual`
  - Unit/integration tests (`pytest`, `npm run build`, etc.)
  - `amprealize scan-secrets --format json --fail-on-findings`
- Merge via fast-forward or squash depending on host policy. Always ensure action logs (`amprealize record-action ...`) are updated prior to merge.

## Secret & Env Protection
- `.gitignore` excludes `.env*`, `.venv`, logs, and `security/scan_reports/`.
- Gitleaks hook (configured in `.pre-commit-config.yaml`) scans staged files locally and in CI.
- Findings must be remediated immediately:
  - Remove secret, rotate credential, add suppression with Compliance sign-off if necessary.
  - Log remediation using `amprealize record-action --artifact <file> --summary "Rotate leaked credential" --behaviors behavior_prevent_secret_leaks,behavior_rotate_leaked_credentials`.
- For historical leaks, follow `SECRETS_MANAGEMENT_PLAN.md` (`git filter-repo`, revoke tokens, notify Compliance).

## Remote-Agnostic Guidance
| Task | GitHub | GitLab | Bitbucket | Self-hosted Git |
| --- | --- | --- | --- | --- |
| Create remote | `gh repo create` (or UI) | `glab repo create` / UI | `bb create repo` (CLI) / UI | `ssh git@example.com mkdir repo.git` |
| Protect branches | Settings → Branch protection rules | Settings → Repository → Protected branches | Settings → Branch permissions | Server config (`gitolite`, `gitea`, etc.) |
| CI enforcement | GitHub Actions / other runner | GitLab CI/CD | Bitbucket Pipelines | Jenkins/Buildkite/etc. |
| Secret scanning | Built-in + pre-commit | Security scanning + pre-commit | Pipelines + pre-commit | Use `scripts/scan_secrets.sh` in CI |

## Agent Role Expectations
- **Strategist**: Define branch plan, map tasks to behaviors, ensure action logging before approvals.
- **Teacher**: Review commits/PRs, verify behaviors cited, and confirm telemetry/secret scans ran.
- **Student**: Execute commits, run pre-commit + tests, provide evidence in PR descriptions.
- All roles keep `PROGRESS_TRACKER.md` up to date with branch milestones and reference the git strategy when handing off work.

## Automation & Tooling Hooks
- After cloning, run `./scripts/install_hooks.sh` to wire `git commit`/`git push` into the shared pre-commit checks (gitleaks, whitespace fixers).
- CI/CD pipelines (GitHub Actions, GitLab CI, Bitbucket Pipelines) must execute the same guardrails (`pre-commit run --all-files`, `pytest`, `npm run build`, planned `amprealize scan-secrets`) before merge.
- Add `pre-commit` job to CI template; fail builds on any gitleaks findings.
- Integrate `amprealize scan-secrets` into pipeline stage `sec-scan`. Upload JSON to `security/scan_reports/` (ignored by Git) for audit.
- Optionally configure server-side hooks (pre-receive) to run gitleaks for centralized enforcement.
- Mirror repositories across hosts (GitHub ↔ GitLab) by reusing SSH keys or tokens stored via the secrets plan.

## Incident Response
1. Trigger `behavior_prevent_secret_leaks` immediately.
2. Notify Compliance with affected branch/commit hashes.
3. Rotate credentials and document steps in `PRD_ALIGNMENT_LOG.md` + ActionService entry.
4. Force-push cleaned history if required (coordinate with stakeholders to avoid data loss).

## References
- `AGENTS.md` behaviors: `behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials`, `behavior_update_docs_after_changes`.
- `SECRETS_MANAGEMENT_PLAN.md` for secret rotation runbooks.
- `.pre-commit-config.yaml` and `scripts/scan_secrets.sh` for tooling setup.
- `contracts/ACTION_REGISTRY_SPEC.md` (`security.scanSecrets`) for reproducible scanning actions.

_Last updated: 2025-10-15_
