"use strict";
/**
 * Compliance Review Panel
 *
 * Webview panel for managing compliance checklists and validation:
 * - Interactive compliance checklist interface
 * - Step-by-step validation workflow
 * - Evidence attachment and documentation
 * - Approval/rejection workflow with comments
 * - Progress tracking and status management
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
exports.ComplianceReviewPanel = void 0;
const vscode = __importStar(require("vscode"));
const actorAvatar_1 = require("../utils/actorAvatar");
class ComplianceReviewPanel {
    constructor(panel, extensionUri, client) {
        this._disposables = [];
        this._checklist = null;
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._client = client;
        // Set the webview's initial html content
        this._update();
        // Listen for when the panel is disposed
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        // Handle messages from the webview
        this._panel.webview.onDidReceiveMessage(async (message) => {
            switch (message.type) {
                case 'recordStep':
                    await this._recordStep(message.stepId, message.status, message.evidence, message.comments);
                    return;
                case 'validateChecklist':
                    await this._validateChecklist(message.notes);
                    return;
                case 'addComment':
                    await this._addComment(message.stepId, message.comment);
                    return;
                case 'attachEvidence':
                    await this._attachEvidence(message.stepId, message.evidenceType);
                    return;
                case 'exportChecklist':
                    await this._exportChecklist();
                    return;
                case 'refreshChecklist':
                    await this._refreshChecklist();
                    return;
            }
        }, null, this._disposables);
    }
    static createOrShow(extensionUri, client, checklist) {
        const column = vscode.ViewColumn.One;
        if (ComplianceReviewPanel.currentPanel) {
            ComplianceReviewPanel.currentPanel._panel.reveal(column);
            ComplianceReviewPanel.currentPanel._checklist = checklist;
            ComplianceReviewPanel.currentPanel._update();
            return;
        }
        const panel = vscode.window.createWebviewPanel(ComplianceReviewPanel.viewType, `Compliance Review: ${checklist.title}`, column || vscode.ViewColumn.One, {
            enableScripts: true,
            localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'out'), vscode.Uri.joinPath(extensionUri, 'webview-ui/build')]
        });
        ComplianceReviewPanel.currentPanel = new ComplianceReviewPanel(panel, extensionUri, client);
        ComplianceReviewPanel.currentPanel._checklist = checklist;
    }
    static revive(panel, extensionUri, client) {
        ComplianceReviewPanel.currentPanel = new ComplianceReviewPanel(panel, extensionUri, client);
    }
    _update() {
        const webview = this._panel.webview;
        if (!this._checklist) {
            this._panel.webview.html = this._getHtmlForWebview(webview, null);
            return;
        }
        this._panel.webview.html = this._getHtmlForWebview(webview, this._checklist);
    }
    async _recordStep(stepId, status, evidence, comments) {
        if (!this._checklist)
            return;
        try {
            await this._client.recordComplianceStep({
                checklist_id: this._checklist.checklist_id,
                title: stepId,
                status: status,
                evidence: evidence ? { notes: evidence } : undefined,
                actor: { id: 'ide-user', role: 'STUDENT', surface: 'MCP' } // IDE-agnostic via MCP
            });
            // Refresh the checklist
            await this._refreshChecklist();
            this._panel.webview.postMessage({ type: 'stepRecorded', stepId, status });
        }
        catch (error) {
            console.error('Failed to record step:', error);
            this._panel.webview.postMessage({ type: 'error', message: `Failed to record step: ${error}` });
        }
    }
    async _validateChecklist(notes) {
        if (!this._checklist)
            return;
        try {
            await this._client.validateComplianceChecklist(this._checklist.checklist_id, {
                id: 'vscode-user',
                role: 'STUDENT',
                surface: 'VSCODE'
            });
            await this._refreshChecklist();
            this._panel.webview.postMessage({ type: 'checklistValidated' });
        }
        catch (error) {
            console.error('Failed to validate checklist:', error);
            this._panel.webview.postMessage({ type: 'error', message: `Failed to validate checklist: ${error}` });
        }
    }
    async _addComment(stepId, comment) {
        // TODO: Add createComplianceComment method to AmprealizeClient
        vscode.window.showInformationMessage(`Comment added: ${comment}`);
    }
    async _attachEvidence(stepId, evidenceType) {
        // TODO: Implement file selection and upload functionality
        vscode.window.showInformationMessage(`Evidence attachment for ${evidenceType} - feature coming soon`);
    }
    async _exportChecklist() {
        if (!this._checklist)
            return;
        try {
            const exportData = {
                title: this._checklist.title,
                category: this._checklist.compliance_category,
                status: this._checklist.status,
                progress: this._checklist.progress,
                createdAt: this._checklist.created_at,
                steps: this._checklist.steps,
                comments: this._checklist.steps?.flatMap(step => step.comments || []) || []
            };
            const jsonContent = JSON.stringify(exportData, null, 2);
            const document = await vscode.workspace.openTextDocument({
                content: jsonContent,
                language: 'json'
            });
            await vscode.window.showTextDocument(document);
            vscode.window.showInformationMessage(`Compliance checklist exported: ${this._checklist.title}`);
        }
        catch (error) {
            vscode.window.showErrorMessage(`Failed to export checklist: ${error}`);
        }
    }
    async _refreshChecklist() {
        if (!this._checklist)
            return;
        try {
            const updatedChecklist = await this._client.getComplianceChecklist(this._checklist.checklist_id);
            this._checklist = updatedChecklist;
            this._update();
        }
        catch (error) {
            console.error('Failed to refresh checklist:', error);
        }
    }
    _getHtmlForWebview(webview, checklist) {
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'webviews', 'complianceReview.js'));
        const styleResetUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'out', 'viewExplorer.css'));
        const styleMainUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'styles', 'ComplianceReviewPanel.css'));
        const nonce = getNonce();
        if (!checklist) {
            return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Compliance Review</title>
	<link href="${styleResetUri}" rel="stylesheet">
	<link href="${styleMainUri}" rel="stylesheet">
</head>
<body>
	<div class="container">
		<div class="no-checklist">
			<h2>No Compliance Checklist Selected</h2>
			<p>Select a compliance checklist from the Compliance Tracker to begin review.</p>
		</div>
	</div>
</body>
</html>`;
        }
        const completedSteps = checklist.steps?.filter(step => step.status === 'COMPLETED')?.length || 0;
        const totalSteps = checklist.steps?.length || 0;
        const progressPercentage = totalSteps > 0 ? Math.round((completedSteps / totalSteps) * 100) : 0;
        const actorAvatarHtml = (0, actorAvatar_1.buildActorAvatarHtml)((0, actorAvatar_1.createActorViewModel)({
            id: checklist.actor.id,
            kind: checklist.actor.role === 'STUDENT' || checklist.actor.role === 'TEACHER' || checklist.actor.role === 'STRATEGIST' ? 'human' : 'agent',
            displayName: checklist.actor.id,
            subtitle: checklist.actor.role,
            presenceState: checklist.status === 'APPROVED' ? 'finished_recently' : checklist.status === 'REJECTED' ? 'paused' : 'working',
        }), 44);
        return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Compliance Review: ${checklist.title}</title>
	<link href="${styleResetUri}" rel="stylesheet">
	<link href="${styleMainUri}" rel="stylesheet">
</head>
<body>
	<div class="container">
		<header class="compliance-header">
			<div class="compliance-title">
				<div style="display:flex;align-items:center;gap:12px;">
					${actorAvatarHtml}
					<div>
						<h1>${checklist.title}</h1>
						<div class="checklist-meta">
							<span class="category-badge">${checklist.compliance_category?.join(', ') || 'General'}</span>
							<span class="checklist-id">ID: ${checklist.checklist_id}</span>
						</div>
					</div>
				</div>
			</div>
			<div class="compliance-status">
				<span class="status-badge status-${checklist.status.toLowerCase()}">${checklist.status}</span>
				<div class="progress-bar">
					<div class="progress-fill" style="width: ${progressPercentage}%"></div>
					<span class="progress-text">${completedSteps}/${totalSteps} steps (${progressPercentage}%)</span>
				</div>
			</div>
		</header>

		<div class="compliance-actions">
			<button class="action-btn" onclick="vscode.postMessage({type: 'refreshChecklist'})">
				<i class="icon-refresh"></i> Refresh
			</button>
			<button class="action-btn" onclick="vscode.postMessage({type: 'exportChecklist'})">
				<i class="icon-export"></i> Export
			</button>
			<button class="action-btn validate-btn" onclick="validateChecklist()">
				<i class="icon-check"></i> Validate Checklist
			</button>
		</div>

		<div class="compliance-content">
			<div class="steps-section">
				<h2>Compliance Steps</h2>
				<div class="steps-list">
					${checklist.steps?.map(step => this._renderStepHTML(step)).join('') || '<p>No steps available</p>'}
				</div>
			</div>

			<div class="comments-section">
				<h2>Comments & Discussion</h2>
				<div class="comments-list">
					${checklist.steps?.flatMap(step => step.comments || []).map(comment => this._renderCommentHTML(comment)).join('') || '<p>No comments yet</p>'}
				</div>
				<div class="comment-form">
					<textarea id="newComment" placeholder="Add a comment..."></textarea>
					<button onclick="addGlobalComment()">Add Comment</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Step Detail Modal -->
	<div id="stepModal" class="modal" style="display: none;">
		<div class="modal-content">
			<span class="close" onclick="closeStepModal()">&times;</span>
			<h2 id="modalStepTitle"></h2>
			<div id="modalStepContent"></div>
		</div>
	</div>

	<script nonce="${nonce}" src="${scriptUri}">
		// Global functions for UI interactions
		function openStepModal(stepId) {
			const modal = document.getElementById('stepModal');
			const step = ${JSON.stringify(checklist.steps || [])}.find(s => s.step_id === stepId);
			if (step) {
				document.getElementById('modalStepTitle').textContent = step.title;
				document.getElementById('modalStepContent').innerHTML = \`
					<div class="step-description">Step: \${step.title}</div>
					<div class="step-actions">
						<button onclick="recordStep('\${step.step_id}', 'COMPLETED')">Mark as Completed</button>
						<button onclick="recordStep('\${step.step_id}', 'BLOCKED')">Mark as Blocked</button>
						<button onclick="recordStep('\${step.step_id}', 'SKIPPED')">Skip Step</button>
					</div>
				\`;
				modal.style.display = 'block';
			}
		}

		function closeStepModal() {
			document.getElementById('stepModal').style.display = 'none';
		}

		function recordStep(stepId, status, evidence, comments) {
			vscode.postMessage({type: 'recordStep', stepId, status, evidence, comments});
		}

		function addGlobalComment() {
			const textarea = document.getElementById('newComment');
			const comment = textarea.value.trim();
			if (comment) {
				vscode.postMessage({type: 'addComment', stepId: null, comment});
				textarea.value = '';
			}
		}

		function validateChecklist() {
			const notes = prompt('Add validation notes (optional):');
			vscode.postMessage({type: 'validateChecklist', notes});
		}

		// Close modal when clicking outside
		window.onclick = function(event) {
			const modal = document.getElementById('stepModal');
			if (event.target === modal) {
				closeStepModal();
			}
		}
	</script>
</body>
</html>`;
    }
    _renderStepHTML(step) {
        const statusClass = `status-${step.status.toLowerCase()}`;
        const evidenceCount = Object.keys(step.evidence || {}).length;
        const commentsCount = step.comments?.length || 0;
        return `
			<div class="step-item ${statusClass}" onclick="openStepModal('${step.step_id}')">
				<div class="step-header">
					<div class="step-title">
						<h3>${step.title}</h3>
						<span class="step-category">Step ${step.step_id}</span>
					</div>
					<div class="step-status">
						<span class="status-badge ${statusClass}">${step.status}</span>
					</div>
				</div>
				<div class="step-description">
					<p>Step: ${step.title}</p>
				</div>
				<div class="step-meta">
					<span class="step-evidence">
						<i class="icon-attachment"></i> ${evidenceCount} evidence items
					</span>
					<span class="step-comments">
						<i class="icon-comment"></i> ${commentsCount} comments
					</span>
					${step.completed_at ? `<span class="step-completed">Completed: ${new Date(step.completed_at).toLocaleDateString()}</span>` : ''}
				</div>
			</div>
		`;
    }
    _renderCommentHTML(comment) {
        return `
			<div class="comment-item">
				<div class="comment-header">
					<span class="comment-author">${comment.actor?.role || 'User'}</span>
					<span class="comment-time">${new Date(comment.created_at).toLocaleString()}</span>
				</div>
				<div class="comment-content">
					<p>${comment.content}</p>
				</div>
			</div>
		`;
    }
    dispose() {
        ComplianceReviewPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
}
exports.ComplianceReviewPanel = ComplianceReviewPanel;
ComplianceReviewPanel.viewType = 'amprealize.complianceReview';
function getNonce() {
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let text = '';
    for (let i = 0; i < 8; i++) {
        const index = Math.floor(Math.random() * possible.length);
        text += possible.charAt(index);
    }
    return text;
}
//# sourceMappingURL=ComplianceReviewPanel.js.map
