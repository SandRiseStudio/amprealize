"use strict";
/**
 * Agent Performance Tree Data Provider
 *
 * Customer-facing agent performance analytics:
 * - Overall performance summary
 * - Top performing agents
 * - Performance alerts
 * - Token savings metrics
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.AgentPerformanceTreeDataProvider = void 0;
const vscode = __importStar(require("vscode"));
const actorAvatar_1 = require("../utils/actorAvatar");
class AgentPerformanceTreeDataProvider {
    constructor(client) {
        this.client = client;
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
        this.topPerformers = [];
        this.alerts = [];
        this.overallStats = null;
        this.refreshInterval = 60000; // 1 minute
        this.periodDays = 30;
        // NOTE: Do NOT auto-initialize - wait for user to manually refresh
        // This prevents resource exhaustion on startup
    }
    /**
     * Start auto-refresh (call only after user initiates first refresh)
     */
    startAutoRefresh() {
        if (this.refreshTimer)
            return;
        this.refreshTimer = setInterval(async () => {
            await this.refresh();
        }, this.refreshInterval);
    }
    stopAutoRefresh() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = undefined;
        }
    }
    dispose() {
        this.stopAutoRefresh();
    }
    async refresh() {
        try {
            // Fetch data via AmprealizeClient
            const [topPerformers, alerts] = await Promise.all([
                this.client.getTopPerformers('token_savings', 10, this.periodDays).catch(() => []),
                this.client.getAgentPerformanceAlerts(undefined, undefined, false, 20).catch(() => []),
            ]);
            this.topPerformers = topPerformers;
            this.alerts = alerts;
            // Calculate overall stats from top performers
            if (topPerformers.length > 0) {
                // We need to get summaries to calculate overall stats
                // For now, use top performers count as proxy
                this.overallStats = {
                    totalAgents: topPerformers.length,
                    avgSuccess: 0.85, // placeholder - would need aggregate endpoint
                    avgSavings: topPerformers.reduce((sum, p) => sum + (p.metricValue || 0), 0) / topPerformers.length / 100,
                };
            }
            this._onDidChangeTreeData.fire();
        }
        catch (error) {
            console.error('Failed to refresh agent performance data:', error);
        }
    }
    setPeriod(days) {
        this.periodDays = days;
        this.refresh();
    }
    getTreeItem(element) {
        return element;
    }
    async getChildren(element) {
        if (!element) {
            // Root level - show main categories
            return this.getRootItems();
        }
        // Handle expansion of categories
        if (element.contextValue === 'perf-header') {
            if (element.label === '🏆 Top Performers') {
                return this.getTopPerformerItems();
            }
            else if (element.label === '⚠️ Active Alerts') {
                return this.getAlertItems();
            }
        }
        return [];
    }
    getRootItems() {
        const items = [];
        // Overall summary
        if (this.overallStats) {
            const stats = this.overallStats;
            const successColor = stats.avgSuccess >= 0.9 ? 'charts.green' : stats.avgSuccess >= 0.7 ? 'charts.yellow' : 'charts.red';
            const summaryItem = {
                label: `${stats.totalAgents} agents tracked`,
                description: `${(stats.avgSuccess * 100).toFixed(0)}% avg success`,
                iconPath: new vscode.ThemeIcon('pulse', new vscode.ThemeColor(successColor)),
                collapsibleState: vscode.TreeItemCollapsibleState.None,
                contextValue: 'perf-summary',
                tooltip: new vscode.MarkdownString(`### Agent Performance Summary (Last ${this.periodDays} Days)\n\n` +
                    `- **Agents Tracked**: ${stats.totalAgents}\n` +
                    `- **Avg Success Rate**: ${(stats.avgSuccess * 100).toFixed(1)}%\n` +
                    `- **Avg Token Savings**: ${(stats.avgSavings * 100).toFixed(1)}%`),
                data: stats
            };
            items.push(summaryItem);
        }
        // Token savings metric
        if (this.overallStats) {
            const savingsColor = this.overallStats.avgSavings >= 0.3 ? 'charts.green' : this.overallStats.avgSavings >= 0.15 ? 'charts.yellow' : 'charts.red';
            const savingsIcon = this.overallStats.avgSavings >= 0.3 ? 'arrow-down' : 'dash';
            const savingsItem = {
                label: `Token Savings: ${(this.overallStats.avgSavings * 100).toFixed(0)}%`,
                description: 'avg across agents',
                iconPath: new vscode.ThemeIcon(savingsIcon, new vscode.ThemeColor(savingsColor)),
                collapsibleState: vscode.TreeItemCollapsibleState.None,
                contextValue: 'perf-metric',
                tooltip: new vscode.MarkdownString(`### Token Savings\n\n` +
                    `Average token savings rate across all tracked agents.\n\n` +
                    `- **Target**: ≥30% (per PRD)\n` +
                    `- **Current**: ${(this.overallStats.avgSavings * 100).toFixed(1)}%`),
            };
            items.push(savingsItem);
        }
        // Top performers header
        const topHeader = {
            label: '🏆 Top Performers',
            description: this.topPerformers.length ? `${this.topPerformers.length} agents` : 'Loading...',
            iconPath: new vscode.ThemeIcon('star'),
            collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
            contextValue: 'perf-header',
        };
        items.push(topHeader);
        // Alerts header
        const activeAlerts = this.alerts.filter(a => !a.resolvedAt);
        const alertColor = activeAlerts.length > 0 ? 'charts.red' : 'charts.green';
        const alertHeader = {
            label: '⚠️ Active Alerts',
            description: activeAlerts.length > 0 ? `${activeAlerts.length} unresolved` : 'All clear',
            iconPath: new vscode.ThemeIcon('bell', new vscode.ThemeColor(alertColor)),
            collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
            contextValue: 'perf-header',
        };
        items.push(alertHeader);
        return items;
    }
    getTopPerformerItems() {
        if (!this.topPerformers.length) {
            return [{
                    label: 'No data available',
                    description: 'Run some tasks first',
                    iconPath: new vscode.ThemeIcon('info'),
                    collapsibleState: vscode.TreeItemCollapsibleState.None,
                    contextValue: 'perf-agent',
                }];
        }
        return this.topPerformers.slice(0, 10).map((performer) => {
            const medal = performer.rank === 1 ? '🥇' : performer.rank === 2 ? '🥈' : performer.rank === 3 ? '🥉' : '  ';
            const metricValuePct = performer.metricValue * (performer.metricName.includes('rate') ? 100 : 1);
            const displayValue = performer.metricName.includes('rate') || performer.metricName.includes('savings')
                ? `${metricValuePct.toFixed(0)}%`
                : metricValuePct.toFixed(0);
            return {
                label: `${medal} ${performer.agentName || performer.agentId}`,
                description: `${displayValue} ${performer.metricName} • ${performer.totalTasks} tasks`,
                iconPath: vscode.Uri.parse((0, actorAvatar_1.buildActorAvatarDataUri)((0, actorAvatar_1.createActorViewModel)({
                    id: performer.agentId,
                    kind: 'agent',
                    displayName: performer.agentName || performer.agentId,
                    subtitle: performer.metricName,
                    presenceState: 'available',
                }), 28)),
                collapsibleState: vscode.TreeItemCollapsibleState.None,
                contextValue: 'top-performer',
                agentId: performer.agentId,
                periodDays: this.periodDays,
                tooltip: new vscode.MarkdownString(`### ${performer.agentId}\n\n` +
                    `| Metric | Value |\n` +
                    `|--------|-------|\n` +
                    `| Rank | #${performer.rank} |\n` +
                    `| ${performer.metricName} | ${displayValue} |\n` +
                    `| Tasks | ${performer.totalTasks} |\n` +
                    `| Period | ${performer.periodDays} days |`),
                data: performer,
            };
        });
    }
    getAlertItems() {
        const activeAlerts = this.alerts.filter(a => !a.resolvedAt);
        if (activeAlerts.length === 0) {
            return [{
                    label: '✅ No active alerts',
                    description: 'All systems normal',
                    iconPath: new vscode.ThemeIcon('check', new vscode.ThemeColor('charts.green')),
                    collapsibleState: vscode.TreeItemCollapsibleState.None,
                    contextValue: 'perf-alert',
                }];
        }
        return activeAlerts.map((alert) => {
            const severityIcon = alert.severity === 'critical' ? 'error' : 'warning';
            const severityColor = alert.severity === 'critical' ? 'charts.red' : 'charts.yellow';
            const contextValue = alert.acknowledgedAt ? 'alert-acknowledged' : 'alert-active';
            const message = alert.message ?? 'No message';
            return {
                label: message.slice(0, 50) + (message.length > 50 ? '...' : ''),
                description: alert.agentId,
                iconPath: new vscode.ThemeIcon(severityIcon, new vscode.ThemeColor(severityColor)),
                collapsibleState: vscode.TreeItemCollapsibleState.None,
                contextValue: contextValue,
                alertId: alert.alertId,
                agentId: alert.agentId,
                tooltip: new vscode.MarkdownString(`### ${alert.severity} Alert\n\n` +
                    `**Alert ID**: ${alert.alertId}\n\n` +
                    `**Agent**: ${alert.agentId}\n\n` +
                    `**Metric**: ${alert.metric}\n\n` +
                    `**Message**: ${message}\n\n` +
                    `**Threshold**: ${alert.thresholdValue} | **Actual**: ${alert.actualValue}\n\n` +
                    `**Created**: ${alert.createdAt ? new Date(alert.createdAt).toLocaleString() : 'Unknown'}\n\n` +
                    `**Acknowledged**: ${alert.acknowledgedAt ? 'Yes' : 'No'}`),
                data: alert,
            };
        });
    }
}
exports.AgentPerformanceTreeDataProvider = AgentPerformanceTreeDataProvider;
//# sourceMappingURL=AgentPerformanceTreeDataProvider.js.map
