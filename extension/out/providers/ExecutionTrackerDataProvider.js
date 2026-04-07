"use strict";
/**
 * Execution Tracker Data Provider
 *
 * Provides tree view data for monitoring workflow runs:
 * - Real-time run status display
 * - Progress indicators and error/warning highlights
 * - Run detail navigation
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
exports.ExecutionTrackerDataProvider = void 0;
const vscode = __importStar(require("vscode"));
const actorAvatar_1 = require("../utils/actorAvatar");
class ExecutionTrackerDataProvider {
    constructor(client) {
        this.client = client;
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
        this.runs = [];
        this.refreshInterval = 30000; // 30 seconds (was 5s - too aggressive)
        this.isLoading = false;
        this.lastRefresh = 0;
        this.minRefreshInterval = 5000; // Minimum 5s between refreshes
        // NOTE: Do NOT auto-initialize - wait for user to manually refresh
        // This prevents resource exhaustion on startup
    }
    /**
     * Start auto-refresh (call this when view becomes visible)
     */
    startAutoRefresh() {
        if (this.refreshTimer)
            return; // Already running
        this.refreshTimer = setInterval(async () => {
            await this.refresh();
        }, this.refreshInterval);
    }
    /**
     * Stop auto-refresh (call this when view is hidden)
     */
    stopAutoRefresh() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = undefined;
        }
    }
    async refresh() {
        // Rate limiting - prevent rapid refreshes
        const now = Date.now();
        if (this.isLoading || (now - this.lastRefresh < this.minRefreshInterval)) {
            return;
        }
        this.isLoading = true;
        this.lastRefresh = now;
        try {
            // Get recent runs (last 20 runs)
            const runs = await this.client.listRuns({ limit: 20 });
            this.runs = runs.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
            this._onDidChangeTreeData.fire();
        }
        catch (error) {
            console.error('Failed to refresh execution tracker:', error);
            // Don't spam errors - just log once
        }
        finally {
            this.isLoading = false;
        }
    }
    getTreeItem(element) {
        if ('run' in element) {
            return this.getRunTreeItem(element);
        }
        else {
            return this.getRunStepTreeItem(element);
        }
    }
    getRunTreeItem(item) {
        const run = item.run;
        const treeItem = new vscode.TreeItem(`${run.workflow_name || run.template_name || 'Unnamed Workflow'}`, vscode.TreeItemCollapsibleState.Collapsed);
        treeItem.iconPath = vscode.Uri.parse((0, actorAvatar_1.buildActorAvatarDataUri)((0, actorAvatar_1.createActorViewModel)({
            id: run.actor.id,
            kind: 'agent',
            displayName: run.actor.id,
            subtitle: run.actor.role,
            presenceState: run.status.toLowerCase() === 'running' || run.status.toLowerCase() === 'in_progress'
                ? 'working'
                : run.status.toLowerCase() === 'failed' || run.status.toLowerCase() === 'cancelled'
                    ? 'paused'
                    : 'available',
        }), 28));
        // Set context value for different run states
        switch (run.status.toLowerCase()) {
            case 'running':
            case 'in_progress':
                treeItem.contextValue = 'run-running';
                treeItem.description = `${run.progress_pct || 0}% complete`;
                break;
            case 'completed':
            case 'success':
                treeItem.contextValue = 'run-completed';
                treeItem.description = 'Completed';
                break;
            case 'failed':
            case 'error':
                treeItem.contextValue = 'run-failed';
                treeItem.description = 'Failed';
                break;
            case 'cancelled':
                treeItem.contextValue = 'run-cancelled';
                treeItem.description = 'Cancelled';
                break;
            default:
                treeItem.contextValue = 'run-item';
                treeItem.description = run.status;
        }
        // Add tooltip with run information
        const tooltip = new vscode.MarkdownString();
        tooltip.appendText(`**Run ID:** ${run.run_id}\n`);
        tooltip.appendText(`**Status:** ${run.status}\n`);
        tooltip.appendText(`**Progress:** ${run.progress_pct || 0}%\n`);
        tooltip.appendText(`**Created:** ${new Date(run.created_at).toLocaleString()}\n`);
        if (run.step_current) {
            tooltip.appendText(`**Current Step:** ${run.step_current.name}\n`);
        }
        if (run.tokens_generated) {
            tooltip.appendText(`**Tokens Generated:** ${run.tokens_generated}\n`);
        }
        if (run.error) {
            tooltip.appendText(`**Error:** ${run.error}\n`);
        }
        treeItem.tooltip = tooltip;
        // Add command for opening run details
        treeItem.command = {
            command: 'amprealize.viewRunDetails',
            title: 'View Run Details',
            arguments: [run]
        };
        return treeItem;
    }
    getRunStepTreeItem(item) {
        const step = item.step;
        const treeItem = new vscode.TreeItem(step.name, vscode.TreeItemCollapsibleState.None);
        // Set context value and icon based on step status
        switch (step.status.toLowerCase()) {
            case 'pending':
            case 'queued':
                treeItem.contextValue = 'run-step-pending';
                treeItem.iconPath = new vscode.ThemeIcon('clock', new vscode.ThemeColor('testing.iconSkipped'));
                break;
            case 'running':
            case 'in_progress':
                treeItem.contextValue = 'run-step-running';
                treeItem.iconPath = new vscode.ThemeIcon('play', new vscode.ThemeColor('testing.iconRunning'));
                break;
            case 'completed':
            case 'success':
                treeItem.contextValue = 'run-step-completed';
                treeItem.iconPath = new vscode.ThemeIcon('check', new vscode.ThemeColor('testing.iconPassed'));
                break;
            case 'failed':
            case 'error':
                treeItem.contextValue = 'run-step-failed';
                treeItem.iconPath = new vscode.ThemeIcon('error', new vscode.ThemeColor('testing.iconFailed'));
                break;
            default:
                treeItem.contextValue = 'run-step';
                treeItem.iconPath = new vscode.ThemeIcon('symbol-method');
        }
        // Add tooltip with step information
        const tooltip = new vscode.MarkdownString();
        tooltip.appendText(`**Step ID:** ${step.step_id}\n`);
        tooltip.appendText(`**Status:** ${step.status}\n`);
        if (step.started_at) {
            tooltip.appendText(`**Started:** ${new Date(step.started_at).toLocaleString()}\n`);
        }
        if (step.completed_at) {
            tooltip.appendText(`**Completed:** ${new Date(step.completed_at).toLocaleString()}\n`);
        }
        treeItem.tooltip = tooltip;
        return treeItem;
    }
    async getChildren(element) {
        if (!element) {
            // Return top-level run items
            return this.runs.map(run => this.createRunTreeItem(run));
        }
        if ('run' in element && element.contextValue.startsWith('run-')) {
            // Return steps for this run
            const run = element.run;
            const steps = [];
            // If run has current step info, add it
            if (run.step_current) {
                steps.push(this.createRunStepTreeItem({
                    step: {
                        step_id: run.step_current.step_id,
                        name: run.step_current.name,
                        status: run.step_current.status,
                        started_at: run.step_current.started_at,
                        completed_at: run.step_current.completed_at
                    }
                }));
            }
            // If we have step progress info, add completed steps
            if (run.step_progress) {
                for (let i = 1; i < run.step_progress.current; i++) {
                    steps.push(this.createRunStepTreeItem({
                        step: {
                            step_id: `step-${i}`,
                            name: `Step ${i}`,
                            status: 'completed',
                            completed_at: new Date().toISOString()
                        }
                    }));
                }
            }
            return steps;
        }
        return [];
    }
    createRunTreeItem(run) {
        const item = {
            label: `${run.workflow_name || run.template_name || 'Unnamed Workflow'}`,
            collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
            run: run,
            contextValue: this.getRunContextValue(run)
        };
        return item;
    }
    createRunStepTreeItem(item) {
        const step = item.step;
        const contextValue = this.getStepContextValue(step);
        return {
            label: step.name,
            collapsibleState: vscode.TreeItemCollapsibleState.None,
            step: step,
            contextValue: contextValue
        };
    }
    getRunContextValue(run) {
        switch (run.status.toLowerCase()) {
            case 'running':
            case 'in_progress':
                return 'run-running';
            case 'completed':
            case 'success':
                return 'run-completed';
            case 'failed':
            case 'error':
                return 'run-failed';
            case 'cancelled':
                return 'run-cancelled';
            default:
                return 'run-item';
        }
    }
    getStepContextValue(step) {
        switch (step.status.toLowerCase()) {
            case 'pending':
            case 'queued':
                return 'run-step-pending';
            case 'running':
            case 'in_progress':
                return 'run-step-running';
            case 'completed':
            case 'success':
                return 'run-step-completed';
            case 'failed':
            case 'error':
                return 'run-step-failed';
            default:
                return 'run-step';
        }
    }
    dispose() {
        this.stopAutoRefresh();
    }
}
exports.ExecutionTrackerDataProvider = ExecutionTrackerDataProvider;
//# sourceMappingURL=ExecutionTrackerDataProvider.js.map
