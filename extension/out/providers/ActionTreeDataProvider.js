"use strict";
/**
 * Action Tree Data Provider
 *
 * Provides hierarchical view of recorded build actions for reproducibility tracking.
 * Actions are displayed in reverse chronological order with filtering capabilities.
 *
 * Following behavior_sanitize_action_registry (Student)
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
exports.ActionTreeItem = exports.ActionTreeDataProvider = void 0;
const vscode = __importStar(require("vscode"));
class ActionTreeDataProvider {
    constructor(mcpClient) {
        this.mcpClient = mcpClient;
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
        this.actions = [];
        this.isLoading = false;
        this.lastError = null;
        this.filterBehaviorId = null;
        this.filterArtifactPath = null;
        this.lastLoad = 0;
        this.minLoadInterval = 5000; // Minimum 5s between loads
        // NOTE: Do NOT auto-load - wait for user to manually refresh
        // This prevents resource exhaustion on startup
    }
    refresh() {
        this.filterBehaviorId = null;
        this.filterArtifactPath = null;
        this.loadActions();
    }
    /**
     * Filter actions by behavior ID
     */
    async filterByBehavior(behaviorId) {
        this.filterBehaviorId = behaviorId;
        this.filterArtifactPath = null;
        await this.loadActions();
    }
    /**
     * Filter actions by artifact path prefix
     */
    async filterByArtifactPath(pathPrefix) {
        this.filterArtifactPath = pathPrefix;
        this.filterBehaviorId = null;
        await this.loadActions();
    }
    /**
     * Clear all filters
     */
    clearFilters() {
        this.filterBehaviorId = null;
        this.filterArtifactPath = null;
        this.loadActions();
    }
    async loadActions() {
        // Rate limiting - prevent rapid loads
        const now = Date.now();
        if (this.isLoading || (now - this.lastLoad < this.minLoadInterval)) {
            return;
        }
        // Check if MCP client is connected before attempting load
        if (!this.mcpClient.isConnected()) {
            this.lastError = 'MCP server not connected. Use "Amprealize: Connect to MCP Server" command.';
            this._onDidChangeTreeData.fire();
            return;
        }
        this.isLoading = true;
        this.lastLoad = now;
        this.lastError = null;
        try {
            const result = await this.mcpClient.actionList({
                behaviorId: this.filterBehaviorId || undefined,
                artifactPathFilter: this.filterArtifactPath || undefined,
                limit: 50
            });
            this.actions = result.actions || [];
            this._onDidChangeTreeData.fire();
        }
        catch (error) {
            this.lastError = error instanceof Error ? error.message : String(error);
            // Don't spam error messages - just update tree to show error state
            console.error('Failed to load actions:', this.lastError);
            this._onDidChangeTreeData.fire();
        }
        finally {
            this.isLoading = false;
        }
    }
    getTreeItem(element) {
        return element;
    }
    async getChildren(element) {
        if (!element) {
            // Root level - show status groups or flat list
            if (this.isLoading) {
                return [new MessageTreeItem('Loading actions...', 'sync~spin')];
            }
            if (this.lastError) {
                return [new MessageTreeItem(`Error: ${this.lastError}`, 'error')];
            }
            if (this.actions.length === 0) {
                const filterMessage = this.filterBehaviorId
                    ? `No actions citing behavior "${this.filterBehaviorId}"`
                    : this.filterArtifactPath
                        ? `No actions matching path "${this.filterArtifactPath}"`
                        : 'No actions recorded yet';
                return [new MessageTreeItem(filterMessage, 'info', 'Record actions with "amprealize record-action" or the Record Action command.')];
            }
            // Group by status
            const statusGroups = new Map();
            for (const action of this.actions) {
                const status = action.replay_status || 'NOT_STARTED';
                if (!statusGroups.has(status)) {
                    statusGroups.set(status, []);
                }
                const group = statusGroups.get(status);
                if (group) {
                    group.push(action);
                }
            }
            // Return groups with actions
            const nodes = [];
            const statusOrder = ['RUNNING', 'QUEUED', 'FAILED', 'NOT_STARTED', 'SUCCEEDED'];
            for (const status of statusOrder) {
                const group = statusGroups.get(status);
                if (group && group.length > 0) {
                    nodes.push(new StatusGroupTreeItem(status, group.length));
                }
            }
            // If only one group, show actions directly
            if (nodes.length === 1 && statusGroups.size === 1) {
                return this.actions.map(a => new ActionTreeItem(a));
            }
            return nodes.length > 0 ? nodes : this.actions.map(a => new ActionTreeItem(a));
        }
        if (element instanceof StatusGroupTreeItem) {
            const statusActions = this.actions.filter(a => (a.replay_status || 'NOT_STARTED') === element.status);
            return statusActions.map(a => new ActionTreeItem(a));
        }
        return [];
    }
    /**
     * Get all current actions for export/analysis
     */
    getActions() {
        return [...this.actions];
    }
    /**
     * Dispose of resources
     */
    dispose() {
        this._onDidChangeTreeData.dispose();
    }
}
exports.ActionTreeDataProvider = ActionTreeDataProvider;
class StatusGroupTreeItem extends vscode.TreeItem {
    constructor(status, count) {
        const label = `${formatStatus(status)} (${count})`;
        super(label, vscode.TreeItemCollapsibleState.Expanded);
        this.status = status;
        this.contextValue = `actionStatus-${status.toLowerCase()}`;
        this.iconPath = getStatusIcon(status);
        this.description = `${count} action${count !== 1 ? 's' : ''}`;
    }
}
class ActionTreeItem extends vscode.TreeItem {
    constructor(action) {
        super(action.summary, vscode.TreeItemCollapsibleState.None);
        this.action = action;
        // Format timestamp for description
        const timestamp = new Date(action.timestamp);
        const timeStr = timestamp.toLocaleString();
        this.description = `${action.artifact_path} • ${timeStr}`;
        // Build tooltip
        const behaviors = action.behaviors_cited?.join(', ') || 'none';
        this.tooltip = new vscode.MarkdownString(`**${action.summary}**\n\n` +
            `**Artifact:** ${action.artifact_path}\n\n` +
            `**Behaviors:** ${behaviors}\n\n` +
            `**Status:** ${action.replay_status || 'NOT_STARTED'}\n\n` +
            `**Recorded:** ${timeStr}\n\n` +
            `**ID:** \`${action.action_id}\``);
        this.contextValue = `action-${(action.replay_status || 'NOT_STARTED').toLowerCase()}`;
        this.iconPath = getStatusIcon(action.replay_status || 'NOT_STARTED');
        // Command to view details on click
        this.command = {
            command: 'amprealize.viewActionDetail',
            title: 'View Action Details',
            arguments: [this]
        };
    }
}
exports.ActionTreeItem = ActionTreeItem;
class MessageTreeItem extends vscode.TreeItem {
    constructor(label, icon = 'info', tooltip) {
        super(label, vscode.TreeItemCollapsibleState.None);
        this.iconPath = new vscode.ThemeIcon(icon);
        if (tooltip) {
            this.tooltip = tooltip;
        }
        this.contextValue = 'info';
    }
}
function formatStatus(status) {
    switch (status) {
        case 'NOT_STARTED': return 'Recorded';
        case 'QUEUED': return 'Queued';
        case 'RUNNING': return 'Running';
        case 'SUCCEEDED': return 'Replayed';
        case 'FAILED': return 'Failed';
        default: return status;
    }
}
function getStatusIcon(status) {
    switch (status) {
        case 'NOT_STARTED': return new vscode.ThemeIcon('circle-outline');
        case 'QUEUED': return new vscode.ThemeIcon('clock');
        case 'RUNNING': return new vscode.ThemeIcon('sync~spin');
        case 'SUCCEEDED': return new vscode.ThemeIcon('pass');
        case 'FAILED': return new vscode.ThemeIcon('error');
        default: return new vscode.ThemeIcon('circle-outline');
    }
}
//# sourceMappingURL=ActionTreeDataProvider.js.map
