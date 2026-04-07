"use strict";
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
exports.WorkflowTreeDataProvider = void 0;
const vscode = __importStar(require("vscode"));
class WorkflowTreeDataProvider {
    constructor(client) {
        this.client = client;
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
        this.workflows = [];
        this.loadWorkflows();
    }
    refresh() {
        this.searchQuery = undefined;
        this.loadWorkflows();
    }
    async search(query) {
        this.searchQuery = query;
        await this.loadWorkflows();
    }
    async loadWorkflows() {
        try {
            if (this.searchQuery) {
                // Filter workflows by name/description containing search query
                const allWorkflows = await this.client.listWorkflowTemplates();
                this.workflows = allWorkflows.filter(w => w.name.toLowerCase().includes(this.searchQuery.toLowerCase()) ||
                    (w.description && w.description.toLowerCase().includes(this.searchQuery.toLowerCase())));
            }
            else {
                this.workflows = await this.client.listWorkflowTemplates();
            }
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to load workflows: ${error}`);
            this.workflows = [];
        }
        finally {
            this._onDidChangeTreeData.fire();
        }
    }
    getTreeItem(element) {
        return element;
    }
    async getChildren(element) {
        if (!element) {
            // Root level: show role groups
            if (this.searchQuery) {
                // In search mode, show flat list of matching workflows
                if (this.workflows.length === 0) {
                    return [new MessageTreeItem('No workflow templates match this search')];
                }
                return this.workflows.map(w => new WorkflowTreeItem(w, vscode.TreeItemCollapsibleState.None));
            }
            else {
                // Group by role
                if (this.workflows.length === 0) {
                    return [new MessageTreeItem('No workflow templates found yet', 'Run "amprealize workflow create-template" to seed your handbook.')];
                }
                return [
                    new RoleTreeItem('Strategist', 'strategist'),
                    new RoleTreeItem('Teacher', 'teacher'),
                    new RoleTreeItem('Student', 'student')
                ];
            }
        }
        else if (element instanceof RoleTreeItem) {
            // Show workflows for this role
            const roleWorkflows = this.workflows.filter(w => this.getTemplateRole(w) === element.role);
            if (roleWorkflows.length === 0) {
                return [new MessageTreeItem(`No templates for the ${element.label} role yet`)];
            }
            return roleWorkflows.map(w => new WorkflowTreeItem(w, vscode.TreeItemCollapsibleState.None));
        }
        return [];
    }
    getTemplateRole(template) {
        return (template.role_focus || template.role || '').toLowerCase();
    }
}
exports.WorkflowTreeDataProvider = WorkflowTreeDataProvider;
class RoleTreeItem extends vscode.TreeItem {
    constructor(label, role) {
        super(label, vscode.TreeItemCollapsibleState.Collapsed);
        this.label = label;
        this.role = role;
        this.contextValue = 'role';
        // Set role-specific icons
        switch (role) {
            case 'strategist':
                this.iconPath = new vscode.ThemeIcon('graph');
                break;
            case 'teacher':
                this.iconPath = new vscode.ThemeIcon('mortar-board');
                break;
            case 'student':
                this.iconPath = new vscode.ThemeIcon('check');
                break;
        }
    }
}
class WorkflowTreeItem extends vscode.TreeItem {
    constructor(workflow, collapsibleState) {
        super(workflow.name, collapsibleState);
        this.workflow = workflow;
        this.collapsibleState = collapsibleState;
        this.tooltip = workflow.description || workflow.name;
        this.description = `${workflow.steps.length} steps`;
        this.contextValue = 'workflow';
        this.iconPath = new vscode.ThemeIcon('symbol-event');
        // Command to create workflow from template
        this.command = {
            command: 'amprealize.createWorkflow',
            title: 'Create Workflow',
            arguments: [this.workflow]
        };
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
//# sourceMappingURL=WorkflowTreeDataProvider.js.map
