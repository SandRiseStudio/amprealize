/**
 * Action Tree Data Provider
 *
 * Provides hierarchical view of recorded build actions for reproducibility tracking.
 * Actions are displayed in reverse chronological order with filtering capabilities.
 *
 * Following behavior_sanitize_action_registry (Student)
 */
import * as vscode from 'vscode';
import { McpClient, ActionItem } from '../client/McpClient';
type ActionNode = ActionTreeItem | StatusGroupTreeItem | MessageTreeItem;
export declare class ActionTreeDataProvider implements vscode.TreeDataProvider<ActionNode> {
    private mcpClient;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<ActionNode | undefined | null | void>;
    private actions;
    private isLoading;
    private lastError;
    private filterBehaviorId;
    private filterArtifactPath;
    private lastLoad;
    private readonly minLoadInterval;
    constructor(mcpClient: McpClient);
    refresh(): void;
    /**
     * Filter actions by behavior ID
     */
    filterByBehavior(behaviorId: string): Promise<void>;
    /**
     * Filter actions by artifact path prefix
     */
    filterByArtifactPath(pathPrefix: string): Promise<void>;
    /**
     * Clear all filters
     */
    clearFilters(): void;
    private loadActions;
    getTreeItem(element: ActionNode): vscode.TreeItem;
    getChildren(element?: ActionNode): Promise<ActionNode[]>;
    /**
     * Get all current actions for export/analysis
     */
    getActions(): ActionItem[];
    /**
     * Dispose of resources
     */
    dispose(): void;
}
declare class StatusGroupTreeItem extends vscode.TreeItem {
    readonly status: string;
    constructor(status: string, count: number);
}
export declare class ActionTreeItem extends vscode.TreeItem {
    readonly action: ActionItem;
    constructor(action: ActionItem);
}
declare class MessageTreeItem extends vscode.TreeItem {
    constructor(label: string, icon?: string, tooltip?: string);
}
export {};
//# sourceMappingURL=ActionTreeDataProvider.d.ts.map
