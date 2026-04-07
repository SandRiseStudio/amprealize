/**
 * Agent Detail Panel
 *
 * Webview panel for displaying comprehensive agent details:
 * - Agent metadata (name, description, role, status)
 * - Model configuration (model, temperature, max_tokens)
 * - Capabilities and behaviors list
 * - MCP servers configuration
 * - Version history
 * - Publish/deprecate actions
 */
import * as vscode from 'vscode';
import { Agent, AmprealizeClient } from '../client/AmprealizeClient';
export declare class AgentDetailPanel {
    static currentPanel: AgentDetailPanel | undefined;
    static readonly viewType = "amprealize.agentDetail";
    private readonly _panel;
    private readonly _extensionUri;
    private readonly _client;
    private _disposables;
    private _agent;
    private _versionHistory;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, client: AmprealizeClient, agent: Agent): Promise<void>;
    static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, client: AmprealizeClient): void;
    private _update;
    private _refreshAgent;
    private _publishAgent;
    private _deprecateAgent;
    private _copyAgentId;
    private _loadVersionHistory;
    private _viewVersion;
    private _editAgent;
    private _getHtmlForWebview;
    private _getRoleIcon;
    private _getRoleDescription;
    private _escapeHtml;
    dispose(): void;
}
//# sourceMappingURL=AgentDetailPanel.d.ts.map
