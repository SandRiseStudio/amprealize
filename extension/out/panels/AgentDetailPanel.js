"use strict";
/**
 * Agent Detail Panel
 *
 * Webview panel for displaying comprehensive agent details:
 * - Agent metadata (name, description, role, status)
 * - Model configuration (model, temperature, max_tokens)
 * - Capabilities and behaviors list
 * - MCP servers configuration
 * - Version history
 * - Publish/deprecate actions
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
exports.AgentDetailPanel = void 0;
const vscode = __importStar(require("vscode"));
const actorAvatar_1 = require("../utils/actorAvatar");
class AgentDetailPanel {
    constructor(panel, extensionUri, client) {
        this._disposables = [];
        this._agent = null;
        this._versionHistory = [];
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._client = client;
        // Set the webview's initial html content
        this._update();
        // Listen for when the panel is disposed
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        // Handle messages from the webview
        this._panel.webview.onDidReceiveMessage(async (message) => {
            switch (message.type) {
                case 'refreshAgent':
                    await this._refreshAgent();
                    return;
                case 'publishAgent':
                    await this._publishAgent();
                    return;
                case 'deprecateAgent':
                    await this._deprecateAgent();
                    return;
                case 'copyAgentId':
                    await this._copyAgentId();
                    return;
                case 'loadVersionHistory':
                    await this._loadVersionHistory();
                    return;
                case 'viewVersion':
                    await this._viewVersion(message.version);
                    return;
                case 'editAgent':
                    await this._editAgent();
                    return;
            }
        }, null, this._disposables);
    }
    static async createOrShow(extensionUri, client, agent) {
        const column = vscode.ViewColumn.One;
        if (AgentDetailPanel.currentPanel) {
            AgentDetailPanel.currentPanel._panel.reveal(column);
            AgentDetailPanel.currentPanel._agent = agent;
            AgentDetailPanel.currentPanel._versionHistory = [];
            await AgentDetailPanel.currentPanel._update();
            return;
        }
        const panel = vscode.window.createWebviewPanel(AgentDetailPanel.viewType, `Agent: ${agent.name}`, column || vscode.ViewColumn.One, {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.joinPath(extensionUri, 'out'),
                vscode.Uri.joinPath(extensionUri, 'src', 'webviews'),
                vscode.Uri.joinPath(extensionUri, 'src', 'styles')
            ]
        });
        AgentDetailPanel.currentPanel = new AgentDetailPanel(panel, extensionUri, client);
        AgentDetailPanel.currentPanel._agent = agent;
    }
    static revive(panel, extensionUri, client) {
        AgentDetailPanel.currentPanel = new AgentDetailPanel(panel, extensionUri, client);
    }
    _update() {
        const webview = this._panel.webview;
        if (!this._agent) {
            this._panel.webview.html = this._getHtmlForWebview(webview, null);
            return;
        }
        this._panel.title = `Agent: ${this._agent.name}`;
        this._panel.webview.html = this._getHtmlForWebview(webview, this._agent);
    }
    async _refreshAgent() {
        if (!this._agent)
            return;
        try {
            const result = await this._client.getAgent(this._agent.agent_id);
            if (result) {
                this._agent = result;
                this._update();
                this._panel.webview.postMessage({ type: 'agentUpdated' });
                vscode.window.showInformationMessage(`Agent "${result.name}" refreshed`);
            }
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to refresh agent: ${error}`);
        }
    }
    async _publishAgent() {
        if (!this._agent)
            return;
        if (this._agent.status !== 'DRAFT') {
            vscode.window.showWarningMessage('Only DRAFT agents can be published');
            return;
        }
        const confirm = await vscode.window.showWarningMessage(`Are you sure you want to publish agent "${this._agent.name}"? This will make it available for use.`, { modal: true }, 'Publish');
        if (confirm !== 'Publish')
            return;
        try {
            await this._client.publishAgent(this._agent.agent_id);
            await this._refreshAgent();
            vscode.window.showInformationMessage(`Agent "${this._agent.name}" published successfully`);
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to publish agent: ${error}`);
        }
    }
    async _deprecateAgent() {
        if (!this._agent)
            return;
        if (this._agent.status === 'DEPRECATED') {
            vscode.window.showWarningMessage('Agent is already deprecated');
            return;
        }
        const reason = await vscode.window.showInputBox({
            prompt: 'Enter deprecation reason (optional)',
            placeHolder: 'e.g., Replaced by newer agent version'
        });
        const confirm = await vscode.window.showWarningMessage(`Are you sure you want to deprecate agent "${this._agent.name}"?`, { modal: true }, 'Deprecate');
        if (confirm !== 'Deprecate')
            return;
        try {
            await this._client.deprecateAgent(this._agent.agent_id, reason ?? '');
            await this._refreshAgent();
            vscode.window.showInformationMessage(`Agent "${this._agent.name}" deprecated`);
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to deprecate agent: ${error}`);
        }
    }
    async _copyAgentId() {
        if (!this._agent)
            return;
        try {
            await vscode.env.clipboard.writeText(this._agent.agent_id);
            vscode.window.showInformationMessage('Agent ID copied to clipboard');
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to copy agent ID: ${error}`);
        }
    }
    async _loadVersionHistory() {
        if (!this._agent)
            return;
        try {
            // Get the agent with all versions
            const result = await this._client.getAgent(this._agent.agent_id);
            if (result && result.versions) {
                // Map versions to Agent-like objects for display
                this._versionHistory = result.versions.map(v => ({
                    ...this._agent,
                    version: v.version,
                    instruction: v.instruction ?? '',
                    tags: v.tags ?? [],
                    capabilities: v.capabilities ?? [],
                    behaviors: v.behaviors ?? [],
                    role_alignment: v.role_alignment ?? 'STUDENT',
                    status: v.status,
                    created_at: v.created_at
                }));
            }
            this._update();
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to load version history: ${error}`);
        }
    }
    async _viewVersion(version) {
        if (!this._agent)
            return;
        try {
            const result = await this._client.getAgent(this._agent.agent_id, version);
            if (result) {
                this._agent = result;
                this._update();
            }
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to load version ${version}: ${error}`);
        }
    }
    async _editAgent() {
        if (!this._agent)
            return;
        if (this._agent.status !== 'DRAFT') {
            vscode.window.showWarningMessage('Only DRAFT agents can be edited directly. Editing a published agent will create a new version.');
        }
        // Open a quick pick for field editing
        const fields = [
            { label: 'Name', value: 'name' },
            { label: 'Description', value: 'description' },
            { label: 'System Prompt', value: 'system_prompt' },
            { label: 'Model', value: 'model' },
            { label: 'Temperature', value: 'temperature' },
            { label: 'Max Tokens', value: 'max_tokens' },
            { label: 'Tags', value: 'tags' },
            { label: 'Capabilities', value: 'capabilities' },
            { label: 'Behaviors', value: 'behaviors' }
        ];
        const selected = await vscode.window.showQuickPick(fields, {
            placeHolder: 'Select field to edit'
        });
        if (!selected)
            return;
        const currentValue = this._agent[selected.value];
        let newValue;
        if (selected.value === 'system_prompt') {
            // Open multi-line editor for system prompt
            const doc = await vscode.workspace.openTextDocument({
                content: currentValue || '',
                language: 'markdown'
            });
            await vscode.window.showTextDocument(doc);
            vscode.window.showInformationMessage('Edit the system prompt and use "amprealize.updateAgent" command to save');
            return;
        }
        else if (['tags', 'capabilities', 'behaviors'].includes(selected.value)) {
            newValue = await vscode.window.showInputBox({
                prompt: `Enter ${selected.label} (comma-separated)`,
                value: Array.isArray(currentValue) ? currentValue.join(', ') : '',
                placeHolder: 'e.g., item1, item2, item3'
            });
        }
        else {
            newValue = await vscode.window.showInputBox({
                prompt: `Enter new ${selected.label}`,
                value: String(currentValue || ''),
                placeHolder: `Enter ${selected.label}`
            });
        }
        if (newValue === undefined)
            return;
        try {
            const updates = {};
            if (['tags', 'capabilities', 'behaviors'].includes(selected.value)) {
                updates[selected.value] = newValue.split(',').map(s => s.trim()).filter(s => s);
            }
            else if (selected.value === 'temperature') {
                updates[selected.value] = parseFloat(newValue);
            }
            else if (selected.value === 'max_tokens') {
                updates[selected.value] = parseInt(newValue, 10);
            }
            else {
                updates[selected.value] = newValue;
            }
            await this._client.updateAgent(this._agent.agent_id, updates);
            await this._refreshAgent();
            vscode.window.showInformationMessage(`Agent ${selected.label} updated successfully`);
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to update agent: ${error}`);
        }
    }
    _getHtmlForWebview(webview, agent) {
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'webviews', 'agentDetail.js'));
        const styleResetUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'out', 'viewExplorer.css'));
        const styleMainUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'styles', 'AgentDetailPanel.css'));
        const nonce = getNonce();
        if (!agent) {
            return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Agent Details</title>
	<link href="${styleResetUri}" rel="stylesheet">
	<link href="${styleMainUri}" rel="stylesheet">
</head>
<body>
	<div class="container">
		<div class="no-agent">
			<h2>No Agent Selected</h2>
			<p>Select an agent from the Agent Registry to view its details.</p>
		</div>
	</div>
</body>
</html>`;
        }
        const statusClass = agent.status.toLowerCase();
        const roleIcon = this._getRoleIcon(agent.role_alignment);
        const canPublish = agent.status === 'DRAFT';
        const canDeprecate = agent.status !== 'DEPRECATED';
        const canEdit = agent.status === 'DRAFT';
        const avatarHtml = (0, actorAvatar_1.buildActorAvatarHtml)((0, actorAvatar_1.createActorViewModel)({
            id: agent.agent_id,
            kind: 'agent',
            displayName: agent.name,
            subtitle: agent.role_alignment,
            presenceState: agent.status === 'DEPRECATED' ? 'offline' : agent.status === 'DRAFT' ? 'paused' : 'available',
        }), 52);
        const versionHistoryHtml = this._versionHistory.length > 0
            ? this._versionHistory.map(v => `
				<div class="version-item ${v.version === agent.version ? 'current' : ''}"
					 onclick="vscode.postMessage({type: 'viewVersion', version: '${v.version}'})">
					<span class="version-number">v${v.version}</span>
					<span class="version-date">${v.created_at ? new Date(v.created_at).toLocaleDateString() : 'Unknown'}</span>
					<span class="version-status status-${v.status.toLowerCase()}">${v.status}</span>
				</div>
			`).join('')
            : '<p class="load-versions" onclick="vscode.postMessage({type: \'loadVersionHistory\'})">Click to load version history</p>';
        return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
	<title>Agent: ${agent.name}</title>
	<link href="${styleResetUri}" rel="stylesheet">
	<link href="${styleMainUri}" rel="stylesheet">
</head>
<body>
	<div class="container">
		<header class="agent-header">
			<div class="agent-title">
				${avatarHtml}
				<div>
					<div class="agent-meta">
						<span class="role-icon">${roleIcon}</span>
						<h1>${this._escapeHtml(agent.name)}</h1>
					</div>
				<div class="agent-meta">
					<span class="agent-id" id="agentId">${agent.agent_id}</span>
					<button class="copy-btn" onclick="vscode.postMessage({type: 'copyAgentId'})">Copy ID</button>
				</div>
				</div>
			</div>
			<div class="agent-status">
				<span class="status-badge status-${statusClass}">${agent.status}</span>
				<span class="visibility-badge visibility-${agent.visibility.toLowerCase()}">${agent.visibility}</span>
				<span class="version-badge">v${agent.version}</span>
			</div>
		</header>

		<div class="agent-actions">
			<button class="action-btn" onclick="vscode.postMessage({type: 'refreshAgent'})">
				🔄 Refresh
			</button>
			${canEdit ? `<button class="action-btn" onclick="vscode.postMessage({type: 'editAgent'})">
				✏️ Edit
			</button>` : ''}
			${canPublish ? `<button class="action-btn action-primary" onclick="vscode.postMessage({type: 'publishAgent'})">
				🚀 Publish
			</button>` : ''}
			${canDeprecate ? `<button class="action-btn action-danger" onclick="vscode.postMessage({type: 'deprecateAgent'})">
				⚠️ Deprecate
			</button>` : ''}
		</div>

		<div class="agent-content">
			<section class="info-section">
				<h2>Description</h2>
				<p class="description">${this._escapeHtml(agent.description || 'No description provided')}</p>
			</section>

			<section class="info-section">
				<h2>Role Alignment</h2>
				<div class="role-info">
					<span class="role-badge role-${agent.role_alignment.toLowerCase()}">${roleIcon} ${agent.role_alignment}</span>
					<p class="role-description">${this._getRoleDescription(agent.role_alignment)}</p>
				</div>
			</section>

			<section class="info-section">
				<h2>Model Configuration</h2>
				<div class="config-grid">
					<div class="config-item">
						<label>Model</label>
						<span>${this._escapeHtml(agent.model || 'Default')}</span>
					</div>
					<div class="config-item">
						<label>Temperature</label>
						<span>${agent.temperature ?? 'Default'}</span>
					</div>
					<div class="config-item">
						<label>Max Tokens</label>
						<span>${agent.max_tokens ?? 'Default'}</span>
					</div>
				</div>
			</section>

			${agent.system_prompt ? `
			<section class="info-section">
				<h2>System Prompt</h2>
				<pre class="system-prompt">${this._escapeHtml(agent.system_prompt)}</pre>
			</section>
			` : ''}

			<section class="info-section">
				<h2>Capabilities</h2>
				<div class="tag-list">
					${agent.capabilities && agent.capabilities.length > 0
            ? agent.capabilities.map(cap => `<span class="tag capability-tag">${this._escapeHtml(cap)}</span>`).join('')
            : '<span class="no-items">No capabilities defined</span>'}
				</div>
			</section>

			<section class="info-section">
				<h2>Behaviors</h2>
				<div class="tag-list">
					${agent.behaviors && agent.behaviors.length > 0
            ? agent.behaviors.map(beh => `<span class="tag behavior-tag">${this._escapeHtml(beh)}</span>`).join('')
            : '<span class="no-items">No behaviors assigned</span>'}
				</div>
			</section>

			<section class="info-section">
				<h2>Tags</h2>
				<div class="tag-list">
					${agent.tags && agent.tags.length > 0
            ? agent.tags.map(tag => `<span class="tag">${this._escapeHtml(tag)}</span>`).join('')
            : '<span class="no-items">No tags</span>'}
				</div>
			</section>

			${agent.mcp_servers && agent.mcp_servers.length > 0 ? `
			<section class="info-section">
				<h2>MCP Servers</h2>
				<div class="mcp-list">
					${agent.mcp_servers.map(server => `<div class="mcp-server">${this._escapeHtml(server)}</div>`).join('')}
				</div>
			</section>
			` : ''}

			<section class="info-section">
				<h2>Version History</h2>
				<div class="version-history">
					${versionHistoryHtml}
				</div>
			</section>

			<section class="info-section metadata-section">
				<h2>Metadata</h2>
				<div class="metadata-grid">
					<div class="metadata-item">
						<label>Owner</label>
						<span>${this._escapeHtml(agent.owner_id ?? 'Unknown')}</span>
					</div>
					<div class="metadata-item">
						<label>Created</label>
						<span>${agent.created_at ? new Date(agent.created_at).toLocaleString() : 'Unknown'}</span>
					</div>
					<div class="metadata-item">
						<label>Updated</label>
						<span>${agent.updated_at ? new Date(agent.updated_at).toLocaleString() : 'Unknown'}</span>
					</div>
				</div>
			</section>
		</div>
	</div>

	<script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
    }
    _getRoleIcon(role) {
        switch (role) {
            case 'STRATEGIST': return '🧠';
            case 'TEACHER': return '🎓';
            case 'STUDENT': return '📖';
            case 'CUSTOM': return '🔧';
            default: return '🤖';
        }
    }
    _getRoleDescription(role) {
        switch (role) {
            case 'STRATEGIST':
                return 'Handles novel problems, pattern extraction, post-mortems, and behavior curation. Uses three-step process: Solve → Reflect → Emit.';
            case 'TEACHER':
                return 'Creates examples, documentation, reviews code, and validates behavior proposals. Focuses on quality and knowledge transfer.';
            case 'STUDENT':
                return 'Follows established patterns and behaviors efficiently. Executes routine tasks and reports pattern observations.';
            case 'CUSTOM':
                return 'Custom role with specialized capabilities defined by configuration.';
            default:
                return 'Unknown role alignment';
        }
    }
    _escapeHtml(text) {
        const escapeMap = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, char => escapeMap[char]);
    }
    dispose() {
        AgentDetailPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
}
exports.AgentDetailPanel = AgentDetailPanel;
AgentDetailPanel.viewType = 'amprealize.agentDetail';
function getNonce() {
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let text = '';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
//# sourceMappingURL=AgentDetailPanel.js.map
