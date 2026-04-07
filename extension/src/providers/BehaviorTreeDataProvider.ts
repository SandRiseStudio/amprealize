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

export class BehaviorTreeDataProvider implements vscode.TreeDataProvider<BehaviorNode> {
	private _onDidChangeTreeData: vscode.EventEmitter<BehaviorNode | undefined | null | void> = new vscode.EventEmitter<BehaviorNode | undefined | null | void>();
	readonly onDidChangeTreeData: vscode.Event<BehaviorNode | undefined | null | void> = this._onDidChangeTreeData.event;	private behaviors: Behavior[] = [];
	private searchQuery: string | null = null;

	constructor(private client: AmprealizeClient) {
		this.loadBehaviors('sidebar.initial_load');
	}

	refresh(): void {
		this.searchQuery = null;
		this.loadBehaviors('sidebar.refresh');
	}

	async search(query: string): Promise<void> {
		this.searchQuery = query;
		try {
			this.behaviors = await this.client.searchBehaviors(query, undefined, {
				source: 'sidebar.search',
				query
			});
			this._onDidChangeTreeData.fire();
		} catch (error) {
			vscode.window.showErrorMessage(`Search failed: ${error}`);
		}
	}

	private async loadBehaviors(source: string): Promise<void> {
		try {
			this.behaviors = await this.client.listBehaviors(undefined, { source });
			this._onDidChangeTreeData.fire();
		} catch (error) {
			vscode.window.showErrorMessage(`Failed to load behaviors: ${error}`);
		}
	}

	getTreeItem(element: BehaviorNode): vscode.TreeItem {
		return element;
	}

	async getChildren(element?: BehaviorNode): Promise<BehaviorNode[]> {
		if (!element) {
			if (this.searchQuery) {
				if (this.behaviors.length === 0) {
					return [new MessageTreeItem('No behaviors match this search')];
				}
				return this.behaviors.map(b => new BehaviorTreeItem(b, vscode.TreeItemCollapsibleState.None));
			}

			if (this.behaviors.length === 0) {
				return [
					new MessageTreeItem('No behaviors found yet',
						'Create one with "amprealize behaviors create" or import from the MCP catalog.')
				];
			}

			return [
				new RoleTreeItem('STRATEGIST', 'Strategist', 'Planning & Decomposition'),
				new RoleTreeItem('TEACHER', 'Teacher', 'Explanation & Guidance'),
				new RoleTreeItem('STUDENT', 'Student', 'Execution & Reporting')
			];
		}

		if (element instanceof RoleTreeItem) {
			const roleBehaviors = this.behaviors.filter(b => {
				const version = b.versions?.[0];
				return version?.role_focus === element.role;
			});
			if (roleBehaviors.length === 0) {
				return [new MessageTreeItem(`No behaviors for the ${element.label} role yet`)];
			}
			return roleBehaviors.map(b => new BehaviorTreeItem(b, vscode.TreeItemCollapsibleState.None));
		}

		return [];
	}
}

class RoleTreeItem extends vscode.TreeItem {
	constructor(
		public readonly role: string,
		label: string,
		description: string
	) {
		super(label, vscode.TreeItemCollapsibleState.Collapsed);
		this.description = description;
		this.contextValue = 'role';
		this.iconPath = new vscode.ThemeIcon(
			role === 'STRATEGIST' ? 'graph' :
			role === 'TEACHER' ? 'mortar-board' :
			'check'
		);
	}
}

class BehaviorTreeItem extends vscode.TreeItem {
	constructor(
		public readonly behavior: Behavior,
		public readonly collapsibleState: vscode.TreeItemCollapsibleState
	) {
		super(behavior.name, collapsibleState);

		const version = behavior.versions?.[0];
		this.description = behavior.description;
		this.tooltip = `${behavior.name}\n\n${behavior.description}\n\nTags: ${behavior.tags.join(', ')}\nStatus: ${version?.status || 'Unknown'}`;
		this.contextValue = 'behavior';

		// Icon based on status
		this.iconPath = new vscode.ThemeIcon(
			version?.status === 'APPROVED' ? 'verified' :
			version?.status === 'IN_REVIEW' ? 'eye' :
			'file'
		);

		// Command to view details on click
		this.command = {
			command: 'amprealize.viewBehaviorDetail',
			title: 'View Behavior Details',
			arguments: [this]
		};
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
