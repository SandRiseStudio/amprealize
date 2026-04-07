"use strict";
/**
 * Conversation Tree Data Provider
 *
 * Provides a flat list of conversations from the Amprealize backend.
 * Conversations are displayed as top-level items with no children.
 *
 * Following behavior_integrate_vscode_extension (Teacher)
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
exports.ConversationTreeDataProvider = exports.ConversationItem = void 0;
const vscode = __importStar(require("vscode"));
const https = __importStar(require("https"));
const http = __importStar(require("http"));
const url = __importStar(require("url"));
class ConversationItem extends vscode.TreeItem {
    constructor(conv) {
        super(conv.title || 'Untitled Conversation', vscode.TreeItemCollapsibleState.None);
        this.conv = conv;
        this.tooltip = conv.last_message_preview || '';
        this.description = new Date(conv.updated_at).toLocaleDateString();
        this.contextValue = 'conversation-item';
        this.iconPath = new vscode.ThemeIcon(conv.status === 'archived' ? 'archive' : 'comment-discussion');
        this.command = {
            command: 'amprealize.openConversation',
            title: 'Open Conversation',
            arguments: [conv.id, conv.title]
        };
    }
}
exports.ConversationItem = ConversationItem;
class ConversationTreeDataProvider {
    constructor(_config) {
        this._config = _config;
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    }
    refresh() {
        this._items = undefined;
        this._onDidChangeTreeData.fire();
    }
    getTreeItem(element) {
        return element;
    }
    async getChildren(element) {
        if (element) {
            return [];
        }
        if (this._items !== undefined) {
            return this._items;
        }
        const conversations = await this._fetchConversations();
        this._items = conversations.map(conv => new ConversationItem(conv));
        return this._items;
    }
    _fetchConversations() {
        return new Promise((resolve) => {
            const { baseUrl, authToken, projectId } = this._config;
            let requestUrl = `${baseUrl}/api/v1/conversations?limit=50`;
            if (projectId) {
                requestUrl += `&project_id=${encodeURIComponent(projectId)}`;
            }
            const parsed = new url.URL(requestUrl);
            const isHttps = parsed.protocol === 'https:';
            const transport = isHttps ? https : http;
            const options = {
                hostname: parsed.hostname,
                port: parsed.port || (isHttps ? 443 : 80),
                path: parsed.pathname + parsed.search,
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    ...(authToken ? { 'Authorization': `Bearer ${authToken}` } : {})
                }
            };
            const req = transport.request(options, (res) => {
                let data = '';
                res.on('data', (chunk) => {
                    data += chunk.toString();
                });
                res.on('end', () => {
                    try {
                        const parsed = JSON.parse(data);
                        if (Array.isArray(parsed)) {
                            resolve(parsed);
                        }
                        else if (parsed && Array.isArray(parsed.conversations)) {
                            resolve(parsed.conversations);
                        }
                        else {
                            resolve([]);
                        }
                    }
                    catch (err) {
                        console.error('ConversationTreeDataProvider: failed to parse response', err);
                        resolve([]);
                    }
                });
            });
            req.on('error', (err) => {
                console.error('ConversationTreeDataProvider: request failed', err);
                resolve([]);
            });
            req.end();
        });
    }
    dispose() {
        this._onDidChangeTreeData.dispose();
    }
}
exports.ConversationTreeDataProvider = ConversationTreeDataProvider;
//# sourceMappingURL=ConversationTreeDataProvider.js.map
