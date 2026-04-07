# Brief - Standalone Open Source Project

**Project Name:** `brief` (package: `ai-brief`)

**Tagline:** "Brief your AI coding assistants once, update them all."

**Status:** 🟢 **v0.1.0 - Production Ready** (October 27, 2025)

**Target Audience:** Developers using AI coding assistants who want consistent behavior across tools

---

## Problem Statement

Developers working with multiple AI coding assistants (Claude Projects, GitHub Copilot, Cursor, custom MCP servers) need to maintain instruction files in multiple places:

- `.github/copilot-instructions.md` (GitHub Copilot)
- `CLAUDE.md` or `.clinerules` (Claude Desktop)
- `AGENTS.md` (Custom agent behaviors)
- `.cursorrules` (Cursor)
- Custom MCP server instructions

**Pain points:**
1. 🔄 Same instruction updates must be manually copied to 3-5 different files
2. 🧠 Each file needs project-specific context (file paths, architecture, conventions)
3. 📝 No validation that instructions are consistent across tools
4. 🎯 Hard to share instruction patterns across projects

---

## Solution: Single Command to Update All

```bash
# Install (Python)
pip install ai-brief

# Initialize in your project
brief init

# Update all instruction files with context awareness
brief update "When editing Python files, always run pytest before committing"

# Sync a specific behavior template
brief sync behavior "behavior_test_before_commit"

# Validate consistency
brief validate

# List discovered instruction files
brief list
```

---

## Core Features (Minimal V1)

### 1. Auto-Discovery
Automatically finds instruction files in your project:
- `.github/copilot-instructions.md`
- `CLAUDE.md`, `.clinerules`
- `AGENTS.md`
- `.cursorrules`
- Custom patterns via config

### 2. Context-Aware Updates
When updating instructions, automatically includes:
- Project language/framework (detected from files)
- Key file paths and structure
- Existing conventions from instruction files
- Links between related behaviors

### 3. Template Library
Ships with battle-tested instruction templates:
- `behavior_test_before_commit`
- `behavior_update_docs_after_changes`
- `behavior_prefer_composition_over_inheritance`
- Language-specific patterns (Python, TypeScript, Rust, etc.)

### 4. Validation
Checks for:
- ✅ All instruction files have consistent core behaviors
- ✅ File paths mentioned in instructions actually exist
- ✅ No conflicting instructions across files
- ✅ Markdown syntax validity

### 5. MCP Server (Optional)
Expose as MCP tools so AI assistants can self-update:
```json
{
  "name": "agent_instructions_update",
  "description": "Update agent instruction files with new behavior",
  "inputSchema": {
    "instruction": "string",
    "files": ["array of target files"]
  }
}
```

---

## Architecture (Minimal)

```
brief/
├── README.md              # Installation, quick start, examples
├── LICENSE               # MIT or Apache 2.0
├── pyproject.toml        # Python package config
├── brief/
│   ├── __init__.py
│   ├── cli.py           # Click-based CLI
│   ├── discovery.py     # Find instruction files
│   ├── context.py       # Analyze project structure
│   ├── updater.py       # Apply updates to files
│   ├── validator.py     # Check consistency
│   ├── templates/       # Built-in instruction templates
│   │   ├── behaviors.yaml
│   │   ├── python.yaml
│   │   └── typescript.yaml
│   └── mcp/             # MCP server (optional)
│       ├── server.py
│       └── tools.json
├── tests/
│   ├── test_discovery.py
│   ├── test_updater.py
│   └── fixtures/
└── examples/
    ├── python-project/
    ├── typescript-app/
    └── multi-language/
```

---

## CLI Commands

### `init`
```bash
brief init

# Creates .brief.yaml config file
# Discovers existing instruction files
# Offers to add missing files from templates
```

**Config file (`.brief.yaml`):**
```yaml
version: 1
instruction_files:
  - .github/copilot-instructions.md
  - CLAUDE.md
  - AGENTS.md
  - .cursorrules

project:
  languages: [python, typescript]
  frameworks: [fastapi, react]

behaviors:
  enabled:
    - test_before_commit
    - update_docs_after_changes
    - prefer_explicit_types
```

### `update`
```bash
brief update "Always use async/await for database calls"

# Smart update:
# 1. Analyzes existing instructions in all files
# 2. Determines best section to add instruction
# 3. Adds project-specific context (e.g., "database calls in src/db/*.py")
# 4. Updates all files consistently
# 5. Shows diff before applying
```

### `sync`
```bash
brief sync behavior behavior_test_before_commit

# Applies a named behavior from template library to all files
# Customizes based on project context (Python → pytest, JS → jest, etc.)
```

### `validate`
```bash
brief validate

# Checks:
# ✅ All files have consistent core behaviors
# ✅ File paths in instructions exist
# ✅ No conflicting rules
# ✅ Valid markdown syntax
# Exit code 0 = all good, 1 = issues found
```

### `list`
```bash
brief list

# Shows:
# - Discovered instruction files
# - Active behaviors in each file
# - Conflicts or inconsistencies
# - Missing recommended files
```

### `diff`
```bash
brief diff

# Shows differences between instruction files
# Highlights inconsistencies
```

### `export`
```bash
brief export --format markdown > INSTRUCTIONS_SUMMARY.md

# Creates unified view of all instructions
# Useful for sharing with team or AI assistants
```

---

## MCP Server (Optional)

**Installation:**
```bash
# Add to Claude Desktop config
{
  "mcpServers": {
    "brief": {
      "command": "python",
      "args": ["-m", "brief.mcp.server"]
    }
  }
}
```

**Tools exposed:**
```json
[
  {
    "name": "brief_read",
    "description": "Read current agent instruction files"
  },
  {
    "name": "brief_update",
    "description": "Update instruction files with new behavior"
  },
  {
    "name": "brief_validate",
    "description": "Validate instruction consistency"
  },
  {
    "name": "brief_list_behaviors",
    "description": "List available behavior templates"
  }
]
```

---

## Example Use Cases

### Use Case 1: Adding a Testing Behavior
```bash
$ brief update "Run tests before committing any code"

📝 Analyzing project...
   Language: Python
   Test framework: pytest
   Test location: tests/

✨ Updating instruction files:
   ├─ .github/copilot-instructions.md
   │  └─ Adding to "Development Workflow" section
   ├─ CLAUDE.md
   │  └─ Adding to "Agent Behaviors" section
   └─ AGENTS.md
      └─ Creating behavior_test_before_commit

📊 Preview changes? (y/n): y

--- .github/copilot-instructions.md
+++ .github/copilot-instructions.md
@@ -15,6 +15,10 @@

 ## Development Workflow

+### Testing
+- Run `pytest` before committing any code changes
+- Tests are located in `tests/` directory
+
 ## Code Style
 ...

✅ Applied updates to 3 files
```

### Use Case 2: Team Onboarding
```bash
# New developer joins, clones repo
$ git clone https://github.com/team/project.git
$ cd project
$ brief validate

⚠️  Missing instruction files:
   - .cursorrules (recommended for Cursor users)

💡 Run `brief init` to set up

$ brief init

✨ Created instruction files:
   ├─ .cursorrules (from template)
   └─ Updated .brief.yaml

🎯 All agents now aligned with project conventions!
```

### Use Case 3: Consistency Check in CI
```yaml
# .github/workflows/validate-instructions.yml
name: Validate Agent Instructions
on: [pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pip install ai-brief
      - run: brief validate
```

---

## Template Library (Built-in Behaviors)

Ship with curated, battle-tested behaviors:

**Universal Behaviors:**
- `behavior_test_before_commit` - Run tests before committing
- `behavior_update_docs_after_changes` - Keep docs synchronized
- `behavior_follow_git_conventions` - Conventional commits, branch naming
- `behavior_security_first` - Secret scanning, dependency checks
- `behavior_prefer_composition` - Architectural guidance

**Language-Specific:**
- Python: `behavior_type_hints`, `behavior_pytest_fixtures`
- TypeScript: `behavior_strict_types`, `behavior_prefer_const`
- Rust: `behavior_clippy_clean`, `behavior_no_unwrap_in_prod`
- Go: `behavior_error_handling`, `behavior_table_tests`

**Framework-Specific:**
- React: `behavior_functional_components`, `behavior_hooks_only`
- FastAPI: `behavior_async_routes`, `behavior_pydantic_validation`
- Express: `behavior_error_middleware`, `behavior_async_await`

---

## Distribution Strategy

### 1. PyPI Package (Primary)
```bash
pip install ai-brief
```

### 2. NPM Package (Alternative)
```bash
npm install -g ai-brief
```

### 3. Homebrew (macOS)
```bash
brew install ai-brief
```

### 4. Cargo (Rust rewrite later)
```bash
cargo install ai-brief
```

---

## Tech Stack (Minimal V1)

**Language:** Python 3.9+ (most accessible)

**Dependencies (keep minimal):**
- `click` - CLI framework
- `pyyaml` - Config files
- `pathlib` - Path handling (stdlib)
- `markdown-it-py` - Markdown parsing/validation (optional)

**Development:**
- `pytest` - Testing
- `black` - Formatting
- `mypy` - Type checking

**Total dependency footprint:** ~5-6 packages

---

## GitHub Repository Structure

```
Nas4146/brief/
├── README.md                    # Hero section, quick start, examples
├── CONTRIBUTING.md              # How to add templates
├── LICENSE                      # MIT
├── .github/
│   ├── workflows/
│   │   ├── ci.yml              # Tests, linting
│   │   └── release.yml         # PyPI publish
│   └── copilot-instructions.md # Dogfooding!
├── docs/
│   ├── getting-started.md
│   ├── templates.md            # How to create custom templates
│   ├── mcp-server.md           # MCP integration guide
│   └── examples/
│       ├── python-fastapi.md
│       ├── typescript-react.md
│       └── rust-cli.md
├── brief/
│   ├── __init__.py
│   ├── cli.py
│   ├── discovery.py
│   ├── context.py
│   ├── updater.py
│   ├── validator.py
│   ├── templates/
│   │   ├── behaviors/
│   │   │   ├── universal.yaml
│   │   │   ├── python.yaml
│   │   │   ├── typescript.yaml
│   │   │   └── rust.yaml
│   │   └── files/
│   │       ├── copilot-instructions.md.template
│   │       ├── CLAUDE.md.template
│   │       └── .cursorrules.template
│   └── mcp/
│       ├── server.py
│       └── schema/
│           └── tools.json
├── tests/
│   ├── test_cli.py
│   ├── test_discovery.py
│   ├── test_updater.py
│   ├── test_validator.py
│   └── fixtures/
│       ├── python-project/
│       ├── typescript-app/
│       └── multi-language/
├── examples/
│   ├── python-fastapi/
│   │   ├── .github/copilot-instructions.md
│   │   ├── CLAUDE.md
│   │   └── AGENTS.md
│   ├── typescript-react/
│   └── rust-cli/
└── pyproject.toml
```

---

## README.md Example (Hero Section)

```markdown
# 🤖 Brief

**Brief your AI coding assistants once, update them all.**

[![PyPI](https://img.shields.io/pypi/v/ai-brief)](https://pypi.org/project/ai-brief/)
[![Tests](https://github.com/Nas4146/brief/workflows/CI/badge.svg)](https://github.com/Nas4146/brief/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## The Problem

You're using Claude Projects, GitHub Copilot, and Cursor. You want them all to follow your project's conventions:

- ✅ Run tests before committing
- ✅ Update docs after code changes
- ✅ Follow your team's architectural patterns

But maintaining 3+ instruction files manually is tedious and error-prone.

## The Solution

```bash
pip install ai-brief

# One command updates all your AI assistants
brief update "Run pytest before committing any code"

# ✅ .github/copilot-instructions.md updated
# ✅ CLAUDE.md updated
# ✅ .cursorrules updated
```

---

## Quick Start

```bash
# 1. Install
pip install ai-brief

# 2. Initialize in your project
cd your-project
brief init

# 3. Add a behavior
brief sync behavior test_before_commit

# 4. Validate everything is consistent
brief validate
```

---

## Features

- 🔍 **Auto-discovery** - Finds all instruction files automatically
- 🧠 **Context-aware** - Understands your project structure and conventions
- 📚 **Template library** - Battle-tested behaviors for common workflows
- ✅ **Validation** - Ensures consistency across all files
- 🚀 **MCP support** - Let AI assistants self-update their instructions
- 🎯 **Zero config** - Works out of the box, customizable when needed

---

## Use Cases

### For Solo Developers
Keep your personal AI assistant instructions consistent across tools.

### For Teams
Onboard new developers with project conventions baked into AI tools.

### For Open Source
Help contributors understand your project's workflow through AI assistants.

---

## Examples

See [examples/](examples/) for complete project setups:
- [Python + FastAPI](examples/python-fastapi/)
- [TypeScript + React](examples/typescript-react/)
- [Rust CLI app](examples/rust-cli/)

---

## Documentation

- [Getting Started Guide](docs/getting-started.md)
- [Template Creation](docs/templates.md)
- [MCP Server Setup](docs/mcp-server.md)

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT © 2025 [Your Name]
```

---

## Go-to-Market Strategy

### 1. Launch Platforms
- **Hacker News** - "Show HN: Keep AI coding assistant instructions in sync"
- **Reddit** - r/programming, r/MachineLearning, r/ClaudeAI
- **Twitter/X** - Tag @AnthropicAI, @GitHub, mention Claude/Copilot communities
- **Dev.to** - Tutorial post

### 2. Content Strategy
- Blog post: "Why Your AI Coding Assistants Need Synchronized Instructions"
- Video demo: 90-second screencast
- Tweet thread: Problem → Solution → Demo

### 3. Community Building
- GitHub Discussions for template sharing
- Discord/Slack for real-time support
- Monthly "Template of the Month" showcase

---

## Success Metrics

**V1 Goals (First Month):**
- 100+ GitHub stars
- 50+ PyPI downloads
- 5+ community-contributed templates
- 2+ blog posts from users

**V2 Goals (First Quarter):**
- 500+ GitHub stars
- 500+ weekly downloads
- MCP server adoption by 50+ users
- Featured in AI coding assistant newsletters

---

## Roadmap

### V1 (MVP) - Week 1-2
- ✅ CLI with `init`, `update`, `validate`, `list` commands
- ✅ Auto-discovery of instruction files
- ✅ Basic template library (10 behaviors)
- ✅ PyPI package
- ✅ Documentation

### V2 - Week 3-4
- MCP server implementation
- Extended template library (25+ behaviors)
- CI/CD validation example
- Framework-specific templates

### V3 - Month 2
- NPM package (for Node.js projects)
- Web UI for non-CLI users
- VS Code extension
- Community template marketplace

### V4 - Month 3+
- Rust rewrite for performance (optional)
- Language-specific analyzers (AST parsing)
- AI-powered instruction generation
- Team collaboration features (shared templates)

---

## Why This Will Be Useful

1. **"Vibe coding" is real** - Developers increasingly rely on AI assistants for complex workflows
2. **Multi-tool fragmentation** - Most devs use 2-3 different AI coding tools
3. **Instruction drift** - Manual sync leads to inconsistent behavior
4. **Team alignment** - Onboarding is easier when AI tools follow project conventions
5. **Time savings** - One command vs editing 3-5 files manually

---

## Next Steps

1. ✅ Create GitHub repository: `Nas4146/brief`
2. ✅ Set up Python project structure with `pyproject.toml`
3. ✅ Implement core discovery + update logic
4. ✅ Add 5 initial behavior templates
5. ✅ Write comprehensive README with examples
6. ✅ Publish to PyPI
7. ✅ Launch on Hacker News / Reddit

**Estimated time to V1:** 2-3 days of focused development

---

**Ready to scaffold the initial project structure?**
