/**
 * Action Timeline Panel
 *
 * WebView panel for viewing action history, details, and triggering quick replays.
 * Provides a richer UI than the tree view for action management.
 *
 * Following behavior_sanitize_action_registry (Student)
 */
import * as vscode from 'vscode';
import { McpClient } from '../client/McpClient';
export declare class ActionTimelinePanel {
    static currentPanel: ActionTimelinePanel | undefined;
    static readonly viewType = "amprealize.actionTimeline";
    private readonly _panel;
    private readonly _extensionUri;
    private _disposables;
    private _mcpClient;
    private _actions;
    private _selectedAction;
    private _replayStatusPollInterval;
    static createOrShow(extensionUri: vscode.Uri, mcpClient: McpClient): void;
    static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, mcpClient: McpClient): void;
    private constructor();
    refresh(): Promise<void>;
    private selectAction;
    private filterByBehavior;
    private quickReplay;
    private pollReplayStatus;
    private update;
    private updateContent;
    private getHtmlForWebview;
    dispose(): void;
}
//# sourceMappingURL=ActionTimelinePanel.d.ts.map
