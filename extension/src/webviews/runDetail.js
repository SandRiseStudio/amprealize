/**
 * Run Detail Webview JavaScript
 * Handles UI interactions for the Run Detail panel
 */

(function() {
    'use strict';

    // Handle messages from the extension
    window.addEventListener('message', function(event) {
        const message = event.data;
        switch (message.type) {
            case 'runUpdated':
                // Update UI to reflect new run data
                console.log('Run data updated');
                break;
            case 'error':
                // Show error message
                showError(message.message);
                break;
        }
    });

    // Copy run ID to clipboard
    function copyRunId() {
        const runIdElement = document.getElementById('runId');
        if (runIdElement) {
            const runId = runIdElement.textContent;
            navigator.clipboard.writeText(runId).then(() => {
                showSuccess('Run ID copied to clipboard');
            }).catch(err => {
                console.error('Failed to copy:', err);
                showError('Failed to copy run ID');
            });
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

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize);
    } else {
        initialize();
    }

    function initialize() {
        console.log('Run Detail panel initialized');

        // Set up event listeners
        setupEventListeners();
    }

    function setupEventListeners() {
        // Copy ID button
        const copyBtn = document.querySelector('.copy-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', copyRunId);
        }

        // Add keyboard shortcuts
        document.addEventListener('keydown', function(e) {
            // Ctrl/Cmd + C to copy run ID when focused on run ID
            if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
                const selectedText = window.getSelection().toString();
                if (selectedText.includes('run-')) {
                    copyRunId();
                }
            }
        });
    }

    // Export functions for use in HTML onclick handlers
    window.copyRunId = copyRunId;

})();
