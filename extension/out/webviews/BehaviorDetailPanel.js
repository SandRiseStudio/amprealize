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
exports.BehaviorDetailPanel = void 0;
const vscode = __importStar(require("vscode"));
class BehaviorDetailPanel {
    constructor(panel, client, behaviorId) {
        this.client = client;
        this.behaviorId = behaviorId;
        this._disposables = [];
        this._panel = panel;
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        this._panel.webview.onDidReceiveMessage(message => this.handleMessage(message), null, this._disposables);
        this.update();
    }
    static async createOrShow(extensionUri, client, behavior) {
        const behaviorId = behavior.behavior_id || behavior;
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;
        // If panel exists, reveal it
        if (BehaviorDetailPanel.currentPanel) {
            BehaviorDetailPanel.currentPanel._panel.reveal(column);
            BehaviorDetailPanel.currentPanel.behaviorId = behaviorId;
            BehaviorDetailPanel.currentPanel.update();
            return;
        }
        // Create new panel
        const panel = vscode.window.createWebviewPanel('behaviorDetail', 'Behavior Detail', column || vscode.ViewColumn.One, {
            enableScripts: true,
            retainContextWhenHidden: true
        });
        BehaviorDetailPanel.currentPanel = new BehaviorDetailPanel(panel, client, behaviorId);
    }
    async update() {
        this._panel.webview.html = '<p>Loading behavior...</p>';
        try {
            const result = await this.client.getBehavior(this.behaviorId);
            const behavior = result.behavior;
            const versions = result.versions;
            this._panel.title = behavior.name;
            this._panel.webview.html = this.getWebviewContent(behavior, versions);
        }
        catch (error) {
            this._panel.webview.html = `<p style="color: red;">Error loading behavior: ${error}</p>`;
        }
    }
    getWebviewContent(behavior, versions) {
        const examplesHtml = behavior.examples && behavior.examples.length > 0
            ? `<h3>Examples</h3>
               <ul>${behavior.examples.map(ex => `<li><code>${this.escapeHtml(ex)}</code></li>`).join('')}</ul>`
            : '';
        const versionsHtml = versions.length > 1
            ? `<h3>Versions</h3>
               <ul>${versions.map(v => `<li>v${v.version} - ${v.status} (${v.updated_at})</li>`).join('')}</ul>`
            : '';
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${this.escapeHtml(behavior.name)}</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            padding: 20px;
            color: var(--vscode-foreground);
            background-color: var(--vscode-editor-background);
        }
        h1 { color: var(--vscode-titleBar-activeForeground); }
        h2, h3 { color: var(--vscode-foreground); margin-top: 20px; }
        .metadata {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            padding: 10px;
            border-radius: 4px;
            margin: 10px 0;
        }
        .metadata-item { margin: 5px 0; }
        .metadata-label { font-weight: bold; margin-right: 8px; }
        .instruction {
            background-color: var(--vscode-textBlockQuote-background);
            border-left: 4px solid var(--vscode-textBlockQuote-border);
            padding: 15px;
            margin: 15px 0;
            font-family: var(--vscode-editor-font-family);
        }
        code {
            background-color: var(--vscode-textCodeBlock-background);
            padding: 2px 6px;
            border-radius: 3px;
            font-family: var(--vscode-editor-font-family);
        }
        button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 8px 16px;
            cursor: pointer;
            border-radius: 4px;
            margin: 5px 5px 5px 0;
        }
        button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        ul { padding-left: 20px; }
        li { margin: 8px 0; }
    </style>
</head>
<body>
    <h1>${this.escapeHtml(behavior.name)}</h1>

    <div class="metadata">
        <div class="metadata-item">
            <span class="metadata-label">Status:</span>
            <span>${this.escapeHtml(behavior.status)}</span>
        </div>
        <div class="metadata-item">
            <span class="metadata-label">Version:</span>
            <span>${this.escapeHtml(behavior.version || 'N/A')}</span>
        </div>
        <div class="metadata-item">
            <span class="metadata-label">Role Focus:</span>
            <span>${this.escapeHtml(behavior.role_focus || 'N/A')}</span>
        </div>
        ${behavior.tags ? `
        <div class="metadata-item">
            <span class="metadata-label">Tags:</span>
            <span>${behavior.tags.map(t => this.escapeHtml(t)).join(', ')}</span>
        </div>
        ` : ''}
    </div>

    <h2>Instruction</h2>
    <div class="instruction">${this.escapeHtml(behavior.instruction || 'No instruction provided')}</div>

    ${examplesHtml}
    ${versionsHtml}

    <div style="margin-top: 30px;">
        <button onclick="insertBehavior()">Insert Reference at Cursor</button>
        <button onclick="copyInstruction()">Copy Instruction</button>
    </div>

    <script>
        const vscode = acquireVsCodeApi();

        function insertBehavior() {
            vscode.postMessage({
                command: 'insertBehavior',
                behaviorId: '${behavior.behavior_id}'
            });
        }

        function copyInstruction() {
            navigator.clipboard.writeText(\`${this.escapeHtml(behavior.instruction || '')}\`);
            vscode.postMessage({ command: 'showMessage', text: 'Instruction copied to clipboard' });
        }
    </script>
</body>
</html>`;
    }
    async handleMessage(message) {
        switch (message.command) {
            case 'insertBehavior': {
                const editor = vscode.window.activeTextEditor;
                if (editor) {
                    const result = await this.client.getBehavior(message.behaviorId);
                    const behavior = result.behavior;
                    const comment = `# behavior: ${behavior.name} (${behavior.behavior_id})`;
                    editor.edit(editBuilder => {
                        editBuilder.insert(editor.selection.active, comment + '\n');
                    });
                }
                break;
            }
            case 'showMessage':
                vscode.window.showInformationMessage(message.text);
                break;
        }
    }
    escapeHtml(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
    dispose() {
        BehaviorDetailPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const disposable = this._disposables.pop();
            if (disposable) {
                disposable.dispose();
            }
        }
    }
}
exports.BehaviorDetailPanel = BehaviorDetailPanel;
//# sourceMappingURL=BehaviorDetailPanel.js.map
