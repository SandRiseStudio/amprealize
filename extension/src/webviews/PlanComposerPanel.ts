import * as vscode from 'vscode';
import {
    AmprealizeClient,
    WorkflowTemplate,
    Behavior,
    BCIRetrieveOptions,
    BCIRetrieveResponse,
    BCIValidateResponse,
    BCIPrependedBehavior,
} from '../client/AmprealizeClient';

export class PlanComposerPanel {
    public static currentPanel: PlanComposerPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private _disposables: vscode.Disposable[] = [];
    private workflows: WorkflowTemplate[] = [];
    private behaviors: Behavior[] = [];

    private constructor(
        panel: vscode.WebviewPanel,
        private client: AmprealizeClient,
        private templateId?: string
    ) {
        this._panel = panel;
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        this._panel.webview.onDidReceiveMessage(
            message => this.handleMessage(message),
            null,
            this._disposables
        );
        this.initialize();
    }

    public static async createOrShow(extensionUri: vscode.Uri, client: AmprealizeClient, template?: any): Promise<void> {
        const templateId = template?.template_id || template;
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;

        // If panel exists, reveal it
        if (PlanComposerPanel.currentPanel) {
            PlanComposerPanel.currentPanel._panel.reveal(column);
            if (templateId) {
                PlanComposerPanel.currentPanel.templateId = templateId;
                PlanComposerPanel.currentPanel.initialize();
            }
            return;
        }

        // Create new panel
        const panel = vscode.window.createWebviewPanel(
            'planComposer',
            'Plan Composer',
            column || vscode.ViewColumn.One,
            {
                enableScripts: true,
                retainContextWhenHidden: true
            }
        );

        PlanComposerPanel.currentPanel = new PlanComposerPanel(panel, client, templateId);
        void client.emitTelemetry('plan_composer_opened', {
            source: 'plan_composer.open',
            template_id: templateId || null
        }).catch(() => undefined);
    }

    private async initialize(): Promise<void> {
        this._panel.webview.html = '<p>Loading composer...</p>';

        try {
            // Load workflows and behaviors
            this.workflows = await this.client.listWorkflowTemplates(undefined, { source: 'plan_composer.load_workflows' });
            this.behaviors = await this.client.listBehaviors({}, { source: 'plan_composer.load_behaviors' });

            this._panel.webview.html = this.getWebviewContent();
            this.emitTelemetry('plan_composer_loaded', {
                template_id: this.templateId || null,
                workflow_template_count: this.workflows.length,
                behavior_count: this.behaviors.length
            });
        } catch (error) {
            this._panel.webview.html = `<p style="color: red;">Error loading composer: ${error}</p>`;
            this.emitTelemetry('plan_composer_load_failed', {
                template_id: this.templateId || null,
                error: error instanceof Error ? error.message : String(error)
            });
        }
    }

    private getWebviewContent(): string {
        const workflowOptions = this.workflows.map(w =>
            `<option value="${w.template_id}" ${w.template_id === this.templateId ? 'selected' : ''}>
                ${this.escapeHtml(w.name)} (${w.role_focus || w.role})
            </option>`
        ).join('');

        const behaviorOptions = this.behaviors.map(b =>
            `<option value="${b.behavior_id}">${this.escapeHtml(b.name)}</option>`
        ).join('');

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Plan Composer</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            padding: 20px;
            color: var(--vscode-foreground);
            background-color: var(--vscode-editor-background);
        }
        h1, h2 { color: var(--vscode-titleBar-activeForeground); }
        .form-group {
            margin: 20px 0;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
        }
        select, input, textarea {
            width: 100%;
            padding: 8px;
            background-color: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 4px;
            font-family: var(--vscode-font-family);
        }
        textarea {
            min-height: 100px;
            font-family: var(--vscode-editor-font-family);
        }
        button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 10px 20px;
            cursor: pointer;
            border-radius: 4px;
            margin: 5px 5px 5px 0;
            font-size: 14px;
        }
        button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        button.secondary {
            background-color: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        button.secondary:hover {
            background-color: var(--vscode-button-secondaryHoverBackground);
        }
        .workflow-info {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            padding: 15px;
            border-radius: 4px;
            margin: 15px 0;
        }
        .step-list {
            list-style: none;
            padding: 0;
        }
        .step-item {
            background-color: var(--vscode-list-hoverBackground);
            padding: 10px;
            margin: 8px 0;
            border-radius: 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .step-number {
            font-weight: bold;
            margin-right: 10px;
        }
        .behavior-injection {
            background-color: var(--vscode-textBlockQuote-background);
            border-left: 4px solid var(--vscode-textBlockQuote-border);
            padding: 15px;
            margin: 15px 0;
        }
        .info-text {
            color: var(--vscode-descriptionForeground);
            font-size: 0.9em;
            margin-top: 5px;
        }
        .button-row {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 10px;
            margin-top: 10px;
        }
        .inline-input {
            width: 140px;
        }
        .behavior-suggestions {
            background-color: var(--vscode-editor-selectionHighlightBackground, rgba(255,255,255,0.05));
            padding: 15px;
            border-radius: 4px;
            margin-top: 15px;
        }
        .suggestion-item {
            align-items: flex-start;
            gap: 12px;
        }
        .suggestion-body {
            flex: 1;
        }
        .suggestion-score {
            color: var(--vscode-descriptionForeground);
            font-size: 0.9em;
            margin-left: 8px;
        }
        .badge {
            display: inline-block;
            background-color: var(--vscode-inputOption-activeBackground, rgba(255,255,255,0.1));
            color: var(--vscode-inputOption-activeForeground, var(--vscode-foreground));
            border-radius: 999px;
            padding: 2px 8px;
            font-size: 0.75em;
            margin-left: 8px;
        }
        .validation-result {
            margin-top: 10px;
        }
        .validation-result.success {
            color: var(--vscode-terminal-ansiGreen, #3fb950);
        }
        .validation-result.error {
            color: var(--vscode-errorForeground, #f85149);
        }
        .validation-details {
            background-color: var(--vscode-editorCodeLens-foreground, rgba(255,255,255,0.05));
            padding: 12px;
            border-radius: 4px;
            margin-top: 12px;
        }
        .validation-details ul {
            margin: 8px 0 0 16px;
        }
        .loading {
            font-style: italic;
            color: var(--vscode-descriptionForeground);
        }
    </style>
</head>
<body>
    <h1>Plan Composer</h1>
    <p class="info-text">Create and execute behavior-conditioned workflows</p>

    <div class="form-group">
        <label for="workflow-select">Select Workflow Template</label>
        <select id="workflow-select" onchange="onWorkflowChange()">
            <option value="">-- Select a template --</option>
            ${workflowOptions}
        </select>
    </div>

    <div id="workflow-details" style="display: none;">
        <div class="workflow-info">
            <h2 id="workflow-name"></h2>
            <p id="workflow-description"></p>
            <p><strong>Role:</strong> <span id="workflow-role"></span></p>
        </div>

        <div class="form-group">
            <label for="context-input">Context / Variables (JSON)</label>
            <textarea id="context-input" placeholder='{"variable": "value"}'>{}</textarea>
            <p class="info-text">Optional: Provide context variables for the workflow</p>
        </div>

        <div class="behavior-injection">
            <h2>Behavior Injection</h2>
            <div class="form-group">
                <label for="behavior-select">Add Behavior to Workflow</label>
                <select id="behavior-select">
                    <option value="">-- Select a behavior --</option>
                    ${behaviorOptions}
                </select>
                <button onclick="addBehavior()" class="secondary">+ Add Behavior</button>
            </div>

            <div class="form-group">
                <label for="task-query">Behavior Suggestions</label>
                <textarea id="task-query" placeholder="Describe the task or plan objective to retrieve behaviors"></textarea>
                <div class="button-row">
                    <div>
                        <span class="info-text">Max behaviors</span>
                        <input type="number" id="suggest-topk" class="inline-input" value="5" min="1" max="20" />
                    </div>
                    <button onclick="suggestBehaviors()">🔍 Suggest Behaviors</button>
                    <button onclick="clearSuggestions()" class="secondary">Clear</button>
                </div>
                <p class="info-text">Amprealize will retrieve relevant behaviors using the BCI retriever.</p>
            </div>

            <div id="suggestions-container" class="behavior-suggestions" style="display: none;">
                <h3>Suggested Behaviors</h3>
                <ul id="suggestions-list" class="step-list">
                    <li class="info-text">Run a suggestion to see recommended behaviors.</li>
                </ul>
            </div>

            <div id="selected-behaviors">
                <h3>Selected Behaviors</h3>
                <ul id="behavior-list" class="step-list">
                    <li class="info-text">No behaviors selected yet</li>
                </ul>
            </div>
        </div>

        <div class="form-group">
            <h2>Plan Draft & Citation Validation</h2>
            <textarea id="plan-output" placeholder="Paste your plan or reasoning here. Reference behaviors like (behavior_example)."></textarea>
            <div class="button-row">
                <button onclick="validateCitations()" class="secondary">✅ Validate Citations</button>
            </div>
            <div id="validation-summary" class="validation-result info-text">No validation run yet.</div>
            <div id="validation-details" class="validation-details" style="display: none;"></div>
        </div>

        <div class="form-group">
            <h2>Workflow Steps</h2>
            <ul id="step-list" class="step-list"></ul>
        </div>

        <div style="margin-top: 30px;">
            <button onclick="runWorkflow()">▶ Run Workflow</button>
            <button onclick="saveWorkflow()" class="secondary">💾 Save as New Template</button>
        </div>
    </div>

    <script>
        const vscode = acquireVsCodeApi();
        const workflows = ${JSON.stringify(this.workflows)};
        const selectedBehaviors = [];
        let suggestionResults = [];
    let pendingSuggestionId = null;
    let pendingValidationId = null;

        function escapeHtml(text) {
            if (typeof text !== 'string') {
                return '';
            }
            return text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function truncate(text, maxLength = 220) {
            if (!text || text.length <= maxLength) {
                return text || '';
            }
            return text.substring(0, maxLength - 1) + '…';
        }

        window.addEventListener('message', (event) => {
            const message = event.data;
            switch (message.command) {
                case 'bciRetrieveResult':
                    if (message.requestId !== pendingSuggestionId) {
                        return;
                    }
                    pendingSuggestionId = null;
                    suggestionResults = message.response?.results || [];
                    renderSuggestions();
                    break;
                case 'bciRetrieveError':
                    if (message.requestId !== pendingSuggestionId) {
                        return;
                    }
                    pendingSuggestionId = null;
                    renderSuggestions(message.error || 'No behaviors were returned.');
                    break;
                case 'bciValidateResult':
                    if (message.requestId !== pendingValidationId) {
                        return;
                    }
                    pendingValidationId = null;
                    renderValidationResult(message.response);
                    break;
                case 'bciValidateError':
                    if (message.requestId !== pendingValidationId) {
                        return;
                    }
                    pendingValidationId = null;
                    renderValidationError(message.error || 'Validation failed.');
                    break;
            }
        });

        function onWorkflowChange() {
            const select = document.getElementById('workflow-select');
            const workflowId = select.value;

            if (!workflowId) {
                document.getElementById('workflow-details').style.display = 'none';
                return;
            }

            const workflow = workflows.find(w => w.template_id === workflowId);
            if (!workflow) {
                return;
            }

            document.getElementById('workflow-name').textContent = workflow.name;
            document.getElementById('workflow-description').textContent = workflow.description || '';
            document.getElementById('workflow-role').textContent = workflow.role_focus || workflow.role;

            const stepList = document.getElementById('step-list');
            stepList.innerHTML = (workflow.steps || []).map((step, i) => {
                const stepLabel = escapeHtml(step.action || step.instruction || 'Untitled step');
                return (
                    '<li class="step-item">'
                    + '<span><span class="step-number">Step ' + (i + 1) + ':</span> ' + stepLabel + '</span>'
                    + '</li>'
                );
            }).join('');

            const taskField = document.getElementById('task-query');
            if (taskField && !taskField.value.trim()) {
                taskField.value = workflow.description || workflow.name;
            }

            document.getElementById('workflow-details').style.display = 'block';
        }

        function addBehavior() {
            const select = document.getElementById('behavior-select');
            const behaviorId = select.value;
            const behaviorName = select.options[select.selectedIndex]?.text || '';

            if (!behaviorId) {
                vscode.postMessage({ command: 'showWarning', text: 'Please select a behavior' });
                return;
            }

            if (selectedBehaviors.find(b => b.id === behaviorId)) {
                vscode.postMessage({ command: 'showWarning', text: 'Behavior already added' });
                return;
            }

            selectedBehaviors.push({ id: behaviorId, name: behaviorName, source: 'manual' });
            updateBehaviorList();
            vscode.postMessage({
                command: 'behaviorSelectionAdded',
                behaviorId,
                behaviorName,
                source: 'manual',
            });
        }

        function addSuggestedBehavior(behaviorId) {
            if (selectedBehaviors.find(b => b.id === behaviorId)) {
                vscode.postMessage({ command: 'showWarning', text: 'Behavior already added' });
                return;
            }
            const match = suggestionResults.find(item => item.behavior_id === behaviorId);
            if (!match) {
                vscode.postMessage({ command: 'showWarning', text: 'Suggestion not found' });
                return;
            }
            selectedBehaviors.push({ id: match.behavior_id, name: match.name, source: 'suggestion' });
            updateBehaviorList();
            vscode.postMessage({
                command: 'behaviorSelectionAdded',
                behaviorId: match.behavior_id,
                behaviorName: match.name,
                source: 'suggestion',
                score: match.score,
            });
        }

        function removeBehavior(behaviorId) {
            const index = selectedBehaviors.findIndex(b => b.id === behaviorId);
            if (index > -1) {
                const removed = selectedBehaviors.splice(index, 1)[0];
                updateBehaviorList();
                vscode.postMessage({
                    command: 'behaviorSelectionRemoved',
                    behaviorId,
                    behaviorName: removed?.name || '',
                    source: removed?.source || 'manual',
                });
            }
        }

        function updateBehaviorList() {
            const list = document.getElementById('behavior-list');
            if (selectedBehaviors.length === 0) {
                list.innerHTML = '<li class="info-text">No behaviors selected yet</li>';
            } else {
                list.innerHTML = selectedBehaviors.map(b => {
                    const behaviorName = escapeHtml(b.name);
                    return (
                        '<li class="step-item">'
                        + '<span>' + behaviorName + '</span>'
                        + '<button onclick="removeBehavior(' + "'" + b.id + "'" + ')" class="secondary">Remove</button>'
                        + '</li>'
                    );
                }).join('');
            }
        }

        function suggestBehaviors() {
            const queryInput = document.getElementById('task-query');
            const query = queryInput.value.trim();
            if (!query) {
                vscode.postMessage({ command: 'showWarning', text: 'Provide a task or query before requesting suggestions.' });
                return;
            }
            const workflowId = document.getElementById('workflow-select').value;
            const workflow = workflows.find(w => w.template_id === workflowId);
            const topKInput = document.getElementById('suggest-topk');
            let topK = parseInt(topKInput.value, 10);
            if (Number.isNaN(topK) || topK <= 0) {
                topK = 5;
            }
            topK = Math.min(Math.max(topK, 1), 20);
            pendingSuggestionId = 'suggest-' + Date.now();
            setSuggestionsLoading();
            vscode.postMessage({
                command: 'bciRetrieve',
                requestId: pendingSuggestionId,
                query,
                topK,
                roleFocus: workflow?.role_focus || workflow?.role || null,
                includeMetadata: true,
            });
        }

        function clearSuggestions() {
            pendingSuggestionId = null;
            if (suggestionResults.length) {
                vscode.postMessage({
                    command: 'bciSuggestionsCleared',
                    count: suggestionResults.length,
                });
            }
            suggestionResults = [];
            const container = document.getElementById('suggestions-container');
            const list = document.getElementById('suggestions-list');
            list.innerHTML = '<li class="info-text">Run a suggestion to see recommended behaviors.</li>';
            container.style.display = 'none';
        }

        function setSuggestionsLoading() {
            const container = document.getElementById('suggestions-container');
            const list = document.getElementById('suggestions-list');
            container.style.display = 'block';
            list.innerHTML = '<li class="loading">Fetching behavior suggestions...</li>';
        }

        function renderSuggestions(errorMessage) {
            const container = document.getElementById('suggestions-container');
            const list = document.getElementById('suggestions-list');
            container.style.display = 'block';
            if (errorMessage) {
                list.innerHTML = '<li class="info-text">' + escapeHtml(errorMessage) + '</li>';
                return;
            }
            if (!suggestionResults.length) {
                list.innerHTML = '<li class="info-text">No behaviors matched the query.</li>';
                return;
            }
            list.innerHTML = suggestionResults.map(item => {
                const score = typeof item.score === 'number' ? item.score.toFixed(3) : '—';
                const role = item.role_focus || 'MULTI_ROLE';
                const tags = (item.tags || []).join(', ');
                const description = item.description
                    ? '<div class="info-text">' + escapeHtml(truncate(item.description)) + '</div>'
                    : '';
                const instruction = item.instruction
                    ? '<div class="info-text">Instruction: ' + escapeHtml(truncate(item.instruction)) + '</div>'
                    : '';
                return [
                    '<li class="step-item suggestion-item">',
                    '<div class="suggestion-body">',
                    '<div><strong>' + escapeHtml(item.name) + '</strong><span class="badge">' + escapeHtml(role) + '</span><span class="suggestion-score">score ' + score + '</span></div>',
                    description,
                    instruction,
                    '<div class="info-text">Tags: ' + escapeHtml(tags || '—') + '</div>',
                    '</div>',
                    '<button onclick="addSuggestedBehavior(' + "'" + item.behavior_id + "'" + ')">Add</button>',
                    '</li>'
                ].join('');
            }).join('');
        }

        function validateCitations() {
            const planOutput = document.getElementById('plan-output').value.trim();
            if (!planOutput) {
                vscode.postMessage({ command: 'showWarning', text: 'Add plan text before running validation.' });
                return;
            }
            if (selectedBehaviors.length === 0) {
                vscode.postMessage({ command: 'showWarning', text: 'Select at least one behavior before validation.' });
                return;
            }
            pendingValidationId = 'validate-' + Date.now();
            setValidationLoading();
            vscode.postMessage({
                command: 'bciValidate',
                requestId: pendingValidationId,
                outputText: planOutput,
                prepended: selectedBehaviors.map(b => ({ behavior_name: b.name, behavior_id: b.id })),
            });
        }

        function setValidationLoading() {
            const summary = document.getElementById('validation-summary');
            summary.textContent = 'Validating citations...';
            summary.className = 'validation-result loading';
            const details = document.getElementById('validation-details');
            details.style.display = 'none';
            details.innerHTML = '';
        }

        function renderValidationResult(result) {
            const summary = document.getElementById('validation-summary');
            const details = document.getElementById('validation-details');
            const complianceRate = typeof result.compliance_rate === 'number'
                ? Math.round(result.compliance_rate * 1000) / 10
                : 0;
            const validCount = (result.valid_citations || []).length;
            summary.textContent = 'Compliance rate ' + complianceRate + '% (' + validCount + '/' + selectedBehaviors.length + ' behaviors cited)';
            summary.className = 'validation-result ' + (result.is_compliant ? 'success' : 'error');

            const sections = [];
            if (Array.isArray(result.missing_behaviors) && result.missing_behaviors.length) {
                const missingList = result.missing_behaviors
                    .map(name => '<li>' + escapeHtml(name) + '</li>')
                    .join('');
                sections.push('<div><strong>Missing behaviors</strong><ul>' + missingList + '</ul></div>');
            }
            if (Array.isArray(result.invalid_citations) && result.invalid_citations.length) {
                const invalidList = result.invalid_citations
                    .map(citation => {
                        const label = citation.behavior_name
                            ? '<span class="badge">' + escapeHtml(citation.behavior_name) + '</span>'
                            : '';
                        return '<li>' + escapeHtml(citation.text || '') + ' ' + label + '</li>';
                    })
                    .join('');
                sections.push('<div><strong>Invalid citations</strong><ul>' + invalidList + '</ul></div>');
            }
            if (Array.isArray(result.warnings) && result.warnings.length) {
                const warningList = result.warnings
                    .map(warning => '<li>' + escapeHtml(warning) + '</li>')
                    .join('');
                sections.push('<div><strong>Warnings</strong><ul>' + warningList + '</ul></div>');
            }

            if (sections.length) {
                details.innerHTML = sections.join('');
                details.style.display = 'block';
            } else {
                details.style.display = 'none';
                details.innerHTML = '';
            }
        }

        function renderValidationError(errorMessage) {
            const summary = document.getElementById('validation-summary');
            const details = document.getElementById('validation-details');
            summary.textContent = errorMessage;
            summary.className = 'validation-result error';
            details.style.display = 'none';
            details.innerHTML = '';
        }

        function runWorkflow() {
            const workflowId = document.getElementById('workflow-select').value;
            const contextInput = document.getElementById('context-input').value;

            if (!workflowId) {
                vscode.postMessage({ command: 'showWarning', text: 'Please select a workflow template' });
                return;
            }

            let context = {};
            try {
                context = JSON.parse(contextInput);
            } catch (e) {
                vscode.postMessage({ command: 'showWarning', text: 'Invalid JSON in context field' });
                return;
            }

            if (selectedBehaviors.length > 0) {
                context.behaviors = selectedBehaviors.map(b => b.id);
            }

            vscode.postMessage({
                command: 'runWorkflow',
                workflowId: workflowId,
                context: context,
                behaviors: selectedBehaviors.map(b => b.id),
                behaviorDetails: selectedBehaviors.map(b => ({ id: b.id, name: b.name })),
            });
        }

        function saveWorkflow() {
            vscode.postMessage({ command: 'showInfo', text: 'Save feature coming soon!' });
        }

        window.addEventListener('load', () => {
            const select = document.getElementById('workflow-select');
            if (select.value) {
                onWorkflowChange();
            }
        });
    </script>
</body>
</html>`;
    }

    private async handleMessage(message: any): Promise<void> {
        if (message.command === 'behaviorSelectionAdded') {
            const behaviorId = typeof message.behaviorId === 'string' ? message.behaviorId : null;
            const behaviorName = typeof message.behaviorName === 'string' ? message.behaviorName : null;
            const source = typeof message.source === 'string' ? message.source : 'unknown';
            const score = typeof message.score === 'number' ? message.score : undefined;
            this.emitTelemetry('plan_composer_behavior_added', {
                behavior_id: behaviorId,
                behavior_name: behaviorName,
                source,
                score
            });
            return;
        }

        if (message.command === 'behaviorSelectionRemoved') {
            const behaviorId = typeof message.behaviorId === 'string' ? message.behaviorId : null;
            const behaviorName = typeof message.behaviorName === 'string' ? message.behaviorName : null;
            const source = typeof message.source === 'string' ? message.source : 'unknown';
            this.emitTelemetry('plan_composer_behavior_removed', {
                behavior_id: behaviorId,
                behavior_name: behaviorName,
                source
            });
            return;
        }

        if (message.command === 'bciSuggestionsCleared') {
            const count = typeof message.count === 'number' ? message.count : 0;
            this.emitTelemetry('plan_composer_suggestions_cleared', {
                count
            });
            return;
        }

        switch (message.command) {
            case 'runWorkflow':
                try {
                    const behaviors: string[] = Array.isArray(message.behaviors) ? message.behaviors : [];
                    const behaviorDetails: Array<{ id: string; name: string }> = Array.isArray(message.behaviorDetails)
                        ? message.behaviorDetails
                        : [];
                    const contextKeys = message.context ? Object.keys(message.context) : [];
                    this.emitTelemetry('plan_created', {
                        template_id: message.workflowId,
                        behavior_ids: behaviors,
                        behavior_names: behaviorDetails.map(item => item.name),
                        selected_behavior_count: behaviors.length,
                        context_keys: contextKeys,
                        checklist_snapshot: message.context?.checklist ?? null
                    });
                    const result = await this.client.runWorkflow(
                        message.workflowId,
                        message.context,
                        { source: 'plan_composer.run' }
                    );
                    vscode.window.showInformationMessage(
                        `Workflow started! Run ID: ${result.run_id}`,
                        'View Status'
                    ).then(selection => {
                        if (selection === 'View Status') {
                            vscode.commands.executeCommand('amprealize.viewWorkflowStatus', result.run_id);
                        }
                    });
                } catch (error) {
                    vscode.window.showErrorMessage(`Failed to run workflow: ${error}`);
                    this.emitTelemetry('plan_composer_run_failed', {
                        template_id: message.workflowId,
                        error: error instanceof Error ? error.message : String(error)
                    });
                }
                break;
            case 'showInfo':
                vscode.window.showInformationMessage(message.text);
                break;
            case 'showWarning':
                vscode.window.showWarningMessage(message.text);
                break;
            case 'bciRetrieve':
                await this.handleBCIRetrieve(message);
                break;
            case 'bciValidate':
                await this.handleBCIValidate(message);
                break;
        }
    }

    private async handleBCIRetrieve(message: any): Promise<void> {
        const requestId = typeof message.requestId === 'string' ? message.requestId : undefined;
        if (!requestId) {
            return;
        }

        const query = typeof message.query === 'string' ? message.query.trim() : '';
        if (!query) {
            this._panel.webview.postMessage({ command: 'bciRetrieveError', requestId, error: 'Query is required.' });
            return;
        }

        const options: BCIRetrieveOptions = {
            query,
            topK: typeof message.topK === 'number' ? message.topK : undefined,
            strategy: typeof message.strategy === 'string' ? message.strategy : undefined,
            roleFocus: typeof message.roleFocus === 'string' ? message.roleFocus : undefined,
            includeMetadata: Boolean(message.includeMetadata),
        };

        if (Array.isArray(message.tags)) {
            options.tags = message.tags.filter((tag: unknown): tag is string => typeof tag === 'string');
        }
        if (typeof message.embeddingWeight === 'number') {
            options.embeddingWeight = message.embeddingWeight;
        }
        if (typeof message.keywordWeight === 'number') {
            options.keywordWeight = message.keywordWeight;
        }

        try {
            const response: BCIRetrieveResponse = await this.client.bciRetrieve(options);
            this.emitTelemetry('plan_composer_bci_retrieved', {
                query_length: query.length,
                result_count: Array.isArray(response.results) ? response.results.length : 0,
                role_focus: options.roleFocus ?? null,
                top_k: options.topK ?? 5,
            });
            this._panel.webview.postMessage({ command: 'bciRetrieveResult', requestId, response });
        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error);
            this.emitTelemetry('plan_composer_bci_retrieve_failed', {
                query_length: query.length,
                role_focus: options.roleFocus ?? null,
                error: errorMessage,
            });
            this._panel.webview.postMessage({ command: 'bciRetrieveError', requestId, error: errorMessage });
        }
    }

    private async handleBCIValidate(message: any): Promise<void> {
        const requestId = typeof message.requestId === 'string' ? message.requestId : undefined;
        if (!requestId) {
            return;
        }

        const outputText = typeof message.outputText === 'string' ? message.outputText : '';
        if (!outputText.trim()) {
            this._panel.webview.postMessage({ command: 'bciValidateError', requestId, error: 'Plan text is required for validation.' });
            return;
        }

        const prependedPayload = Array.isArray(message.prepended) ? message.prepended : [];
        const prepended: BCIPrependedBehavior[] = prependedPayload
            .map((item: any) => {
                const behaviorName = typeof item.behavior_name === 'string'
                    ? item.behavior_name
                    : typeof item.name === 'string'
                        ? item.name
                        : '';
                if (!behaviorName) {
                    return undefined;
                }
                const mapped: BCIPrependedBehavior = { behavior_name: behaviorName };
                if (typeof item.behavior_id === 'string') {
                    mapped.behavior_id = item.behavior_id;
                }
                if (typeof item.version === 'string') {
                    mapped.version = item.version;
                }
                return mapped;
            })
            .filter((item: BCIPrependedBehavior | undefined): item is BCIPrependedBehavior => Boolean(item));

        if (prepended.length === 0) {
            this._panel.webview.postMessage({ command: 'bciValidateError', requestId, error: 'At least one behavior is required for validation.' });
            return;
        }

        const minimumCitations = typeof message.minimumCitations === 'number' ? message.minimumCitations : undefined;
        const allowUnlisted = Boolean(message.allowUnlisted);

        try {
            const response: BCIValidateResponse = await this.client.bciValidateCitations({
                outputText,
                prepended,
                minimumCitations,
                allowUnlisted,
            });
            this.emitTelemetry('plan_composer_bci_validate_succeeded', {
                prepended_count: prepended.length,
                total_citations: response.total_citations,
                valid_citations: Array.isArray(response.valid_citations) ? response.valid_citations.length : 0,
                compliance_rate: response.compliance_rate,
                is_compliant: response.is_compliant,
            });
            this._panel.webview.postMessage({ command: 'bciValidateResult', requestId, response });
        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error);
            this.emitTelemetry('plan_composer_bci_validate_failed', {
                prepended_count: prepended.length,
                error: errorMessage,
            });
            this._panel.webview.postMessage({ command: 'bciValidateError', requestId, error: errorMessage });
        }
    }

    private emitTelemetry(eventType: string, payload: Record<string, unknown>): void {
        void this.client.emitTelemetry(eventType, payload).catch(() => undefined);
    }

    private escapeHtml(text: string): string {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    public dispose(): void {
        PlanComposerPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const disposable = this._disposables.pop();
            if (disposable) {
                disposable.dispose();
            }
        }
    }
}
