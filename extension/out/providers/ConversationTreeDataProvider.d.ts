/**
 * Conversation Tree Data Provider
 *
 * Provides a flat list of conversations from the Amprealize backend.
 * Conversations are displayed as top-level items with no children.
 *
 * Following behavior_integrate_vscode_extension (Teacher)
 */
import * as vscode from 'vscode';
export interface ConversationRecord {
    id: string;
    title: string;
    status: 'active' | 'archived';
    updated_at: string;
    last_message_preview?: string;
}
export declare class ConversationItem extends vscode.TreeItem {
    readonly conv: ConversationRecord;
    constructor(conv: ConversationRecord);
}
export declare class ConversationTreeDataProvider implements vscode.TreeDataProvider<ConversationItem>, vscode.Disposable {
    private readonly _config;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<ConversationItem | undefined | null | void>;
    private _items;
    constructor(_config: {
        baseUrl: string;
        authToken?: string;
        projectId?: string;
    });
    refresh(): void;
    getTreeItem(element: ConversationItem): vscode.TreeItem;
    getChildren(element?: ConversationItem): Promise<ConversationItem[]>;
    private _fetchConversations;
    dispose(): void;
}
//# sourceMappingURL=ConversationTreeDataProvider.d.ts.map
