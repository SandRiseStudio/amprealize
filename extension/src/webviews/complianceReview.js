/**
 * Compliance Review Webview JavaScript
 * Handles UI interactions for the Compliance Review panel
 */

(function() {
    'use strict';

    // Global state
    let currentStepId = null;
    let checklistData = null;

    // Handle messages from the extension
    window.addEventListener('message', function(event) {
        const message = event.data;
        switch (message.type) {
            case 'stepRecorded':
                // Update step status in UI
                updateStepStatus(message.stepId, message.status);
                showSuccess(`Step marked as ${message.status}`);
                break;
            case 'checklistValidated':
                showSuccess('Checklist validation completed');
                break;
            case 'error':
                showError(message.message);
                break;
        }
    });

    // Update step status in the UI
    function updateStepStatus(stepId, status) {
        const stepElement = document.querySelector(`[data-step-id="${stepId}"]`);
        if (stepElement) {
            const statusBadge = stepElement.querySelector('.status-badge');
            if (statusBadge) {
                statusBadge.textContent = status;
                statusBadge.className = `status-badge status-${status.toLowerCase()}`;
            }
        }
    }

    // Show success message
    function showSuccess(message) {
        showMessage(message, 'success');
    }

    // Show error message
    function showError(message) {
        showMessage(message, 'error');
    }

    // Show message to user
    function showMessage(message, type) {
        // Create message element
        const messageEl = document.createElement('div');
        messageEl.className = `message message-${type}`;
        messageEl.textContent = message;

        // Add to page
        document.body.appendChild(messageEl);

        // Remove after 3 seconds
        setTimeout(() => {
            messageEl.remove();
        }, 3000);
    }

    // Record a step completion
    function recordStep(stepId, status, evidence, comments) {
        vscode.postMessage({
            type: 'recordStep',
            stepId: stepId,
            status: status,
            evidence: evidence,
            comments: comments
        });
    }

    // Add a comment
    function addComment(stepId, comment) {
        if (!comment.trim()) {
            showError('Comment cannot be empty');
            return;
        }

        vscode.postMessage({
            type: 'addComment',
            stepId: stepId,
            comment: comment.trim()
        });

        // Clear the comment form if this is a global comment
        if (!stepId) {
            const textarea = document.getElementById('newComment');
            if (textarea) {
                textarea.value = '';
            }
        }
    }

    // Validate checklist
    function validateChecklist(notes) {
        vscode.postMessage({
            type: 'validateChecklist',
            notes: notes
        });
    }

    // Export checklist
    function exportChecklist() {
        vscode.postMessage({
            type: 'exportChecklist'
        });
    }

    // Refresh checklist
    function refreshChecklist() {
        vscode.postMessage({
            type: 'refreshChecklist'
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize);
    } else {
        initialize();
    }

    function initialize() {
        console.log('Compliance Review panel initialized');

        // Set up event listeners
        setupEventListeners();
    }

    function setupEventListeners() {
        // Add global comment form
        const commentForm = document.querySelector('.comment-form');
        if (commentForm) {
            const textarea = commentForm.querySelector('textarea');
            const button = commentForm.querySelector('button');

            if (textarea && button) {
                button.addEventListener('click', function() {
                    const comment = textarea.value;
                    addComment(null, comment);
                });

                // Handle Enter key
                textarea.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                        e.preventDefault();
                        const comment = textarea.value;
                        addComment(null, comment);
                    }
                });
            }
        }

        // Step items click handling
        const stepItems = document.querySelectorAll('.step-item');
        stepItems.forEach(item => {
            item.addEventListener('click', function() {
                const stepId = this.getAttribute('data-step-id');
                if (stepId) {
                    openStepModal(stepId);
                }
            });
        });

        // Add keyboard shortcuts
        document.addEventListener('keydown', function(e) {
            // Ctrl/Cmd + R to refresh
            if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                e.preventDefault();
                refreshChecklist();
            }

            // Ctrl/Cmd + E to export
            if ((e.ctrlKey || e.metaKey) && e.key === 'e') {
                e.preventDefault();
                exportChecklist();
            }
        });
    }

    // Modal functions
    window.openStepModal = function(stepId) {
        const modal = document.getElementById('stepModal');
        if (!modal || !checklistData) return;

        const step = checklistData.steps?.find(s => s.step_id === stepId);
        if (step) {
            const titleEl = document.getElementById('modalStepTitle');
            const contentEl = document.getElementById('modalStepContent');

            if (titleEl) {
                titleEl.textContent = step.title;
            }

            if (contentEl) {
                contentEl.innerHTML = `
                    <div class="step-details">
                        <p><strong>Step ID:</strong> ${step.step_id}</p>
                        <p><strong>Status:</strong> ${step.status}</p>
                        <p><strong>Checklist ID:</strong> ${step.checklist_id}</p>
                    </div>
                    <div class="step-actions">
                        <button onclick="window.recordStepAction('${stepId}', 'COMPLETED')" class="btn-success">Mark as Completed</button>
                        <button onclick="window.recordStepAction('${stepId}', 'BLOCKED')" class="btn-warning">Mark as Blocked</button>
                        <button onclick="window.recordStepAction('${stepId}', 'SKIPPED')" class="btn-info">Skip Step</button>
                    </div>
                    <div class="step-comments">
                        <h4>Comments (${step.comments?.length || 0})</h4>
                        <div class="comment-list">
                            ${(step.comments || []).map(comment => `
                                <div class="comment-item">
                                    <div class="comment-meta">
                                        <span class="comment-author">${comment.actor?.role || 'User'}</span>
                                        <span class="comment-time">${new Date(comment.created_at).toLocaleString()}</span>
                                    </div>
                                    <div class="comment-content">${comment.content}</div>
                                </div>
                            `).join('')}
                        </div>
                        <div class="add-comment-form">
                            <textarea id="stepComment_${stepId}" placeholder="Add a comment for this step..."></textarea>
                            <button onclick="window.addStepComment('${stepId}')">Add Comment</button>
                        </div>
                    </div>
                `;
            }

            modal.style.display = 'block';
            currentStepId = stepId;
        }
    };

    window.closeStepModal = function() {
        const modal = document.getElementById('stepModal');
        if (modal) {
            modal.style.display = 'none';
            currentStepId = null;
        }
    };

    window.recordStepAction = function(stepId, status) {
        const evidenceTextarea = document.getElementById('stepEvidence');
        const commentTextarea = document.getElementById(`stepComment_${stepId}`);

        const evidence = evidenceTextarea ? evidenceTextarea.value : '';
        const comments = commentTextarea ? commentTextarea.value : '';

        recordStep(stepId, status, evidence, comments);
        closeStepModal();
    };

    window.addStepComment = function(stepId) {
        const textarea = document.getElementById(`stepComment_${stepId}`);
        if (textarea) {
            addComment(stepId, textarea.value);
            textarea.value = '';
        }
    };

    // Global functions for HTML onclick handlers
    window.addGlobalComment = function() {
        const textarea = document.getElementById('newComment');
        if (textarea) {
            addComment(null, textarea.value);
        }
    };

    window.validateChecklist = function() {
        const notes = prompt('Add validation notes (optional):');
        validateChecklist(notes);
    };

    // Close modal when clicking outside
    window.onclick = function(event) {
        const modal = document.getElementById('stepModal');
        if (event.target === modal) {
            closeStepModal();
        }
    };

    // Store checklist data for modal access
    window.setChecklistData = function(data) {
        checklistData = data;
    };

})();
