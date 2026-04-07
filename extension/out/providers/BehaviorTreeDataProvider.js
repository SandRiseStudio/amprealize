"use strict";
/**
 * Behavior Tree Data Provider
 *
 * Provides hierarchical view of behaviors grouped by role:
 * - Strategist (planning and decomposition)
 * - Teacher (explanation and guidance)
 * - Student (execution and reporting)
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
exports.BehaviorTreeDataProvider = void 0;
const vscode = __importStar(require("vscode"));
class BehaviorTreeDataProvider {
    constructor(client) {
        this.client = client;
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
        this.behaviors = [];
        this.searchQuery = null;
        this.loadBehaviors('sidebar.initial_load');
    }
    refresh() {
        this.searchQuery = null;
        this.loadBehaviors('sidebar.refresh');
    }
    async search(query) {
        this.searchQuery = query;
        try {
            this.behaviors = await this.client.searchBehaviors(query, undefined, {
                source: 'sidebar.search',
                query
            });
            this._onDidChangeTreeData.fire();
        }
        catch (error) {
            vscode.window.showErrorMessage(`Search failed: ${error}`);
        }
    }
    async loadBehaviors(source) {
        try {
            this.behaviors = await this.client.listBehaviors(undefined, { source });
            this._onDidChangeTreeData.fire();
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to load behaviors: ${error}`);
        }
    }
    getTreeItem(element) {
        return element;
    }
    async getChildren(element) {
        if (!element) {
            if (this.searchQuery) {
                if (this.behaviors.length === 0) {
                    return [new MessageTreeItem('No behaviors match this search')];
                }
                return this.behaviors.map(b => new BehaviorTreeItem(b, vscode.TreeItemCollapsibleState.None));
            }
            if (this.behaviors.length === 0) {
                return [
                    new MessageTreeItem('No behaviors found yet', 'Create one with "amprealize behaviors create" or import from the MCP catalog.')
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
exports.BehaviorTreeDataProvider = BehaviorTreeDataProvider;
class RoleTreeItem extends vscode.TreeItem {
    constructor(role, label, description) {
        super(label, vscode.TreeItemCollapsibleState.Collapsed);
        this.role = role;
        this.description = description;
        this.contextValue = 'role';
        this.iconPath = new vscode.ThemeIcon(role === 'STRATEGIST' ? 'graph' :
            role === 'TEACHER' ? 'mortar-board' :
                'check');
    }
}
class BehaviorTreeItem extends vscode.TreeItem {
    constructor(behavior, collapsibleState) {
        super(behavior.name, collapsibleState);
        this.behavior = behavior;
        this.collapsibleState = collapsibleState;
        const version = behavior.versions?.[0];
        this.description = behavior.description;
        this.tooltip = `${behavior.name}\n\n${behavior.description}\n\nTags: ${behavior.tags.join(', ')}\nStatus: ${version?.status || 'Unknown'}`;
        this.contextValue = 'behavior';
        // Icon based on status
        this.iconPath = new vscode.ThemeIcon(version?.status === 'APPROVED' ? 'verified' :
            version?.status === 'IN_REVIEW' ? 'eye' :
                'file');
        // Command to view details on click
        this.command = {
            command: 'amprealize.viewBehaviorDetail',
            title: 'View Behavior Details',
            arguments: [this]
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
//# sourceMappingURL=BehaviorTreeDataProvider.js.map
