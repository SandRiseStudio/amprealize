# Agent Handbook Reference

Long-form guidance moved out of always-loaded `AGENTS.md` so agents follow the operating contract reliably.

| Document | Contents |
|----------|----------|
| [mcp-startup.md](mcp-startup.md) | Amprealize MCP session startup and tool catalog |
| [design-workflow.md](design-workflow.md) | Design skill packs (Layers, Superdesign, Taste, Impeccable, Refactoring UI) |
| [behavior-lifecycle.md](behavior-lifecycle.md) | Roles, lifecycle, proposals, checklists, research appendix |
| [behavior-catalog.md](behavior-catalog.md) | Full quick-trigger table and behavior definitions |

Seed behaviors after catalog changes: `python scripts/seed_behaviors_from_agents_md.py` (use `--apply-context` when Neon is the canonical DB).

Sync instruction artifacts (handbook copy, MCP tool manifests, workspace Cursor rule): `python scripts/sync_agent_instruction_files.py` from the OSS repo. Edit compact `AGENTS.md` / `CLAUDE.md` / `.github/copilot-instructions.md` per repo intentionally; do not run `brief update` to mirror the same text into all three.
