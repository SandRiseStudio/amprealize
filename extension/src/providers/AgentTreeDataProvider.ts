/**
 * Agent Tree Data Provider
 *
 * Provides hierarchical view of agents grouped by status and role alignment:
 * - Status grouping: Draft, Published, Deprecated
 * - Role grouping: Strategist, Teacher, Student, Multi
 */

import * as vscode from 'vscode';
import { AmprealizeClient, Agent, AgentStatus, AgentVisibility, RoleAlignment, AgentSearchResult } from '../client/AmprealizeClient';
import { buildActorAvatarDataUri, createActorViewModel } from '../utils/actorAvatar';

type AgentNode = AgentTreeItem | StatusGroupTreeItem | RoleGroupTreeItem | MessageTreeItem;

export class AgentTreeDataProvider implements vscode.TreeDataProvider<AgentNode>, vscode.Disposable {
	private _onDidChangeTreeData: vscode.EventEmitter<AgentNode | undefined | null | void> = new vscode.EventEmitter<AgentNode | undefined | null | void>();
	readonly onDidChangeTreeData: vscode.Event<AgentNode | undefined | null | void> = this._onDidChangeTreeData.event;

	private agents: Agent[] = [];
	private searchQuery: string | null = null;
	private groupBy: 'status' | 'role' = 'status';
	private statusFilter: AgentStatus | null = null;
	private visibilityFilter: AgentVisibility | null = null;

	constructor(private client: AmprealizeClient) {
		this.loadAgents('sidebar.initial_load');
	}

	dispose(): void {
		this._onDidChangeTreeData.dispose();
	}

	refresh(): void {
		this.searchQuery = null;
		this.loadAgents('sidebar.refresh');
	}

	setGroupBy(groupBy: 'status' | 'role'): void {
		this.groupBy = groupBy;
		this._onDidChangeTreeData.fire();
	}

	setStatusFilter(status: AgentStatus | null): void {
		this.statusFilter = status;
		this.loadAgents('sidebar.filter');
	}

	setVisibilityFilter(visibility: AgentVisibility | null): void {
		this.visibilityFilter = visibility;
		this.loadAgents('sidebar.filter');
	}

	async search(query: string): Promise<void> {
		this.searchQuery = query;
		try {
			const results = await this.client.searchAgents(query, {
				status: this.statusFilter ?? undefined,
				visibility: this.visibilityFilter ?? undefined,
			}, {
				source: 'sidebar.search',
				query
			});
			this.agents = results.map(r => r.agent);
			this._onDidChangeTreeData.fire();
		} catch (error) {
			vscode.window.showErrorMessage(`Search failed: ${error}`);
		}
	}

	private async loadAgents(source: string): Promise<void> {
		try {
			this.agents = await this.client.listAgents({
				status: this.statusFilter ?? undefined,
				visibility: this.visibilityFilter ?? undefined,
			}, { source });
			this._onDidChangeTreeData.fire();
		} catch (error) {
			vscode.window.showErrorMessage(`Failed to load agents: ${error}`);
		}
	}

	getTreeItem(element: AgentNode): vscode.TreeItem {
		return element;
	}

	async getChildren(element?: AgentNode): Promise<AgentNode[]> {
		if (!element) {
			// Root level - show search results or groups
			if (this.searchQuery) {
				if (this.agents.length === 0) {
					return [new MessageTreeItem('No agents match this search')];
				}
				return this.agents.map(a => new AgentTreeItem(a, vscode.TreeItemCollapsibleState.None));
			}

			if (this.agents.length === 0) {
				return [
					new MessageTreeItem('No agents found yet',
						'Create one with "amprealize agent-registry create" or bootstrap from existing playbooks.')
				];
			}

			// Show groups based on groupBy setting
			if (this.groupBy === 'status') {
				return [
					new StatusGroupTreeItem('PUBLISHED', 'Published', 'Active agents ready for use'),
					new StatusGroupTreeItem('DRAFT', 'Drafts', 'Work-in-progress agents'),
					new StatusGroupTreeItem('DEPRECATED', 'Deprecated', 'Archived agents')
				];
			} else {
				return [
					new RoleGroupTreeItem('STRATEGIST', 'Strategist', 'Planning & Architecture'),
					new RoleGroupTreeItem('TEACHER', 'Teacher', 'Guidance & Examples'),
					new RoleGroupTreeItem('STUDENT', 'Student', 'Execution & Reporting'),
					new RoleGroupTreeItem('MULTI', 'Multi-Role', 'Flexible role agents')
				];
			}
		}

		// Second level - show agents in group
		if (element instanceof StatusGroupTreeItem) {
			const statusAgents = this.agents.filter(a => a.status === element.status);
			if (statusAgents.length === 0) {
				return [new MessageTreeItem(`No ${element.label?.toString().toLowerCase()} agents`)];
			}
			return statusAgents.map(a => new AgentTreeItem(a, vscode.TreeItemCollapsibleState.None));
		}

		if (element instanceof RoleGroupTreeItem) {
			const roleAgents = this.agents.filter(a => a.role_alignment === element.role);
			if (roleAgents.length === 0) {
				return [new MessageTreeItem(`No ${element.label?.toString().toLowerCase()} agents`)];
			}
			return roleAgents.map(a => new AgentTreeItem(a, vscode.TreeItemCollapsibleState.None));
		}

		return [];
	}

	getAgentCount(): number {
		return this.agents.length;
	}

	getAgentsByStatus(status: AgentStatus): Agent[] {
		return this.agents.filter(a => a.status === status);
	}

	getAgentsByRole(role: RoleAlignment): Agent[] {
		return this.agents.filter(a => a.role_alignment === role);
	}
}

class StatusGroupTreeItem extends vscode.TreeItem {
	constructor(
		public readonly status: AgentStatus,
		label: string,
		description: string
	) {
		super(label, vscode.TreeItemCollapsibleState.Collapsed);
		this.description = description;
		this.contextValue = 'agentStatusGroup';
		this.iconPath = new vscode.ThemeIcon(
			status === 'PUBLISHED' ? 'verified' :
			status === 'DRAFT' ? 'edit' :
			'archive'
		);
	}
}

class RoleGroupTreeItem extends vscode.TreeItem {
	constructor(
		public readonly role: RoleAlignment,
		label: string,
		description: string
	) {
		super(label, vscode.TreeItemCollapsibleState.Collapsed);
		this.description = description;
		this.contextValue = 'agentRoleGroup';
		this.iconPath = new vscode.ThemeIcon(
			role === 'STRATEGIST' ? 'graph' :
			role === 'TEACHER' ? 'mortar-board' :
			role === 'STUDENT' ? 'check' :
			'symbol-misc'
		);
	}
}

class AgentTreeItem extends vscode.TreeItem {
	constructor(
		public readonly agent: Agent,
		public readonly collapsibleState: vscode.TreeItemCollapsibleState
	) {
		super(agent.name, collapsibleState);

		this.description = agent.description;
		this.tooltip = this.buildTooltip();
		this.contextValue = this.getContextValue();

		// Icon based on status and role
		this.iconPath = vscode.Uri.parse(
			buildActorAvatarDataUri(
				createActorViewModel({
					id: agent.agent_id,
					kind: 'agent',
					displayName: agent.name,
					subtitle: agent.role_alignment,
					presenceState: agent.status === 'DEPRECATED' ? 'offline' : agent.status === 'DRAFT' ? 'paused' : 'available',
				}),
				32,
			)
		);

		// Command to view details on click
		this.command = {
			command: 'amprealize.viewAgentDetail',
			title: 'View Agent Details',
			arguments: [this]
		};
	}

	private buildTooltip(): string {
		const lines = [
			`${this.agent.name}`,
			'',
			this.agent.description,
			'',
			`Status: ${this.agent.status}`,
			`Visibility: ${this.agent.visibility}`,
			`Role: ${this.agent.role_alignment}`,
			`Version: ${this.agent.version}`,
		];

		if (this.agent.tags.length > 0) {
			lines.push(`Tags: ${this.agent.tags.join(', ')}`);
		}

		if (this.agent.capabilities.length > 0) {
			lines.push(`Capabilities: ${this.agent.capabilities.join(', ')}`);
		}

		if (this.agent.behaviors.length > 0) {
			lines.push(`Behaviors: ${this.agent.behaviors.length} attached`);
		}

		return lines.join('\n');
	}

	private getContextValue(): string {
		// Context value for menu contributions
		const parts = ['agent'];
		parts.push(this.agent.status.toLowerCase());
		parts.push(this.agent.visibility.toLowerCase());
		return parts.join('.');
	}

}

class MessageTreeItem extends vscode.TreeItem {
	constructor(label: string, tooltip?: string) {
		super(label, vscode.TreeItemCollapsibleState.None);
		this.iconPath = new vscode.ThemeIcon('info');
		if (tooltip) {
			this.tooltip = tooltip;
		}
		this.contextValue = 'info';
	}
}
