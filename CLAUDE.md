# Claude adapter

**Canonical instructions**: [`AGENTS.md`](AGENTS.md) (compact operating contract).

**Full handbook** (not always loaded—open when needed):

- [`docs/agent-handbook/README.md`](docs/agent-handbook/README.md)
- [`docs/agent-handbook/behavior-catalog.md`](docs/agent-handbook/behavior-catalog.md) — all behaviors and quick triggers
- [`docs/agent-handbook/behavior-lifecycle.md`](docs/agent-handbook/behavior-lifecycle.md) — roles, lifecycle, checklists
- [`docs/agent-handbook/mcp-startup.md`](docs/agent-handbook/mcp-startup.md)
- [`docs/agent-handbook/design-workflow.md`](docs/agent-handbook/design-workflow.md)

---

## Mandatory before every task

Use Amprealize MCP when available:

```
behaviors.getForTask(task_description="...", role="Student")
```

CLI fallback: `amprealize behaviors get-for-task "..." --role Student`

Then follow `AGENTS.md`: declare role, cite `behavior_name` (Role) in output, run MCP startup for platform work.

---

## Claude-specific notes

- Amprealize MCP tools work in Claude Desktop / VS Code Copilot Chat; prefer them over guessing CLI.
- Device login for MCP may auto-approve in agent environments; only ask the user to visit a URL if polling fails and the tool requires manual consent.
- After handbook or behavior-catalog edits, seed: `python scripts/seed_behaviors_from_agents_md.py` (add `--apply-context` when Neon is the canonical DB).

---

_Last updated: 2026-05-26 — adapter only; see `AGENTS.md`_
