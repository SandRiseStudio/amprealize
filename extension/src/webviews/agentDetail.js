/**
 * Agent Detail Webview JavaScript
 * Handles UI interactions for the Agent Detail panel
 */

(function() {
    'use strict';

    // Get VS Code API
    const vscode = acquireVsCodeApi();

    // Handle messages from the extension
    window.addEventListener('message', function(event) {
        const message = event.data;
        switch (message.type) {
            case 'agentUpdated':
                showSuccess('Agent data refreshed');
                break;
            case 'error':
                showError(message.message);
                break;
        }
    });

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

    // Handle keyboard shortcuts
    document.addEventListener('keydown', function(event) {
        // Ctrl/Cmd + R to refresh
        if ((event.ctrlKey || event.metaKey) && event.key === 'r') {
            event.preventDefault();
            vscode.postMessage({ type: 'refreshAgent' });
        }
        // Ctrl/Cmd + C when agent ID is focused
        if ((event.ctrlKey || event.metaKey) && event.key === 'c') {
            const selection = window.getSelection();
            if (selection && selection.toString() === '') {
                // No text selected, check if we should copy agent ID
                const agentIdEl = document.getElementById('agentId');
                if (agentIdEl && document.activeElement === agentIdEl) {
                    event.preventDefault();
                    vscode.postMessage({ type: 'copyAgentId' });
                }
            }
        }
    });

    // Initialize any dynamic behaviors
    function init() {
        // Add click handler for agent ID to select all
        const agentIdEl = document.getElementById('agentId');
        if (agentIdEl) {
            agentIdEl.addEventListener('click', function() {
                const range = document.createRange();
                range.selectNodeContents(this);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            });
        }

        // Add hover effects for version items
        const versionItems = document.querySelectorAll('.version-item');
        versionItems.forEach(item => {
            item.setAttribute('tabindex', '0');
            item.addEventListener('keydown', function(event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    this.click();
                }
            });
        });

        // Make tags clickable for filtering (future feature)
        const tags = document.querySelectorAll('.tag');
        tags.forEach(tag => {
            tag.style.cursor = 'default';
            tag.title = tag.textContent;
        });
    }

    // Run initialization when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
