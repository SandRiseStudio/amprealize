---
name: amprealize-mcp-doctor
description: Run Amprealize MCP smoke checks after client or env changes. Use when MCP tools fail to load, after upgrading the amprealize package, or when validating stdio MCP wiring.
---

# Amprealize MCP doctor

1. Ensure Python env has `amprealize` installed (`pip install amprealize` or project venv).
2. From the project using MCP, run:

   ```bash
   amprealize mcp-server doctor
   ```

3. If using a **git clone** of Amprealize, prefer `amprealize mcp-server init` from the repo root to regenerate `.cursor/mcp.json` and friends (see [MCP client setup](https://github.com/SandRiseStudio/amprealize/blob/main/docs/MCP_CLIENT_SETUP.md)).
4. In Cursor, check **Output → MCP** logs for JSON-RPC or import errors.

Reference: [docs/MCP_CLIENT_SETUP.md](https://github.com/SandRiseStudio/amprealize/blob/main/docs/MCP_CLIENT_SETUP.md).
