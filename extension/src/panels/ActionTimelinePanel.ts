/**
 * Action Timeline Panel
 *
 * WebView panel for viewing action history, details, and triggering quick replays.
 * Provides a richer UI than the tree view for action management.
 *
 * Following behavior_sanitize_action_registry (Student)
 */

import * as vscode from 'vscode';
import { McpClient, ActionItem, ActionGetResult } from '../client/McpClient';

export class ActionTimelinePanel {
    public static currentPanel: ActionTimelinePanel | undefined;
    public static readonly viewType = 'amprealize.actionTimeline';

    private readonly _panel: vscode.WebviewPanel;
    private readonly _extensionUri: vscode.Uri;
    private _disposables: vscode.Disposable[] = [];
    private _mcpClient: McpClient;
    private _actions: ActionItem[] = [];
    private _selectedAction: ActionGetResult | null = null;
    private _replayStatusPollInterval: NodeJS.Timeout | null = null;

    public static createOrShow(extensionUri: vscode.Uri, mcpClient: McpClient) {
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;

        if (ActionTimelinePanel.currentPanel) {
            ActionTimelinePanel.currentPanel._panel.reveal(column);
            ActionTimelinePanel.currentPanel.refresh();
            return;
        }

        const panel = vscode.window.createWebviewPanel(
            ActionTimelinePanel.viewType,
            'Action Timeline',
            column || vscode.ViewColumn.One,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'src', 'styles')]
            }
        );

        ActionTimelinePanel.currentPanel = new ActionTimelinePanel(panel, extensionUri, mcpClient);
    }

    public static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, mcpClient: McpClient) {
        ActionTimelinePanel.currentPanel = new ActionTimelinePanel(panel, extensionUri, mcpClient);
    }

    private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, mcpClient: McpClient) {
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._mcpClient = mcpClient;

        this.update();
        this.refresh();

        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

        this._panel.webview.onDidReceiveMessage(
            async message => {
                switch (message.command) {
                    case 'refresh':
                        await this.refresh();
                        break;
                    case 'selectAction':
                        await this.selectAction(message.actionId);
                        break;
                    case 'quickReplay':
                        await this.quickReplay(message.actionIds, message.dryRun);
                        break;
                    case 'copyActionId':
                        await vscode.env.clipboard.writeText(message.actionId);
                        vscode.window.showInformationMessage('Action ID copied to clipboard');
                        break;
                    case 'filterByBehavior':
                        await this.filterByBehavior(message.behaviorId);
                        break;
                    case 'clearFilters':
                        await this.refresh();
                        break;
                }
            },
            null,
            this._disposables
        );
    }

    public async refresh() {
        try {
            const result = await this._mcpClient.actionList({ limit: 100 });
            this._actions = result.actions || [];
            this.updateContent();
        } catch (error) {
            const errorMsg = error instanceof Error ? error.message : String(error);
            vscode.window.showErrorMessage(`Failed to load actions: ${errorMsg}`);
        }
    }

    private async selectAction(actionId: string) {
        try {
            this._selectedAction = await this._mcpClient.actionGet(actionId);
            this.updateContent();
        } catch (error) {
            const errorMsg = error instanceof Error ? error.message : String(error);
            vscode.window.showErrorMessage(`Failed to load action details: ${errorMsg}`);
        }
    }

    private async filterByBehavior(behaviorId: string) {
        try {
            const result = await this._mcpClient.actionList({ behaviorId, limit: 100 });
            this._actions = result.actions || [];
            this.updateContent();
        } catch (error) {
            const errorMsg = error instanceof Error ? error.message : String(error);
            vscode.window.showErrorMessage(`Failed to filter actions: ${errorMsg}`);
        }
    }

    private async quickReplay(actionIds: string[], dryRun = false) {
        try {
            const result = await this._mcpClient.actionReplay({
                actionIds,
                strategy: 'SEQUENTIAL',
                options: { dryRun }
            });

            vscode.window.showInformationMessage(
                dryRun
                    ? `Dry run started for ${actionIds.length} action(s)`
                    : `Replay started: ${result.replay_id}`
            );

            // Start polling for status
            this.pollReplayStatus(result.replay_id);

        } catch (error) {
            const errorMsg = error instanceof Error ? error.message : String(error);
            vscode.window.showErrorMessage(`Failed to start replay: ${errorMsg}`);
        }
    }

    private pollReplayStatus(replayId: string) {
        if (this._replayStatusPollInterval) {
            clearInterval(this._replayStatusPollInterval);
        }

        this._replayStatusPollInterval = setInterval(async () => {
            try {
                const status = await this._mcpClient.actionReplayStatus(replayId);

                // Update UI with status
                this._panel.webview.postMessage({
                    command: 'replayStatus',
                    status
                });

                // Stop polling when complete
                if (status.status === 'SUCCEEDED' || status.status === 'FAILED') {
                    if (this._replayStatusPollInterval) {
                        clearInterval(this._replayStatusPollInterval);
                        this._replayStatusPollInterval = null;
                    }

                    const message = status.status === 'SUCCEEDED'
                        ? `Replay completed: ${status.completed_actions.length} action(s)`
                        : `Replay failed: ${status.error || 'Unknown error'}`;

                    if (status.status === 'SUCCEEDED') {
                        vscode.window.showInformationMessage(message);
                    } else {
                        vscode.window.showErrorMessage(message);
                    }

                    // Refresh to show updated statuses
                    await this.refresh();
                }
            } catch {
                // Silently handle polling errors
            }
        }, 2000);
    }

    private update() {
        this._panel.title = 'Action Timeline';
        this._panel.webview.html = this.getHtmlForWebview();
    }

    private updateContent() {
        this._panel.webview.postMessage({
            command: 'updateContent',
            actions: this._actions,
            selectedAction: this._selectedAction
        });
    }

    private getHtmlForWebview(): string {
        const styleUri = this._panel.webview.asWebviewUri(
            vscode.Uri.joinPath(this._extensionUri, 'src', 'styles', 'ActionTimelinePanel.css')
        );

        const nonce = getNonce();

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${this._panel.webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="${styleUri}" rel="stylesheet">
    <title>Action Timeline</title>
    <style>
        :root {
            --vscode-foreground: var(--vscode-editor-foreground);
            --vscode-background: var(--vscode-editor-background);
        }
        body {
            padding: 10px;
            font-family: var(--vscode-font-family);
            color: var(--vscode-foreground);
            background: var(--vscode-background);
        }
        .toolbar {
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
            align-items: center;
        }
        .toolbar button {
            padding: 6px 12px;
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            cursor: pointer;
            border-radius: 2px;
        }
        .toolbar button:hover {
            background: var(--vscode-button-hoverBackground);
        }
        .container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            height: calc(100vh - 80px);
        }
        .panel {
            background: var(--vscode-editorWidget-background);
            border: 1px solid var(--vscode-editorWidget-border);
            border-radius: 4px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .panel-header {
            padding: 8px 12px;
            background: var(--vscode-sideBarSectionHeader-background);
            border-bottom: 1px solid var(--vscode-editorWidget-border);
            font-weight: bold;
        }
        .panel-content {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
        }
        .action-item {
            padding: 8px;
            margin-bottom: 4px;
            background: var(--vscode-list-hoverBackground);
            border-radius: 4px;
            cursor: pointer;
            border-left: 3px solid transparent;
        }
        .action-item:hover {
            background: var(--vscode-list-activeSelectionBackground);
        }
        .action-item.selected {
            border-left-color: var(--vscode-focusBorder);
            background: var(--vscode-list-activeSelectionBackground);
        }
        .action-item .summary {
            font-weight: 500;
            margin-bottom: 4px;
        }
        .action-item .meta {
            font-size: 0.85em;
            opacity: 0.8;
        }
        .action-item .status {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.75em;
            margin-left: 8px;
        }
        .status-not_started { background: var(--vscode-badge-background); }
        .status-queued { background: var(--vscode-inputValidation-warningBackground); }
        .status-running { background: var(--vscode-inputValidation-infoBackground); }
        .status-succeeded { background: var(--vscode-testing-iconPassed); color: white; }
        .status-failed { background: var(--vscode-testing-iconFailed); color: white; }
        .detail-section {
            margin-bottom: 16px;
        }
        .detail-section h3 {
            margin: 0 0 8px 0;
            font-size: 0.9em;
            opacity: 0.9;
        }
        .detail-value {
            font-family: var(--vscode-editor-font-family);
            background: var(--vscode-textBlockQuote-background);
            padding: 8px;
            border-radius: 4px;
            word-break: break-all;
        }
        .behavior-tag {
            display: inline-block;
            padding: 2px 8px;
            margin: 2px;
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
            border-radius: 3px;
            font-size: 0.85em;
            cursor: pointer;
        }
        .behavior-tag:hover {
            background: var(--vscode-focusBorder);
        }
        .replay-progress {
            padding: 12px;
            background: var(--vscode-inputValidation-infoBackground);
            border-radius: 4px;
            margin-bottom: 16px;
        }
        .replay-progress .progress-bar {
            height: 4px;
            background: var(--vscode-progressBar-background);
            border-radius: 2px;
            margin-top: 8px;
        }
        .replay-progress .progress-fill {
            height: 100%;
            background: var(--vscode-progressBar-foreground, #0e639c);
            border-radius: 2px;
            transition: width 0.3s;
        }
        .empty-state {
            text-align: center;
            padding: 40px;
            opacity: 0.7;
        }
        .checkbox-list {
            margin-bottom: 8px;
        }
        .checkbox-list label {
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="toolbar">
        <button onclick="refresh()">⟳ Refresh</button>
        <button onclick="replaySelected(false)">▶ Quick Replay Selected</button>
        <button onclick="replaySelected(true)">🔍 Dry Run Selected</button>
        <button onclick="clearFilters()">✕ Clear Filters</button>
    </div>

    <div id="replay-status" class="replay-progress" style="display: none;">
        <div>Replay in progress: <span id="replay-status-text">...</span></div>
        <div class="progress-bar">
            <div class="progress-fill" id="replay-progress-fill" style="width: 0%"></div>
        </div>
    </div>

    <div class="container">
        <div class="panel">
            <div class="panel-header">Actions Timeline</div>
            <div class="panel-content" id="actions-list">
                <div class="empty-state">Loading actions...</div>
            </div>
        </div>
        <div class="panel">
            <div class="panel-header">Action Details</div>
            <div class="panel-content" id="action-detail">
                <div class="empty-state">Select an action to view details</div>
            </div>
        </div>
    </div>

    <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();
        let actions = [];
        let selectedActionId = null;
        let selectedActionIds = new Set();

        function refresh() {
            vscode.postMessage({ command: 'refresh' });
        }

        function clearFilters() {
            vscode.postMessage({ command: 'clearFilters' });
        }

        function selectAction(actionId) {
            selectedActionId = actionId;
            vscode.postMessage({ command: 'selectAction', actionId });
            updateActionsList();
        }

        function toggleActionSelection(actionId, event) {
            event.stopPropagation();
            if (selectedActionIds.has(actionId)) {
                selectedActionIds.delete(actionId);
            } else {
                selectedActionIds.add(actionId);
            }
            updateActionsList();
        }

        function replaySelected(dryRun) {
            const ids = Array.from(selectedActionIds);
            if (ids.length === 0) {
                if (selectedActionId) {
                    ids.push(selectedActionId);
                } else {
                    return;
                }
            }
            vscode.postMessage({ command: 'quickReplay', actionIds: ids, dryRun });
        }

        function filterByBehavior(behaviorId) {
            vscode.postMessage({ command: 'filterByBehavior', behaviorId });
        }

        function copyActionId(actionId) {
            vscode.postMessage({ command: 'copyActionId', actionId });
        }

        function formatStatus(status) {
            const map = {
                'NOT_STARTED': 'Recorded',
                'QUEUED': 'Queued',
                'RUNNING': 'Running',
                'SUCCEEDED': 'Replayed',
                'FAILED': 'Failed'
            };
            return map[status] || status;
        }

        function formatDate(dateStr) {
            return new Date(dateStr).toLocaleString();
        }

        function updateActionsList() {
            const container = document.getElementById('actions-list');

            if (actions.length === 0) {
                container.innerHTML = '<div class="empty-state">No actions recorded yet.<br><br>Record actions using:<br><code>amprealize record-action</code></div>';
                return;
            }

            container.innerHTML = actions.map(action => {
                const isSelected = action.action_id === selectedActionId;
                const isChecked = selectedActionIds.has(action.action_id);
                const statusClass = 'status-' + (action.replay_status || 'not_started').toLowerCase();

                return \`
                    <div class="action-item \${isSelected ? 'selected' : ''}" onclick="selectAction('\${action.action_id}')">
                        <div class="checkbox-list">
                            <label onclick="event.stopPropagation()">
                                <input type="checkbox" \${isChecked ? 'checked' : ''} onchange="toggleActionSelection('\${action.action_id}', event)">
                                <span class="summary">\${escapeHtml(action.summary)}</span>
                                <span class="status \${statusClass}">\${formatStatus(action.replay_status || 'NOT_STARTED')}</span>
                            </label>
                        </div>
                        <div class="meta">
                            📁 \${escapeHtml(action.artifact_path)} • 🕐 \${formatDate(action.timestamp)}
                        </div>
                    </div>
                \`;
            }).join('');
        }

        function updateActionDetail(action) {
            const container = document.getElementById('action-detail');

            if (!action) {
                container.innerHTML = '<div class="empty-state">Select an action to view details</div>';
                return;
            }

            const behaviors = (action.behaviors_cited || []).map(b =>
                \`<span class="behavior-tag" onclick="filterByBehavior('\${escapeHtml(b)}')">\${escapeHtml(b)}</span>\`
            ).join('');

            const commands = action.metadata?.commands?.map(c =>
                \`<code>\${escapeHtml(c)}</code>\`
            ).join('<br>') || 'None recorded';

            container.innerHTML = \`
                <div class="detail-section">
                    <h3>Summary</h3>
                    <div class="detail-value">\${escapeHtml(action.summary)}</div>
                </div>
                <div class="detail-section">
                    <h3>Artifact Path</h3>
                    <div class="detail-value">\${escapeHtml(action.artifact_path)}</div>
                </div>
                <div class="detail-section">
                    <h3>Action ID</h3>
                    <div class="detail-value" style="cursor: pointer" onclick="copyActionId('\${action.action_id}')">\${action.action_id} 📋</div>
                </div>
                <div class="detail-section">
                    <h3>Behaviors Cited</h3>
                    <div>\${behaviors || 'None'}</div>
                </div>
                <div class="detail-section">
                    <h3>Status</h3>
                    <div class="detail-value">\${formatStatus(action.replay_status || 'NOT_STARTED')}</div>
                </div>
                <div class="detail-section">
                    <h3>Timestamp</h3>
                    <div class="detail-value">\${formatDate(action.timestamp)}</div>
                </div>
                <div class="detail-section">
                    <h3>Checksum</h3>
                    <div class="detail-value">\${action.checksum || 'Not calculated'}</div>
                </div>
                <div class="detail-section">
                    <h3>Commands</h3>
                    <div class="detail-value">\${commands}</div>
                </div>
                \${action.metadata?.validation_output ? \`
                <div class="detail-section">
                    <h3>Validation Output</h3>
                    <div class="detail-value"><pre>\${escapeHtml(action.metadata.validation_output)}</pre></div>
                </div>
                \` : ''}
            \`;
        }

        function updateReplayStatus(status) {
            const container = document.getElementById('replay-status');
            const statusText = document.getElementById('replay-status-text');
            const progressFill = document.getElementById('replay-progress-fill');

            if (status.status === 'RUNNING' || status.status === 'QUEUED') {
                container.style.display = 'block';
                statusText.textContent = \`\${status.status} - \${status.completed_actions?.length || 0} completed, \${status.failed_actions?.length || 0} failed\`;
                progressFill.style.width = (status.progress || 0) + '%';
            } else {
                container.style.display = 'none';
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text || '';
            return div.innerHTML;
        }

        // Handle messages from extension
        window.addEventListener('message', event => {
            const message = event.data;
            switch (message.command) {
                case 'updateContent':
                    actions = message.actions || [];
                    updateActionsList();
                    if (message.selectedAction) {
                        updateActionDetail(message.selectedAction);
                    }
                    break;
                case 'replayStatus':
                    updateReplayStatus(message.status);
                    break;
            }
        });

        // Initial load
        refresh();
    </script>
</body>
</html>`;
    }

    public dispose() {
        if (this._replayStatusPollInterval) {
            clearInterval(this._replayStatusPollInterval);
        }

        ActionTimelinePanel.currentPanel = undefined;
        this._panel.dispose();

        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
}

function getNonce() {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
