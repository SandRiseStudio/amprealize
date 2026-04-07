# Amprealize Multi-IDE Installation Guide

> **Complete Installation Guide for VSCode, Cursor, and Claude Desktop**
> **Status:** Phase 3 Implementation
> **Updated:** 2025-11-07

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [VSCode Installation](#vscode-installation)
- [Cursor Installation](#cursor-installation)
- [Claude Desktop Setup](#claude-desktop-setup)
- [Authentication](#authentication)
- [Troubleshooting](#troubleshooting)
- [Platform Comparison](#platform-comparison)

## Overview

Amprealize is an **AI agent orchestration platform** that works seamlessly across multiple development environments. This guide covers installation and setup for three supported IDE platforms:

| Platform | Type | Extension | Status |
|----------|------|-----------|--------|
| **VSCode** | Full IDE | Native Extension | ✅ Available |
| **Cursor** | AI IDE | Native Extension | ✅ Available |
| **Claude Desktop** | AI Assistant | MCP Integration | ✅ Available |

### Key Features Available Across All Platforms

- **64 MCP Tools** for comprehensive AI agent management
- **Real-time run monitoring** with auto-refresh
- **Interactive compliance tracking** with evidence management
- **Behavior management** with semantic search
- **Workflow orchestration** with template execution
- **OAuth2 device flow authentication** with secure token management

## Quick Start

For immediate access to Amprealize's core features:

```bash
# 1. Install CLI (works on all platforms)
pip install -e .

# 2. Quick authentication
amprealize auth login

# 3. Test the installation
amprealize behaviors list
amprealize workflows list
```

## VSCode Installation

### Method 1: Marketplace Installation (Recommended)

1. **Open VSCode** (version 1.74.0 or later)
2. **Navigate to Extensions**: Press `Ctrl+Shift+X` (Windows/Linux) or `Cmd+Shift+X` (macOS)
3. **Search for "Amprealize"**
4. **Install**: Click the **Install** button for "Amprealize IDE Extension"
5. **Reload VSCode**: Click **Reload** to activate the extension

### Method 2: Manual Installation

```bash
# Download VSIX from releases
wget https://github.com/SandRiseStudio/amprealize/releases/latest/download/amprealize-ide-extension-1.0.0.vsix

# Install via command line
code --install-extension amprealize-ide-extension-1.0.0.vsix
```

### VSCode Setup

1. **Authenticate**:
   - Press `Ctrl+Shift+P` to open command palette
   - Type `Amprealize: Sign In` and select it
   - Follow the OAuth2 device flow authentication

2. **Verify Installation**:
   - Look for the **Amprealize** view container in the sidebar
   - Check both **Execution Tracker** and **Compliance Tracker** panels
   - Test with a sample command: `Amprealize: Show Output`

### VSCode Features

**🌟 Available Features:**
- **Execution Tracker**: Real-time run monitoring with auto-refresh every 5 seconds
- **Compliance Tracker**: Interactive validation with coverage tracking
- **Behavior Sidebar**: Search and manage AI behaviors
- **Workflow Explorer**: Browse and execute workflow templates
- **Plan Composer**: AI-powered workflow planning with behavior suggestions

**⚡ Quick Commands:**
- `Ctrl+Alt+G I`: Amprealize Sign In
- `Ctrl+Alt+G R`: Refresh Execution Tracker
- `Ctrl+Alt+G C`: Open Compliance Review
- `Ctrl+Alt+G O`: Show Output

## Cursor Installation

### Method 1: Marketplace Installation (Recommended)

1. **Open Cursor IDE** (latest version)
2. **Navigate to Extensions**: Press `Cmd+Shift+X` (macOS) or `Ctrl+Shift+X` (Windows/Linux)
3. **Search for "Amprealize"**
4. **Install**: Click **Install** for "Amprealize IDE Extension"
5. **Reload Cursor**: Restart Cursor to activate the extension

### Method 2: Manual Installation

```bash
# Download Cursor-compatible VSIX (same artifact as VS Code unless releases publish a separate build)
wget https://github.com/SandRiseStudio/amprealize/releases/latest/download/amprealize-ide-extension-1.0.0.vsix

# Install via command line
cursor --install-extension amprealize-ide-extension-1.0.0.vsix
```

### Cursor Setup

1. **Authenticate**:
   - Press `Cmd+Shift+P` (macOS) or `Ctrl+Shift+P` (Windows/Linux)
   - Type `Amprealize: Sign In` and select it
   - Complete the device flow authentication

2. **Configure MCP Integration**:
   ```json
   // Add to Cursor settings (File > Preferences > Settings)
   {
     "amprealize.mcpServer": "python -m amprealize.mcp_server"
   }
   ```

### Cursor-Specific Features

**🤖 AI-Enhanced Features:**
- **Integrated AI Workflows**: Amprealize works alongside Cursor's built-in AI
- **Enhanced Code Intelligence**: Combine Cursor's AI with Amprealize's agent orchestration
- **Context-Aware Automation**: Smart suggestions based on your code and AI patterns

## Claude Desktop Setup

Claude Desktop integrates with Amprealize via the **Model Context Protocol (MCP)**. This provides a powerful AI assistant experience with Amprealize's full feature set.

### Prerequisites

1. **Install Claude Desktop**: Download from [claude.ai/download](https://claude.ai/download)
2. **Amprealize Platform**: Ensure Amprealize backend services are running
3. **Python Environment**: Python 3.10+ with Amprealize installed

### MCP Server Setup

1. **Start Amprealize MCP Server**:
   ```bash
   amprealize mcp-server --port 3000
   ```

2. **Configure Claude Desktop**:
   ```json
   // Add to Claude Desktop config file:
   // macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
   // Windows: %APPDATA%/Claude/claude_desktop_config.json
   // Linux: ~/.config/Claude/claude_desktop_config.json

   {
     "mcpServers": {
       "amprealize": {
         "command": "python",
         "args": ["-m", "amprealize.mcp_server"],
         "env": {
           "AMPREALIZE_MCP_HOST": "localhost",
           "AMPREALIZE_MCP_PORT": "3000"
         }
       }
     }
   }
   ```

### Advanced MCP Configuration

**Full Configuration Example:**
```json
{
  "mcpServers": {
    "amprealize": {
      "command": "python",
      "args": ["-m", "amprealize.mcp_server"],
      "env": {
        "AMPREALIZE_MCP_HOST": "localhost",
        "AMPREALIZE_MCP_PORT": "3000",
        "AMPREALIZE_BEHAVIOR_PG_DSN": "postgresql://...",
        "AMPREALIZE_WORKFLOW_PG_DSN": "postgresql://...",
        "AMPREALIZE_TELEMETRY_SINK": "postgres"
      }
    }
  }
}
```

### Claude Desktop Features

**💬 Conversational AI:**
- **Natural Language Commands**: "Show me the latest AI agent runs"
- **Complex Workflows**: "Create a behavior for code review automation"
- **Compliance Queries**: "What's our compliance coverage this week?"

**🔗 Available Tools:**
- `behaviors.list`: Browse available AI behaviors
- `workflows.create`: Execute workflow templates
- `compliance.validate`: Check compliance status
- `actions.replay`: Reproduce previous actions
- `analytics.kpi`: View performance metrics

## Authentication

All Amprealize integrations use **OAuth2 Device Flow** for secure, cross-platform authentication.

### Device Flow Process

1. **Authentication Request**:
   ```bash
   amprealize auth login
   ```

2. **Device Authorization**:
   - Visit the provided URL (e.g., `https://device.amprealize.com/authorize`)
   - Enter the provided code
   - Grant permissions

3. **Token Management**:
   - **VSCode**: Automatic keychain storage
   - **Cursor**: Same keychain integration
   - **Claude Desktop**: Secure file storage
   - **CLI**: Environment-specific storage

### Token Security

- **Secure Storage**: OS-specific keychain (macOS/Windows) or encrypted files (Linux)
- **Automatic Refresh**: Tokens refresh automatically before expiration
- **Cross-Platform Sync**: Same account works across all platforms
- **Revocation**: Tokens can be revoked via `amprealize auth revoke`

### Troubleshooting Authentication

**Common Issues:**

1. **Token Expired**:
   ```bash
   amprealize auth refresh
   ```

2. **Invalid Token**:
   ```bash
   amprealize auth status  # Check token status
   amprealize auth login   # Re-authenticate
   ```

3. **Permission Denied**:
   - Check your Amprealize account permissions
   - Verify scope requirements for specific features

## Troubleshooting

### VSCode Issues

**Extension Not Loading:**
1. Check VSCode version (≥1.74.0)
2. Verify extension compatibility
3. Restart VSCode and check output panel

**Authentication Fails:**
1. Check internet connection
2. Verify Amprealize services are running
3. Clear extension data and re-authenticate

**Performance Issues:**
1. Check resource usage in task manager
2. Reduce auto-refresh frequency
3. Clear extension cache

### Cursor Issues

**MCP Connection Failed:**
1. Verify MCP server is running: `amprealize mcp-server --status`
2. Check port configuration
3. Restart Cursor and retry

**AI Feature Conflicts:**
1. Configure Amprealize to use specific AI models
2. Disable conflicting Cursor AI features
3. Use environment variables to control behavior

### Claude Desktop Issues

**MCP Server Not Responding:**
1. Check MCP server logs: `amprealize mcp-server --log-level debug`
2. Verify Python environment and dependencies
3. Restart Claude Desktop

**Tool Execution Errors:**
1. Check Amprealize backend service status
2. Verify network connectivity
3. Review MCP server logs for details

### General Platform Issues

**Connection Timeouts:**
```bash
# Check Amprealize service status
amprealize health-check

# Verify network connectivity
ping api.amprealize.com
```

**Permission Errors:**
```bash
# Check authentication status
amprealize auth status

# Refresh token if needed
amprealize auth refresh
```

## Platform Comparison

| Feature | VSCode | Cursor | Claude Desktop |
|---------|--------|--------|----------------|
| **Real-time Monitoring** | ✅ Full | ✅ Full | ✅ MCP |
| **Behavior Management** | ✅ Native | ✅ Native | ✅ MCP |
| **Workflow Execution** | ✅ Native | ✅ Native | ✅ MCP |
| **Compliance Tracking** | ✅ Native | ✅ Native | ✅ MCP |
| **AI Integration** | ✅ Extension | ✅ Enhanced | ✅ Native |
| **Performance** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Ease of Use** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |

### Best Platform for Your Use Case

**🖥️ VSCode - Best for:**
- **Traditional Development**: Full-featured IDE with Amprealize enhancement
- **Team Collaboration**: Enterprise-grade features and integrations
- **Custom Workflows**: Extensive customization and plugin ecosystem

**🤖 Cursor - Best for:**
- **AI-First Development**: Enhanced AI features combined with Amprealize
- **Productivity Focus**: Streamlined workflow for AI-powered development
- **Modern Development**: Latest AI capabilities in IDE

**💬 Claude Desktop - Best for:**
- **Conversational AI**: Natural language interaction with Amprealize
- **Research & Analysis**: Complex query and analysis workflows
- **Strategic Planning**: High-level AI agent orchestration

## Next Steps

After successful installation:

1. **Explore Features**:
   - Browse available behaviors and workflows
   - Set up compliance tracking
   - Configure AI agent orchestration

2. **Customize Setup**:
   - Adjust auto-refresh intervals
   - Configure notifications
   - Set up team collaboration

3. **Advanced Usage**:
   - Create custom behaviors
   - Design workflow templates
   - Set up automated compliance checks

## Support & Resources

- **Documentation**: [docs.amprealize.com](https://docs.amprealize.com)
- **GitHub**: [github.com/SandRiseStudio/amprealize](https://github.com/SandRiseStudio/amprealize)
- **Community**: [github.com/SandRiseStudio/amprealize/discussions](https://github.com/SandRiseStudio/amprealize/discussions)
- **Support**: [amprealize.com/support](https://amprealize.com/support)

---

*Last updated: 2025-11-07*
*For the latest installation instructions, visit [docs.amprealize.com/installation](https://docs.amprealize.com/installation)*
