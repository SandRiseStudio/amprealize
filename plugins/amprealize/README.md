# Amprealize (Cursor plugin)

This directory is the **Cursor Marketplace plugin** bundle for [Amprealize](https://github.com/SandRiseStudio/amprealize): MCP configuration, curated rules (`.mdc`), and skills (`skills/*/SKILL.md`). It ships beside the main codebase under `plugins/amprealize/` and is registered from the repo root via [.cursor-plugin/marketplace.json](../../.cursor-plugin/marketplace.json).

## Install from Marketplace

When listed, install from the Cursor Marketplace panel (search **Amprealize**). The marketplace entry points at this Git repository; Cursor clones/syncs the plugin definition.

## Install locally (development)

Per [Cursor plugins docs](https://cursor.com/docs/plugins):

```bash
ln -sf /path/to/amprealize/plugins/amprealize ~/.cursor/plugins/local/amprealize
```

Restart Cursor or **Developer: Reload Window**. Confirm rules under **Cursor Settings → Rules**, MCP under **Tools & MCPs**, and skills where your Cursor version surfaces plugin skills.

## Prerequisites for MCP

The bundled [`mcp.json`](mcp.json) starts the server with **`python3 -m amprealize.mcp_server`** so it works in **any** workspace (not only this repo).

1. **Python 3.10+**
2. Install the package (same major version you expect from docs):

   ```bash
   pip install amprealize
   ```

   or use a project virtualenv whose `python` you reference manually if you customize MCP config.

3. Optional: configure services via environment variables or a workspace `.env` (see [MCP client setup](../../docs/MCP_CLIENT_SETUP.md)). Do not commit secrets.

Full tooling parity (launcher script, `PYTHONPATH`, merged `.env.mcp`) is available when you use **`amprealize mcp-server init`** from a **git clone** of this repository; this plugin targets **pip-installed** workflows.

## Plugin vs VS Code extension

| Surface | What you get |
|--------|----------------|
| **This Cursor plugin** | MCP wiring + rules + skills; no extra Activity Bar UI. |
| **[VS Code / Cursor extension](../../extension/)** | Tree views (runs, compliance, etc.), webviews, extension commands. |

Use both if you want IDE chrome **and** marketplace-delivered agent guidance.

## Publish / submit

Maintainers: submit or update the listing at [cursor.com/marketplace/publish](https://cursor.com/marketplace/publish) using the **public GitHub repository URL** for `SandRiseStudio/amprealize`. Open-source and manual review apply per [Marketplace security](https://cursor.com/help/security-and-privacy/marketplace-security).

**Maintainers:** see [SUBMISSION.md](SUBMISSION.md) for the marketplace publish URL and CI validation.

## References

- [Plugins reference](https://cursor.com/docs/reference/plugins.md)
- [MCP client setup](../../docs/MCP_CLIENT_SETUP.md)
- [AGENTS.md](../../AGENTS.md) (full handbook)
