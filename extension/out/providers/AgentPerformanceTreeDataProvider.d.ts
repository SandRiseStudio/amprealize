/**
 * Agent Performance Tree Data Provider
 *
 * Customer-facing agent performance analytics:
 * - Overall performance summary
 * - Top performing agents
 * - Performance alerts
 * - Token savings metrics
 */
import * as vscode from 'vscode';
import { AmprealizeClient } from '../client/AmprealizeClient';
export interface AgentPerformanceTreeItem extends vscode.TreeItem {
    contextValue: string;
    agentId?: string;
    alertId?: string;
    periodDays?: number;
    data?: any;
}
export declare class AgentPerformanceTreeDataProvider implements vscode.TreeDataProvider<AgentPerformanceTreeItem> {
    private client;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<AgentPerformanceTreeItem | undefined | null | void>;
    private topPerformers;
    private alerts;
    private overallStats;
    private readonly refreshInterval;
    private refreshTimer?;
    private periodDays;
    constructor(client: AmprealizeClient);
    /**
     * Start auto-refresh (call only after user initiates first refresh)
     */
    private startAutoRefresh;
    private stopAutoRefresh;
    dispose(): void;
    refresh(): Promise<void>;
    setPeriod(days: number): void;
    getTreeItem(element: AgentPerformanceTreeItem): vscode.TreeItem;
    getChildren(element?: AgentPerformanceTreeItem): Promise<AgentPerformanceTreeItem[]>;
    private getRootItems;
    private getTopPerformerItems;
    private getAlertItems;
}
//# sourceMappingURL=AgentPerformanceTreeDataProvider.d.ts.map
