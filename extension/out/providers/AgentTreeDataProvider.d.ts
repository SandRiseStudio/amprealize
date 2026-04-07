/**
 * Agent Tree Data Provider
 *
 * Provides hierarchical view of agents grouped by status and role alignment:
 * - Status grouping: Draft, Published, Deprecated
 * - Role grouping: Strategist, Teacher, Student, Multi
 */
import * as vscode from 'vscode';
import { AmprealizeClient, Agent, AgentStatus, AgentVisibility, RoleAlignment } from '../client/AmprealizeClient';
type AgentNode = AgentTreeItem | StatusGroupTreeItem | RoleGroupTreeItem | MessageTreeItem;
export declare class AgentTreeDataProvider implements vscode.TreeDataProvider<AgentNode>, vscode.Disposable {
    private client;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<AgentNode | undefined | null | void>;
    private agents;
    private searchQuery;
    private groupBy;
    private statusFilter;
    private visibilityFilter;
    constructor(client: AmprealizeClient);
    dispose(): void;
    refresh(): void;
    setGroupBy(groupBy: 'status' | 'role'): void;
    setStatusFilter(status: AgentStatus | null): void;
    setVisibilityFilter(visibility: AgentVisibility | null): void;
    search(query: string): Promise<void>;
    private loadAgents;
    getTreeItem(element: AgentNode): vscode.TreeItem;
    getChildren(element?: AgentNode): Promise<AgentNode[]>;
    getAgentCount(): number;
    getAgentsByStatus(status: AgentStatus): Agent[];
    getAgentsByRole(role: RoleAlignment): Agent[];
}
declare class StatusGroupTreeItem extends vscode.TreeItem {
    readonly status: AgentStatus;
    constructor(status: AgentStatus, label: string, description: string);
}
declare class RoleGroupTreeItem extends vscode.TreeItem {
    readonly role: RoleAlignment;
    constructor(role: RoleAlignment, label: string, description: string);
}
declare class AgentTreeItem extends vscode.TreeItem {
    readonly agent: Agent;
    readonly collapsibleState: vscode.TreeItemCollapsibleState;
    constructor(agent: Agent, collapsibleState: vscode.TreeItemCollapsibleState);
    private buildTooltip;
    private getContextValue;
}
declare class MessageTreeItem extends vscode.TreeItem {
    constructor(label: string, tooltip?: string);
}
export {};
//# sourceMappingURL=AgentTreeDataProvider.d.ts.map
