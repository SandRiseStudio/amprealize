/**
 * Run Detail Panel
 *
 * Webview panel for displaying comprehensive run details:
 * - Real-time run status and progress
 * - Step-by-step execution timeline
 * - Error logs and debugging information
 * - Token usage and performance metrics
 * - Download run artifacts and logs
 */
import * as vscode from 'vscode';
import { Run } from '../client/AmprealizeClient';
export declare class RunDetailPanel {
    static currentPanel: RunDetailPanel | undefined;
    static readonly viewType = "amprealize.runDetail";
    private readonly _panel;
    private readonly _extensionUri;
    private _disposables;
    private _run;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, run: Run): void;
    static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri): void;
    private _update;
    private _refreshRun;
    private _exportLogs;
    private _copyRunId;
    private _openLogsFile;
    private _getHtmlForWebview;
    dispose(): void;
}
//# sourceMappingURL=RunDetailPanel.d.ts.map
