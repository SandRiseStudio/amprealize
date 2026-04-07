/**
 * MCP Status Bar Provider
 *
 * Displays MCP connection health status in the VS Code status bar.
 * Shows connected/disconnected/reconnecting state with real-time updates.
 */
import * as vscode from 'vscode';
import { McpClient } from '../client/McpClient';
export declare class McpStatusBarProvider implements vscode.Disposable {
    private mcpClient;
    private statusBarItem;
    private disposables;
    constructor(mcpClient: McpClient);
    private onConnectionStateChanged;
    private onHeartbeat;
    private onHeartbeatFailed;
    private onReconnecting;
    private onReconnected;
    private onReconnectFailed;
    private updateStatusBar;
    private buildTooltip;
    /**
     * Show connection status and options in a quick pick
     */
    showStatusQuickPick(): Promise<void>;
    dispose(): void;
}
//# sourceMappingURL=McpStatusBarProvider.d.ts.map
