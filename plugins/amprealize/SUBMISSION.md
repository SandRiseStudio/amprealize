# Cursor Marketplace submission (maintainers)

Amprealize ships as a **Git-based Cursor plugin** (not a VSIX to a separate “Cursor extension store”).

## Submit or update

1. Ensure `main` (or your release branch) contains valid manifests:
   - [`../../.cursor-plugin/marketplace.json`](../../.cursor-plugin/marketplace.json)
   - [`plugins/amprealize/.cursor-plugin/plugin.json`](./.cursor-plugin/plugin.json)
   - [`plugins/amprealize/mcp.json`](./mcp.json)
2. Open **[cursor.com/marketplace/publish](https://cursor.com/marketplace/publish)**.
3. Submit the **public GitHub repository URL**: `https://github.com/SandRiseStudio/amprealize`
4. Respond to Cursor review feedback (security and quality review applies).

## CI validation

On GitHub Actions, run workflow **CI/CD Pipeline** manually with **publish_cursor** enabled to validate JSON and required plugin files before or after you submit.

## References

- [Cursor Plugins reference](https://cursor.com/docs/reference/plugins.md)
- [Plugin README](./README.md)
