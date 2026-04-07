"use strict";
/**
 * Onboarding Panel (AMPREALIZE-276 / E2 Phase 3)
 *
 * Webview panel for workspace bootstrap onboarding:
 * - Detects workspace profile via MCP bootstrap.detect
 * - Displays profile with confidence and signal evidence
 * - Lets user confirm or override the detected profile
 * - Runs bootstrap.init to scaffold AGENTS.md and pack
 * - Shows summary of files created and next steps
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
exports.OnboardingPanel = void 0;
const vscode = __importStar(require("vscode"));
const PROFILE_LABELS = {
    'solo-dev': 'Solo Developer',
    'amprealize-platform': 'Amprealize Platform',
    'team-collab': 'Team Collaboration',
    'extension-dev': 'Extension Development',
    'api-backend': 'API Backend',
    'compliance-sensitive': 'Compliance-Sensitive'
};
const PROFILE_DESCRIPTIONS = {
    'solo-dev': 'Individual developer workspace with minimal process overhead.',
    'amprealize-platform': 'Amprealize core platform development (behaviors, MCP, services).',
    'team-collab': 'Multi-developer workspace with shared workflows and review processes.',
    'extension-dev': 'VS Code extension or IDE plugin development.',
    'api-backend': 'REST/GraphQL API backend with database and deployment concerns.',
    'compliance-sensitive': 'Regulated environment requiring audit trails and policy enforcement.'
};
const PROFILE_ICONS = {
    'solo-dev': '👤',
    'amprealize-platform': '🏗️',
    'team-collab': '👥',
    'extension-dev': '🧩',
    'api-backend': '⚙️',
    'compliance-sensitive': '🔒'
};
class OnboardingPanel {
    constructor(panel, extensionUri, mcpClient, workspacePath) {
        this._disposables = [];
        // State
        this._step = 'detect';
        this._detecting = false;
        this._initializing = false;
        this._detection = null;
        this._status = null;
        this._initResult = null;
        this._selectedProfile = null;
        this._error = null;
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._mcpClient = mcpClient;
        this._workspacePath = workspacePath;
        this.update();
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        this._panel.webview.onDidReceiveMessage(async (message) => {
            switch (message.type) {
                case 'detect':
                    await this.runDetection();
                    return;
                case 'selectProfile':
                    this._selectedProfile = message.profile;
                    this._step = 'confirm';
                    this.update();
                    return;
                case 'confirmProfile':
                    await this.initWorkspace(message.profile);
                    return;
                case 'changeProfile':
                    this._step = 'confirm';
                    this.update();
                    return;
                case 'dismiss':
                    this._panel.dispose();
                    return;
            }
        }, null, this._disposables);
        // Auto-detect on open
        this.runDetection();
    }
    static createOrShow(extensionUri, mcpClient) {
        const column = vscode.ViewColumn.One;
        if (OnboardingPanel.currentPanel) {
            OnboardingPanel.currentPanel._panel.reveal(column);
            return;
        }
        // Get workspace path
        const workspaceFolders = vscode.workspace.workspaceFolders;
        const workspacePath = workspaceFolders?.[0]?.uri.fsPath || '.';
        const panel = vscode.window.createWebviewPanel(OnboardingPanel.viewType, 'Amprealize Workspace Setup', column, {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.joinPath(extensionUri, 'out'),
                vscode.Uri.joinPath(extensionUri, 'src', 'styles')
            ]
        });
        OnboardingPanel.currentPanel = new OnboardingPanel(panel, extensionUri, mcpClient, workspacePath);
    }
    /**
     * Check if workspace needs onboarding and prompt user
     */
    static async checkAndPrompt(extensionUri, mcpClient) {
        try {
            const status = await mcpClient.bootstrapStatus();
            if (!status.is_bootstrapped) {
                const action = await vscode.window.showInformationMessage('This workspace has not been set up with Amprealize. Would you like to configure it now?', 'Set Up Workspace', 'Not Now');
                if (action === 'Set Up Workspace') {
                    OnboardingPanel.createOrShow(extensionUri, mcpClient);
                }
            }
        }
        catch {
            // MCP not connected or tool unavailable — skip prompt
        }
    }
    dispose() {
        OnboardingPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
    async runDetection() {
        this._detecting = true;
        this._error = null;
        this.update();
        try {
            const [detection, status] = await Promise.all([
                this._mcpClient.bootstrapDetect({ workspace_path: this._workspacePath }),
                this._mcpClient.bootstrapStatus({ workspace_path: this._workspacePath })
            ]);
            this._detection = detection;
            this._status = status;
            this._selectedProfile = detection.profile;
            if (status.is_bootstrapped) {
                this._step = 'complete';
                this._initResult = {
                    success: true,
                    profile: status.profile || detection.profile,
                    detection,
                    pack_id: status.pack_id || '',
                    pack_version: status.pack_version || '',
                    files_written: [],
                    notes: ['Workspace was already bootstrapped.']
                };
            }
            else {
                this._step = 'confirm';
            }
        }
        catch (err) {
            this._error = err instanceof Error ? err.message : String(err);
            this._step = 'detect';
        }
        finally {
            this._detecting = false;
            this.update();
        }
    }
    async initWorkspace(profile) {
        this._initializing = true;
        this._error = null;
        this.update();
        try {
            this._initResult = await this._mcpClient.bootstrapInit({
                workspace_path: this._workspacePath,
                profile
            });
            this._step = 'complete';
        }
        catch (err) {
            this._error = err instanceof Error ? err.message : String(err);
        }
        finally {
            this._initializing = false;
            this.update();
        }
    }
    update() {
        this._panel.webview.html = this.getHtmlForWebview(this._panel.webview);
    }
    getHtmlForWebview(webview) {
        const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'styles', 'OnboardingPanel.css'));
        const nonce = getNonce();
        return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
	<title>Amprealize Workspace Setup</title>
	<link href="${styleUri}" rel="stylesheet">
</head>
<body>
	<div class="onboarding-container">
		<header class="onboarding-header">
			<h1>Amprealize Workspace Setup</h1>
			<p class="subtitle">Configure your workspace with the right profile, knowledge pack, and AGENTS.md primer.</p>
		</header>

		${this.renderStepIndicator()}
		${this.renderContent()}
	</div>

	<script nonce="${nonce}">
		const vscode = acquireVsCodeApi();

		function detect() {
			vscode.postMessage({ type: 'detect' });
		}

		function selectProfile(profile) {
			vscode.postMessage({ type: 'selectProfile', profile });
		}

		function confirmProfile(profile) {
			vscode.postMessage({ type: 'confirmProfile', profile });
		}

		function changeProfile() {
			vscode.postMessage({ type: 'changeProfile' });
		}

		function dismiss() {
			vscode.postMessage({ type: 'dismiss' });
		}
	</script>
</body>
</html>`;
    }
    renderStepIndicator() {
        const steps = [
            { key: 'detect', label: 'Detect' },
            { key: 'confirm', label: 'Configure' },
            { key: 'complete', label: 'Done' }
        ];
        const currentIdx = steps.findIndex(s => s.key === this._step || (this._step === 'init' && s.key === 'confirm'));
        return `
		<div class="step-indicator">
			${steps.map((s, i) => `
				<div class="step ${i < currentIdx ? 'completed' : ''} ${i === currentIdx ? 'active' : ''}">
					<span class="step-number">${i < currentIdx ? '✓' : i + 1}</span>
					<span class="step-label">${s.label}</span>
				</div>
				${i < steps.length - 1 ? '<div class="step-connector"></div>' : ''}
			`).join('')}
		</div>`;
    }
    renderContent() {
        if (this._error) {
            return `
			<div class="error-banner">
				<span class="error-icon">⚠️</span>
				<span>${this.escapeHtml(this._error)}</span>
			</div>
			${this.renderStepContent()}`;
        }
        return this.renderStepContent();
    }
    renderStepContent() {
        switch (this._step) {
            case 'detect':
                return this.renderDetectStep();
            case 'confirm':
                return this.renderConfirmStep();
            case 'init':
                return this.renderInitStep();
            case 'complete':
                return this.renderCompleteStep();
        }
    }
    renderDetectStep() {
        if (this._detecting) {
            return `
			<div class="step-content detecting">
				<div class="spinner"></div>
				<p>Analyzing workspace signals...</p>
			</div>`;
        }
        return `
		<div class="step-content">
			<p>Click below to analyze your workspace and detect the best profile.</p>
			<button class="primary-btn" onclick="detect()">Detect Workspace Profile</button>
		</div>`;
    }
    renderConfirmStep() {
        if (!this._detection) {
            return this.renderDetectStep();
        }
        const profiles = [
            'solo-dev', 'amprealize-platform', 'team-collab',
            'extension-dev', 'api-backend', 'compliance-sensitive'
        ];
        return `
		<div class="step-content confirm-step">
			<div class="detection-summary">
				<h2>Detected Profile</h2>
				<div class="detected-profile">
					<span class="profile-icon">${PROFILE_ICONS[this._detection.profile]}</span>
					<div>
						<strong>${PROFILE_LABELS[this._detection.profile]}</strong>
						<span class="confidence-badge ${this._detection.confidence >= 0.7 ? 'high' : this._detection.confidence >= 0.4 ? 'medium' : 'low'}">
							${Math.round(this._detection.confidence * 100)}% confidence
						</span>
					</div>
				</div>
				${this._detection.is_ambiguous && this._detection.runner_up ? `
					<p class="ambiguity-note">
						Detection was ambiguous. Runner-up: <strong>${PROFILE_LABELS[this._detection.runner_up]}</strong>
					</p>
				` : ''}
			</div>

			<div class="signals-section">
				<h3>Detected Signals</h3>
				<div class="signal-list">
					${this._detection.signals
            .filter(s => s.detected)
            .map(s => `
							<div class="signal-item detected">
								<span class="signal-icon">✓</span>
								<span class="signal-name">${this.escapeHtml(s.signal_name)}</span>
								<span class="signal-evidence">${this.escapeHtml(s.evidence)}</span>
							</div>
						`).join('')}
				</div>
			</div>

			<div class="profile-selector">
				<h3>Select Profile</h3>
				<p>Confirm the detected profile or choose a different one.</p>
				<div class="profile-grid">
					${profiles.map(p => `
						<div class="profile-card ${this._selectedProfile === p ? 'selected' : ''} ${this._detection?.profile === p ? 'recommended' : ''}"
							 onclick="selectProfile('${p}')">
							<span class="profile-icon">${PROFILE_ICONS[p]}</span>
							<strong>${PROFILE_LABELS[p]}</strong>
							<p>${PROFILE_DESCRIPTIONS[p]}</p>
							${this._detection?.profile === p ? '<span class="recommended-badge">Recommended</span>' : ''}
						</div>
					`).join('')}
				</div>
			</div>

			<div class="actions-bar">
				<button class="primary-btn" onclick="confirmProfile('${this._selectedProfile || this._detection.profile}')"
					${this._initializing ? 'disabled' : ''}>
					${this._initializing ? 'Initializing...' : 'Initialize Workspace'}
				</button>
			</div>
		</div>`;
    }
    renderInitStep() {
        return `
		<div class="step-content detecting">
			<div class="spinner"></div>
			<p>Initializing workspace...</p>
		</div>`;
    }
    renderCompleteStep() {
        if (!this._initResult) {
            return '';
        }
        return `
		<div class="step-content complete-step">
			<div class="success-banner">
				<span class="success-icon">✅</span>
				<h2>Workspace Configured!</h2>
			</div>

			<div class="result-summary">
				<div class="result-item">
					<span class="result-label">Profile</span>
					<span class="result-value">
						${PROFILE_ICONS[this._initResult.profile]} ${PROFILE_LABELS[this._initResult.profile]}
					</span>
				</div>
				${this._initResult.pack_id ? `
				<div class="result-item">
					<span class="result-label">Knowledge Pack</span>
					<span class="result-value">${this.escapeHtml(this._initResult.pack_id)} v${this.escapeHtml(this._initResult.pack_version)}</span>
				</div>
				` : ''}
			</div>

			${this._initResult.files_written.length > 0 ? `
			<div class="files-section">
				<h3>Files Created</h3>
				<ul class="file-list">
					${this._initResult.files_written.map(f => `
						<li>${this.escapeHtml(f)}</li>
					`).join('')}
				</ul>
			</div>
			` : ''}

			${this._initResult.notes.length > 0 ? `
			<div class="notes-section">
				<h3>Notes</h3>
				<ul>
					${this._initResult.notes.map(n => `<li>${this.escapeHtml(n)}</li>`).join('')}
				</ul>
			</div>
			` : ''}

			<div class="next-steps">
				<h3>Next Steps</h3>
				<ol>
					<li>Review <code>AGENTS.md</code> in your workspace root</li>
					<li>Customize behavior triggers for your team's workflow</li>
					<li>Connect to MCP server for real-time behavior retrieval</li>
				</ol>
			</div>

			<div class="actions-bar">
				<button class="primary-btn" onclick="dismiss()">Done</button>
			</div>
		</div>`;
    }
    escapeHtml(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
}
exports.OnboardingPanel = OnboardingPanel;
OnboardingPanel.viewType = 'amprealize.onboarding';
function getNonce() {
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let text = '';
    for (let i = 0; i < 32; i++) {
        const index = Math.floor(Math.random() * possible.length);
        text += possible.charAt(index);
    }
    return text;
}
//# sourceMappingURL=OnboardingPanel.js.map
