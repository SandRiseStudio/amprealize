/**
 * Cost Analytics Tree Data Provider
 *
 * Customer-facing cost visibility for Amprealize usage:
 * - Daily/monthly cost summary
 * - Cost by service breakdown
 * - ROI metrics (token savings value)
 * - Top expensive workflows
 */
import * as vscode from 'vscode';
import { AmprealizeClient } from '../client/AmprealizeClient';
export interface CostTreeItem extends vscode.TreeItem {
    contextValue: 'cost-summary' | 'cost-service' | 'cost-roi' | 'cost-workflow' | 'cost-trend' | 'cost-header';
    data?: any;
}
export declare class CostTreeDataProvider implements vscode.TreeDataProvider<CostTreeItem> {
    private client;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<CostTreeItem | undefined | null | void>;
    private costByService;
    private roiSummary;
    private dailyCosts;
    private topExpensive;
    private readonly refreshInterval;
    private refreshTimer?;
    private periodDays;
    constructor(client: AmprealizeClient);
    /**
     * Start auto-refresh (call only after user initiates first refresh)
     */
    private startAutoRefresh;
    private stopAutoRefresh;
    refresh(): Promise<void>;
    setPeriod(days: number): void;
    getTreeItem(element: CostTreeItem): vscode.TreeItem;
    getChildren(element?: CostTreeItem): Promise<CostTreeItem[]>;
    private getRootItems;
    private getServiceItems;
    private getTopWorkflowItems;
    private getTrendItems;
    private getServiceIcon;
    dispose(): void;
}
//# sourceMappingURL=CostTreeDataProvider.d.ts.map
