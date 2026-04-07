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

// Define interfaces for tree items
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

export class ComplianceTreeDataProvider implements vscode.TreeDataProvider<ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem> {
	private _onDidChangeTreeData: vscode.EventEmitter<ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem | undefined | null | void> = new vscode.EventEmitter<ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem | undefined | null | void>();
	readonly onDidChangeTreeData: vscode.Event<ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem | undefined | null | void> = this._onDidChangeTreeData.event;

	private checklists: ComplianceChecklist[] = [];
	private readonly refreshInterval: number = 30000; // 30 seconds
	private refreshTimer?: NodeJS.Timeout;

	constructor(private client: AmprealizeClient) {
		// NOTE: Do NOT auto-initialize - wait for user to manually refresh
		// This prevents resource exhaustion on startup
	}

	/**
	 * Start auto-refresh (call only after user initiates first refresh)
	 */
	private startAutoRefresh(): void {
		if (this.refreshTimer) return;
		this.refreshTimer = setInterval(async () => {
			await this.refresh();
		}, this.refreshInterval);
	}

	private stopAutoRefresh(): void {
		if (this.refreshTimer) {
			clearInterval(this.refreshTimer);
			this.refreshTimer = undefined;
		}
	}

	async refresh(): Promise<void> {
		try {
			// Get recent compliance checklists (last 20)
			const checklists = await this.client.listComplianceChecklists({});
			this.checklists = checklists.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
			this._onDidChangeTreeData.fire();
		} catch (error) {
			console.error('Failed to refresh compliance tracker:', error);
		}
	}

	getTreeItem(element: ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem): vscode.TreeItem {
		if ('checklist' in element) {
			return this.getChecklistTreeItem(element);
		} else if ('step' in element) {
			return this.getStepTreeItem(element);
		} else {
			return this.getCommentTreeItem(element);
		}
	}

	private getChecklistTreeItem(item: ComplianceChecklistItem): vscode.TreeItem {
		const checklist = item.checklist;
		const treeItem = new vscode.TreeItem(
			checklist.title,
			vscode.TreeItemCollapsibleState.Collapsed
		);

		// Set context value and icon based on checklist status
		switch (checklist.status) {
			case 'DRAFT':
				treeItem.contextValue = 'checklist-draft';
				treeItem.iconPath = new vscode.ThemeIcon('edit', new vscode.ThemeColor('testing.iconSkipped'));
				treeItem.description = 'Draft';
				break;
			case 'IN_PROGRESS':
				treeItem.contextValue = 'checklist-in-progress';
				treeItem.iconPath = new vscode.ThemeIcon('play', new vscode.ThemeColor('testing.iconRunning'));
				treeItem.description = `${checklist.progress.completed_steps}/${checklist.progress.total_steps} steps`;
				break;
			case 'COMPLETED':
				treeItem.contextValue = 'checklist-completed';
				treeItem.iconPath = new vscode.ThemeIcon('check', new vscode.ThemeColor('testing.iconPassed'));
				treeItem.description = 'Completed';
				break;
			case 'APPROVED':
				treeItem.contextValue = 'checklist-approved';
				treeItem.iconPath = new vscode.ThemeIcon('verified', new vscode.ThemeColor('testing.iconPassed'));
				treeItem.description = 'Approved';
				break;
			case 'REJECTED':
				treeItem.contextValue = 'checklist-rejected';
				treeItem.iconPath = new vscode.ThemeIcon('x', new vscode.ThemeColor('testing.iconFailed'));
				treeItem.description = 'Rejected';
				break;
			default:
				treeItem.contextValue = 'checklist-in-progress';
				treeItem.iconPath = new vscode.ThemeIcon('clock');
				treeItem.description = checklist.status;
		}

		// Add tooltip with checklist information
		const tooltip = new vscode.MarkdownString();
		tooltip.appendText(`**Checklist ID:** ${checklist.checklist_id}\n`);
		tooltip.appendText(`**Title:** ${checklist.title}\n`);
		tooltip.appendText(`**Status:** ${checklist.status}\n`);
		tooltip.appendText(`**Progress:** ${checklist.progress.completed_steps}/${checklist.progress.total_steps} steps (${checklist.progress.coverage_score}%)\n`);
		tooltip.appendText(`**Categories:** ${checklist.compliance_category?.join(', ') || 'None'}\n`);
		tooltip.appendText(`**Created:** ${new Date(checklist.created_at).toLocaleString()}\n`);
		tooltip.appendText(`**Updated:** ${new Date(checklist.updated_at).toLocaleString()}\n`);

		const totalComments = checklist.steps?.reduce((acc, step) => acc + (step.comments?.length || 0), 0) || 0;
		if (totalComments > 0) {
			tooltip.appendText(`**Comments:** ${totalComments} total\n`);
		}

		treeItem.tooltip = tooltip;

		// Add command for opening compliance review
		treeItem.command = {
			command: 'amprealize.openComplianceReview',
			title: 'Open Compliance Review',
			arguments: [checklist]
		};

		return treeItem;
	}

	private getStepTreeItem(item: ComplianceStepItem): vscode.TreeItem {
		const step = item.step;
		const treeItem = new vscode.TreeItem(step.title, vscode.TreeItemCollapsibleState.None);

		// Set context value and icon based on step status
		switch (step.status) {
			case 'PENDING':
				treeItem.contextValue = 'step-pending';
				treeItem.iconPath = new vscode.ThemeIcon('clock', new vscode.ThemeColor('testing.iconSkipped'));
				break;
			case 'IN_PROGRESS':
				treeItem.contextValue = 'step-in-progress';
				treeItem.iconPath = new vscode.ThemeIcon('play', new vscode.ThemeColor('testing.iconRunning'));
				break;
			case 'COMPLETED':
				treeItem.contextValue = 'step-completed';
				treeItem.iconPath = new vscode.ThemeIcon('check', new vscode.ThemeColor('testing.iconPassed'));
				break;
			case 'BLOCKED':
				treeItem.contextValue = 'step-blocked';
				treeItem.iconPath = new vscode.ThemeIcon('error', new vscode.ThemeColor('testing.iconFailed'));
				break;
			case 'SKIPPED':
				treeItem.contextValue = 'step-skipped';
				treeItem.iconPath = new vscode.ThemeIcon('debug-step-over', new vscode.ThemeColor('testing.iconSkipped'));
				break;
			default:
				treeItem.contextValue = 'step-pending';
				treeItem.iconPath = new vscode.ThemeIcon('symbol-method');
		}

		// Add tooltip with step information
		const tooltip = new vscode.MarkdownString();
		tooltip.appendText(`**Step ID:** ${step.step_id}\n`);
		tooltip.appendText(`**Title:** ${step.title}\n`);
		tooltip.appendText(`**Status:** ${step.status}\n`);
		tooltip.appendText(`**Checklist ID:** ${step.checklist_id}\n`);

		const evidenceCount = Object.keys(step.evidence || {}).length;
		if (evidenceCount > 0) {
			tooltip.appendText(`**Evidence:** ${evidenceCount} items\n`);
		}

		if (step.behaviors_cited?.length > 0) {
			tooltip.appendText(`**Behaviors Cited:** ${step.behaviors_cited.join(', ')}\n`);
		}

		if (step.related_run_id) {
			tooltip.appendText(`**Related Run:** ${step.related_run_id}\n`);
		}

		tooltip.appendText(`**Created:** ${new Date(step.created_at).toLocaleString()}\n`);
		if (step.completed_at) {
			tooltip.appendText(`**Completed:** ${new Date(step.completed_at).toLocaleString()}\n`);
		}

		treeItem.tooltip = tooltip;

		// Add description with metadata
		const commentsCount = step.comments?.length || 0;
		if (commentsCount > 0) {
			treeItem.description = `${commentsCount} comments`;
		}

		return treeItem;
	}

	private getCommentTreeItem(item: ComplianceCommentItem): vscode.TreeItem {
		const comment = item.comment;
		const treeItem = new vscode.TreeItem(
			comment.content.length > 50 ? `${comment.content.substring(0, 50)}...` : comment.content,
			vscode.TreeItemCollapsibleState.None
		);

		treeItem.contextValue = 'comment';
		treeItem.iconPath = new vscode.ThemeIcon('comment');

		// Add tooltip with comment information
		const tooltip = new vscode.MarkdownString();
		tooltip.appendText(`**Comment ID:** ${comment.comment_id}\n`);
		tooltip.appendText(`**Step ID:** ${comment.step_id}\n`);
		tooltip.appendText(`**Author:** ${comment.actor?.role || 'Unknown'}\n`);
		tooltip.appendText(`**Created:** ${new Date(comment.created_at).toLocaleString()}\n`);
		tooltip.appendText(`**Content:** ${comment.content}\n`);

		treeItem.tooltip = tooltip;

		return treeItem;
	}

	async getChildren(element?: ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem): Promise<(ComplianceChecklistItem | ComplianceStepItem | ComplianceCommentItem)[]> {
		if (!element) {
			// Return top-level checklist items
			return this.checklists.map(checklist => this.createChecklistTreeItem(checklist));
		}

		if ('checklist' in element) {
			// Return steps for this checklist
			const checklist = element.checklist;
			const items: (ComplianceStepItem | ComplianceCommentItem)[] = [];

			// Add steps
			if (checklist.steps) {
				for (const step of checklist.steps) {
					items.push(this.createStepTreeItem(step));
				}
			}

			return items;
		}

		if ('step' in element) {
			// Return comments for this step
			const step = element.step;
			const items: ComplianceCommentItem[] = [];

			if (step.comments) {
				for (const comment of step.comments) {
					items.push(this.createCommentTreeItem(comment));
				}
			}

			return items;
		}

		return [];
	}

	private createChecklistTreeItem(checklist: ComplianceChecklist): ComplianceChecklistItem {
		const contextValue = this.getChecklistContextValue(checklist);
		return {
			label: checklist.title,
			collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
			checklist: checklist,
			contextValue: contextValue
		} as ComplianceChecklistItem;
	}

	private createStepTreeItem(step: ComplianceStep): ComplianceStepItem {
		const contextValue = this.getStepContextValue(step);
		return {
			label: step.title,
			collapsibleState: vscode.TreeItemCollapsibleState.None,
			step: step,
			contextValue: contextValue
		} as ComplianceStepItem;
	}

	private createCommentTreeItem(comment: ComplianceComment): ComplianceCommentItem {
		return {
			label: comment.content.length > 50 ? `${comment.content.substring(0, 50)}...` : comment.content,
			collapsibleState: vscode.TreeItemCollapsibleState.None,
			comment: comment,
			contextValue: 'comment'
		} as ComplianceCommentItem;
	}

	private getChecklistContextValue(checklist: ComplianceChecklist): ComplianceChecklistItem['contextValue'] {
		switch (checklist.status) {
			case 'DRAFT':
				return 'checklist-draft';
			case 'IN_PROGRESS':
				return 'checklist-in-progress';
			case 'COMPLETED':
				return 'checklist-completed';
			case 'APPROVED':
				return 'checklist-approved';
			case 'REJECTED':
				return 'checklist-rejected';
			default:
				return 'checklist-in-progress';
		}
	}

	private getStepContextValue(step: ComplianceStep): ComplianceStepItem['contextValue'] {
		switch (step.status) {
			case 'PENDING':
				return 'step-pending';
			case 'IN_PROGRESS':
				return 'step-in-progress';
			case 'COMPLETED':
				return 'step-completed';
			case 'BLOCKED':
				return 'step-blocked';
			case 'SKIPPED':
				return 'step-skipped';
			default:
				return 'step-pending';
		}
	}

	dispose(): void {
		this.stopAutoRefresh();
	}
}
