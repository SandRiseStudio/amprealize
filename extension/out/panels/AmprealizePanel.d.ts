/**
 * Amprealize Panel
 *
 * Webview panel for the Amprealize Orchestrator:
 * - Blueprint management (list, select, edit)
 * - Visual DAG renderer
 * - Plan and Apply execution
 * - Real-time status monitoring
 */
import * as vscode from 'vscode';
import { AmprealizeClient } from '../client/AmprealizeClient';
import { McpClient } from '../client/McpClient';
export declare class AmprealizePanel {
    static currentPanel: AmprealizePanel | undefined;
    static readonly viewType = "amprealize.amprealize";
    private readonly _panel;
    private readonly _extensionUri;
    private readonly _client;
    private readonly _mcpClient;
    private _disposables;
    private _blueprints;
    private _selectedBlueprint;
    private _planResult;
    private _runId;
    private _runStatus;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, client: AmprealizeClient, mcpClient: McpClient): void;
    dispose(): void;
    private refreshBlueprints;
    private runPlan;
    private runApply;
    private startStatusPolling;
    private refreshStatus;
    private runDestroy;
    private update;
    private getHtmlForWebview;
}
//# sourceMappingURL=AmprealizePanel.d.ts.map
