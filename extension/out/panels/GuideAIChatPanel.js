"use strict";
/**
 * Amprealize Chat Panel
 *
 * A native VS Code webview panel for interacting with Amprealize MCP tools directly.
 * Bypasses GitHub Copilot Chat's MCP integration to avoid timeout/hanging issues.
 *
 * Features:
 * - Direct MCP tool invocation via McpClient
 * - Real-time streaming responses
 * - Tool group management (lazy loading)
 * - Progress indicators for long-running operations
 * - Chat history persistence
 *
 * Following behavior_prefer_mcp_tools: Use MCP directly for consistent schemas and telemetry.
 * Following behavior_integrate_vscode_extension: Standard webview panel patterns.
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
exports.AmprealizeChatPanel = void 0;
const crypto = __importStar(require("crypto"));
const vscode = __importStar(require("vscode"));
// ============================================
// Panel Implementation
// ============================================
class AmprealizeChatPanel {
    constructor(panel, extensionUri, mcpClient) {
        this._disposables = [];
        this._messages = [];
        this._toolGroups = [];
        this._activeTools = [];
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._mcpClient = mcpClient;
        // Set initial HTML
        this._update();
        // Handle panel disposal
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        // Handle messages from webview
        this._panel.webview.onDidReceiveMessage(async (message) => {
            switch (message.type) {
                case 'sendMessage':
                    await this._handleUserMessage(message.text);
                    break;
                case 'callTool':
                    await this._handleToolCall(message.toolName, message.args);
                    break;
                case 'activateGroup':
                    await this._activateToolGroup(message.groupId);
                    break;
                case 'deactivateGroup':
                    await this._deactivateToolGroup(message.groupId);
                    break;
                case 'refreshGroups':
                    await this._loadToolGroups();
                    break;
                case 'listTools':
                    await this._listActiveTools();
                    break;
                case 'clearHistory':
                    this._clearHistory();
                    break;
                case 'ready':
                    await this._onWebviewReady();
                    break;
            }
        }, null, this._disposables);
        // Listen for MCP connection state changes
        this._mcpClient.on('connectionStateChanged', (state) => {
            this._postMessage({
                type: 'connectionState',
                state: state.currentState
            });
        });
    }
    static createOrShow(extensionUri, mcpClient) {
        const column = vscode.ViewColumn.Beside;
        if (AmprealizeChatPanel.currentPanel) {
            AmprealizeChatPanel.currentPanel._panel.reveal(column);
            return;
        }
        const panel = vscode.window.createWebviewPanel(AmprealizeChatPanel.viewType, 'Amprealize Chat', column, {
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [
                vscode.Uri.joinPath(extensionUri, 'out'),
                vscode.Uri.joinPath(extensionUri, 'src', 'styles')
            ]
        });
        AmprealizeChatPanel.currentPanel = new AmprealizeChatPanel(panel, extensionUri, mcpClient);
    }
    static revive(panel, extensionUri, mcpClient) {
        AmprealizeChatPanel.currentPanel = new AmprealizeChatPanel(panel, extensionUri, mcpClient);
    }
    dispose() {
        AmprealizeChatPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
    // ============================================
    // Webview Lifecycle
    // ============================================
    async _onWebviewReady() {
        // Ensure MCP connection
        try {
            await this._mcpClient.connect();
            this._postMessage({
                type: 'connectionState',
                state: 'connected'
            });
        }
        catch (error) {
            this._postMessage({
                type: 'connectionState',
                state: 'disconnected',
                error: error instanceof Error ? error.message : String(error)
            });
        }
        // Load tool groups
        await this._loadToolGroups();
        // Load active tools
        await this._listActiveTools();
        // Send existing messages
        this._postMessage({
            type: 'history',
            messages: this._messages
        });
    }
    _postMessage(message) {
        this._panel.webview.postMessage(message);
    }
    _update() {
        this._panel.webview.html = this._getHtmlForWebview();
    }
    // ============================================
    // Message Handling
    // ============================================
    async _handleUserMessage(text) {
        const userMessage = {
            id: generateId(),
            role: 'user',
            content: text,
            timestamp: new Date()
        };
        this._messages.push(userMessage);
        this._postMessage({ type: 'message', message: userMessage });
        // Check if this is a tool command
        const toolMatch = text.match(/^@(\w+(?:\.\w+)?)\s*(.*)?$/);
        if (toolMatch) {
            const toolName = toolMatch[1];
            const argsText = toolMatch[2] || '';
            await this._handleToolCommand(toolName, argsText);
            return;
        }
        // Check for special commands
        if (text.startsWith('/')) {
            await this._handleSlashCommand(text);
            return;
        }
        // Default: Try to intelligently route the message
        await this._handleNaturalLanguage(text);
    }
    async _handleSlashCommand(text) {
        const [command, ...args] = text.slice(1).split(' ');
        switch (command.toLowerCase()) {
            case 'tools':
                await this._listActiveTools();
                this._addAssistantMessage(`Active tools: ${this._activeTools.map(t => t.name).join(', ')}`);
                break;
            case 'groups':
                await this._loadToolGroups();
                const groupList = this._toolGroups.map(g => `${g.is_active ? '✓' : '○'} ${g.id} (${g.available_tools} tools)`).join('\n');
                this._addAssistantMessage(`Tool groups:\n${groupList}`);
                break;
            case 'activate':
                if (args[0]) {
                    await this._activateToolGroup(args[0]);
                }
                else {
                    this._addAssistantMessage('Usage: /activate <group_id>');
                }
                break;
            case 'deactivate':
                if (args[0]) {
                    await this._deactivateToolGroup(args[0]);
                }
                else {
                    this._addAssistantMessage('Usage: /deactivate <group_id>');
                }
                break;
            case 'help':
                this._addAssistantMessage(`Available commands:
/tools - List active tools
/groups - List tool groups
/activate <group> - Activate a tool group
/deactivate <group> - Deactivate a tool group
/clear - Clear chat history
/help - Show this help

Tool invocation:
@toolname {"arg": "value"} - Call a tool with JSON args
@context.getContext - Get current context
@behaviors.getForTask {"task_description": "..."} - Get behaviors for a task`);
                break;
            case 'clear':
                this._clearHistory();
                break;
            default:
                this._addAssistantMessage(`Unknown command: /${command}. Type /help for available commands.`);
        }
    }
    async _handleToolCommand(toolName, argsText) {
        let args = {};
        if (argsText.trim()) {
            try {
                args = JSON.parse(argsText);
            }
            catch {
                // Try to parse as key=value pairs
                const pairs = argsText.split(/\s+/);
                for (const pair of pairs) {
                    const [key, value] = pair.split('=');
                    if (key && value) {
                        args[key] = value;
                    }
                }
            }
        }
        await this._handleToolCall(toolName, args);
    }
    async _handleNaturalLanguage(text) {
        // Inject BCI behaviors for the user's task
        try {
            this._addSystemMessage('Retrieving relevant behaviors...');
            const bciResult = await this._mcpClient.bciInject({
                task: text,
                surface: 'vscode'
            });
            const behaviors = bciResult.behaviors_injected || [];
            const overlays = bciResult.overlays_included || [];
            let response = '';
            if (bciResult.composed_prompt) {
                response += `**BCI Context for your task:**\n\n${bciResult.composed_prompt}\n\n`;
            }
            if (behaviors.length > 0) {
                response += `**Behaviors injected** (${behaviors.length}): ${behaviors.join(', ')}\n`;
            }
            if (overlays.length > 0) {
                response += `**Overlays included** (${overlays.length}): ${overlays.join(', ')}\n`;
            }
            if (bciResult.token_estimate) {
                response += `\n_Token estimate: ${bciResult.token_estimate}_\n`;
            }
            response += `\nYou can also:\n• Use @toolname {...args} to call a specific tool\n• Type /tools to see available tools`;
            this._addAssistantMessage(response);
        }
        catch {
            // Fallback to suggestion if BCI inject unavailable
            const suggestMessage = `I understand: "${text}"

To get relevant behaviors for this task, try:
@behaviors.getForTask {"task_description": "${text}"}

Or type /tools to see available tools.`;
            this._addAssistantMessage(suggestMessage);
        }
    }
    async _handleToolCall(toolName, args) {
        // Add a streaming indicator
        const streamingMessage = {
            id: generateId(),
            role: 'tool',
            content: 'Calling tool...',
            timestamp: new Date(),
            toolName,
            toolArgs: args,
            isStreaming: true
        };
        this._messages.push(streamingMessage);
        this._postMessage({ type: 'message', message: streamingMessage });
        try {
            const startTime = Date.now();
            const result = await this._mcpClient.callTool(toolName, args);
            const duration = Date.now() - startTime;
            // Update the message with the result
            streamingMessage.content = formatToolResult(result);
            streamingMessage.toolResult = result;
            streamingMessage.isStreaming = false;
            this._postMessage({
                type: 'updateMessage',
                id: streamingMessage.id,
                message: streamingMessage
            });
            // Add timing info
            this._addSystemMessage(`Tool ${toolName} completed in ${duration}ms`);
        }
        catch (error) {
            streamingMessage.content = `Error: ${error instanceof Error ? error.message : String(error)}`;
            streamingMessage.isError = true;
            streamingMessage.isStreaming = false;
            this._postMessage({
                type: 'updateMessage',
                id: streamingMessage.id,
                message: streamingMessage
            });
        }
    }
    // ============================================
    // Tool Group Management
    // ============================================
    async _loadToolGroups() {
        try {
            const result = await this._mcpClient.callTool('tools.listGroups', {});
            this._toolGroups = result.groups || [];
            this._postMessage({
                type: 'toolGroups',
                groups: this._toolGroups
            });
        }
        catch (error) {
            console.error('Failed to load tool groups:', error);
            // Fallback: Use static list if MCP fails
            this._postMessage({
                type: 'toolGroups',
                groups: [],
                error: error instanceof Error ? error.message : String(error)
            });
        }
    }
    async _activateToolGroup(groupId) {
        try {
            const result = await this._mcpClient.callTool('tools.activateGroup', {
                group_id: groupId
            });
            this._addSystemMessage(`Activated group "${groupId}": ${result.loaded_tools?.length || 0} tools loaded`);
            await this._loadToolGroups();
            await this._listActiveTools();
        }
        catch (error) {
            this._addAssistantMessage(`Failed to activate group: ${error instanceof Error ? error.message : String(error)}`, true);
        }
    }
    async _deactivateToolGroup(groupId) {
        try {
            await this._mcpClient.callTool('tools.deactivateGroup', {
                group_id: groupId
            });
            this._addSystemMessage(`Deactivated group "${groupId}"`);
            await this._loadToolGroups();
            await this._listActiveTools();
        }
        catch (error) {
            this._addAssistantMessage(`Failed to deactivate group: ${error instanceof Error ? error.message : String(error)}`, true);
        }
    }
    async _listActiveTools() {
        try {
            // Use tools/list to get active tools
            const result = await this._mcpClient.callTool('tools.activeGroups', {});
            // This returns groups not tools, we need a different approach
            // For now, just update the groups view
            this._postMessage({
                type: 'activeTools',
                tools: this._activeTools
            });
        }
        catch (error) {
            console.error('Failed to list active tools:', error);
        }
    }
    // ============================================
    // Helper Methods
    // ============================================
    _addAssistantMessage(content, isError = false) {
        const message = {
            id: generateId(),
            role: 'assistant',
            content,
            timestamp: new Date(),
            isError
        };
        this._messages.push(message);
        this._postMessage({ type: 'message', message });
    }
    _addSystemMessage(content) {
        const message = {
            id: generateId(),
            role: 'system',
            content,
            timestamp: new Date()
        };
        this._messages.push(message);
        this._postMessage({ type: 'message', message });
    }
    _clearHistory() {
        this._messages = [];
        this._postMessage({ type: 'clearHistory' });
        this._addSystemMessage('Chat history cleared');
    }
    // ============================================
    // HTML Generation
    // ============================================
    _getHtmlForWebview() {
        const webview = this._panel.webview;
        const nonce = generateNonce();
        const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'styles', 'AmprealizeChatPanel.css'));
        return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
	<title>Amprealize Chat</title>
	<style>
		:root {
			--vscode-font-family: var(--vscode-editor-font-family, 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif);
		}
		body {
			padding: 0;
			margin: 0;
			height: 100vh;
			display: flex;
			flex-direction: column;
			font-family: var(--vscode-font-family);
			background: var(--vscode-editor-background);
			color: var(--vscode-editor-foreground);
		}
		.header {
			padding: 8px 16px;
			border-bottom: 1px solid var(--vscode-panel-border);
			display: flex;
			align-items: center;
			gap: 8px;
		}
		.header h2 {
			margin: 0;
			font-size: 14px;
			font-weight: 600;
		}
		.connection-status {
			padding: 2px 8px;
			border-radius: 10px;
			font-size: 11px;
		}
		.connection-status.connected {
			background: var(--vscode-testing-iconPassed);
			color: white;
		}
		.connection-status.disconnected {
			background: var(--vscode-testing-iconFailed);
			color: white;
		}
		.connection-status.connecting {
			background: var(--vscode-testing-iconQueued);
			color: white;
		}
		.sidebar {
			width: 200px;
			border-right: 1px solid var(--vscode-panel-border);
			overflow-y: auto;
			padding: 8px;
		}
		.sidebar h3 {
			font-size: 12px;
			margin: 8px 0 4px;
			text-transform: uppercase;
			opacity: 0.7;
		}
		.group-item {
			padding: 4px 8px;
			cursor: pointer;
			border-radius: 4px;
			display: flex;
			align-items: center;
			gap: 4px;
			font-size: 12px;
		}
		.group-item:hover {
			background: var(--vscode-list-hoverBackground);
		}
		.group-item.active {
			background: var(--vscode-list-activeSelectionBackground);
		}
		.group-item .count {
			margin-left: auto;
			opacity: 0.6;
		}
		.main-content {
			flex: 1;
			display: flex;
			flex-direction: column;
			overflow: hidden;
		}
		.messages {
			flex: 1;
			overflow-y: auto;
			padding: 16px;
		}
		.message {
			margin-bottom: 16px;
			padding: 8px 12px;
			border-radius: 8px;
			max-width: 85%;
		}
		.message.user {
			background: var(--vscode-button-background);
			color: var(--vscode-button-foreground);
			margin-left: auto;
		}
		.message.assistant {
			background: var(--vscode-editor-inactiveSelectionBackground);
		}
		.message.system {
			background: transparent;
			color: var(--vscode-descriptionForeground);
			font-size: 12px;
			text-align: center;
			max-width: 100%;
		}
		.message.tool {
			background: var(--vscode-textCodeBlock-background);
			font-family: var(--vscode-editor-font-family);
			font-size: 12px;
		}
		.message.error {
			border-left: 3px solid var(--vscode-testing-iconFailed);
		}
		.message.streaming::after {
			content: '...';
			animation: dots 1.5s infinite;
		}
		@keyframes dots {
			0%, 20% { content: '.'; }
			40% { content: '..'; }
			60%, 100% { content: '...'; }
		}
		.tool-header {
			font-weight: 600;
			margin-bottom: 4px;
			color: var(--vscode-textLink-foreground);
		}
		.tool-result {
			white-space: pre-wrap;
			word-break: break-word;
		}
		.input-area {
			padding: 12px 16px;
			border-top: 1px solid var(--vscode-panel-border);
			display: flex;
			gap: 8px;
		}
		.input-area input {
			flex: 1;
			padding: 8px 12px;
			border: 1px solid var(--vscode-input-border);
			background: var(--vscode-input-background);
			color: var(--vscode-input-foreground);
			border-radius: 4px;
			font-size: 13px;
		}
		.input-area input:focus {
			outline: 1px solid var(--vscode-focusBorder);
		}
		.input-area button {
			padding: 8px 16px;
			background: var(--vscode-button-background);
			color: var(--vscode-button-foreground);
			border: none;
			border-radius: 4px;
			cursor: pointer;
		}
		.input-area button:hover {
			background: var(--vscode-button-hoverBackground);
		}
		.quick-actions {
			padding: 8px 16px;
			display: flex;
			gap: 8px;
			flex-wrap: wrap;
		}
		.quick-action {
			padding: 4px 8px;
			background: var(--vscode-badge-background);
			color: var(--vscode-badge-foreground);
			border-radius: 4px;
			font-size: 11px;
			cursor: pointer;
		}
		.quick-action:hover {
			opacity: 0.8;
		}
	</style>
</head>
<body>
	<div class="header">
		<h2>🤖 Amprealize Chat</h2>
		<span id="connection-status" class="connection-status connecting">Connecting...</span>
	</div>

	<div style="display: flex; flex: 1; overflow: hidden;">
		<div class="sidebar" id="sidebar">
			<h3>Tool Groups</h3>
			<div id="groups-list">Loading...</div>
		</div>

		<div class="main-content">
			<div class="messages" id="messages">
				<div class="message system">
					Welcome to Amprealize Chat! This panel connects directly to the MCP server.<br>
					Type /help for available commands or use @toolname to call tools directly.
				</div>
			</div>

			<div class="quick-actions">
				<span class="quick-action" data-action="@context.getContext">📍 Get Context</span>
				<span class="quick-action" data-action="@behaviors.getForTask">🧠 Get Behaviors</span>
				<span class="quick-action" data-action="@projects.list">📁 List Projects</span>
				<span class="quick-action" data-action="@runs.list">🏃 List Runs</span>
				<span class="quick-action" data-action="/groups">📦 Tool Groups</span>
			</div>

			<div class="input-area">
				<input type="text" id="input" placeholder="Type a message, /command, or @tool {...}" />
				<button id="send">Send</button>
			</div>
		</div>
	</div>

	<script nonce="${nonce}">
		const vscode = acquireVsCodeApi();

		// Elements
		const messagesEl = document.getElementById('messages');
		const inputEl = document.getElementById('input');
		const sendBtn = document.getElementById('send');
		const statusEl = document.getElementById('connection-status');
		const groupsListEl = document.getElementById('groups-list');

		// Send message
		function sendMessage() {
			const text = inputEl.value.trim();
			if (!text) return;
			vscode.postMessage({ type: 'sendMessage', text });
			inputEl.value = '';
		}

		sendBtn.addEventListener('click', sendMessage);
		inputEl.addEventListener('keypress', (e) => {
			if (e.key === 'Enter') sendMessage();
		});

		// Quick actions
		document.querySelectorAll('.quick-action').forEach(el => {
			el.addEventListener('click', () => {
				const action = el.dataset.action;
				if (action) {
					if (action.startsWith('/')) {
						vscode.postMessage({ type: 'sendMessage', text: action });
					} else {
						inputEl.value = action + ' ';
						inputEl.focus();
					}
				}
			});
		});

		// Handle messages from extension
		window.addEventListener('message', (event) => {
			const msg = event.data;

			switch (msg.type) {
				case 'connectionState':
					statusEl.textContent = msg.state;
					statusEl.className = 'connection-status ' + msg.state;
					break;

				case 'message':
					appendMessage(msg.message);
					break;

				case 'updateMessage':
					updateMessage(msg.id, msg.message);
					break;

				case 'history':
					messagesEl.innerHTML = '';
					(msg.messages || []).forEach(appendMessage);
					break;

				case 'clearHistory':
					messagesEl.innerHTML = '';
					break;

				case 'toolGroups':
					renderToolGroups(msg.groups || []);
					break;
			}
		});

		function appendMessage(msg) {
			const div = document.createElement('div');
			div.className = 'message ' + msg.role;
			div.id = 'msg-' + msg.id;

			if (msg.isError) div.classList.add('error');
			if (msg.isStreaming) div.classList.add('streaming');

			if (msg.role === 'tool' && msg.toolName) {
				div.innerHTML = '<div class="tool-header">@' + escapeHtml(msg.toolName) + '</div>' +
					'<div class="tool-result">' + escapeHtml(msg.content) + '</div>';
			} else {
				div.innerHTML = escapeHtml(msg.content).replace(/\\n/g, '<br>');
			}

			messagesEl.appendChild(div);
			messagesEl.scrollTop = messagesEl.scrollHeight;
		}

		function updateMessage(id, msg) {
			const div = document.getElementById('msg-' + id);
			if (div) {
				div.className = 'message ' + msg.role;
				if (msg.isError) div.classList.add('error');
				if (msg.isStreaming) div.classList.add('streaming');

				if (msg.role === 'tool' && msg.toolName) {
					div.innerHTML = '<div class="tool-header">@' + escapeHtml(msg.toolName) + '</div>' +
						'<div class="tool-result">' + escapeHtml(msg.content) + '</div>';
				} else {
					div.innerHTML = escapeHtml(msg.content).replace(/\\n/g, '<br>');
				}
			}
		}

		function renderToolGroups(groups) {
			if (groups.length === 0) {
				groupsListEl.innerHTML = '<div style="opacity: 0.6; font-size: 12px;">No groups loaded</div>';
				return;
			}

			groupsListEl.innerHTML = groups.map(g =>
				'<div class="group-item' + (g.is_active ? ' active' : '') + '" data-group="' + g.id + '">' +
				(g.is_active ? '✓' : '○') + ' ' + g.id +
				'<span class="count">' + g.available_tools + '</span>' +
				'</div>'
			).join('');

			groupsListEl.querySelectorAll('.group-item').forEach(el => {
				el.addEventListener('click', () => {
					const groupId = el.dataset.group;
					const isActive = el.classList.contains('active');
					vscode.postMessage({
						type: isActive ? 'deactivateGroup' : 'activateGroup',
						groupId
					});
				});
			});
		}

		function escapeHtml(str) {
			if (typeof str !== 'string') str = JSON.stringify(str, null, 2);
			return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
		}

		// Notify extension that webview is ready
		vscode.postMessage({ type: 'ready' });
	</script>
</body>
</html>`;
    }
}
exports.AmprealizeChatPanel = AmprealizeChatPanel;
AmprealizeChatPanel.viewType = 'amprealize.chat';
// ============================================
// Utility Functions
// ============================================
function generateId() {
    return crypto.randomBytes(8).toString('hex');
}
function generateNonce() {
    return crypto.randomBytes(16).toString('base64');
}
function formatToolResult(result) {
    if (typeof result === 'string') {
        return result;
    }
    try {
        return JSON.stringify(result, null, 2);
    }
    catch {
        return String(result);
    }
}
//# sourceMappingURL=AmprealizeChatPanel.js.map
