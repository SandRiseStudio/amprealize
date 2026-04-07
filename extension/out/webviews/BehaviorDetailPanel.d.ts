import * as vscode from 'vscode';
import { AmprealizeClient } from '../client/AmprealizeClient';
export declare class BehaviorDetailPanel {
    private client;
    private behaviorId;
    static currentPanel: BehaviorDetailPanel | undefined;
    private readonly _panel;
    private _disposables;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, client: AmprealizeClient, behavior: any): Promise<void>;
    private update;
    private getWebviewContent;
    private handleMessage;
    private escapeHtml;
    dispose(): void;
}
//# sourceMappingURL=BehaviorDetailPanel.d.ts.map
