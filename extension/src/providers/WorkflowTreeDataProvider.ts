import * as vscode from 'vscode';
import { AmprealizeClient, WorkflowTemplate } from '../client/AmprealizeClient';

type WorkflowNode = WorkflowTreeItem | RoleTreeItem | MessageTreeItem;

export class WorkflowTreeDataProvider implements vscode.TreeDataProvider<WorkflowNode> {
    private _onDidChangeTreeData: vscode.EventEmitter<WorkflowNode | undefined | null | void> = new vscode.EventEmitter<WorkflowNode | undefined | null | void>();
    readonly onDidChangeTreeData: vscode.Event<WorkflowNode | undefined | null | void> = this._onDidChangeTreeData.event;

    private workflows: WorkflowTemplate[] = [];
    private searchQuery: string | undefined;

    constructor(private client: AmprealizeClient) {
        this.loadWorkflows();
    }

    refresh(): void {
        this.searchQuery = undefined;
        this.loadWorkflows();
    }

    async search(query: string): Promise<void> {
        this.searchQuery = query;
        await this.loadWorkflows();
    }

    private async loadWorkflows(): Promise<void> {
        try {
            if (this.searchQuery) {
                // Filter workflows by name/description containing search query
                const allWorkflows = await this.client.listWorkflowTemplates();
                this.workflows = allWorkflows.filter(w =>
                    w.name.toLowerCase().includes(this.searchQuery!.toLowerCase()) ||
                    (w.description && w.description.toLowerCase().includes(this.searchQuery!.toLowerCase()))
                );
            } else {
                this.workflows = await this.client.listWorkflowTemplates();
            }
        } catch (error) {
            vscode.window.showErrorMessage(`Failed to load workflows: ${error}`);
            this.workflows = [];
        } finally {
            this._onDidChangeTreeData.fire();
        }
    }

    getTreeItem(element: WorkflowNode): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: WorkflowNode): Promise<WorkflowNode[]> {
        if (!element) {
            // Root level: show role groups
            if (this.searchQuery) {
                // In search mode, show flat list of matching workflows
                if (this.workflows.length === 0) {
                    return [new MessageTreeItem('No workflow templates match this search')];
                }
                return this.workflows.map(w => new WorkflowTreeItem(w, vscode.TreeItemCollapsibleState.None));
            } else {
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
        } else if (element instanceof RoleTreeItem) {
            // Show workflows for this role
            const roleWorkflows = this.workflows.filter(w => this.getTemplateRole(w) === element.role);
            if (roleWorkflows.length === 0) {
                return [new MessageTreeItem(`No templates for the ${element.label} role yet`)];
            }
            return roleWorkflows.map(w => new WorkflowTreeItem(w, vscode.TreeItemCollapsibleState.None));
        }
        return [];
    }

    private getTemplateRole(template: WorkflowTemplate): string {
        return (template.role_focus || template.role || '').toLowerCase();
    }
}

class RoleTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly role: string
    ) {
        super(label, vscode.TreeItemCollapsibleState.Collapsed);
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
    constructor(
        public readonly workflow: WorkflowTemplate,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState
    ) {
        super(workflow.name, collapsibleState);

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
    constructor(label: string, tooltip?: string) {
        super(label, vscode.TreeItemCollapsibleState.None);
        this.iconPath = new vscode.ThemeIcon('info');
        if (tooltip) {
            this.tooltip = tooltip;
        }
        this.contextValue = 'info';
    }
}
