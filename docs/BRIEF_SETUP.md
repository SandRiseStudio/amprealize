# Brief AI MCP Server Setup

## ✅ Installation Complete

Brief AI has been successfully installed with MCP support in the amprealize project.

## Installation Details

- **Version**: 0.1.0
- **Installation**: `pip install 'ai-brief[mcp]'`
- **CLI Binary**: `brief` (verified at `/Users/nick/miniconda3/bin/brief`)
- **MCP Server**: `brief-mcp` (verified at `/Users/nick/miniconda3/bin/brief-mcp`)

## Discovered Instruction Files

Brief automatically discovered 3 instruction files in the amprealize project:

| File | Size | Purpose |
|------|------|---------|
| `.github/copilot-instructions.md` | 3,439 bytes | GitHub Copilot instructions |
| `AGENTS.md` | 29,903 bytes | Agent behavioral handbook (primary) |
| `CLAUDE.md` | 28,163 bytes | Claude Projects instructions |

## Claude Desktop MCP Configuration

Configuration file created at:
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Configuration:
```json
{
  "mcpServers": {
    "brief": {
      "command": "brief-mcp"
    }
  }
}
```

**To activate**: Restart Claude Desktop application.

## Brief CLI Commands

### List instruction files
```bash
brief list
```

### Add/update an instruction (updates all files)
```bash
brief update "Always run pre-commit hooks before pushing code"
```

### Validate consistency across files
```bash
brief validate

# Check only latest update
brief validate --check-latest --no-check-all

# Check both overall consistency and latest update
brief validate --check-latest
```

### Initialize Brief in a new project
```bash
cd /path/to/project
brief init
```

## MCP Server Tools (available after Claude Desktop restart)

Once Claude Desktop is restarted, the following Brief tools will be available:

1. **`brief_list`** - List all instruction files
2. **`brief_update`** - Add instructions to all files
3. **`brief_validate`** - Check file consistency
4. **`brief_init`** - Initialize Brief in a project

## Current Status

- ✅ Brief CLI installed and tested
- ✅ MCP server binary verified (`brief-mcp`)
- ✅ Project initialized (3 files discovered)
- ✅ Claude Desktop config created
- ⏳ **Next step**: Restart Claude Desktop to activate MCP tools

## Validation Notes

Current validation shows intentional differences between files:
- `AGENTS.md` (29KB) - Comprehensive behavioral handbook with 50+ behaviors
- `CLAUDE.md` (28KB) - Similar scope, Claude-specific formatting
- `.github/copilot-instructions.md` (3.4KB) - Focused Copilot-specific guidance

These differences are **expected** given the files serve different scopes. Use `brief update` to synchronize common instructions across all three files.

## Example: Synchronizing an instruction

```bash
# Add a new testing requirement to all files
brief update "Run pytest with coverage before committing: pytest --cov=amprealize tests/"

# Preview shows color-coded diffs for each file
# Confirm with 'y' to apply to all files

# Verify the update was applied
brief validate --check-latest
```

## Integration with amprealize Workflows

Brief can now be used to maintain consistency between:
- Agent behaviors in `AGENTS.md`
- Claude Projects guidance in `CLAUDE.md`
- GitHub Copilot conventions in `.github/copilot-instructions.md`

When updating agent behaviors or project conventions, use:
```bash
brief update "behavior_name: description of reusable workflow"
```

This ensures all AI assistants (Claude, Copilot, and custom agents) follow the same patterns.

## Resources

- **GitHub**: https://github.com/Nas4146/brief
- **PyPI**: https://pypi.org/project/ai-brief/
- **Documentation**: See project README for full command reference
- **MCP Docs**: See `docs/MCP_SERVER.md` in Brief repository

---

_Last updated: 2025-10-30_
_Installation verified: Brief v0.1.0 with MCP support_
