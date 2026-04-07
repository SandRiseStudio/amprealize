/**
 * BreakerAmp Panel
 *
 * Webview panel for the BreakerAmp Orchestrator:
 * - Blueprint management (list, select, edit)
 * - Visual DAG renderer
 * - Plan and Apply execution
 * - Real-time status monitoring
 */

import * as vscode from 'vscode';
import { AmprealizeClient } from '../client/AmprealizeClient';
import { McpClient, BreakerAmpPlanResult, BreakerAmpStatusResult, BreakerAmpListBlueprintsResult } from '../client/McpClient';

interface BlueprintInfo {
	id: string;
	path: string;
	source: 'package' | 'user';
}

export class BreakerAmpPanel {
	public static currentPanel: BreakerAmpPanel | undefined;

	public static readonly viewType = 'amprealize.breakeramp';

	private readonly _panel: vscode.WebviewPanel;
	private readonly _extensionUri: vscode.Uri;
	private readonly _client: AmprealizeClient;
	private readonly _mcpClient: McpClient;
	private _disposables: vscode.Disposable[] = [];

	// State
	private _blueprints: BlueprintInfo[] = [];
	private _selectedBlueprint: BlueprintInfo | null = null;
	private _planResult: BreakerAmpPlanResult | null = null;
	private _runId: string | null = null;
	private _runStatus: BreakerAmpStatusResult | null = null;

	private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, client: AmprealizeClient, mcpClient: McpClient) {
		this._panel = panel;
		this._extensionUri = extensionUri;
		this._client = client;
		this._mcpClient = mcpClient;

		// Set the webview's initial html content
		this.update();

		// Listen for when the panel is disposed
		this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

		// Handle messages from the webview
		this._panel.webview.onDidReceiveMessage(
			async (message) => {
				switch (message.type) {
					case 'refreshBlueprints':
						await this.refreshBlueprints();
						return;
					case 'selectBlueprint':
						this._selectedBlueprint = this._blueprints.find(b => b.id === message.blueprintId) || null;
						this._planResult = null;
						this._runId = null;
						this._runStatus = null;
						this.update();
						return;
					case 'plan':
						await this.runPlan();
						return;
					case 'apply':
						await this.runApply();
						return;
					case 'refreshStatus':
						await this.refreshStatus();
						return;
					case 'destroy':
						await this.runDestroy();
						return;
				}
			},
			null,
			this._disposables
		);

		// Initial load
		this.refreshBlueprints();
	}

	public static createOrShow(extensionUri: vscode.Uri, client: AmprealizeClient, mcpClient: McpClient) {
		const column = vscode.ViewColumn.One;

		if (BreakerAmpPanel.currentPanel) {
			BreakerAmpPanel.currentPanel._panel.reveal(column);
			return;
		}

		const panel = vscode.window.createWebviewPanel(
			BreakerAmpPanel.viewType,
			'BreakerAmp Orchestrator',
			column,
			{
				enableScripts: true,
				localResourceRoots: [
					vscode.Uri.joinPath(extensionUri, 'out'),
					vscode.Uri.joinPath(extensionUri, 'src', 'webviews'),
					vscode.Uri.joinPath(extensionUri, 'src', 'styles')
				]
			}
		);

		BreakerAmpPanel.currentPanel = new BreakerAmpPanel(panel, extensionUri, client, mcpClient);
	}

	public dispose() {
		BreakerAmpPanel.currentPanel = undefined;
		this._panel.dispose();
		while (this._disposables.length) {
			const x = this._disposables.pop();
			if (x) {
				x.dispose();
			}
		}
	}

	private async refreshBlueprints() {
		try {
			// Use MCP tool to list blueprints from BreakerAmpService
			const result = await this._mcpClient.breakerampListBlueprints({ source: 'all' });
			this._blueprints = result.blueprints;
			this.update();
		} catch (error) {
			// Fallback to scanning workspace if MCP fails (e.g., server not connected)
			const files = await vscode.workspace.findFiles('**/*.yaml');
			this._blueprints = files.map(f => ({
				id: f.path.split('/').pop()?.replace(/\.ya?ml$/i, '') || 'unknown',
				path: f.fsPath,
				source: 'user' as const
			}));
			this.update();
		}
	}

	private async runPlan() {
		if (!this._selectedBlueprint) {
			return;
		}

		try {
			this._panel.webview.postMessage({ type: 'planningStarted' });

			// Call MCP tool with blueprint ID from selection
			const result = await this._mcpClient.breakerampPlan({
				blueprintId: this._selectedBlueprint.id,
				complianceTier: 'dev',
				lifetime: '90m'
			});

			this._planResult = result;
			this._runId = result.amp_run_id;

			this.update();
			this._panel.webview.postMessage({ type: 'planningComplete', result: this._planResult });

		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			vscode.window.showErrorMessage(`Planning failed: ${message}`);
			this._panel.webview.postMessage({ type: 'planningFailed', error: message });
		}
	}

	private async runApply() {
		if (!this._planResult?.amp_run_id) {
			vscode.window.showWarningMessage('Please run Plan first');
			return;
		}

		try {
			this._panel.webview.postMessage({ type: 'applyStarted' });

			// Call MCP tool with plan ID
			const result = await this._mcpClient.breakerampApply({
				planId: this._planResult.amp_run_id,
				watch: false  // We'll poll status ourselves
			});

			this._runId = result.amp_run_id;
			this._runStatus = {
				amp_run_id: result.amp_run_id,
				status: result.status,
				progress: 0
			};

			this.update();

			// Start polling status
			this.startStatusPolling();

		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			vscode.window.showErrorMessage(`Apply failed: ${message}`);
			this._panel.webview.postMessage({ type: 'applyFailed', error: message });
		}
	}

	private startStatusPolling() {
		const interval = setInterval(async () => {
			if (!this._runId) {
				clearInterval(interval);
				return;
			}

			await this.refreshStatus();

			if (this._runStatus && (this._runStatus.status === 'completed' || this._runStatus.status === 'failed' || this._runStatus.status === 'destroyed')) {
				clearInterval(interval);
			}
		}, 2000);
	}

	private async refreshStatus() {
		if (!this._runId) {
			return;
		}

		try {
			// Call MCP tool
			const status = await this._mcpClient.breakerampStatus(this._runId);

			this._runStatus = status;
			this.update();

			// Notify webview of status update
			this._panel.webview.postMessage({ type: 'statusUpdate', status: this._runStatus });

		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			console.error('Failed to refresh status:', message);
		}
	}

	private async runDestroy() {
		if (!this._runId) {
			vscode.window.showWarningMessage('No active run to destroy');
			return;
		}

		const confirm = await vscode.window.showWarningMessage(
			`Are you sure you want to destroy run ${this._runId}?`,
			{ modal: true },
			'Destroy'
		);

		if (confirm !== 'Destroy') {
			return;
		}

		try {
			this._panel.webview.postMessage({ type: 'destroyStarted' });

			const result = await this._mcpClient.breakerampDestroy({
				runId: this._runId,
				cascade: true,
				reason: 'MANUAL'
			});

			if (result.status === 'destroyed') {
				vscode.window.showInformationMessage(`Run ${this._runId} destroyed successfully`);
				this._runId = null;
				this._runStatus = null;
				this._planResult = null;
			}

			this.update();
			this._panel.webview.postMessage({ type: 'destroyComplete', result });

		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			vscode.window.showErrorMessage(`Destroy failed: ${message}`);
			this._panel.webview.postMessage({ type: 'destroyFailed', error: message });
		}
	}

	private update() {
		const webview = this._panel.webview;
		this._panel.webview.html = this.getHtmlForWebview(webview);
	}

	private getHtmlForWebview(webview: vscode.Webview) {
		const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'webviews', 'breakeramp.js'));
		const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'styles', 'BreakerAmpPanel.css'));
		const nonce = getNonce();

		return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>BreakerAmp Orchestrator</title>
	<link href="${styleUri}" rel="stylesheet">
</head>
<body>
	<div class="container">
		<header>
			<h1>BreakerAmp Orchestrator</h1>
		</header>

		<div class="main-layout">
			<div class="sidebar">
				<h2>Blueprints</h2>
				<div class="blueprint-list">
					${this._blueprints.length > 0
						? this._blueprints.map(bp => `
							<div class="blueprint-item ${this._selectedBlueprint?.id === bp.id ? 'selected' : ''}"
								 onclick="selectBlueprint('${bp.id}')">
								<span class="blueprint-name">${bp.id}</span>
								<span class="blueprint-source ${bp.source}">${bp.source}</span>
							</div>
						`).join('')
						: '<p>No blueprints found</p>'
					}
				</div>
				<button class="refresh-btn" onclick="refreshBlueprints()">Refresh List</button>
			</div>

			<div class="content">
				${this._selectedBlueprint ? `
					<div class="blueprint-details">
						<h2>${this._selectedBlueprint.id}</h2>
						<p class="blueprint-path">${this._selectedBlueprint.path}</p>

						<div class="actions-bar">
							<button class="primary-btn" onclick="runPlan()">Plan</button>
							<button class="secondary-btn" onclick="runApply()" ${this._runId ? 'disabled' : ''}>Apply</button>
							<button class="danger-btn" onclick="runDestroy()">Destroy</button>
						</div>

						${this._planResult ? `
							<div class="plan-result">
								<h3>Plan Result</h3>
								<div class="dag-visualizer">
									<!-- Placeholder for DAG visualization -->
									<div class="dag-placeholder">
										${(this._planResult.steps || []).map((step: any) => `
											<div class="dag-node">
												<span class="node-name">${step.name}</span>
												<span class="node-type">${step.type}</span>
											</div>
										`).join('<div class="dag-arrow">↓</div>')}
									</div>
								</div>
							</div>
						` : ''}

						${this._runStatus ? `
							<div class="run-status-section">
								<h3>Execution Status: ${this._runStatus.status}</h3>
								<div class="progress-bar">
									<div class="progress-fill" style="width: ${this._runStatus.progress}%"></div>
								</div>
								<div class="step-status-list">
									${(this._runStatus.steps || []).map((step: any) => `
										<div class="step-status-item ${step.status}">
											${step.id}: ${step.status}
										</div>
									`).join('')}
								</div>
							</div>
						` : ''}

					</div>
				` : `
					<div class="empty-state">
						<p>Select a blueprint to get started</p>
					</div>
				`}
			</div>
		</div>
	</div>

	<script nonce="${nonce}" src="${scriptUri}"></script>
	<script nonce="${nonce}">
		const vscode = acquireVsCodeApi();

		function refreshBlueprints() {
			vscode.postMessage({ type: 'refreshBlueprints' });
		}

		function selectBlueprint(blueprintId) {
			vscode.postMessage({ type: 'selectBlueprint', blueprintId: blueprintId });
		}

		function runPlan() {
			vscode.postMessage({ type: 'plan' });
		}

		function runApply() {
			vscode.postMessage({ type: 'apply' });
		}

		function runDestroy() {
			vscode.postMessage({ type: 'destroy' });
		}
	</script>
</body>
</html>`;
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
