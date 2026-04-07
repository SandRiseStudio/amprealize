"use strict";
/**
 * BehaviorAccuracyPanel
 *
 * Webview panel for behavior accuracy scoring and effectiveness metrics.
 * Allows users to:
 * - View behavior effectiveness metrics (usage count, token savings, accuracy)
 * - Submit manual feedback on behavior accuracy
 * - Configure scoring mode (manual vs LLM-as-judge)
 * - View and manage pending accuracy reviews
 *
 * Following `behavior_curate_behavior_handbook` (Student)
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.BehaviorAccuracyPanel = void 0;
const vscode = __importStar(require("vscode"));
class BehaviorAccuracyPanel {
    constructor(panel, _client, _extensionUri) {
        this._client = _client;
        this._extensionUri = _extensionUri;
        this._disposables = [];
        this._behaviors = [];
        this._effectiveness = [];
        this._scoringConfig = { mode: 'manual' };
        this._selectedBehaviorId = null;
        this._panel = panel;
        // Set initial HTML content
        this._update();
        // Listen for panel disposal
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        // Handle messages from the webview
        this._panel.webview.onDidReceiveMessage(async (message) => {
            switch (message.command) {
                case 'refresh':
                    await this._loadData();
                    break;
                case 'submitFeedback':
                    await this._submitFeedback(message.feedback);
                    break;
                case 'updateConfig':
                    await this._updateScoringConfig(message.config);
                    break;
                case 'selectBehavior':
                    this._selectedBehaviorId = message.behaviorId;
                    this._update();
                    break;
                case 'exportMetrics':
                    await this._exportMetrics();
                    break;
            }
        }, null, this._disposables);
        // Load initial data
        this._loadData();
    }
    static createOrShow(client, extensionUri) {
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;
        // If we already have a panel, show it
        if (BehaviorAccuracyPanel.currentPanel) {
            BehaviorAccuracyPanel.currentPanel._panel.reveal(column);
            return;
        }
        // Otherwise, create a new panel
        const panel = vscode.window.createWebviewPanel('behaviorAccuracy', 'Behavior Accuracy', column || vscode.ViewColumn.One, {
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'resources')]
        });
        BehaviorAccuracyPanel.currentPanel = new BehaviorAccuracyPanel(panel, client, extensionUri);
    }
    dispose() {
        BehaviorAccuracyPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const disposable = this._disposables.pop();
            if (disposable) {
                disposable.dispose();
            }
        }
    }
    async _loadData() {
        try {
            // Load behaviors
            this._behaviors = await this._client.listBehaviors(undefined, {
                source: 'accuracy_panel.load'
            });
            // Load effectiveness metrics via CLI
            const effectivenessResult = await this._client.runCLI([
                'behaviors', 'effectiveness', '--format', 'json'
            ]);
            this._effectiveness = effectivenessResult;
            // Load scoring config
            const configResult = await this._client.runCLI([
                'behaviors', 'scoring-config', '--format', 'json'
            ]);
            this._scoringConfig = configResult;
            this._update();
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to load accuracy data: ${error}`);
        }
    }
    async _submitFeedback(feedback) {
        try {
            const args = [
                'behaviors', 'submit-feedback',
                '--behavior-id', feedback.behavior_id,
                '--helpful', feedback.was_helpful ? 'true' : 'false',
                '--rating', String(feedback.accuracy_rating)
            ];
            if (feedback.run_id) {
                args.push('--run-id', feedback.run_id);
            }
            if (feedback.query) {
                args.push('--query', feedback.query);
            }
            if (feedback.comment) {
                args.push('--comment', feedback.comment);
            }
            await this._client.runCLI(args);
            vscode.window.showInformationMessage('Feedback submitted successfully');
            await this._loadData();
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to submit feedback: ${error}`);
        }
    }
    async _updateScoringConfig(config) {
        try {
            const args = [
                'behaviors', 'set-scoring-config',
                '--mode', config.mode
            ];
            if (config.llm_model) {
                args.push('--llm-model', config.llm_model);
            }
            if (config.auto_score_threshold !== undefined) {
                args.push('--auto-score-threshold', String(config.auto_score_threshold));
            }
            if (config.require_human_review_below !== undefined) {
                args.push('--require-human-review-below', String(config.require_human_review_below));
            }
            await this._client.runCLI(args);
            this._scoringConfig = config;
            vscode.window.showInformationMessage('Scoring configuration updated');
            this._update();
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to update config: ${error}`);
        }
    }
    async _exportMetrics() {
        try {
            const uri = await vscode.window.showSaveDialog({
                defaultUri: vscode.Uri.file('behavior-effectiveness.json'),
                filters: { 'JSON': ['json'], 'CSV': ['csv'] }
            });
            if (uri) {
                const format = uri.fsPath.endsWith('.csv') ? 'csv' : 'json';
                const result = await this._client.runCLI([
                    'behaviors', 'export-effectiveness',
                    '--format', format
                ], { parseJson: false });
                await vscode.workspace.fs.writeFile(uri, Buffer.from(result));
                vscode.window.showInformationMessage(`Exported to ${uri.fsPath}`);
            }
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to export: ${error}`);
        }
    }
    _update() {
        this._panel.webview.html = this._getHtmlForWebview();
    }
    _getHtmlForWebview() {
        const webview = this._panel.webview;
        const nonce = getNonce();
        // Find selected behavior's effectiveness
        const selectedEffectiveness = this._selectedBehaviorId
            ? this._effectiveness.find(e => e.behavior_id === this._selectedBehaviorId)
            : null;
        // Calculate aggregate stats
        const totalUsage = this._effectiveness.reduce((sum, e) => sum + e.usage_count, 0);
        const avgTokenSavings = this._effectiveness.length > 0
            ? this._effectiveness.reduce((sum, e) => sum + e.token_savings_pct, 0) / this._effectiveness.length
            : 0;
        const avgAccuracy = this._effectiveness.length > 0
            ? this._effectiveness.reduce((sum, e) => sum + e.accuracy_score, 0) / this._effectiveness.length
            : 0;
        const totalFeedback = this._effectiveness.reduce((sum, e) => sum + e.feedback_count, 0);
        return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Behavior Accuracy</title>
	<style>
		:root {
			--bg-primary: var(--vscode-editor-background);
			--bg-secondary: var(--vscode-sideBar-background);
			--text-primary: var(--vscode-editor-foreground);
			--text-secondary: var(--vscode-descriptionForeground);
			--border-color: var(--vscode-panel-border);
			--accent: var(--vscode-button-background);
			--success: var(--vscode-terminal-ansiGreen);
			--warning: var(--vscode-terminal-ansiYellow);
			--error: var(--vscode-terminal-ansiRed);
		}

		body {
			font-family: var(--vscode-font-family);
			font-size: var(--vscode-font-size);
			color: var(--text-primary);
			background: var(--bg-primary);
			padding: 16px;
			margin: 0;
		}

		.header {
			display: flex;
			justify-content: space-between;
			align-items: center;
			margin-bottom: 24px;
			padding-bottom: 16px;
			border-bottom: 1px solid var(--border-color);
		}

		.header h1 {
			margin: 0;
			font-size: 1.5em;
		}

		.header-actions {
			display: flex;
			gap: 8px;
		}

		.btn {
			background: var(--vscode-button-background);
			color: var(--vscode-button-foreground);
			border: none;
			padding: 6px 12px;
			border-radius: 4px;
			cursor: pointer;
			font-size: 12px;
		}

		.btn:hover {
			background: var(--vscode-button-hoverBackground);
		}

		.btn-secondary {
			background: var(--vscode-button-secondaryBackground);
			color: var(--vscode-button-secondaryForeground);
		}

		.stats-grid {
			display: grid;
			grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
			gap: 12px;
			margin-bottom: 24px;
		}

		.stat-card {
			background: var(--bg-secondary);
			padding: 16px;
			border-radius: 8px;
			border: 1px solid var(--border-color);
		}

		.stat-card__label {
			display: block;
			font-size: 11px;
			text-transform: uppercase;
			color: var(--text-secondary);
			margin-bottom: 4px;
		}

		.stat-card__value {
			font-size: 1.5em;
			font-weight: bold;
		}

		.config-section {
			background: var(--bg-secondary);
			padding: 16px;
			border-radius: 8px;
			border: 1px solid var(--border-color);
			margin-bottom: 24px;
		}

		.config-section h3 {
			margin: 0 0 12px 0;
			font-size: 1em;
		}

		.config-row {
			display: flex;
			gap: 16px;
			align-items: center;
			flex-wrap: wrap;
		}

		.config-field {
			display: flex;
			flex-direction: column;
			gap: 4px;
		}

		.config-field label {
			font-size: 11px;
			color: var(--text-secondary);
		}

		.config-field select,
		.config-field input {
			background: var(--vscode-input-background);
			color: var(--vscode-input-foreground);
			border: 1px solid var(--vscode-input-border);
			padding: 4px 8px;
			border-radius: 4px;
		}

		.layout-grid {
			display: grid;
			grid-template-columns: 1fr 1fr;
			gap: 24px;
		}

		@media (max-width: 800px) {
			.layout-grid {
				grid-template-columns: 1fr;
			}
		}

		.panel {
			background: var(--bg-secondary);
			border-radius: 8px;
			border: 1px solid var(--border-color);
			overflow: hidden;
		}

		.panel-header {
			padding: 12px 16px;
			border-bottom: 1px solid var(--border-color);
			font-weight: bold;
		}

		.panel-content {
			padding: 16px;
			max-height: 400px;
			overflow-y: auto;
		}

		.behavior-list {
			list-style: none;
			padding: 0;
			margin: 0;
		}

		.behavior-item {
			display: flex;
			justify-content: space-between;
			align-items: center;
			padding: 8px 12px;
			border-bottom: 1px solid var(--border-color);
			cursor: pointer;
		}

		.behavior-item:hover {
			background: var(--vscode-list-hoverBackground);
		}

		.behavior-item.selected {
			background: var(--vscode-list-activeSelectionBackground);
			color: var(--vscode-list-activeSelectionForeground);
		}

		.behavior-item:last-child {
			border-bottom: none;
		}

		.behavior-name {
			font-weight: 500;
		}

		.behavior-stats {
			display: flex;
			gap: 12px;
			font-size: 12px;
			color: var(--text-secondary);
		}

		.accuracy-badge {
			padding: 2px 6px;
			border-radius: 4px;
			font-weight: bold;
		}

		.accuracy-high { background: var(--success); color: #000; }
		.accuracy-medium { background: var(--warning); color: #000; }
		.accuracy-low { background: var(--error); color: #fff; }

		.feedback-form {
			display: flex;
			flex-direction: column;
			gap: 12px;
		}

		.form-group {
			display: flex;
			flex-direction: column;
			gap: 4px;
		}

		.form-group label {
			font-size: 12px;
			font-weight: 500;
		}

		.form-group textarea,
		.form-group input,
		.form-group select {
			background: var(--vscode-input-background);
			color: var(--vscode-input-foreground);
			border: 1px solid var(--vscode-input-border);
			padding: 8px;
			border-radius: 4px;
		}

		.form-group textarea {
			min-height: 80px;
			resize: vertical;
		}

		.rating-group {
			display: flex;
			gap: 8px;
		}

		.rating-btn {
			width: 36px;
			height: 36px;
			border-radius: 50%;
			border: 2px solid var(--border-color);
			background: transparent;
			color: var(--text-primary);
			cursor: pointer;
			font-weight: bold;
		}

		.rating-btn:hover {
			border-color: var(--accent);
		}

		.rating-btn.selected {
			background: var(--accent);
			color: var(--vscode-button-foreground);
			border-color: var(--accent);
		}

		.helpful-toggle {
			display: flex;
			gap: 8px;
		}

		.helpful-btn {
			flex: 1;
			padding: 8px;
			border: 2px solid var(--border-color);
			background: transparent;
			color: var(--text-primary);
			cursor: pointer;
			border-radius: 4px;
		}

		.helpful-btn:hover {
			border-color: var(--accent);
		}

		.helpful-btn.selected {
			border-color: var(--accent);
			background: var(--accent);
			color: var(--vscode-button-foreground);
		}

		.empty-state {
			text-align: center;
			padding: 32px;
			color: var(--text-secondary);
		}
	</style>
</head>
<body>
	<div class="header">
		<h1>🎯 Behavior Accuracy Dashboard</h1>
		<div class="header-actions">
			<button class="btn btn-secondary" onclick="refresh()">Refresh</button>
			<button class="btn btn-secondary" onclick="exportMetrics()">Export</button>
		</div>
	</div>

	<div class="stats-grid">
		<div class="stat-card">
			<span class="stat-card__label">Total Usage</span>
			<span class="stat-card__value">${totalUsage.toLocaleString()}</span>
		</div>
		<div class="stat-card">
			<span class="stat-card__label">Avg Token Savings</span>
			<span class="stat-card__value">${avgTokenSavings.toFixed(1)}%</span>
		</div>
		<div class="stat-card">
			<span class="stat-card__label">Avg Accuracy</span>
			<span class="stat-card__value">${avgAccuracy.toFixed(1)}%</span>
		</div>
		<div class="stat-card">
			<span class="stat-card__label">Total Feedback</span>
			<span class="stat-card__value">${totalFeedback}</span>
		</div>
		<div class="stat-card">
			<span class="stat-card__label">Behaviors Tracked</span>
			<span class="stat-card__value">${this._effectiveness.length}</span>
		</div>
		<div class="stat-card">
			<span class="stat-card__label">Scoring Mode</span>
			<span class="stat-card__value" style="font-size: 1em; text-transform: capitalize;">${this._scoringConfig.mode}</span>
		</div>
	</div>

	<div class="config-section">
		<h3>⚙️ Scoring Configuration</h3>
		<div class="config-row">
			<div class="config-field">
				<label>Mode</label>
				<select id="scoringMode" onchange="updateConfig()">
					<option value="manual" ${this._scoringConfig.mode === 'manual' ? 'selected' : ''}>Manual Only</option>
					<option value="llm" ${this._scoringConfig.mode === 'llm' ? 'selected' : ''}>LLM-as-Judge</option>
					<option value="hybrid" ${this._scoringConfig.mode === 'hybrid' ? 'selected' : ''}>Hybrid</option>
				</select>
			</div>
			<div class="config-field" id="llmModelField" style="display: ${this._scoringConfig.mode !== 'manual' ? 'flex' : 'none'}">
				<label>LLM Model</label>
				<input type="text" id="llmModel" value="${this._scoringConfig.llm_model || 'gpt-4'}" placeholder="gpt-4" />
			</div>
			<div class="config-field" id="thresholdField" style="display: ${this._scoringConfig.mode === 'hybrid' ? 'flex' : 'none'}">
				<label>Auto-score Threshold</label>
				<input type="number" id="autoThreshold" value="${this._scoringConfig.auto_score_threshold || 80}" min="0" max="100" />
			</div>
			<div class="config-field" id="reviewField" style="display: ${this._scoringConfig.mode === 'hybrid' ? 'flex' : 'none'}">
				<label>Require Review Below</label>
				<input type="number" id="reviewBelow" value="${this._scoringConfig.require_human_review_below || 50}" min="0" max="100" />
			</div>
			<button class="btn" onclick="saveConfig()">Save Config</button>
		</div>
	</div>

	<div class="layout-grid">
		<div class="panel">
			<div class="panel-header">📊 Behavior Effectiveness</div>
			<div class="panel-content">
				${this._effectiveness.length > 0 ? `
					<ul class="behavior-list">
						${this._effectiveness.map(e => `
							<li class="behavior-item ${this._selectedBehaviorId === e.behavior_id ? 'selected' : ''}"
								onclick="selectBehavior('${e.behavior_id}')">
								<span class="behavior-name">${e.behavior_name}</span>
								<span class="behavior-stats">
									<span>📈 ${e.usage_count} uses</span>
									<span>💾 ${e.token_savings_pct.toFixed(0)}%</span>
									<span class="accuracy-badge ${e.accuracy_score >= 80 ? 'accuracy-high' : e.accuracy_score >= 50 ? 'accuracy-medium' : 'accuracy-low'}">
										${e.accuracy_score.toFixed(0)}%
									</span>
								</span>
							</li>
						`).join('')}
					</ul>
				` : `
					<div class="empty-state">
						<p>No effectiveness data yet</p>
						<p>Use behaviors in your workflows to start collecting metrics</p>
					</div>
				`}
			</div>
		</div>

		<div class="panel">
			<div class="panel-header">📝 Submit Feedback</div>
			<div class="panel-content">
				${this._selectedBehaviorId ? `
					<form class="feedback-form" onsubmit="submitFeedback(event)">
						<div class="form-group">
							<label>Selected Behavior</label>
							<input type="text" value="${selectedEffectiveness?.behavior_name || 'Unknown'}" disabled />
							<input type="hidden" id="feedbackBehaviorId" value="${this._selectedBehaviorId}" />
						</div>

						<div class="form-group">
							<label>Was this behavior helpful?</label>
							<div class="helpful-toggle">
								<button type="button" class="helpful-btn" id="helpfulYes" onclick="setHelpful(true)">👍 Yes</button>
								<button type="button" class="helpful-btn" id="helpfulNo" onclick="setHelpful(false)">👎 No</button>
							</div>
							<input type="hidden" id="wasHelpful" />
						</div>

						<div class="form-group">
							<label>Accuracy Rating (1-5)</label>
							<div class="rating-group">
								<button type="button" class="rating-btn" onclick="setRating(1)">1</button>
								<button type="button" class="rating-btn" onclick="setRating(2)">2</button>
								<button type="button" class="rating-btn" onclick="setRating(3)">3</button>
								<button type="button" class="rating-btn" onclick="setRating(4)">4</button>
								<button type="button" class="rating-btn" onclick="setRating(5)">5</button>
							</div>
							<input type="hidden" id="accuracyRating" />
						</div>

						<div class="form-group">
							<label>Query Context (optional)</label>
							<input type="text" id="queryContext" placeholder="What were you trying to do?" />
						</div>

						<div class="form-group">
							<label>Additional Comments (optional)</label>
							<textarea id="feedbackComment" placeholder="Any additional feedback..."></textarea>
						</div>

						<button type="submit" class="btn">Submit Feedback</button>
					</form>
				` : `
					<div class="empty-state">
						<p>Select a behavior to submit feedback</p>
						<p>Click on a behavior in the list to get started</p>
					</div>
				`}
			</div>
		</div>
	</div>

	<script nonce="${nonce}">
		const vscode = acquireVsCodeApi();
		let currentRating = null;
		let currentHelpful = null;

		function refresh() {
			vscode.postMessage({ command: 'refresh' });
		}

		function exportMetrics() {
			vscode.postMessage({ command: 'exportMetrics' });
		}

		function selectBehavior(behaviorId) {
			vscode.postMessage({ command: 'selectBehavior', behaviorId });
		}

		function setRating(rating) {
			currentRating = rating;
			document.getElementById('accuracyRating').value = rating;
			document.querySelectorAll('.rating-btn').forEach((btn, i) => {
				btn.classList.toggle('selected', i + 1 === rating);
			});
		}

		function setHelpful(helpful) {
			currentHelpful = helpful;
			document.getElementById('wasHelpful').value = helpful ? 'true' : 'false';
			document.getElementById('helpfulYes').classList.toggle('selected', helpful === true);
			document.getElementById('helpfulNo').classList.toggle('selected', helpful === false);
		}

		function updateConfig() {
			const mode = document.getElementById('scoringMode').value;
			document.getElementById('llmModelField').style.display = mode !== 'manual' ? 'flex' : 'none';
			document.getElementById('thresholdField').style.display = mode === 'hybrid' ? 'flex' : 'none';
			document.getElementById('reviewField').style.display = mode === 'hybrid' ? 'flex' : 'none';
		}

		function saveConfig() {
			const mode = document.getElementById('scoringMode').value;
			const config = { mode };

			if (mode !== 'manual') {
				config.llm_model = document.getElementById('llmModel').value;
			}
			if (mode === 'hybrid') {
				config.auto_score_threshold = parseInt(document.getElementById('autoThreshold').value);
				config.require_human_review_below = parseInt(document.getElementById('reviewBelow').value);
			}

			vscode.postMessage({ command: 'updateConfig', config });
		}

		function submitFeedback(event) {
			event.preventDefault();

			if (currentHelpful === null) {
				alert('Please indicate if the behavior was helpful');
				return;
			}
			if (currentRating === null) {
				alert('Please provide an accuracy rating');
				return;
			}

			const feedback = {
				behavior_id: document.getElementById('feedbackBehaviorId').value,
				was_helpful: currentHelpful,
				accuracy_rating: currentRating,
				query: document.getElementById('queryContext').value || '',
				comment: document.getElementById('feedbackComment').value || ''
			};

			vscode.postMessage({ command: 'submitFeedback', feedback });

			// Reset form
			currentRating = null;
			currentHelpful = null;
			document.querySelectorAll('.rating-btn').forEach(btn => btn.classList.remove('selected'));
			document.querySelectorAll('.helpful-btn').forEach(btn => btn.classList.remove('selected'));
			document.getElementById('queryContext').value = '';
			document.getElementById('feedbackComment').value = '';
		}
	</script>
</body>
</html>`;
    }
}
exports.BehaviorAccuracyPanel = BehaviorAccuracyPanel;
function getNonce() {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
//# sourceMappingURL=BehaviorAccuracyPanel.js.map
