/**
 * GitHub App Callback Page
 *
 * Handles the redirect from GitHub after app installation.
 * Shows a loading state while the backend processes the callback,
 * then redirects to the project settings page.
 *
 * Following:
 * - behavior_design_api_contract (Student)
 * - COLLAB_SAAS_REQUIREMENTS.md: fast, floaty, animated
 */

import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { razeLog } from '../telemetry/raze';
import './GitHubAppCallbackPage.css';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CallbackStatus = 'processing' | 'success' | 'error';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GitHubAppCallbackPage(): React.JSX.Element {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<CallbackStatus>('processing');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const processCallback = async () => {
      const installationId = searchParams.get('installation_id');
      const setupAction = searchParams.get('setup_action') || 'install';

      // Check for GitHub error parameters
      const error = searchParams.get('error');
      const errorDescription = searchParams.get('error_description');

      if (error) {
        await razeLog('ERROR', 'GitHub App callback error', {
          error,
          error_description: errorDescription,
        });
        setErrorMessage(errorDescription || error || 'GitHub returned an error');
        setStatus('error');
        return;
      }

      if (!installationId) {
        await razeLog('ERROR', 'GitHub App callback missing installation_id');
        setErrorMessage('Missing installation ID from GitHub');
        setStatus('error');
        return;
      }

      await razeLog('INFO', 'Processing GitHub App callback', {
        installation_id: installationId,
        setup_action: setupAction,
      });

      // The backend handles the actual callback via redirect
      // This page is just a loading state in case JavaScript needs to process anything
      // In most cases, the user is redirected directly by the backend

      // If we're here with an installation_id but no state, the user might have
      // navigated here manually - redirect to home
      const state = searchParams.get('state');
      if (!state) {
        await razeLog('WARN', 'GitHub App callback missing state - redirecting to home');
        setStatus('success');
        setTimeout(() => navigate('/'), 1500);
        return;
      }

      // Backend should have processed and redirected, but if we're still here,
      // show success and redirect after a brief delay
      setStatus('success');
      await razeLog('INFO', 'GitHub App callback processed', {
        installation_id: installationId,
        setup_action: setupAction,
      });

      // Redirect to home after showing success (backend should have redirected with proper URL)
      setTimeout(() => navigate('/'), 2000);
    };

    void processCallback();
  }, [searchParams, navigate]);

  return (
    <div className="github-callback-page">
      <div className="github-callback-card">
        {status === 'processing' && (
          <>
            <div className="callback-spinner" />
            <h1 className="callback-title">Connecting GitHub App...</h1>
            <p className="callback-description">
              Please wait while we complete the connection.
            </p>
          </>
        )}

        {status === 'success' && (
          <>
            <div className="callback-success-icon">✓</div>
            <h1 className="callback-title">GitHub App Connected!</h1>
            <p className="callback-description">
              Redirecting you back to your project...
            </p>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="callback-error-icon">✕</div>
            <h1 className="callback-title">Connection Failed</h1>
            <p className="callback-description">
              {errorMessage || 'Something went wrong connecting to GitHub.'}
            </p>
            <button
              type="button"
              className="callback-retry-button"
              onClick={() => navigate('/')}
            >
              Return to Dashboard
            </button>
          </>
        )}
      </div>
    </div>
  );
}
