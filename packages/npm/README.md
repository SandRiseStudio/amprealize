# Amprealize CLI

AI-powered developer tooling and task orchestration.

## Installation

```bash
npm install -g @amprealize/cli
```

This npm package is a wrapper that manages the Python-based Amprealize CLI. Python 3.10+ is required and will be detected automatically.

### Prerequisites

- **Node.js** 18+ (for the npm wrapper)
- **Python** 3.10+ (for Amprealize itself)

The wrapper will automatically install the Python package on first use if not already present.

## Usage

```bash
# Initialize a new project
amprealize init

# AI-powered setup wizard (requires API key)
amprealize wizard

# Check installation health
amprealize doctor

# Start the MCP server for VS Code/Cursor integration
amprealize mcp-server

# Show help
amprealize --help
```

## VS Code / Cursor Integration

Add to your VS Code settings.json:

```json
{
  "github.copilot.chat.mcpServers": {
    "amprealize": {
      "command": "amprealize",
      "args": ["mcp-server"]
    }
  }
}
```

## Alternative Installation Methods

### pip (Python)

```bash
pip install amprealize
```

### Homebrew (macOS)

Requires a published tap repository (for example `SandRiseStudio/homebrew-amprealize`; see `packages/homebrew/README.md`).

```bash
brew tap sandrisestudio/amprealize
brew install amprealize
```

## Configuration

Configuration is stored in YAML format:

- `~/.amprealize/config.yaml` - User-level configuration
- `.amprealize/config.yaml` - Project-level configuration

Run `amprealize init` to create a configuration file interactively.

## Links

- [Documentation](https://breakeramp.ai/docs)
- [GitHub](https://github.com/SandRiseStudio/amprealize)
- [PyPI](https://pypi.org/project/amprealize/)

## License

Apache-2.0
