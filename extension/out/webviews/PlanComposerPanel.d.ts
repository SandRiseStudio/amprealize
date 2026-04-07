import * as vscode from 'vscode';
import { AmprealizeClient } from '../client/AmprealizeClient';
export declare class PlanComposerPanel {
    private client;
    private templateId?;
    static currentPanel: PlanComposerPanel | undefined;
    private readonly _panel;
    private _disposables;
    private workflows;
    private behaviors;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, client: AmprealizeClient, template?: any): Promise<void>;
    private initialize;
    private getWebviewContent;
    private handleMessage;
    private handleBCIRetrieve;
    private handleBCIValidate;
    private emitTelemetry;
    private escapeHtml;
    dispose(): void;
}
//# sourceMappingURL=PlanComposerPanel.d.ts.map
