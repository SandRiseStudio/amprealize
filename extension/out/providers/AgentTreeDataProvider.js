"use strict";
/**
 * Agent Tree Data Provider
 *
 * Provides hierarchical view of agents grouped by status and role alignment:
 * - Status grouping: Draft, Published, Deprecated
 * - Role grouping: Strategist, Teacher, Student, Multi
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
exports.AgentTreeDataProvider = void 0;
const vscode = __importStar(require("vscode"));
const actorAvatar_1 = require("../utils/actorAvatar");
class AgentTreeDataProvider {
    constructor(client) {
        this.client = client;
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
        this.agents = [];
        this.searchQuery = null;
        this.groupBy = 'status';
        this.statusFilter = null;
        this.visibilityFilter = null;
        this.loadAgents('sidebar.initial_load');
    }
    dispose() {
        this._onDidChangeTreeData.dispose();
    }
    refresh() {
        this.searchQuery = null;
        this.loadAgents('sidebar.refresh');
    }
    setGroupBy(groupBy) {
        this.groupBy = groupBy;
        this._onDidChangeTreeData.fire();
    }
    setStatusFilter(status) {
        this.statusFilter = status;
        this.loadAgents('sidebar.filter');
    }
    setVisibilityFilter(visibility) {
        this.visibilityFilter = visibility;
        this.loadAgents('sidebar.filter');
    }
    async search(query) {
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
        }
        catch (error) {
            vscode.window.showErrorMessage(`Search failed: ${error}`);
        }
    }
    async loadAgents(source) {
        try {
            this.agents = await this.client.listAgents({
                status: this.statusFilter ?? undefined,
                visibility: this.visibilityFilter ?? undefined,
            }, { source });
            this._onDidChangeTreeData.fire();
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to load agents: ${error}`);
        }
    }
    getTreeItem(element) {
        return element;
    }
    async getChildren(element) {
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
                    new MessageTreeItem('No agents found yet', 'Create one with "amprealize agent-registry create" or bootstrap from existing playbooks.')
                ];
            }
            // Show groups based on groupBy setting
            if (this.groupBy === 'status') {
                return [
                    new StatusGroupTreeItem('PUBLISHED', 'Published', 'Active agents ready for use'),
                    new StatusGroupTreeItem('DRAFT', 'Drafts', 'Work-in-progress agents'),
                    new StatusGroupTreeItem('DEPRECATED', 'Deprecated', 'Archived agents')
                ];
            }
            else {
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
    getAgentCount() {
        return this.agents.length;
    }
    getAgentsByStatus(status) {
        return this.agents.filter(a => a.status === status);
    }
    getAgentsByRole(role) {
        return this.agents.filter(a => a.role_alignment === role);
    }
}
exports.AgentTreeDataProvider = AgentTreeDataProvider;
class StatusGroupTreeItem extends vscode.TreeItem {
    constructor(status, label, description) {
        super(label, vscode.TreeItemCollapsibleState.Collapsed);
        this.status = status;
        this.description = description;
        this.contextValue = 'agentStatusGroup';
        this.iconPath = new vscode.ThemeIcon(status === 'PUBLISHED' ? 'verified' :
            status === 'DRAFT' ? 'edit' :
                'archive');
    }
}
class RoleGroupTreeItem extends vscode.TreeItem {
    constructor(role, label, description) {
        super(label, vscode.TreeItemCollapsibleState.Collapsed);
        this.role = role;
        this.description = description;
        this.contextValue = 'agentRoleGroup';
        this.iconPath = new vscode.ThemeIcon(role === 'STRATEGIST' ? 'graph' :
            role === 'TEACHER' ? 'mortar-board' :
                role === 'STUDENT' ? 'check' :
                    'symbol-misc');
    }
}
class AgentTreeItem extends vscode.TreeItem {
    constructor(agent, collapsibleState) {
        super(agent.name, collapsibleState);
        this.agent = agent;
        this.collapsibleState = collapsibleState;
        this.description = agent.description;
        this.tooltip = this.buildTooltip();
        this.contextValue = this.getContextValue();
        // Icon based on status and role
        this.iconPath = vscode.Uri.parse((0, actorAvatar_1.buildActorAvatarDataUri)((0, actorAvatar_1.createActorViewModel)({
            id: agent.agent_id,
            kind: 'agent',
            displayName: agent.name,
            subtitle: agent.role_alignment,
            presenceState: agent.status === 'DEPRECATED' ? 'offline' : agent.status === 'DRAFT' ? 'paused' : 'available',
        }), 32));
        // Command to view details on click
        this.command = {
            command: 'amprealize.viewAgentDetail',
            title: 'View Agent Details',
            arguments: [this]
        };
    }
    buildTooltip() {
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
    getContextValue() {
        // Context value for menu contributions
        const parts = ['agent'];
        parts.push(this.agent.status.toLowerCase());
        parts.push(this.agent.visibility.toLowerCase());
        return parts.join('.');
    }
}
class MessageTreeItem extends vscode.TreeItem {
    constructor(label, tooltip) {
        super(label, vscode.TreeItemCollapsibleState.None);
        this.iconPath = new vscode.ThemeIcon('info');
        if (tooltip) {
            this.tooltip = tooltip;
        }
        this.contextValue = 'info';
    }
}
//# sourceMappingURL=AgentTreeDataProvider.js.map
