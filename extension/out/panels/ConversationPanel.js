"use strict";
/**
 * ConversationPanel
 *
 * A VS Code webview panel for displaying and composing conversation messages.
 * Connects to a backend conversation via WebSocket and renders a real-time
 * chat UI within the editor.
 *
 * Following behavior_integrate_vscode_extension: Singleton pattern, CSP nonces,
 * webview security, disposable cleanup.
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
exports.ConversationPanel = void 0;
const crypto = __importStar(require("crypto"));
const vscode = __importStar(require("vscode"));
// ============================================
// Panel Implementation
// ============================================
class ConversationPanel {
    constructor(panel, extensionUri, conversationId, title, config) {
        this._disposables = [];
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._conversationId = conversationId;
        this._title = title;
        this._config = config;
        // Set initial HTML
        this._update();
        // Handle panel disposal
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        // Handle messages from webview
        this._panel.webview.onDidReceiveMessage((message) => {
            switch (message.type) {
                case 'ready':
                    this._sendInit();
                    break;
                case 'sendMessage':
                    // Extension host can intercept outbound messages here if needed
                    // (e.g. audit logging). WS send is also done in the webview JS directly.
                    break;
                case 'sendReaction':
                    // Forward reaction to backend if needed
                    break;
                case 'markRead':
                    // Forward markRead to backend if needed
                    break;
            }
        }, null, this._disposables);
    }
    static createOrShow(extensionUri, conversationId, conversationTitle, config) {
        const column = vscode.ViewColumn.Beside;
        if (ConversationPanel.currentPanel) {
            ConversationPanel.currentPanel._panel.reveal(column);
            ConversationPanel.currentPanel.openConversation(conversationId, conversationTitle);
            return;
        }
        const panel = vscode.window.createWebviewPanel(ConversationPanel.viewType, conversationTitle, column, {
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [
                vscode.Uri.joinPath(extensionUri, 'out'),
                vscode.Uri.joinPath(extensionUri, 'src', 'styles')
            ]
        });
        ConversationPanel.currentPanel = new ConversationPanel(panel, extensionUri, conversationId, conversationTitle, config);
    }
    /**
     * Switch to a different conversation without opening a new panel.
     */
    openConversation(conversationId, title) {
        this._conversationId = conversationId;
        this._title = title;
        this._panel.title = title;
        this._update();
        // After HTML reload the webview will post 'ready', which triggers _sendInit.
        // No need to call _sendInit() here directly.
    }
    dispose() {
        ConversationPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const disposable = this._disposables.pop();
            if (disposable) {
                disposable.dispose();
            }
        }
    }
    // ============================================
    // Private Helpers
    // ============================================
    _buildWsUrl() {
        const base = this._config.baseUrl.replace(/\/$/, '');
        const wsBase = base.replace(/^http/, 'ws');
        const params = new URLSearchParams({ user_id: this._config.userId });
        if (this._config.authToken) {
            params.set('token', this._config.authToken);
        }
        return `${wsBase}/api/v1/conversations/${this._conversationId}/ws?${params.toString()}`;
    }
    _sendInit() {
        this._panel.webview.postMessage({
            type: 'init',
            conversationId: this._conversationId,
            userId: this._config.userId,
            wsUrl: this._buildWsUrl(),
            authToken: this._config.authToken
        });
    }
    _update() {
        this._panel.webview.html = this._getHtmlForWebview();
    }
    // ============================================
    // HTML Generation
    // ============================================
    _getHtmlForWebview() {
        const nonce = crypto.randomBytes(16).toString('base64');
        return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'; connect-src ws: wss:;">
	<title>${escapeHtmlAttr(this._title)}</title>
	<style>
		*, *::before, *::after { box-sizing: border-box; }
		body {
			margin: 0;
			padding: 0;
			height: 100vh;
			display: flex;
			flex-direction: column;
			font-family: var(--vscode-font-family, 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif);
			font-size: var(--vscode-font-size, 13px);
			background: var(--vscode-editor-background);
			color: var(--vscode-editor-foreground);
		}

		/* ---- Header ---- */
		.header {
			display: flex;
			align-items: center;
			gap: 8px;
			padding: 8px 14px;
			border-bottom: 1px solid var(--vscode-panel-border);
			flex-shrink: 0;
		}
		.header-title {
			flex: 1;
			font-weight: 600;
			font-size: 13px;
			white-space: nowrap;
			overflow: hidden;
			text-overflow: ellipsis;
		}
		.status-dot {
			font-size: 16px;
			line-height: 1;
			color: #f44336; /* red by default (disconnected) */
			transition: color 0.2s;
			flex-shrink: 0;
		}
		.status-dot.connected {
			color: #4caf50;
		}

		/* ---- Messages ---- */
		.messages {
			flex: 1;
			overflow-y: auto;
			padding: 12px 14px;
			display: flex;
			flex-direction: column;
			gap: 10px;
		}
		.message {
			display: flex;
			gap: 8px;
			align-items: flex-start;
		}
		.message-icon {
			flex-shrink: 0;
			font-size: 16px;
			line-height: 1.4;
			width: 22px;
			text-align: center;
		}
		.message-body {
			flex: 1;
			min-width: 0;
		}
		.message-content {
			white-space: pre-wrap;
			word-break: break-word;
			line-height: 1.5;
		}
		.message-time {
			font-size: 11px;
			color: var(--vscode-descriptionForeground);
			margin-top: 2px;
		}

		/* ---- Composer ---- */
		.composer {
			display: flex;
			gap: 8px;
			align-items: flex-end;
			padding: 10px 14px;
			border-top: 1px solid var(--vscode-panel-border);
			flex-shrink: 0;
		}
		.composer textarea {
			flex: 1;
			resize: none;
			min-height: 38px;
			max-height: 120px;
			padding: 8px 10px;
			border: 1px solid var(--vscode-input-border);
			background: var(--vscode-input-background);
			color: var(--vscode-input-foreground);
			border-radius: 4px;
			font-family: inherit;
			font-size: inherit;
			line-height: 1.4;
			overflow-y: auto;
		}
		.composer textarea:focus {
			outline: 1px solid var(--vscode-focusBorder);
		}
		.composer button {
			height: 38px;
			padding: 0 14px;
			background: var(--vscode-button-background);
			color: var(--vscode-button-foreground);
			border: none;
			border-radius: 4px;
			cursor: pointer;
			font-size: 12px;
			font-weight: 500;
			flex-shrink: 0;
		}
		.composer button:hover {
			background: var(--vscode-button-hoverBackground);
		}
		.composer button:disabled {
			opacity: 0.5;
			cursor: not-allowed;
		}
	</style>
</head>
<body>
	<div class="header">
		<span class="header-title" id="header-title">${escapeHtml(this._title)}</span>
		<span class="status-dot" id="status-dot" title="Disconnected">&#9679;</span>
	</div>

	<div class="messages" id="messages"></div>

	<div class="composer">
		<textarea id="composer-input" placeholder="Type a message… (Cmd+Enter or Ctrl+Enter to send)" rows="1"></textarea>
		<button id="send-btn" disabled>Send</button>
	</div>

	<script nonce="${nonce}">
		(function () {
			'use strict';

			const vscode = acquireVsCodeApi();

			const messagesEl = document.getElementById('messages');
			const composerInput = document.getElementById('composer-input');
			const sendBtn = document.getElementById('send-btn');
			const statusDot = document.getElementById('status-dot');
			const headerTitle = document.getElementById('header-title');

			let ws = null;
			let currentConversationId = null;

			// ---- Utility ----

			function escapeHtml(str) {
				if (typeof str !== 'string') { str = String(str); }
				return str
					.replace(/&/g, '&amp;')
					.replace(/</g, '&lt;')
					.replace(/>/g, '&gt;')
					.replace(/"/g, '&quot;');
			}

			function formatTime(isoStr) {
				if (!isoStr) { return ''; }
				try {
					const d = new Date(isoStr);
					return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
				} catch (_) {
					return isoStr;
				}
			}

			function actorIcon(actorType) {
				if (actorType === 'user') { return '👤'; }
				if (actorType === 'agent') { return '🤖'; }
				return '⚙️';
			}

			// ---- Status ----

			function setConnected(connected) {
				if (connected) {
					statusDot.classList.add('connected');
					statusDot.title = 'Connected';
					sendBtn.disabled = false;
				} else {
					statusDot.classList.remove('connected');
					statusDot.title = 'Disconnected';
					sendBtn.disabled = true;
				}
			}

			// ---- Messages ----

			function renderMessage(msg) {
				const div = document.createElement('div');
				div.className = 'message';
				div.dataset.msgId = msg.id;
				div.innerHTML =
					'<span class="message-icon">' + actorIcon(msg.actor_type) + '</span>' +
					'<div class="message-body">' +
						'<div class="message-content">' + escapeHtml(msg.content) + '</div>' +
						'<div class="message-time">' + escapeHtml(formatTime(msg.created_at)) + '</div>' +
					'</div>';
				return div;
			}

			function appendMessage(msg) {
				const existing = messagesEl.querySelector('[data-msg-id="' + msg.id + '"]');
				if (existing) {
					// Update in-place
					const contentEl = existing.querySelector('.message-content');
					if (contentEl) { contentEl.textContent = msg.content; }
					return;
				}
				messagesEl.appendChild(renderMessage(msg));
				messagesEl.scrollTop = messagesEl.scrollHeight;
			}

			function renderHistory(messages) {
				messagesEl.innerHTML = '';
				if (Array.isArray(messages)) {
					messages.forEach(appendMessage);
				}
				messagesEl.scrollTop = messagesEl.scrollHeight;
			}

			function removeMessage(messageId) {
				const el = messagesEl.querySelector('[data-msg-id="' + messageId + '"]');
				if (el) { el.remove(); }
			}

			// ---- WebSocket ----

			function connectWs(wsUrl) {
				if (ws) {
					try { ws.close(); } catch (_) {}
					ws = null;
				}

				setConnected(false);

				ws = new WebSocket(wsUrl);

				ws.onopen = function () {
					setConnected(true);
				};

				ws.onclose = function () {
					setConnected(false);
					ws = null;
				};

				ws.onerror = function () {
					setConnected(false);
				};

				ws.onmessage = function (event) {
					let data;
					try {
						data = JSON.parse(event.data);
					} catch (_) {
						return;
					}

					switch (data.type) {
						case 'conversation.ready':
							if (data.payload && Array.isArray(data.payload.history)) {
								renderHistory(data.payload.history);
							}
							break;
						case 'message.new':
							if (data.payload) {
								appendMessage(data.payload);
							}
							break;
						case 'message.updated':
							if (data.payload) {
								appendMessage(data.payload);
							}
							break;
						case 'message.deleted':
							if (data.payload && data.payload.id) {
								removeMessage(data.payload.id);
							}
							break;
					}
				};
			}

			// ---- Send ----

			function sendMessage() {
				const content = composerInput.value.trim();
				if (!content) { return; }

				// Notify extension host
				vscode.postMessage({ type: 'sendMessage', content: content });

				// Send over WebSocket
				if (ws && ws.readyState === WebSocket.OPEN) {
					ws.send(JSON.stringify({ type: 'message.send', content: content }));
				}

				composerInput.value = '';
				composerInput.style.height = 'auto';
			}

			// ---- Composer Events ----

			composerInput.addEventListener('keydown', function (e) {
				if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
					e.preventDefault();
					sendMessage();
				}
			});

			composerInput.addEventListener('input', function () {
				// Auto-grow textarea
				this.style.height = 'auto';
				this.style.height = Math.min(this.scrollHeight, 120) + 'px';
			});

			sendBtn.addEventListener('click', function () {
				sendMessage();
			});

			// ---- Extension Host Messages ----

			window.addEventListener('message', function (event) {
				const msg = event.data;
				if (!msg || !msg.type) { return; }

				switch (msg.type) {
					case 'init':
						currentConversationId = msg.conversationId;
						if (headerTitle) {
							// Title update is already handled by panel.title on the host side,
							// but we keep the DOM in sync too.
						}
						connectWs(msg.wsUrl);
						break;

					case 'conversation.history':
						if (Array.isArray(msg.messages)) {
							renderHistory(msg.messages);
						}
						break;
				}
			});

			// ---- Boot ----

			// Signal to extension host that webview is ready to receive init
			vscode.postMessage({ type: 'ready' });
		}());
	</script>
</body>
</html>`;
    }
}
exports.ConversationPanel = ConversationPanel;
ConversationPanel.viewType = 'amprealize.conversation';
// ============================================
// Utility Functions
// ============================================
/** Escape HTML for text node content. */
function escapeHtml(text) {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}
/** Escape HTML for attribute values (double-quoted). */
function escapeHtmlAttr(text) {
    return escapeHtml(text).replace(/"/g, '&quot;');
}
//# sourceMappingURL=ConversationPanel.js.map
