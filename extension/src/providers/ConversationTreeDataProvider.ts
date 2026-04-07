/**
 * Conversation Tree Data Provider
 *
 * Provides a flat list of conversations from the Amprealize backend.
 * Conversations are displayed as top-level items with no children.
 *
 * Following behavior_integrate_vscode_extension (Teacher)
 */

import * as vscode from 'vscode';
import * as https from 'https';
import * as http from 'http';
import * as url from 'url';

export interface ConversationRecord {
    id: string;
    title: string;
    status: 'active' | 'archived';
    updated_at: string;
    last_message_preview?: string;
}

export class ConversationItem extends vscode.TreeItem {
    constructor(public readonly conv: ConversationRecord) {
        super(conv.title || 'Untitled Conversation', vscode.TreeItemCollapsibleState.None);

        this.tooltip = conv.last_message_preview || '';
        this.description = new Date(conv.updated_at).toLocaleDateString();
        this.contextValue = 'conversation-item';
        this.iconPath = new vscode.ThemeIcon(
            conv.status === 'archived' ? 'archive' : 'comment-discussion'
        );
        this.command = {
            command: 'amprealize.openConversation',
            title: 'Open Conversation',
            arguments: [conv.id, conv.title]
        };
    }
}

export class ConversationTreeDataProvider
    implements vscode.TreeDataProvider<ConversationItem>, vscode.Disposable {

    private _onDidChangeTreeData: vscode.EventEmitter<ConversationItem | undefined | null | void> =
        new vscode.EventEmitter<ConversationItem | undefined | null | void>();

    readonly onDidChangeTreeData: vscode.Event<ConversationItem | undefined | null | void> =
        this._onDidChangeTreeData.event;

    private _items: ConversationItem[] | undefined;

    constructor(
        private readonly _config: {
            baseUrl: string;
            authToken?: string;
            projectId?: string;
        }
    ) {}

    refresh(): void {
        this._items = undefined;
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: ConversationItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: ConversationItem): Promise<ConversationItem[]> {
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

    private _fetchConversations(): Promise<ConversationRecord[]> {
        return new Promise((resolve) => {
            const { baseUrl, authToken, projectId } = this._config;

            let requestUrl = `${baseUrl}/api/v1/conversations?limit=50`;
            if (projectId) {
                requestUrl += `&project_id=${encodeURIComponent(projectId)}`;
            }

            const parsed = new url.URL(requestUrl);
            const isHttps = parsed.protocol === 'https:';
            const transport = isHttps ? https : http;

            const options: http.RequestOptions = {
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

                res.on('data', (chunk: Buffer) => {
                    data += chunk.toString();
                });

                res.on('end', () => {
                    try {
                        const parsed = JSON.parse(data);
                        if (Array.isArray(parsed)) {
                            resolve(parsed as ConversationRecord[]);
                        } else if (parsed && Array.isArray(parsed.conversations)) {
                            resolve(parsed.conversations as ConversationRecord[]);
                        } else {
                            resolve([]);
                        }
                    } catch (err) {
                        console.error('ConversationTreeDataProvider: failed to parse response', err);
                        resolve([]);
                    }
                });
            });

            req.on('error', (err: Error) => {
                console.error('ConversationTreeDataProvider: request failed', err);
                resolve([]);
            });

            req.end();
        });
    }

    dispose(): void {
        this._onDidChangeTreeData.dispose();
    }
}
