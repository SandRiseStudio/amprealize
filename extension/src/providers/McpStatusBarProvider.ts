/**
 * MCP Status Bar Provider
 *
 * Displays MCP connection health status in the VS Code status bar.
 * Shows connected/disconnected/reconnecting state with real-time updates.
 */

import * as vscode from 'vscode';
import { McpClient, ConnectionState, ConnectionStatus } from '../client/McpClient';

export class McpStatusBarProvider implements vscode.Disposable {
    private statusBarItem: vscode.StatusBarItem;
    private disposables: vscode.Disposable[] = [];

    constructor(private mcpClient: McpClient) {
        // Create status bar item (right side, lower priority to appear after other items)
        this.statusBarItem = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Right,
            100
        );
        this.statusBarItem.command = 'amprealize.mcp.showStatus';

        // Subscribe to connection events
        this.mcpClient.on('connectionStateChanged', this.onConnectionStateChanged.bind(this));
        this.mcpClient.on('heartbeat', this.onHeartbeat.bind(this));
        this.mcpClient.on('heartbeatFailed', this.onHeartbeatFailed.bind(this));
        this.mcpClient.on('reconnecting', this.onReconnecting.bind(this));
        this.mcpClient.on('reconnected', this.onReconnected.bind(this));
        this.mcpClient.on('reconnectFailed', this.onReconnectFailed.bind(this));

        // Set initial state
        this.updateStatusBar();
        this.statusBarItem.show();
    }

    private onConnectionStateChanged(_event: { previousState: ConnectionState; currentState: ConnectionState }): void {
        this.updateStatusBar();
    }

    private onHeartbeat(_event: { timestamp: Date }): void {
        // Update tooltip with last heartbeat time
        this.updateStatusBar();
    }

    private onHeartbeatFailed(_event: { error: unknown }): void {
        this.updateStatusBar();
    }

    private onReconnecting(_event: { attempt: number; backoffMs: number }): void {
        this.updateStatusBar();
    }

    private onReconnected(event: { attempts: number }): void {
        vscode.window.showInformationMessage(`Amprealize MCP reconnected after ${event.attempts} attempt(s)`);
        this.updateStatusBar();
    }

    private onReconnectFailed(event: { attempts: number }): void {
        vscode.window.showErrorMessage(
            `Amprealize MCP failed to reconnect after ${event.attempts} attempts. Click the status bar to retry.`
        );
        this.updateStatusBar();
    }

    private updateStatusBar(): void {
        const status = this.mcpClient.getConnectionStatus();

        switch (status.state) {
            case 'connected':
                this.statusBarItem.text = '$(plug) Amprealize';
                this.statusBarItem.backgroundColor = undefined;
                this.statusBarItem.tooltip = this.buildTooltip(status, 'Connected to MCP server');
                break;

            case 'connecting':
                this.statusBarItem.text = '$(sync~spin) Amprealize';
                this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
                this.statusBarItem.tooltip = 'Connecting to MCP server...';
                break;

            case 'reconnecting':
                this.statusBarItem.text = `$(sync~spin) Amprealize (${status.reconnectAttempts})`;
                this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
                this.statusBarItem.tooltip = this.buildTooltip(
                    status,
                    `Reconnecting... (attempt ${status.reconnectAttempts})`
                );
                break;

            case 'disconnected':
                this.statusBarItem.text = '$(debug-disconnect) Amprealize';
                this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
                this.statusBarItem.tooltip = this.buildTooltip(status, 'Disconnected from MCP server');
                break;
        }
    }

    private buildTooltip(status: ConnectionStatus, message: string): vscode.MarkdownString {
        const md = new vscode.MarkdownString();
        md.appendMarkdown(`**Amprealize MCP Status**\n\n`);
        md.appendMarkdown(`Status: ${message}\n\n`);

        if (status.lastHeartbeat) {
            const ago = Math.round((Date.now() - status.lastHeartbeat.getTime()) / 1000);
            md.appendMarkdown(`Last heartbeat: ${ago}s ago\n\n`);
        }

        if (status.lastError) {
            md.appendMarkdown(`Last error: ${status.lastError}\n\n`);
        }

        if (status.reconnectAttempts > 0 && status.state !== 'connected') {
            md.appendMarkdown(`Reconnect attempts: ${status.reconnectAttempts}\n\n`);
        }

        md.appendMarkdown(`---\n\nClick to show connection options`);
        md.isTrusted = true;

        return md;
    }

    /**
     * Show connection status and options in a quick pick
     */
    async showStatusQuickPick(): Promise<void> {
        const status = this.mcpClient.getConnectionStatus();

        const options: vscode.QuickPickItem[] = [];

        if (status.state === 'connected') {
            options.push({
                label: '$(debug-disconnect) Disconnect',
                description: 'Disconnect from MCP server'
            });
            options.push({
                label: '$(refresh) Ping Server',
                description: 'Send heartbeat ping to verify connection'
            });
        } else {
            options.push({
                label: '$(plug) Connect',
                description: 'Connect to MCP server'
            });
        }

        options.push({
            label: '$(output) Show Output',
            description: 'Open MCP output channel'
        });

        options.push({
            label: '$(gear) Settings',
            description: 'Open MCP connection settings'
        });

        const selected = await vscode.window.showQuickPick(options, {
            placeHolder: `MCP Status: ${status.state}`
        });

        if (!selected) {
            return;
        }

        switch (selected.label) {
            case '$(plug) Connect':
                try {
                    await this.mcpClient.connect();
                    vscode.window.showInformationMessage('Connected to Amprealize MCP server');
                } catch (error) {
                    vscode.window.showErrorMessage(
                        `Failed to connect: ${error instanceof Error ? error.message : String(error)}`
                    );
                }
                break;

            case '$(debug-disconnect) Disconnect':
                this.mcpClient.disconnect();
                vscode.window.showInformationMessage('Disconnected from Amprealize MCP server');
                break;

            case '$(refresh) Ping Server':
                try {
                    const result = await this.mcpClient.ping();
                    vscode.window.showInformationMessage(`MCP server responded: ${result.status}`);
                } catch (error) {
                    vscode.window.showErrorMessage(
                        `Ping failed: ${error instanceof Error ? error.message : String(error)}`
                    );
                }
                break;

            case '$(output) Show Output':
                vscode.commands.executeCommand('workbench.action.output.show', 'Amprealize MCP');
                break;

            case '$(gear) Settings':
                vscode.commands.executeCommand('workbench.action.openSettings', 'amprealize.mcp');
                break;
        }
    }

    dispose(): void {
        this.statusBarItem.dispose();
        this.disposables.forEach(d => d.dispose());

        // Remove event listeners
        this.mcpClient.removeAllListeners('connectionStateChanged');
        this.mcpClient.removeAllListeners('heartbeat');
        this.mcpClient.removeAllListeners('heartbeatFailed');
        this.mcpClient.removeAllListeners('reconnecting');
        this.mcpClient.removeAllListeners('reconnected');
        this.mcpClient.removeAllListeners('reconnectFailed');
    }
}
