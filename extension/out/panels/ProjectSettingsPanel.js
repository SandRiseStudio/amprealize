"use strict";
/**
 * Project Settings Panel
 *
 * Webview panel for configuring project settings:
 * - Local project path (with workspace auto-detection)
 * - GitHub repository URL
 * - GitHub branch selection
 * - Execution mode (local, github_pr, local_and_pr)
 * - GitHub Credential linking (per-user)
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
exports.ProjectSettingsPanel = void 0;
const vscode = __importStar(require("vscode"));
class ProjectSettingsPanel {
    constructor(panel, extensionUri, client, projectId, mcpClient) {
        this._disposables = [];
        this._settings = null;
        this._bootstrapStatus = null;
        this._validatedGithub = null;
        this._credentials = [];
        // GitHub credential linking
        this._githubLink = null;
        this._githubResolution = null;
        this._myGitHubCredentials = [];
        this._myGitHubAppInstallations = [];
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._client = client;
        this._mcpClient = mcpClient || null;
        this._projectId = projectId;
        this._update();
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        this._panel.webview.onDidReceiveMessage(async (message) => {
            switch (message.type) {
                case 'detectWorkspace':
                    await this._detectWorkspace();
                    return;
                case 'validateGithub':
                    await this._validateGithub(message.url);
                    return;
                case 'saveSettings':
                    await this._saveSettings(message.settings);
                    return;
                case 'refresh':
                    await this._loadSettings();
                    return;
                case 'addCredential':
                    await this._addCredential(message.provider, message.apiKey, message.name);
                    return;
                case 'deleteCredential':
                    await this._deleteCredential(message.credentialId);
                    return;
                case 'reEnableCredential':
                    await this._reEnableCredential(message.credentialId, message.apiKey);
                    return;
                // GitHub credential linking
                case 'linkGitHubPAT':
                    await this._linkGitHubPAT(message.token, message.name);
                    return;
                case 'linkGitHubApp':
                    await this._linkGitHubApp(message.installationId);
                    return;
                case 'unlinkGitHub':
                    await this._unlinkGitHub(message.linkType);
                    return;
                case 'openOnboarding':
                    vscode.commands.executeCommand('amprealize.openOnboarding');
                    return;
            }
        }, null, this._disposables);
        // Load settings on init
        void this._loadSettings();
    }
    static createOrShow(extensionUri, client, projectId, projectName, mcpClient) {
        const column = vscode.ViewColumn.One;
        if (ProjectSettingsPanel.currentPanel) {
            ProjectSettingsPanel.currentPanel._panel.reveal(column);
            ProjectSettingsPanel.currentPanel._projectId = projectId;
            void ProjectSettingsPanel.currentPanel._loadSettings();
            return;
        }
        const panel = vscode.window.createWebviewPanel(ProjectSettingsPanel.viewType, `Settings: ${projectName || 'Project'}`, column || vscode.ViewColumn.One, {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.joinPath(extensionUri, 'out'),
                vscode.Uri.joinPath(extensionUri, 'src', 'styles')
            ]
        });
        ProjectSettingsPanel.currentPanel = new ProjectSettingsPanel(panel, extensionUri, client, projectId, mcpClient);
    }
    static revive(panel, extensionUri, client, projectId, mcpClient) {
        ProjectSettingsPanel.currentPanel = new ProjectSettingsPanel(panel, extensionUri, client, projectId, mcpClient);
    }
    async _loadSettings() {
        try {
            this._settings = await this._client.getProjectSettings(this._projectId);
            // Load LLM credentials
            try {
                this._credentials = await this._client.getProjectCredentials(this._projectId);
            }
            catch (credError) {
                console.warn('Failed to load credentials:', credError);
                this._credentials = [];
            }
            // Load GitHub link data
            try {
                this._githubLink = await this._client.getMyGitHubLink(this._projectId);
                this._githubResolution = await this._client.getGitHubResolution(this._projectId);
                this._myGitHubCredentials = await this._client.listMyGitHubCredentials();
                this._myGitHubAppInstallations = await this._client.listMyGitHubAppInstallations();
            }
            catch (ghError) {
                console.warn('Failed to load GitHub link data:', ghError);
                this._githubLink = null;
                this._githubResolution = null;
                this._myGitHubCredentials = [];
                this._myGitHubAppInstallations = [];
            }
            // Load bootstrap status (local workspace)
            await this._loadBootstrapStatus();
            this._update();
        }
        catch (error) {
            console.error('Failed to load project settings:', error);
            vscode.window.showErrorMessage(`Failed to load settings: ${error}`);
        }
    }
    async _loadBootstrapStatus() {
        if (!this._mcpClient) {
            return;
        }
        try {
            this._bootstrapStatus = await this._mcpClient.bootstrapStatus();
        }
        catch {
            this._bootstrapStatus = null;
        }
    }
    async _detectWorkspace() {
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            vscode.window.showWarningMessage('No workspace folder is currently open.');
            return;
        }
        if (workspaceFolders.length === 1) {
            // Single workspace - use it directly
            const localPath = workspaceFolders[0].uri.fsPath;
            this._panel.webview.postMessage({
                type: 'workspaceDetected',
                path: localPath
            });
        }
        else {
            // Multiple workspaces - let user pick
            const items = workspaceFolders.map(folder => ({
                label: folder.name,
                description: folder.uri.fsPath,
                path: folder.uri.fsPath
            }));
            const selected = await vscode.window.showQuickPick(items, {
                placeHolder: 'Select a workspace folder',
                title: 'Choose Project Location'
            });
            if (selected) {
                this._panel.webview.postMessage({
                    type: 'workspaceDetected',
                    path: selected.path
                });
            }
        }
    }
    async _validateGithub(url) {
        try {
            this._panel.webview.postMessage({
                type: 'validationStarted'
            });
            const result = await this._client.validateGithubRepo(this._projectId, url);
            this._validatedGithub = result;
            this._panel.webview.postMessage({
                type: 'validationResult',
                result
            });
            if (result.valid) {
                vscode.window.showInformationMessage(`Repository validated: ${result.repo_name}`);
            }
            else {
                vscode.window.showWarningMessage(result.error || 'Failed to validate repository');
            }
        }
        catch (error) {
            console.error('GitHub validation failed:', error);
            this._panel.webview.postMessage({
                type: 'validationResult',
                result: { valid: false, error: String(error) }
            });
            vscode.window.showErrorMessage(`Validation failed: ${error}`);
        }
    }
    async _saveSettings(settings) {
        try {
            await this._client.updateProjectSettings(this._projectId, settings);
            vscode.window.showInformationMessage('Project settings saved successfully');
            await this._loadSettings();
        }
        catch (error) {
            console.error('Failed to save settings:', error);
            vscode.window.showErrorMessage(`Failed to save settings: ${error}`);
        }
    }
    async _addCredential(provider, apiKey, name) {
        try {
            await this._client.addProjectCredential(this._projectId, provider, apiKey, name);
            vscode.window.showInformationMessage(`${provider} credential added successfully`);
            await this._loadSettings();
        }
        catch (error) {
            console.error('Failed to add credential:', error);
            vscode.window.showErrorMessage(`Failed to add credential: ${error}`);
        }
    }
    async _deleteCredential(credentialId) {
        const confirm = await vscode.window.showWarningMessage('Are you sure you want to delete this credential?', { modal: true }, 'Delete');
        if (confirm !== 'Delete') {
            return;
        }
        try {
            await this._client.deleteProjectCredential(this._projectId, credentialId);
            vscode.window.showInformationMessage('Credential deleted successfully');
            await this._loadSettings();
        }
        catch (error) {
            console.error('Failed to delete credential:', error);
            vscode.window.showErrorMessage(`Failed to delete credential: ${error}`);
        }
    }
    async _reEnableCredential(credentialId, apiKey) {
        try {
            await this._client.reEnableProjectCredential(this._projectId, credentialId, apiKey);
            vscode.window.showInformationMessage('Credential re-enabled successfully');
            await this._loadSettings();
        }
        catch (error) {
            console.error('Failed to re-enable credential:', error);
            vscode.window.showErrorMessage(`Failed to re-enable credential: ${error}`);
        }
    }
    async _linkGitHubPAT(token, name) {
        try {
            await this._client.linkMyPATToProject(this._projectId, { token, name });
            vscode.window.showInformationMessage('GitHub PAT linked successfully');
            await this._loadSettings();
        }
        catch (error) {
            console.error('Failed to link GitHub PAT:', error);
            vscode.window.showErrorMessage(`Failed to link GitHub PAT: ${error}`);
        }
    }
    async _linkGitHubApp(installationId) {
        try {
            await this._client.linkMyAppToProject(this._projectId, { installation_id: installationId });
            vscode.window.showInformationMessage('GitHub App linked successfully');
            await this._loadSettings();
        }
        catch (error) {
            console.error('Failed to link GitHub App:', error);
            vscode.window.showErrorMessage(`Failed to link GitHub App: ${error}`);
        }
    }
    async _unlinkGitHub(linkType) {
        const confirm = await vscode.window.showWarningMessage('Are you sure you want to unlink this GitHub credential?', { modal: true }, 'Unlink');
        if (confirm !== 'Unlink') {
            return;
        }
        try {
            await this._client.unlinkMyGitHubFromProject(this._projectId, linkType);
            vscode.window.showInformationMessage('GitHub credential unlinked successfully');
            await this._loadSettings();
        }
        catch (error) {
            console.error('Failed to unlink GitHub credential:', error);
            vscode.window.showErrorMessage(`Failed to unlink GitHub credential: ${error}`);
        }
    }
    _update() {
        this._panel.webview.html = this._getHtmlForWebview();
    }
    _renderBootstrapSection() {
        const status = this._bootstrapStatus;
        if (!this._mcpClient) {
            return '';
        }
        const profileLabels = {
            'solo-dev': 'Solo Developer',
            'amprealize-platform': 'Amprealize Platform',
            'team-collab': 'Team Collaboration',
            'extension-dev': 'Extension Development',
            'api-backend': 'API Backend',
            'compliance-sensitive': 'Compliance-Sensitive'
        };
        if (!status || !status.is_bootstrapped) {
            return `
			<section class="settings-section">
				<h2>Workspace Profile</h2>
				<p class="section-description">
					Detect your workspace type and install a tailored knowledge pack with behaviors and AGENTS.md.
				</p>
				<div class="info-card warning">
					<span class="info-icon">⚠️</span>
					<span>This workspace has not been bootstrapped yet.</span>
				</div>
				<button class="primary-btn" id="setupWorkspaceBtn">Set Up Workspace</button>
			</section>`;
        }
        const profileLabel = profileLabels[status.profile] || status.profile || 'Unknown';
        return `
		<section class="settings-section">
			<h2>Workspace Profile</h2>
			<p class="section-description">
				Your workspace profile determines which knowledge pack and behaviors are active.
			</p>
			<div class="result-summary">
				<div class="form-row">
					<span class="field-label">Profile</span>
					<span>${escapeHtml(profileLabel)}</span>
				</div>
				${status.pack_id ? `
				<div class="form-row">
					<span class="field-label">Knowledge Pack</span>
					<span>${escapeHtml(status.pack_id)}${status.pack_version ? ` v${escapeHtml(status.pack_version)}` : ''}</span>
				</div>` : ''}
			</div>
			<button class="secondary-btn" id="setupWorkspaceBtn" style="margin-top: 8px;">Reconfigure</button>
		</section>`;
    }
    _renderGitHubResolutionStatus() {
        const resolution = this._githubResolution;
        if (!resolution) {
            return '';
        }
        if (!resolution.has_credential) {
            return `
				<div class="info-card warning">
					<span class="info-icon">⚠️</span>
					<span>No GitHub credential configured. Agents won't be able to create PRs or access private repositories.</span>
				</div>
			`;
        }
        const sourceLabels = {
            'user_app': 'Your linked GitHub App',
            'user_pat': 'Your linked Personal Access Token',
            'project_app': 'Shared project GitHub App',
            'project_pat': 'Shared project PAT',
            'org_app': 'Organization GitHub App',
            'org_pat': 'Organization PAT',
            'platform': 'Platform default',
        };
        const sourceLabel = sourceLabels[resolution.source || ''] || resolution.source || 'Unknown';
        const scopeStatus = resolution.has_required_scopes
            ? '<span class="status-badge success">✓ Required scopes</span>'
            : `<span class="status-badge warning">⚠️ ${escapeHtml(resolution.scope_warning || 'Missing scopes')}</span>`;
        return `
			<div class="info-card success">
				<span class="info-icon">✓</span>
				<div class="resolution-info">
					<span><strong>Active credential:</strong> ${escapeHtml(sourceLabel)}</span>
					${resolution.github_username ? `<span>GitHub user: @${escapeHtml(resolution.github_username)}</span>` : ''}
					${scopeStatus}
				</div>
			</div>
		`;
    }
    _renderGitHubLinkSection() {
        const link = this._githubLink;
        // If user has a link, show it
        if (link) {
            const linkTypeLabel = link.link_type === 'app' ? 'GitHub App' : 'Personal Access Token';
            return `
				<div class="github-link-active">
					<div class="link-info">
						<span class="link-type">${escapeHtml(linkTypeLabel)}</span>
						${link.credential_name ? `<span class="link-name">${escapeHtml(link.credential_name)}</span>` : ''}
						${link.github_identity ? `<span class="link-identity">@${escapeHtml(link.github_identity)}</span>` : ''}
						${link.last_used_at ? `<span class="link-usage">Last used: ${new Date(link.last_used_at).toLocaleDateString()}</span>` : ''}
					</div>
					<button class="danger-btn small" id="unlinkGitHubBtn" data-type="${link.link_type}">
						Unlink
					</button>
				</div>
			`;
        }
        // Show options to link
        const appOptions = this._myGitHubAppInstallations
            .filter(i => i.is_active)
            .map(i => `<option value="${i.installation_id}">${escapeHtml(i.account_login)} (${escapeHtml(i.account_type)})</option>`)
            .join('');
        return `
			<div class="github-link-form">
				<div class="link-option">
					<h4>Option 1: Link a GitHub App Installation</h4>
					<p class="option-description">Recommended. GitHub Apps have fine-grained permissions and don't expire.</p>
					${appOptions
            ? `
							<div class="form-row">
								<label for="ghAppSelect" class="field-label">Select Installation</label>
								<select id="ghAppSelect" class="select-input">
									<option value="">Choose an installation...</option>
									${appOptions}
								</select>
							</div>
							<button class="primary-btn" id="linkGitHubAppBtn">Link App</button>
						`
            : `<p class="empty-state">No GitHub App installations available. <a href="https://github.com/apps/amprealize" target="_blank">Install the GitHub App</a></p>`}
				</div>

				<div class="divider">or</div>

				<div class="link-option">
					<h4>Option 2: Link a Personal Access Token</h4>
					<p class="option-description">Use a classic or fine-grained PAT. Requires 'repo' scope for private repos.</p>
					<div class="form-row">
						<label for="ghPATInput" class="field-label">Personal Access Token</label>
						<input
							type="password"
							id="ghPATInput"
							class="text-input"
							placeholder="ghp_... or github_pat_..."
						/>
					</div>
					<div class="form-row">
						<label for="ghPATName" class="field-label">Name (optional)</label>
						<input
							type="text"
							id="ghPATName"
							class="text-input"
							placeholder="e.g., My GitHub PAT"
						/>
					</div>
					<button class="primary-btn" id="linkGitHubPATBtn">Link PAT</button>
				</div>
			</div>
		`;
    }
    _getHtmlForWebview() {
        const webview = this._panel.webview;
        const styleResetUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'out', 'viewExplorer.css'));
        const styleMainUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'styles', 'ProjectSettingsPanel.css'));
        const nonce = getNonce();
        const settings = this._settings;
        const localPath = settings?.local_path || '';
        const githubRepo = settings?.github_repo || '';
        const githubBranch = settings?.github_branch || '';
        const executionMode = settings?.execution_mode || 'github_pr';
        // Generate branch options if we have validated github
        let branchOptions = '';
        if (this._validatedGithub?.branches) {
            branchOptions = this._validatedGithub.branches
                .map(b => `<option value="${b}" ${b === githubBranch ? 'selected' : ''}>${b}</option>`)
                .join('');
        }
        else if (githubBranch) {
            branchOptions = `<option value="${githubBranch}" selected>${githubBranch}</option>`;
        }
        // Generate credentials list HTML
        const credentialsHtml = this._credentials.map(cred => {
            const statusClass = cred.is_valid ? 'valid' : 'invalid';
            const statusText = cred.is_valid ? 'Active' : `Disabled (${cred.failure_count} failures)`;
            const lastUsed = cred.last_used_at ? new Date(cred.last_used_at).toLocaleDateString() : 'Never';
            return `
				<div class="credential-item ${statusClass}" data-id="${cred.credential_id}">
					<div class="credential-info">
						<span class="credential-provider">${escapeHtml(cred.provider)}</span>
						${cred.name ? `<span class="credential-name">${escapeHtml(cred.name)}</span>` : ''}
						<span class="credential-prefix">${escapeHtml(cred.key_prefix)}...</span>
					</div>
					<div class="credential-meta">
						<span class="credential-status ${statusClass}">${statusText}</span>
						<span class="credential-usage">Last used: ${lastUsed}</span>
					</div>
					<div class="credential-actions">
						${!cred.is_valid ? `<button class="secondary-btn small re-enable-btn" data-id="${cred.credential_id}">Re-enable</button>` : ''}
						<button class="danger-btn small delete-btn" data-id="${cred.credential_id}">Delete</button>
					</div>
				</div>
			`;
        }).join('');
        return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
	<link href="${styleResetUri}" rel="stylesheet">
	<link href="${styleMainUri}" rel="stylesheet">
	<title>Project Settings</title>
</head>
<body>
	<div class="container">
		<header class="panel-header">
			<h1>Project Settings</h1>
			<p class="subtitle">${settings?.name || 'Configure your project'}</p>
		</header>

		<section class="settings-section">
			<h2>Local Path</h2>
			<p class="section-description">
				Path to your project folder on this machine. Used for IDE integrations.
			</p>
			<div class="input-group">
				<input
					type="text"
					id="localPath"
					class="text-input"
					value="${escapeHtml(localPath)}"
					placeholder="/path/to/your/project"
				/>
				<button class="secondary-btn" id="detectBtn">
					Detect Workspace
				</button>
			</div>
		</section>

		<section class="settings-section">
			<h2>GitHub Repository</h2>
			<p class="section-description">
				Link this project to a GitHub repository for enhanced collaboration features.
			</p>
			<div class="input-group">
				<input
					type="text"
					id="githubRepo"
					class="text-input"
					value="${escapeHtml(githubRepo)}"
					placeholder="https://github.com/owner/repo"
				/>
				<button class="secondary-btn" id="validateBtn">
					Validate
				</button>
			</div>
			<div id="validationStatus" class="validation-status"></div>

			<div class="branch-section ${branchOptions ? '' : 'hidden'}" id="branchSection">
				<label for="githubBranch" class="field-label">Default Branch</label>
				<select id="githubBranch" class="select-input">
					<option value="">Select a branch</option>
					${branchOptions}
				</select>
			</div>
		</section>

		<section class="settings-section">
			<h2>Execution Mode</h2>
			<p class="section-description">
				Choose where file changes are written during agent execution.
			</p>
			<div class="form-row">
				<label for="executionMode" class="field-label">Mode</label>
				<select id="executionMode" class="select-input">
					<option value="github_pr" ${executionMode === 'github_pr' ? 'selected' : ''}>GitHub PR Only</option>
					<option value="local" ${executionMode === 'local' ? 'selected' : ''}>Local Files Only</option>
					<option value="local_and_pr" ${executionMode === 'local_and_pr' ? 'selected' : ''}>Local + GitHub PR</option>
				</select>
			</div>
			<div class="mode-info" id="modeInfo">
				<div class="info-card ${executionMode === 'github_pr' ? '' : 'hidden'}" id="prModeInfo">
					<span class="info-icon">ℹ️</span>
					<span>Changes are committed to a branch and opened as a PR. Works from any interface (web, CLI, VS Code).</span>
				</div>
				<div class="info-card warning ${executionMode === 'local' ? '' : 'hidden'}" id="localModeInfo">
					<span class="info-icon">⚠️</span>
					<span>Changes are written directly to local files. <strong>Requires VS Code extension or CLI</strong> — not available from web.</span>
				</div>
				<div class="info-card warning ${executionMode === 'local_and_pr' ? '' : 'hidden'}" id="bothModeInfo">
					<span class="info-icon">⚠️</span>
					<span>Changes are written locally AND opened as a PR. <strong>Requires VS Code extension or CLI</strong> — not available from web.</span>
				</div>
			</div>
		</section>

		<section class="settings-section">
			<h2>LLM Credentials (BYOK)</h2>
			<p class="section-description">
				Add your own API keys for LLM providers. Project-level keys take priority over organization defaults.
			</p>

			<div class="credentials-list" id="credentialsList">
				${credentialsHtml || '<p class="empty-state">No credentials configured</p>'}
			</div>

			<div class="add-credential-form" id="addCredentialForm">
				<h3>Add New Credential</h3>
				<div class="form-row">
					<label for="credProvider" class="field-label">Provider</label>
					<select id="credProvider" class="select-input">
						<option value="anthropic">Anthropic (Claude)</option>
						<option value="openai">OpenAI (GPT)</option>
						<option value="openrouter">OpenRouter</option>
					</select>
				</div>
				<div class="form-row">
					<label for="credApiKey" class="field-label">API Key</label>
					<input
						type="password"
						id="credApiKey"
						class="text-input"
						placeholder="sk-..."
					/>
				</div>
				<div class="form-row">
					<label for="credName" class="field-label">Name (optional)</label>
					<input
						type="text"
						id="credName"
						class="text-input"
						placeholder="e.g., Production Key"
					/>
				</div>
				<button class="primary-btn" id="addCredBtn">Add Credential</button>
			</div>
		</section>

		<section class="settings-section">
			<h2>GitHub Credentials</h2>
			<p class="section-description">
				Link your personal GitHub credentials for agent access to repositories. When agents run work items,
				they'll use your linked credentials to interact with GitHub on your behalf.
			</p>

			${this._renderGitHubResolutionStatus()}

			${this._renderGitHubLinkSection()}
		</section>

		${this._renderBootstrapSection()}

		<div class="actions">
			<button class="primary-btn" id="saveBtn">Save Settings</button>
		</div>

		<!-- Re-enable Modal -->
		<div class="modal hidden" id="reEnableModal">
			<div class="modal-content">
				<h3>Re-enable Credential</h3>
				<p>This credential was disabled after authentication failures. Enter a new API key to re-enable it.</p>
				<input
					type="password"
					id="newApiKey"
					class="text-input"
					placeholder="New API key"
				/>
				<div class="modal-actions">
					<button class="secondary-btn" id="cancelReEnable">Cancel</button>
					<button class="primary-btn" id="confirmReEnable">Re-enable</button>
				</div>
			</div>
		</div>
	</div>

	<script nonce="${nonce}">
		(function() {
			const vscode = acquireVsCodeApi();

			const localPathInput = document.getElementById('localPath');
			const githubRepoInput = document.getElementById('githubRepo');
			const githubBranchSelect = document.getElementById('githubBranch');
			const detectBtn = document.getElementById('detectBtn');
			const validateBtn = document.getElementById('validateBtn');
			const saveBtn = document.getElementById('saveBtn');
			const validationStatus = document.getElementById('validationStatus');
			const branchSection = document.getElementById('branchSection');

			// Execution mode elements
			const executionModeSelect = document.getElementById('executionMode');
			const prModeInfo = document.getElementById('prModeInfo');
			const localModeInfo = document.getElementById('localModeInfo');
			const bothModeInfo = document.getElementById('bothModeInfo');

			// Credential elements
			const addCredBtn = document.getElementById('addCredBtn');
			const credProvider = document.getElementById('credProvider');
			const credApiKey = document.getElementById('credApiKey');
			const credName = document.getElementById('credName');
			const credentialsList = document.getElementById('credentialsList');
			const reEnableModal = document.getElementById('reEnableModal');
			const newApiKeyInput = document.getElementById('newApiKey');
			const cancelReEnable = document.getElementById('cancelReEnable');
			const confirmReEnable = document.getElementById('confirmReEnable');

			let reEnableCredentialId = null;

			detectBtn.addEventListener('click', () => {
				vscode.postMessage({ type: 'detectWorkspace' });
			});

			validateBtn.addEventListener('click', () => {
				const url = githubRepoInput.value.trim();
				if (url) {
					vscode.postMessage({ type: 'validateGithub', url });
				}
			});

			// Execution mode change handler - show appropriate info card
			executionModeSelect.addEventListener('change', () => {
				const mode = executionModeSelect.value;
				prModeInfo.classList.toggle('hidden', mode !== 'github_pr');
				localModeInfo.classList.toggle('hidden', mode !== 'local');
				bothModeInfo.classList.toggle('hidden', mode !== 'local_and_pr');
			});

			saveBtn.addEventListener('click', () => {
				vscode.postMessage({
					type: 'saveSettings',
					settings: {
						local_path: localPathInput.value.trim() || null,
						github_repo: githubRepoInput.value.trim() || null,
						github_branch: githubBranchSelect.value || null,
						execution_mode: executionModeSelect.value || 'github_pr'
					}
				});
			});

			// Credential handlers
			addCredBtn.addEventListener('click', () => {
				const provider = credProvider.value;
				const apiKey = credApiKey.value.trim();
				const name = credName.value.trim();

				if (!apiKey) {
					return;
				}

				vscode.postMessage({
					type: 'addCredential',
					provider: provider,
					apiKey: apiKey,
					name: name || undefined
				});

				// Clear form
				credApiKey.value = '';
				credName.value = '';
			});

			// Delegate click handlers for credential actions
			credentialsList.addEventListener('click', (e) => {
				const target = e.target;
				if (target.classList.contains('delete-btn')) {
					const credId = target.dataset.id;
					vscode.postMessage({ type: 'deleteCredential', credentialId: credId });
				} else if (target.classList.contains('re-enable-btn')) {
					reEnableCredentialId = target.dataset.id;
					reEnableModal.classList.remove('hidden');
					newApiKeyInput.value = '';
					newApiKeyInput.focus();
				}
			});

			cancelReEnable.addEventListener('click', () => {
				reEnableModal.classList.add('hidden');
				reEnableCredentialId = null;
			});

			confirmReEnable.addEventListener('click', () => {
				const newKey = newApiKeyInput.value.trim();
				if (!newKey || !reEnableCredentialId) {
					return;
				}
				vscode.postMessage({
					type: 'reEnableCredential',
					credentialId: reEnableCredentialId,
					apiKey: newKey
				});
				reEnableModal.classList.add('hidden');
				reEnableCredentialId = null;
			});

			// GitHub credential link handlers
			const linkGitHubAppBtn = document.getElementById('linkGitHubAppBtn');
			const linkGitHubPATBtn = document.getElementById('linkGitHubPATBtn');
			const unlinkGitHubBtn = document.getElementById('unlinkGitHubBtn');
			const ghAppSelect = document.getElementById('ghAppSelect');
			const ghPATInput = document.getElementById('ghPATInput');
			const ghPATName = document.getElementById('ghPATName');

			if (linkGitHubAppBtn && ghAppSelect) {
				linkGitHubAppBtn.addEventListener('click', () => {
					const installationId = parseInt(ghAppSelect.value, 10);
					if (installationId) {
						vscode.postMessage({
							type: 'linkGitHubApp',
							installationId: installationId
						});
					}
				});
			}

			if (linkGitHubPATBtn && ghPATInput) {
				linkGitHubPATBtn.addEventListener('click', () => {
					const token = ghPATInput.value.trim();
					if (token) {
						vscode.postMessage({
							type: 'linkGitHubPAT',
							token: token,
							name: ghPATName ? ghPATName.value.trim() : undefined
						});
						ghPATInput.value = '';
						if (ghPATName) ghPATName.value = '';
					}
				});
			}

			if (unlinkGitHubBtn) {
				unlinkGitHubBtn.addEventListener('click', () => {
					const linkType = unlinkGitHubBtn.dataset.type;
					vscode.postMessage({
						type: 'unlinkGitHub',
						linkType: linkType
					});
				});
			}

			const setupWorkspaceBtn = document.getElementById('setupWorkspaceBtn');
			if (setupWorkspaceBtn) {
				setupWorkspaceBtn.addEventListener('click', () => {
					vscode.postMessage({ type: 'openOnboarding' });
				});
			}

			window.addEventListener('message', event => {
				const message = event.data;
				switch (message.type) {
					case 'workspaceDetected':
						localPathInput.value = message.path;
						break;
					case 'validationStarted':
						validationStatus.textContent = 'Validating...';
						validationStatus.className = 'validation-status loading';
						break;
					case 'validationResult':
						if (message.result.valid) {
							validationStatus.textContent = '✓ Repository validated: ' + message.result.repo_name;
							validationStatus.className = 'validation-status success';

							if (message.result.branches && message.result.branches.length > 0) {
								branchSection.classList.remove('hidden');
								githubBranchSelect.innerHTML = '<option value="">Select a branch</option>' +
									message.result.branches.map(b =>
										'<option value="' + b + '"' +
										(b === message.result.default_branch ? ' selected' : '') +
										'>' + b + '</option>'
									).join('');
							}
						} else {
							validationStatus.textContent = '✗ ' + (message.result.error || 'Validation failed');
							validationStatus.className = 'validation-status error';
							branchSection.classList.add('hidden');
						}
						break;
				}
			});
		})();
	</script>
</body>
</html>`;
    }
    dispose() {
        ProjectSettingsPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
}
exports.ProjectSettingsPanel = ProjectSettingsPanel;
ProjectSettingsPanel.viewType = 'amprealize.projectSettings';
function getNonce() {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
//# sourceMappingURL=ProjectSettingsPanel.js.map
