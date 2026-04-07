/**
 * Amprealize Chat Panel
 *
 * A native VS Code webview panel for interacting with Amprealize MCP tools directly.
 * Bypasses GitHub Copilot Chat's MCP integration to avoid timeout/hanging issues.
 *
 * Features:
 * - Direct MCP tool invocation via McpClient
 * - Real-time streaming responses
 * - Tool group management (lazy loading)
 * - Progress indicators for long-running operations
 * - Chat history persistence
 *
 * Following behavior_prefer_mcp_tools: Use MCP directly for consistent schemas and telemetry.
 * Following behavior_integrate_vscode_extension: Standard webview panel patterns.
 */
import * as vscode from 'vscode';
import { McpClient } from '../client/McpClient';
export declare class AmprealizeChatPanel {
    static currentPanel: AmprealizeChatPanel | undefined;
    static readonly viewType = "amprealize.chat";
    private readonly _panel;
    private readonly _extensionUri;
    private readonly _mcpClient;
    private _disposables;
    private _messages;
    private _toolGroups;
    private _activeTools;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, mcpClient: McpClient): void;
    static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, mcpClient: McpClient): void;
    dispose(): void;
    private _onWebviewReady;
    private _postMessage;
    private _update;
    private _handleUserMessage;
    private _handleSlashCommand;
    private _handleToolCommand;
    private _handleNaturalLanguage;
    private _handleToolCall;
    private _loadToolGroups;
    private _activateToolGroup;
    private _deactivateToolGroup;
    private _listActiveTools;
    private _addAssistantMessage;
    private _addSystemMessage;
    private _clearHistory;
    private _getHtmlForWebview;
}
//# sourceMappingURL=AmprealizeChatPanel.d.ts.map
