/**
 * OAuthCallback Component
 *
 * Handles OAuth callback redirects from social login providers (GitHub, Google).
 * Exchanges the authorization code for tokens and completes the login flow.
 *
 * Following:
 * - behavior_prototype_consent_ux (Teacher)
 * - behavior_lock_down_security_surface (Student)
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  LoaderCircle,
} from 'lucide-react';
import { useAuth } from '../auth';
import { AuthStage } from './auth/AuthStage';
import { parseOAuthState } from './auth/oauthState';
import { OAUTH_COMPLETE_MESSAGE_TYPE, PRODUCT_DISPLAY_NAME } from '../config/branding';
import './OAuthCallback.css';

type CallbackStatus = 'processing' | 'success' | 'error';

let processingPromise: Promise<void> | null = null;
let processingCode: string | null = null;

export function OAuthCallback() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { completeOAuthLogin, isAuthenticated, logout } = useAuth();

  const [status, setStatus] = useState<CallbackStatus>('processing');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const parsedState = useMemo(() => parseOAuthState(searchParams.get('state')), [searchParams]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    async function handleCallback() {
      const code = searchParams.get('code');
      const rawState = searchParams.get('state');
      const error = searchParams.get('error');
      const errorDescription = searchParams.get('error_description');
      const returnTo = parsedState?.returnTo ?? '/';
      const isPopup = Boolean(parsedState?.popup && window.opener && !window.opener.closed);

      if (error) {
        setStatus('error');
        setErrorMessage(errorDescription ?? `OAuth error: ${error}`);
        return;
      }

      if (!code) {
        if (isAuthenticated) {
          navigate(returnTo, { replace: true });
          return;
        }

        setStatus('error');
        setErrorMessage('Missing authorization code');
        return;
      }

      if (processingCode === code && processingPromise) {
        try {
          await processingPromise;
          if (!mountedRef.current) {
            return;
          }
          setStatus('success');
          window.setTimeout(() => {
            if (isPopup && window.opener && !window.opener.closed) {
              window.opener.postMessage({ type: OAUTH_COMPLETE_MESSAGE_TYPE, provider: parsedState?.provider ?? 'oauth' }, window.location.origin);
              window.close();
              return;
            }
            navigate(returnTo, { replace: true });
          }, isPopup ? 650 : 850);
        } catch (err) {
          if (mountedRef.current) {
            setStatus('error');
            setErrorMessage(err instanceof Error ? err.message : 'Authentication failed');
          }
        }
        return;
      }

      processingCode = code;

      const doExchange = async () => {
        try {
          await logout();
        } catch {
          // Ignore logout errors
        }

        await completeOAuthLogin(code, rawState ?? undefined);
      };

      processingPromise = doExchange();

      try {
        await processingPromise;
        if (!mountedRef.current) {
          return;
        }
        setStatus('success');
        window.setTimeout(() => {
          if (isPopup && window.opener && !window.opener.closed) {
            window.opener.postMessage({ type: OAUTH_COMPLETE_MESSAGE_TYPE, provider: parsedState?.provider ?? 'oauth' }, window.location.origin);
            window.close();
            return;
          }
          navigate(returnTo, { replace: true });
        }, isPopup ? 650 : 850);
      } catch (err) {
        if (mountedRef.current) {
          setStatus('error');
          setErrorMessage(err instanceof Error ? err.message : 'Failed to complete authentication');
        }
        throw err;
      } finally {
        processingPromise = null;
        processingCode = null;
      }
    }

    handleCallback().catch(() => {
      // The component state already captures the error path.
    });
  }, [searchParams, completeOAuthLogin, navigate, isAuthenticated, logout, parsedState]);

  return (
    <AuthStage
      panelEyebrow={
        status === 'processing'
          ? 'Completing sign in'
          : status === 'success'
            ? 'Success'
            : 'Authentication issue'
      }
      panelTitle={
        status === 'processing'
          ? 'Securing your session'
          : status === 'success'
            ? 'You are signed in'
            : 'We could not finish sign in'
      }
      panelSubtitle={
        status === 'processing'
          ? `Hold tight while ${PRODUCT_DISPLAY_NAME} validates your identity and prepares the web console.`
          : status === 'success'
            ? parsedState?.popup
              ? 'This sign-in window will close automatically.'
              : 'Taking you to your destination now.'
            : 'You can return to the login screen and try again. The rest of the console remains unchanged.'
      }
    >
      {status === 'processing' && (
        <div className="oauth-callback-state oauth-callback-state-processing" aria-live="polite">
          <div className="oauth-callback-icon-shell" aria-hidden="true">
            <LoaderCircle className="oauth-callback-spinner" size={28} strokeWidth={2} />
          </div>
          <div className="oauth-callback-copy">
            <h2>Verifying your credentials</h2>
            <p>We are finishing the provider handoff and preparing your {PRODUCT_DISPLAY_NAME} session.</p>
          </div>
        </div>
      )}

      {status === 'success' && (
        <div className="oauth-callback-state oauth-callback-state-success" aria-live="polite">
          <div className="oauth-callback-icon-shell oauth-callback-icon-shell-success" aria-hidden="true">
            <CheckCircle2 size={28} strokeWidth={2} />
          </div>
          <div className="oauth-callback-copy">
            <h2>Sign-in successful</h2>
            <p>
              {parsedState?.popup
                ? `You can return to the main ${PRODUCT_DISPLAY_NAME} window. This popup will close in a moment.`
                : `${PRODUCT_DISPLAY_NAME} confirmed your account and will continue in just a moment.`}
            </p>
          </div>
        </div>
      )}

      {status === 'error' && (
        <div className="oauth-callback-state oauth-callback-state-error" role="alert">
          <div className="oauth-callback-icon-shell oauth-callback-icon-shell-error" aria-hidden="true">
            <AlertCircle size={28} strokeWidth={2} />
          </div>
          <div className="oauth-callback-copy">
            <h2>Authentication did not complete</h2>
            <p>{errorMessage}</p>
          </div>
          <button
            type="button"
            className="oauth-callback-retry"
            onClick={() => navigate('/login', { replace: true })}
          >
            <ArrowLeft size={16} strokeWidth={2} aria-hidden="true" />
            <span>Return to sign in</span>
          </button>
        </div>
      )}
    </AuthStage>
  );
}

export default OAuthCallback;
