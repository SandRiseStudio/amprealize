/**
 * Execution Tracker Data Provider
 *
 * Provides tree view data for monitoring workflow runs:
 * - Real-time run status display
 * - Progress indicators and error/warning highlights
 * - Run detail navigation
 */
import * as vscode from 'vscode';
import { AmprealizeClient, Run } from '../client/AmprealizeClient';
interface RunStep {
    step_id: string;
    name: string;
    status: string;
    started_at?: string;
    completed_at?: string;
}
export interface RunTreeItem extends vscode.TreeItem {
    run: Run;
    contextValue: 'run-item' | 'run-running' | 'run-completed' | 'run-failed' | 'run-cancelled';
}
export interface RunStepTreeItem extends vscode.TreeItem {
    step: RunStep;
    contextValue: 'run-step' | 'run-step-pending' | 'run-step-running' | 'run-step-completed' | 'run-step-failed';
}
export declare class ExecutionTrackerDataProvider implements vscode.TreeDataProvider<RunTreeItem | RunStepTreeItem> {
    private client;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<RunTreeItem | RunStepTreeItem | undefined | null | void>;
    private runs;
    private readonly refreshInterval;
    private refreshTimer?;
    private isLoading;
    private lastRefresh;
    private readonly minRefreshInterval;
    constructor(client: AmprealizeClient);
    /**
     * Start auto-refresh (call this when view becomes visible)
     */
    startAutoRefresh(): void;
    /**
     * Stop auto-refresh (call this when view is hidden)
     */
    stopAutoRefresh(): void;
    refresh(): Promise<void>;
    getTreeItem(element: RunTreeItem | RunStepTreeItem): vscode.TreeItem;
    private getRunTreeItem;
    private getRunStepTreeItem;
    getChildren(element?: RunTreeItem | RunStepTreeItem): Promise<(RunTreeItem | RunStepTreeItem)[]>;
    private createRunTreeItem;
    private createRunStepTreeItem;
    private getRunContextValue;
    private getStepContextValue;
    dispose(): void;
}
export {};
//# sourceMappingURL=ExecutionTrackerDataProvider.d.ts.map
