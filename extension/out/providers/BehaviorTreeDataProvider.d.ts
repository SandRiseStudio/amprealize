/**
 * Behavior Tree Data Provider
 *
 * Provides hierarchical view of behaviors grouped by role:
 * - Strategist (planning and decomposition)
 * - Teacher (explanation and guidance)
 * - Student (execution and reporting)
 */
import * as vscode from 'vscode';
import { AmprealizeClient, Behavior } from '../client/AmprealizeClient';
type BehaviorNode = BehaviorTreeItem | RoleTreeItem | MessageTreeItem;
export declare class BehaviorTreeDataProvider implements vscode.TreeDataProvider<BehaviorNode> {
    private client;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<BehaviorNode | undefined | null | void>;
    private behaviors;
    private searchQuery;
    constructor(client: AmprealizeClient);
    refresh(): void;
    search(query: string): Promise<void>;
    private loadBehaviors;
    getTreeItem(element: BehaviorNode): vscode.TreeItem;
    getChildren(element?: BehaviorNode): Promise<BehaviorNode[]>;
}
declare class RoleTreeItem extends vscode.TreeItem {
    readonly role: string;
    constructor(role: string, label: string, description: string);
}
declare class BehaviorTreeItem extends vscode.TreeItem {
    readonly behavior: Behavior;
    readonly collapsibleState: vscode.TreeItemCollapsibleState;
    constructor(behavior: Behavior, collapsibleState: vscode.TreeItemCollapsibleState);
}
declare class MessageTreeItem extends vscode.TreeItem {
    constructor(label: string, tooltip?: string);
}
export {};
//# sourceMappingURL=BehaviorTreeDataProvider.d.ts.map
