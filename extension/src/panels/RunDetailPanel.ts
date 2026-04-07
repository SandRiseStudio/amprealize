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

import * as crypto from 'crypto';
import * as vscode from 'vscode';
import { Run } from '../client/AmprealizeClient';
import { buildActorAvatarHtml, createActorViewModel } from '../utils/actorAvatar';

export class RunDetailPanel {
	public static currentPanel: RunDetailPanel | undefined;

	public static readonly viewType = 'amprealize.runDetail';

	private readonly _panel: vscode.WebviewPanel;
	private readonly _extensionUri: vscode.Uri;
	private _disposables: vscode.Disposable[] = [];
	private _run: Run | null = null;

	private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
		this._panel = panel;
		this._extensionUri = extensionUri;

		// Set the webview's initial html content
		this._update();

		// Listen for when the panel is disposed
		// This happens when the user closes the panel or when the panel is closed programmatically
		this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

		// Handle messages from the webview
		this._panel.webview.onDidReceiveMessage(
			async (message) => {
				switch (message.type) {
					case 'refreshRun':
						await this._refreshRun();
						return;
					case 'exportLogs':
						await this._exportLogs();
						return;
					case 'copyRunId':
						await this._copyRunId();
						return;
					case 'openLogsFile':
						await this._openLogsFile();
						return;
				}
			},
			null,
			this._disposables
		);
	}

	public static createOrShow(extensionUri: vscode.Uri, run: Run) {
		// If we already have a panel, show it
		const column = vscode.ViewColumn.One;
		if (RunDetailPanel.currentPanel) {
			RunDetailPanel.currentPanel._panel.reveal(column);
			RunDetailPanel.currentPanel._run = run;
			RunDetailPanel.currentPanel._update();
			return;
		}

		// Otherwise, create a new panel
		const panel = vscode.window.createWebviewPanel(
			RunDetailPanel.viewType,
			`Run Details: ${run.workflow_name || run.template_name || 'Unnamed Workflow'}`,
			column || vscode.ViewColumn.One,
			{
				// Enable javascript in the webview
				enableScripts: true,
				// Restrict the webview to only load resources from the `out` directory
				localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'out'), vscode.Uri.joinPath(extensionUri, 'webview-ui/build')]
			}
		);

		RunDetailPanel.currentPanel = new RunDetailPanel(panel, extensionUri);
		RunDetailPanel.currentPanel._run = run;
	}

	public static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
		RunDetailPanel.currentPanel = new RunDetailPanel(panel, extensionUri);
	}

	private _update() {
		const webview = this._panel.webview;

		// Vary the webview content based on whether a run is available
		if (!this._run) {
			this._panel.webview.html = this._getHtmlForWebview(webview, null);
			return;
		}

		this._panel.webview.html = this._getHtmlForWebview(webview, this._run);
	}

	private async _refreshRun() {
		if (!this._run) return;

		try {
			// TODO: Get updated run from RunService via AmprealizeClient
			// For now, we'll just trigger a visual refresh
			this._update();
			this._panel.webview.postMessage({ type: 'runUpdated' });
		} catch (error) {
			console.error('Failed to refresh run:', error);
		}
	}

	private async _exportLogs() {
		if (!this._run) return;

		try {
			const exportData = {
				runId: this._run.run_id,
				workflowName: this._run.workflow_name,
				status: this._run.status,
				progress: this._run.progress_pct,
				createdAt: this._run.created_at,
				updatedAt: this._run.updated_at,
				tokensGenerated: this._run.tokens_generated,
				error: this._run.error,
				stepCurrent: this._run.step_current
			};

			const jsonContent = JSON.stringify(exportData, null, 2);
			const document = await vscode.workspace.openTextDocument({
				content: jsonContent,
				language: 'json'
			});

			await vscode.window.showTextDocument(document);
			vscode.window.showInformationMessage(`Run logs exported for run ${this._run.run_id}`);
		} catch (error) {
			vscode.window.showErrorMessage(`Failed to export logs: ${error}`);
		}
	}

	private async _copyRunId() {
		if (!this._run) return;

		try {
			await vscode.env.clipboard.writeText(this._run.run_id);
			vscode.window.showInformationMessage('Run ID copied to clipboard');
		} catch (error) {
			vscode.window.showErrorMessage(`Failed to copy run ID: ${error}`);
		}
	}

	private async _openLogsFile() {
		if (!this._run) return;

		// TODO: This would open a logs file if one exists
		// For now, show a message that this feature is coming soon
		vscode.window.showInformationMessage('Opening logs file - feature coming soon');
	}

	private _getHtmlForWebview(webview: vscode.Webview, run: Run | null) {
		// Local path to script run in the webview, then it can use the vscode api to perform webview specific operations
		const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'webviews', 'runDetail.js'));

		// Local path to css styles
		const styleResetUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'out', 'viewExplorer.css'));
		const styleMainUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'styles', 'RunDetailPanel.css'));

		// Use a nonce to only allow specific scripts to be run
		const nonce = getNonce();

		if (!run) {
			return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Run Details</title>
	<link href="${styleResetUri}" rel="stylesheet">
	<link href="${styleMainUri}" rel="stylesheet">
</head>
<body>
	<div class="container">
		<div class="no-run">
			<h2>No Run Selected</h2>
			<p>Select a run from the Execution Tracker to view its details.</p>
		</div>
	</div>
</body>
</html>`;
		}

		const actorAvatarHtml = buildActorAvatarHtml(
			createActorViewModel({
				id: run.actor.id,
				kind: 'agent',
				displayName: run.actor.id,
				subtitle: run.actor.role,
				presenceState:
					run.status.toLowerCase() === 'running' || run.status.toLowerCase() === 'in_progress'
						? 'working'
						: run.status.toLowerCase() === 'failed' || run.status.toLowerCase() === 'cancelled'
							? 'paused'
							: 'available',
			}),
			44,
		);

		return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Run Details: ${run.workflow_name || run.template_name || 'Unnamed Workflow'}</title>
	<link href="${styleResetUri}" rel="stylesheet">
	<link href="${styleMainUri}" rel="stylesheet">
</head>
<body>
	<div class="container">
		<header class="run-header">
			<div class="run-title">
				<div style="display:flex;align-items:center;gap:12px;">
					${actorAvatarHtml}
					<div>
						<h1>${run.workflow_name || run.template_name || 'Unnamed Workflow'}</h1>
						<div class="run-meta">
							<span class="run-id" id="runId">${run.run_id}</span>
							<button class="copy-btn" onclick="vscode.postMessage({type: 'copyRunId'})">Copy ID</button>
						</div>
					</div>
				</div>
			</div>
			<div class="run-status">
				<span class="status-badge status-${run.status.toLowerCase()}">${run.status}</span>
				<span class="progress-text">${run.progress_pct || 0}% complete</span>
			</div>
		</header>

		<div class="run-actions">
			<button class="action-btn" onclick="vscode.postMessage({type: 'refreshRun'})">
				<i class="icon-refresh"></i> Refresh
			</button>
			<button class="action-btn" onclick="vscode.postMessage({type: 'exportLogs'})">
				<i class="icon-export"></i> Export Logs
			</button>
			<button class="action-btn" onclick="vscode.postMessage({type: 'openLogsFile'})">
				<i class="icon-file"></i> Open Logs
			</button>
		</div>

		<div class="run-content">
			<div class="timeline-section">
				<h2>Execution Timeline</h2>
				<div class="timeline">
					<div class="timeline-item current">
						<div class="timeline-marker"></div>
						<div class="timeline-content">
							<h3>Current Step: ${run.step_current?.name || 'Not started'}</h3>
							<p class="step-status">Status: ${run.step_current?.status || 'Pending'}</p>
							${(run.step_current as any)?.started_at ? `<p class="step-time">Started: ${new Date((run.step_current as any).started_at).toLocaleString()}</p>` : ''}
							${(run.step_current as any)?.completed_at ? `<p class="step-time">Completed: ${new Date((run.step_current as any).completed_at).toLocaleString()}</p>` : ''}
						</div>
					</div>
					${run.step_progress ? `
					<div class="timeline-item completed">
						<div class="timeline-marker"></div>
						<div class="timeline-content">
							<h3>Progress: Step ${run.step_progress.current} of ${run.step_progress.total}</h3>
						</div>
					</div>` : ''}
				</div>
			</div>

			<div class="metrics-section">
				<h2>Metrics</h2>
				<div class="metrics-grid">
					<div class="metric-card">
						<h3>Token Usage</h3>
						<div class="metric-value">${run.tokens_generated || 0}</div>
					</div>
					<div class="metric-card">
						<h3>Started</h3>
						<div class="metric-value">${new Date(run.created_at).toLocaleString()}</div>
					</div>
					<div class="metric-card">
						<h3>Last Updated</h3>
						<div class="metric-value">${new Date(run.updated_at).toLocaleString()}</div>
					</div>
				</div>
			</div>

			${run.error ? `
			<div class="error-section">
				<h2>Error Information</h2>
				<div class="error-box">
					<p>${run.error}</p>
				</div>
			</div>` : ''}
		</div>
	</div>

	<script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
	}

	public dispose() {
		RunDetailPanel.currentPanel = undefined;

		// Clean up our resources
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
	const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
	let text = '';
	for (let i = 0; i < 8; i++) {
		const index = Math.floor(Math.random() * possible.length);
		text += possible.charAt(index);
	}
	return text;
}
