---
name: amprealize-mcp-server-init
description: Regenerate IDE MCP config files for Amprealize from a repository clone. Use when setting up a new machine, after pulling MCP-related changes, or when switching between launcher script and module mode.
---

# Regenerate MCP client configs (clone)

When the workspace is a **clone** of the Amprealize repository (not only `pip install`):

1. At the **repository root**, run:

   ```bash
   amprealize mcp-server init
   amprealize mcp-server doctor
   ```

2. This writes/updates project-local configs (e.g. `.cursor/mcp.json`, `.vscode/mcp.json`, `.claude/mcp.json`) using the repo launcher when appropriate.
3. Reload the editor MCP connection after changes.

See [docs/MCP_CLIENT_SETUP.md](https://github.com/SandRiseStudio/amprealize/blob/main/docs/MCP_CLIENT_SETUP.md) for Cursor vs VS Code differences.
