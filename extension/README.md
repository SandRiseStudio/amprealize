# Amprealize IDE Extension

<div align="center">

![Amprealize](resources/icon.png)

**Transform your IDE into an intelligent development companion with AI agent orchestration, real-time monitoring, and compliance validation.**

[![Version](https://img.shields.io/github/v/release/SandRiseStudio/amprealize?label=version)](https://github.com/SandRiseStudio/amprealize/releases)
[![Build Status](https://img.shields.io/github/actions/workflow/status/SandRiseStudio/amprealize/ci.yml?branch=main&label=build)](https://github.com/SandRiseStudio/amprealize/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](https://github.com/SandRiseStudio/amprealize/blob/main/LICENSE)
[![VSCode Marketplace](https://img.shields.io/badge/vscode-marketplace-blue)](https://marketplace.visualstudio.com/items?itemName=amprealize.amprealize-ide-extension)

</div>

## What is Amprealize?

Amprealize is an AI agent orchestration platform that brings intelligent automation into your development workflow. This VS Code extension provides run monitoring, compliance tracking, and MCP-backed agent tooling.

## Key features

### Execution Tracker
- Real-time monitoring of AI agent runs with auto-refresh
- Visual status indicators for progress, completion, and errors
- Detailed run information with step-by-step tracking
- Error highlighting with actionable debugging context

### Compliance Tracker
- Interactive checklists for process and standards
- Coverage progress tracking
- Evidence attachment for audit trails
- Approval workflows with comments and decisions

### AI agent orchestration
- Broad MCP tool surface for agent management (works with VS Code Copilot Chat where configured)
- Behavior management with search and categorization
- Workflow templates for common patterns
- Multi-agent coordination for complex tasks

### Enterprise-ready
- OAuth2 device flow and secure token storage
- Multi-tenant patterns for teams and organizations
- Compliance-oriented audit logging
- Telemetry hooks for operations visibility

## Who should use this?

- Development teams adopting AI agent workflows
- Organizations that need compliance tracking and audit trails
- Developers who want orchestration inside the IDE
- Teams managing complex multi-agent setups

## Quick start

1. **Install the extension**

   ```bash
   code --install-extension amprealize.amprealize-ide-extension
   ```

2. **Sign in**
   - Use the command palette and run **Amprealize: Connect** (or your configured auth command) to complete device-flow or provider sign-in.

3. **Explore**
   - Open **Execution Tracker** and **Compliance Tracker** from the activity bar or Explorer.
   - Use the command palette for Amprealize commands (see `package.json` for the full list).

## Platform overview

| Component | Notes |
|-----------|--------|
| **Backend services** | CLI / REST / MCP parity across core services |
| **MCP tools** | Large catalog for IDE and agent use |
| **Authentication** | OAuth2 device flow and provider integrations |

## Architecture

- Service-oriented backend with PostgreSQL/TimescaleDB options in production layouts
- Redis caching where deployed
- Optional streaming and analytics pipelines
- MCP as the primary IDE integration protocol

## Commands (examples)

Command titles and IDs are defined in `package.json`. Typical entries include run refresh, compliance review, MCP connect/disconnect, and action tracking. Open **Command Palette** and type `Amprealize` to browse.

## Documentation and support

- **Repository**: [github.com/SandRiseStudio/amprealize](https://github.com/SandRiseStudio/amprealize)
- **Issues**: [GitHub Issues](https://github.com/SandRiseStudio/amprealize/issues)
- **Discussions**: [GitHub Discussions](https://github.com/SandRiseStudio/amprealize/discussions)
- **Product docs**: [docs.amprealize.dev](https://docs.amprealize.dev) when available; otherwise use the repo `docs/` tree

## Contributing

See [Contributing Guide](https://github.com/SandRiseStudio/amprealize/blob/main/.github/CONTRIBUTING.md).

## License

Apache License 2.0 — see [LICENSE](https://github.com/SandRiseStudio/amprealize/blob/main/LICENSE).

## Acknowledgments

- Built for developers shipping agentic workflows
- Inspired by the [Model Context Protocol](https://modelcontextprotocol.io/) specification

---

<div align="center">

**Made for developers who build with agents**

[VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=amprealize.amprealize-ide-extension) · [GitHub](https://github.com/SandRiseStudio/amprealize)

</div>
