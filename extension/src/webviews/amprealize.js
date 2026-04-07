(function() {
    const vscode = acquireVsCodeApi();

    // State
    let blueprints = [];
    let selectedBlueprint = null;
    let runStatus = null;

    // Elements
    const blueprintSelect = document.getElementById('blueprint-select');
    const refreshBtn = document.getElementById('refresh-btn');
    const planBtn = document.getElementById('plan-btn');
    const applyBtn = document.getElementById('apply-btn');
    const destroyBtn = document.getElementById('destroy-btn');
    const statusContainer = document.getElementById('status-container');
    const dagContainer = document.getElementById('dag-container');
    const logsContainer = document.getElementById('logs-container');

    // Event Listeners
    refreshBtn.addEventListener('click', () => {
        vscode.postMessage({ command: 'refresh' });
    });

    blueprintSelect.addEventListener('change', (e) => {
        const blueprint = e.target.value;
        if (blueprint) {
            vscode.postMessage({ command: 'selectBlueprint', blueprint });
            selectedBlueprint = blueprint;
            updateButtons();
        }
    });

    planBtn.addEventListener('click', () => {
        if (selectedBlueprint) {
            vscode.postMessage({ command: 'plan' });
            setLoading(true, 'Planning...');
        }
    });

    applyBtn.addEventListener('click', () => {
        if (selectedBlueprint) {
            vscode.postMessage({ command: 'apply' });
            setLoading(true, 'Applying...');
        }
    });

    destroyBtn.addEventListener('click', () => {
        if (selectedBlueprint) {
            vscode.postMessage({ command: 'destroy' });
        }
    });

    // Message Handler
    window.addEventListener('message', event => {
        const message = event.data;

        switch (message.type) {
            case 'updateBlueprints':
                updateBlueprints(message.blueprints);
                break;
            case 'planningStarted':
                setLoading(true, 'Planning...');
                break;
            case 'planningComplete':
                setLoading(false);
                showPlanResult(message.result);
                break;
            case 'applyStarted':
                setLoading(true, 'Starting Apply...');
                break;
            case 'statusUpdate':
                setLoading(false);
                updateStatus(message.status);
                break;
        }
    });

    // Helper Functions
    function updateBlueprints(items) {
        blueprints = items;
        blueprintSelect.innerHTML = '<option value="">Select a blueprint...</option>';

        items.forEach(bp => {
            const option = document.createElement('option');
            option.value = bp;
            option.textContent = bp;
            if (selectedBlueprint === bp) {
                option.selected = true;
            }
            blueprintSelect.appendChild(option);
        });

        updateButtons();
    }

    function updateButtons() {
        const hasSelection = !!blueprintSelect.value;
        planBtn.disabled = !hasSelection;
        applyBtn.disabled = !hasSelection;
        destroyBtn.disabled = !hasSelection;
    }

    function setLoading(isLoading, text) {
        if (isLoading) {
            statusContainer.innerHTML = `<div class="loading">${text || 'Loading...'}</div>`;
        } else {
            statusContainer.innerHTML = '';
        }
    }

    function showPlanResult(result) {
        if (!result) return;

        let html = '<h3>Plan Result</h3>';

        if (result.valid) {
            html += '<div class="success">Plan is valid</div>';
        } else {
            html += '<div class="error">Plan is invalid</div>';
        }

        if (result.steps && result.steps.length > 0) {
            html += '<ul>';
            result.steps.forEach(step => {
                html += `<li>${step.name} (${step.type})</li>`;
            });
            html += '</ul>';
        }

        statusContainer.innerHTML = html;
        renderDag(result.steps);
    }

    function updateStatus(status) {
        if (!status) return;

        let html = `<h3>Run Status: ${status.status}</h3>`;
        html += `<div class="progress-bar"><div class="progress-fill" style="width: ${status.progress}%"></div></div>`;

        if (status.steps) {
            html += '<ul class="step-list">';
            status.steps.forEach(step => {
                let icon = '⚪';
                if (step.status === 'completed') icon = '✅';
                else if (step.status === 'running') icon = '🔄';
                else if (step.status === 'failed') icon = '❌';

                html += `<li>${icon} ${step.id}</li>`;
            });
            html += '</ul>';
        }

        statusContainer.innerHTML = html;
    }

    function renderDag(steps) {
        // Simple placeholder for DAG rendering
        // In a real implementation, we might use a library like cytoscape.js or d3
        if (!steps) {
            dagContainer.innerHTML = '';
            return;
        }

        dagContainer.innerHTML = '<div class="dag-placeholder">DAG Visualization Placeholder</div>';
    }

    // Initial state
    updateButtons();

})();
