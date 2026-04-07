/**
 * Compliance Tracker Data Provider
 *
 * Provides tree view data for compliance checklist navigation:
 * - Checklist categories and status overview
 * - Progress tracking and completion metrics
 * - Quick access to compliance review panel
 * - Evidence and comment count indicators
 */
import * as vscode from 'vscode';
import { AmprealizeClient, ComplianceChecklist, ComplianceStep, ComplianceComment } from '../client/AmprealizeClient';
export interface ComplianceChecklistItem extends vscode.TreeItem {
    checklist: ComplianceChecklist;
    contextValue: 'checklist-draft' | 'checklist-in-progress' | 'checklist-completed' | 'checklist-approved' | 'checklist-rejected';
}
export interface ComplianceStepItem extends vscode.TreeItem {
    step: ComplianceStep;
    contextValue: 'step-pending' | 'step-in-progress' | 'step-completed' | 'step-blocked' | 'step-skipped';
}
export interface ComplianceCommentItem extends vscode.TreeItem {
    comment: ComplianceComment;
    contextValue: 'comment';
}
export declare class ComplianceTreeDataProvider implements vscode.TreeDataProvider<ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem> {
    private client;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem | undefined | null | void>;
    private checklists;
    private readonly refreshInterval;
    private refreshTimer?;
    constructor(client: AmprealizeClient);
    /**
     * Start auto-refresh (call only after user initiates first refresh)
     */
    private startAutoRefresh;
    private stopAutoRefresh;
    refresh(): Promise<void>;
    getTreeItem(element: ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem): vscode.TreeItem;
    private getChecklistTreeItem;
    private getStepTreeItem;
    private getCommentTreeItem;
    getChildren(element?: ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem): Promise<(ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem)[]>;
    private createChecklistTreeItem;
    private createStepTreeItem;
    private createCommentTreeItem;
    private getChecklistContextValue;
    private getStepContextValue;
    dispose(): void;
}
//# sourceMappingURL=ComplianceTreeDataProvider.d.ts.map
