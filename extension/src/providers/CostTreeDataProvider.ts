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
import {
	AmprealizeClient,
	CostByServiceResponse,
	ROISummaryResponse,
	DailyCostResponse,
	TopExpensiveResponse
} from '../client/AmprealizeClient';

export interface CostTreeItem extends vscode.TreeItem {
	contextValue: 'cost-summary' | 'cost-service' | 'cost-roi' | 'cost-workflow' | 'cost-trend' | 'cost-header';
	data?: any;
}

export class CostTreeDataProvider implements vscode.TreeDataProvider<CostTreeItem> {
	private _onDidChangeTreeData: vscode.EventEmitter<CostTreeItem | undefined | null | void> =
		new vscode.EventEmitter<CostTreeItem | undefined | null | void>();
	readonly onDidChangeTreeData: vscode.Event<CostTreeItem | undefined | null | void> =
		this._onDidChangeTreeData.event;

	private costByService: CostByServiceResponse | null = null;
	private roiSummary: ROISummaryResponse | null = null;
	private dailyCosts: DailyCostResponse | null = null;
	private topExpensive: TopExpensiveResponse | null = null;
	private readonly refreshInterval: number = 60000; // 1 minute
	private refreshTimer?: NodeJS.Timeout;
	private periodDays = 30;

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
			// Fetch all cost data in parallel
			const [costByService, roiSummary, dailyCosts, topExpensive] = await Promise.all([
				this.client.getCostByService(this.periodDays).catch(() => null),
				this.client.getROISummary(this.periodDays).catch(() => null),
				this.client.getDailyCosts(this.periodDays).catch(() => null),
				this.client.getTopExpensiveWorkflows(this.periodDays, 5).catch(() => null),
			]);

			this.costByService = costByService;
			this.roiSummary = roiSummary;
			this.dailyCosts = dailyCosts;
			this.topExpensive = topExpensive;

			this._onDidChangeTreeData.fire();
		} catch (error) {
			console.error('Failed to refresh cost data:', error);
		}
	}

	setPeriod(days: number): void {
		this.periodDays = days;
		this.refresh();
	}

	getTreeItem(element: CostTreeItem): vscode.TreeItem {
		return element;
	}

	async getChildren(element?: CostTreeItem): Promise<CostTreeItem[]> {
		if (!element) {
			// Root level - show main categories
			return this.getRootItems();
		}

		// Handle expansion of categories
		switch (element.contextValue) {
			case 'cost-header':
				if (element.label === '💰 Cost by Service') {
					return this.getServiceItems();
				} else if (element.label === '📊 Top Workflows') {
					return this.getTopWorkflowItems();
				} else if (element.label === '📈 Daily Trend') {
					return this.getTrendItems();
				}
				return [];
			default:
				return [];
		}
	}

	private getRootItems(): CostTreeItem[] {
		const items: CostTreeItem[] = [];

		// Summary card
		if (this.roiSummary || this.dailyCosts) {
			const totalCost = this.roiSummary?.total_cost_usd ?? this.dailyCosts?.rows?.reduce((sum, r) => sum + r.cost_usd, 0) ?? 0;
			const avgDaily = this.dailyCosts?.avg_daily_cost ?? totalCost / this.periodDays;

			const summaryItem: CostTreeItem = {
				label: `$${totalCost.toFixed(2)} total (${this.periodDays}d)`,
				description: `~$${avgDaily.toFixed(2)}/day`,
				iconPath: new vscode.ThemeIcon('credit-card', new vscode.ThemeColor('charts.blue')),
				collapsibleState: vscode.TreeItemCollapsibleState.None,
				contextValue: 'cost-summary',
				tooltip: new vscode.MarkdownString(
					`### Cost Summary (Last ${this.periodDays} Days)\n\n` +
					`- **Total Cost**: $${totalCost.toFixed(2)}\n` +
					`- **Avg Daily**: $${avgDaily.toFixed(2)}\n` +
					`- **Max Daily**: $${(this.dailyCosts?.max_daily_cost ?? 0).toFixed(2)}`
				),
				data: { totalCost, avgDaily }
			};
			items.push(summaryItem);
		}

		// ROI card
		if (this.roiSummary) {
			const roi = this.roiSummary;
			const roiColor = roi.roi_ratio >= 1 ? 'charts.green' : roi.roi_ratio >= 0.5 ? 'charts.yellow' : 'charts.red';
			const roiIcon = roi.roi_ratio >= 1 ? 'arrow-up' : 'arrow-down';

			const roiItem: CostTreeItem = {
				label: `ROI: ${(roi.roi_ratio * 100).toFixed(0)}%`,
				description: `$${roi.token_savings_value_usd.toFixed(2)} saved`,
				iconPath: new vscode.ThemeIcon(roiIcon, new vscode.ThemeColor(roiColor)),
				collapsibleState: vscode.TreeItemCollapsibleState.None,
				contextValue: 'cost-roi',
				tooltip: new vscode.MarkdownString(
					`### ROI Analysis\n\n` +
					`- **Token Savings Value**: $${roi.token_savings_value_usd.toFixed(2)}\n` +
					`- **Tokens Saved**: ${roi.total_tokens_saved.toLocaleString()}\n` +
					`- **Net Cost**: $${roi.net_cost_usd.toFixed(2)}\n` +
					`- **ROI Ratio**: ${(roi.roi_ratio * 100).toFixed(1)}%\n` +
					`- **Runs Analyzed**: ${roi.runs_analyzed}`
				),
				data: roi
			};
			items.push(roiItem);
		}

		// Cost by Service header
		if (this.costByService && this.costByService.rows.length > 0) {
			const headerItem: CostTreeItem = {
				label: '💰 Cost by Service',
				description: `${this.costByService.rows.length} services`,
				collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
				contextValue: 'cost-header'
			};
			items.push(headerItem);
		}

		// Top Workflows header
		if (this.topExpensive && this.topExpensive.rows.length > 0) {
			const headerItem: CostTreeItem = {
				label: '📊 Top Workflows',
				description: `${this.topExpensive.rows.length} most expensive`,
				collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
				contextValue: 'cost-header'
			};
			items.push(headerItem);
		}

		// Daily Trend header
		if (this.dailyCosts && this.dailyCosts.rows.length > 0) {
			const headerItem: CostTreeItem = {
				label: '📈 Daily Trend',
				description: `last ${this.dailyCosts.rows.length} days`,
				collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
				contextValue: 'cost-header'
			};
			items.push(headerItem);
		}

		// Empty state
		if (items.length === 0) {
			const emptyItem: CostTreeItem = {
				label: 'No cost data available',
				description: 'Run workflows to see cost analytics',
				iconPath: new vscode.ThemeIcon('info'),
				collapsibleState: vscode.TreeItemCollapsibleState.None,
				contextValue: 'cost-summary'
			};
			items.push(emptyItem);
		}

		return items;
	}

	private getServiceItems(): CostTreeItem[] {
		if (!this.costByService) {
			return [];
		}

		return this.costByService.rows.map(row => {
			const item: CostTreeItem = {
				label: row.service,
				description: `$${row.total_cost_usd.toFixed(2)} (${row.pct_of_total.toFixed(1)}%)`,
				iconPath: this.getServiceIcon(row.service),
				collapsibleState: vscode.TreeItemCollapsibleState.None,
				contextValue: 'cost-service',
				tooltip: new vscode.MarkdownString(
					`### ${row.service}\n\n` +
					`- **Total Cost**: $${row.total_cost_usd.toFixed(2)}\n` +
					`- **% of Total**: ${row.pct_of_total.toFixed(1)}%\n` +
					`- **Runs**: ${row.total_runs}\n` +
					`- **Avg Cost/Run**: $${row.avg_cost_per_run.toFixed(4)}`
				),
				data: row
			};
			return item;
		});
	}

	private getTopWorkflowItems(): CostTreeItem[] {
		if (!this.topExpensive) {
			return [];
		}

		return this.topExpensive.rows.map((row, index) => {
			const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : '  ';
			const item: CostTreeItem = {
				label: `${medal} ${row.workflow_name || row.workflow_id}`,
				description: `$${row.total_cost_usd.toFixed(2)} (${row.run_count} runs)`,
				iconPath: new vscode.ThemeIcon('rocket'),
				collapsibleState: vscode.TreeItemCollapsibleState.None,
				contextValue: 'cost-workflow',
				tooltip: new vscode.MarkdownString(
					`### ${row.workflow_name || row.workflow_id}\n\n` +
					`- **Total Cost**: $${row.total_cost_usd.toFixed(2)}\n` +
					`- **Runs**: ${row.run_count}\n` +
					`- **Avg Cost/Run**: $${row.avg_cost_per_run.toFixed(4)}`
				),
				data: row
			};
			return item;
		});
	}

	private getTrendItems(): CostTreeItem[] {
		if (!this.dailyCosts) {
			return [];
		}

		// Show last 7 days only for tree view
		const recentDays = this.dailyCosts.rows.slice(-7);

		return recentDays.map(row => {
			const date = new Date(row.date);
			const dayLabel = date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });

			const item: CostTreeItem = {
				label: dayLabel,
				description: `$${row.cost_usd.toFixed(2)} • ${row.runs} runs`,
				iconPath: new vscode.ThemeIcon('calendar'),
				collapsibleState: vscode.TreeItemCollapsibleState.None,
				contextValue: 'cost-trend',
				tooltip: new vscode.MarkdownString(
					`### ${dayLabel}\n\n` +
					`- **Cost**: $${row.cost_usd.toFixed(2)}\n` +
					`- **Runs**: ${row.runs}\n` +
					`- **Tokens**: ${row.tokens.toLocaleString()}`
				),
				data: row
			};
			return item;
		});
	}

	private getServiceIcon(service: string): vscode.ThemeIcon {
		const lower = service.toLowerCase();
		if (lower.includes('llm') || lower.includes('openai') || lower.includes('anthropic')) {
			return new vscode.ThemeIcon('hubot', new vscode.ThemeColor('charts.purple'));
		}
		if (lower.includes('storage') || lower.includes('database')) {
			return new vscode.ThemeIcon('database', new vscode.ThemeColor('charts.blue'));
		}
		if (lower.includes('compute') || lower.includes('cpu')) {
			return new vscode.ThemeIcon('server-process', new vscode.ThemeColor('charts.orange'));
		}
		if (lower.includes('embedding')) {
			return new vscode.ThemeIcon('symbol-array', new vscode.ThemeColor('charts.green'));
		}
		return new vscode.ThemeIcon('cloud', new vscode.ThemeColor('charts.foreground'));
	}

	dispose(): void {
		this.stopAutoRefresh();
	}
}
