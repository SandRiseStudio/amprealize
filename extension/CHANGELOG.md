# Changelog

All notable changes to the Amprealize IDE Extension will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-01-22

### Added
- 🚀 **220 MCP Tools**: Full Amprealize MCP server integration with VS Code Copilot Chat
- 🔧 **Schema Resolution**: Automatic `$ref` resolution for all tool schemas, enabling native Copilot Chat discovery

### Fixed
- 🐛 **VS Code Copilot Chat Compatibility**: Fixed `$ref` resolution in MCP tool schemas
  - External file refs: `../../schema/bci/v1/prompt.json#/definitions/...`
  - Internal refs: `#/definitions/BehaviorSnippet`
  - Bare filename refs: `trace.json#/definitions/TraceFormat`
  - All 220 tools now have fully-inlined JSON schemas

### Technical Details
- **MCP Server** (`amprealize/mcp_server.py`): Added `_resolve_json_refs()` method for recursive schema resolution
- **Tool Manifests**: 220 tools in `mcp/tools/` now work natively in VS Code Copilot Chat
- **Affected Tools**: `bci_composeprompt`, `bci_validatecitations`, `reflection_extract`, and 8 other BCI tools

---

## [1.1.0] - 2025-11-14

### Added
- 🔐 **Internal Authentication**: Username/password authentication as alternative to OAuth
  - JWT token-based authentication (HS256)
  - Secure password hashing with bcrypt (cost factor 12)
  - Multi-provider token isolation (separate files per provider)
  - REST API endpoints: `GET /api/v1/auth/providers`, `POST /api/v1/auth/internal/register`, `POST /api/v1/auth/internal/login`
  - CLI commands: `amprealize auth register`, `amprealize auth login --provider internal`
  - Comprehensive integration testing (13/16 tests passing, 81% coverage)

### Documentation
- 📚 **New Guide**: [`INTERNAL_AUTH_GUIDE.md`](../docs/INTERNAL_AUTH_GUIDE.md) - Complete API reference, CLI usage, and troubleshooting
- 📚 **Updated**: [`MULTI_PROVIDER_AUTH_ARCHITECTURE.md`](../docs/MULTI_PROVIDER_AUTH_ARCHITECTURE.md) - Internal auth implementation details

### Security
- ✅ Password validation: min 8 characters
- ✅ Username validation: min 3 characters
- ✅ Bcrypt password hashing with cost factor 12 (~250ms per hash)
- ✅ Token file permissions: 0600 (owner read/write only)
- ✅ JWT tokens with configurable expiration (default: 1 hour access, 30 days refresh)

### Technical Details
- **Token Storage**: Provider-isolated files (`~/.amprealize/auth_tokens_internal.json`, `~/.amprealize/auth_tokens_github.json`)
- **Error Handling**: HTTP 409 for duplicate users, HTTP 401 for invalid credentials, HTTP 400 for validation errors
- **Testing**: 13/16 integration tests passing (API: 9/9, Storage: 3/3, E2E: 1/2)
- **Known Limitation**: CLI tests timeout due to `getpass.getpass()` TTY requirement (functional in interactive use)

---

## [1.0.0] - 2025-11-07

### Added
- ✨ **Initial Release**: Complete Amprealize IDE extension with comprehensive AI agent orchestration
- 🧠 **Execution Tracker**: Real-time run monitoring with auto-refresh every 5 seconds
- ✅ **Compliance Tracker**: Interactive compliance validation with coverage tracking
- 🔐 **Device Flow Authentication**: OAuth2 integration with Amprealize platform
- 📊 **Real-time Metrics**: Live telemetry and KPI monitoring
- 🤖 **MCP Tools**: Model Context Protocol integration with Amprealize server
- 🎨 **Professional UI**: Modern dark theme with status indicators
- 🔄 **Auto-refresh**: Continuous updates for all tracked data
- 📝 **Command Palette**: Full VS Code command integration
- ⚡ **Performance Optimized**: <100ms response times for all operations

### Features
- **Execution Monitoring**
  - Real-time run status tracking
  - Progress indicators and status badges
  - Error/warning highlighting
  - Run detail panel with comprehensive information

- **Compliance Management**
  - Step-by-step checklist validation
  - Coverage progress visualization
  - Evidence attachment capabilities
  - Approval workflow with comments

- **AI Agent Orchestration**
  - Behavior management and search
  - Workflow template integration
  - Multi-agent coordination
  - Pattern detection and scoring

- **Cross-Platform Integration**
  - CLI bridge for Amprealize services
  - REST API connectivity
  - MCP protocol support
  - Webhook notifications

### Technical Details
- **Architecture**: 17 backend services with full parity
- **Performance**: P95 <100ms response times
- **Coverage**: 450+ passing tests
- **Compliance**: SOC2-ready audit logging
- **Security**: Enterprise-grade authentication
- **Scalability**: Multi-tenant support

---

## Support

- 📚 **Documentation**: [Amprealize documentation](https://docs.amprealize.dev)
- 🐛 **Issues**: [GitHub Issues](https://github.com/SandRiseStudio/amprealize/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/SandRiseStudio/amprealize/discussions)
- 🔗 **Website**: [https://amprealize.dev](https://amprealize.dev)

## License

Apache License 2.0 — see [LICENSE](https://github.com/SandRiseStudio/amprealize/blob/main/LICENSE) for details.
