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
import * as vscode from 'vscode';
export interface ConversationPanelConfig {
    baseUrl: string;
    userId: string;
    authToken?: string;
}
export declare class ConversationPanel {
    static currentPanel: ConversationPanel | undefined;
    static readonly viewType = "amprealize.conversation";
    private readonly _panel;
    private readonly _extensionUri;
    private _conversationId;
    private _title;
    private _config;
    private _disposables;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, conversationId: string, conversationTitle: string, config: ConversationPanelConfig): void;
    /**
     * Switch to a different conversation without opening a new panel.
     */
    openConversation(conversationId: string, title: string): void;
    dispose(): void;
    private _buildWsUrl;
    private _sendInit;
    private _update;
    private _getHtmlForWebview;
}
//# sourceMappingURL=ConversationPanel.d.ts.map
