/**
 * Device Flow Authentication Webview JavaScript
 * Handles the OAuth2 device flow UI interactions
 */

(function() {
    'use strict';

    // Handle messages from the extension
    window.addEventListener('message', function(event) {
        const message = event.data;
        switch (message.type) {
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
        const statusEl = document.getElementById('authStatus');
        if (statusEl) {
            statusEl.innerHTML = `<div class="message message-${type}">${message}</div>`;
        }
    }

    // Verify that user has completed authentication
    window.verifyCode = function() {
        const verifyBtn = document.getElementById('verifyBtn');
        if (verifyBtn) {
            verifyBtn.textContent = 'Verifying...';
            verifyBtn.disabled = true;
        }

        // Send message to extension to verify the code
        vscode.postMessage({
            type: 'verifyCode',
            userCode: 'VERIFIED' // User confirms they completed the flow
        });
    };

    // Cancel authentication
    window.cancelAuth = function() {
        vscode.postMessage({
            type: 'cancel'
        });
    };

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize);
    } else {
        initialize();
    }

    function initialize() {
        console.log('Device Flow authentication UI initialized');

        // Focus on the verify button for accessibility
        const verifyBtn = document.getElementById('verifyBtn');
        if (verifyBtn) {
            verifyBtn.focus();
        }
    }

})();
