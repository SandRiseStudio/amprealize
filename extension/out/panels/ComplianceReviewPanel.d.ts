/**
 * Compliance Review Panel
 *
 * Webview panel for managing compliance checklists and validation:
 * - Interactive compliance checklist interface
 * - Step-by-step validation workflow
 * - Evidence attachment and documentation
 * - Approval/rejection workflow with comments
 * - Progress tracking and status management
 */
import * as vscode from 'vscode';
import { AmprealizeClient, ComplianceChecklist } from '../client/AmprealizeClient';
export declare class ComplianceReviewPanel {
    static currentPanel: ComplianceReviewPanel | undefined;
    static readonly viewType = "amprealize.complianceReview";
    private readonly _panel;
    private readonly _extensionUri;
    private _disposables;
    private _checklist;
    private _client;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, client: AmprealizeClient, checklist: ComplianceChecklist): void;
    static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, client: AmprealizeClient): void;
    private _update;
    private _recordStep;
    private _validateChecklist;
    private _addComment;
    private _attachEvidence;
    private _exportChecklist;
    private _refreshChecklist;
    private _getHtmlForWebview;
    private _renderStepHTML;
    private _renderCommentHTML;
    dispose(): void;
}
//# sourceMappingURL=ComplianceReviewPanel.d.ts.map
