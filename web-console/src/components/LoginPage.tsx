/**
 * LoginPage Component
 *
 * Authentication page supporting both device flow (humans) and
 * client credentials (agents).
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 * - behavior_prototype_consent_ux (Teacher)
 * - COLLAB_SAAS_REQUIREMENTS.md animation specs
 */

import { useState, useEffect, useCallback, useRef, type FormEvent } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  Copy,
  KeyRound,
  LaptopMinimal,
  Link2,
  Sparkles,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { authStore, AUTH_STORE_INSTANCE_ID } from '../stores/authStore';
import { AuthStage } from './auth/AuthStage';
import { createOAuthState } from './auth/oauthState';
import {
  OAUTH_COMPLETE_MESSAGE_TYPE,
  OAUTH_COMPLETE_MESSAGE_TYPE_LEGACY,
  OAUTH_GOOGLE_POPUP_NAME,
  PRODUCT_DISPLAY_NAME,
} from '../config/branding';
import './LoginPage.css';

type LoginMode = 'human' | 'device-flow' | 'agent-credentials';
type EntrySection = 'install' | 'sign-in';

interface LocationState {
  from?: string;
}

/* ─── Install metadata ────────────────────────────────────────────────── */

const INSTALL_COMMAND = 'npx @amprealize/cli wizard';
const DOCS_URL = '/docs/getting-started/wizard';

function GitHubLogo(): React.JSX.Element {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        fill="#24292f"
        d="M12 0C5.373 0 0 5.373 0 12a12 12 0 0 0 8.207 11.387c.6.11.793-.26.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.547-1.387-1.334-1.756-1.334-1.756-1.088-.744.084-.729.084-.729 1.205.084 1.838 1.237 1.838 1.237 1.07 1.834 2.807 1.304 3.493.997.106-.775.418-1.304.761-1.604-2.665-.305-5.466-1.333-5.466-5.93 0-1.31.468-2.381 1.236-3.22-.124-.303-.536-1.524.117-3.176 0 0 1.008-.323 3.301 1.23A11.46 11.46 0 0 1 12 5.802c1.02.005 2.047.138 3.004.404 2.292-1.553 3.3-1.23 3.3-1.23.653 1.652.242 2.873.118 3.176.77.839 1.235 1.91 1.235 3.22 0 4.609-2.804 5.624-5.475 5.92.43.373.814 1.103.814 2.223v3.293c0 .319.192.69.8.576A12.002 12.002 0 0 0 24 12c0-6.627-5.373-12-12-12Z"
      />
    </svg>
  );
}

function GoogleLogo(): React.JSX.Element {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.25 1.37-1.03 2.53-2.2 3.31v2.75h3.57c2.08-1.92 3.27-4.73 3.27-8.07Z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.75c-.99.66-2.25 1.06-3.71 1.06-2.85 0-5.27-1.92-6.14-4.5H2.18v2.83A11 11 0 0 0 12 23Z" />
      <path fill="#FBBC05" d="M5.86 14.15A6.61 6.61 0 0 1 5.5 12c0-.74.13-1.45.36-2.15V7.02H2.18A10.97 10.97 0 0 0 1 12c0 1.77.42 3.43 1.18 4.98l3.68-2.83Z" />
      <path fill="#EA4335" d="M12 5.35c1.61 0 3.05.55 4.19 1.63l3.14-3.13C17.45 2.08 14.97 1 12 1A11 11 0 0 0 2.18 7.02l3.68 2.83c.87-2.58 3.29-4.5 6.14-4.5Z" />
    </svg>
  );
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    return true;
  } catch {
    return false;
  }
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    isAuthenticated,
    startLogin,
    cancelLogin,
    loginWithClientCredentials,
    error: authError,
    deviceFlowStatus,
    deviceCode,
  } = useAuth();

  const [mode, setMode] = useState<LoginMode>('human');
  const [entrySection, setEntrySection] = useState<EntrySection>('sign-in');
  const [copied, setCopied] = useState(false);
  const [installCopied, setInstallCopied] = useState(false);
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [credentialsError, setCredentialsError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [googlePopupPending, setGooglePopupPending] = useState(false);
  const from = (location.state as LocationState)?.from ?? '/';
  const [timeRemaining, setTimeRemaining] = useState<number | null>(null);
  const googlePopupRef = useRef<Window | null>(null);
  const googlePopupTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isAuthenticated) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, from]);

  useEffect(() => {
    if (import.meta.env.DEV) {
      console.log('[LoginPage] AUTH_STORE_INSTANCE_ID', AUTH_STORE_INSTANCE_ID);
      console.log('[LoginPage] device flow state', { deviceFlowStatus, deviceCode });
      console.log('[LoginPage] authStore.getState().deviceFlow', authStore.getState().deviceFlow);
    }
  }, [deviceFlowStatus, deviceCode]);

  useEffect(() => {
    if (deviceCode?.expiresIn) {
      const expiresAt = Date.now() + (deviceCode.expiresIn * 1000);
      const updateTimer = () => {
        const remaining = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
        setTimeRemaining(remaining);
      };

      updateTimer();
      const interval = setInterval(updateTimer, 1000);
      return () => clearInterval(interval);
    }

    setTimeRemaining(null);
    return undefined;
  }, [deviceCode?.expiresIn]);

  useEffect(() => {
    return () => {
      if (googlePopupTimeoutRef.current) {
        clearTimeout(googlePopupTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const handleOAuthMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) {
        return;
      }

      const payload = event.data as { type?: string } | null;
      if (
        payload?.type !== OAUTH_COMPLETE_MESSAGE_TYPE &&
        payload?.type !== OAUTH_COMPLETE_MESSAGE_TYPE_LEGACY
      ) {
        return;
      }

      setGooglePopupPending(false);
      googlePopupRef.current = null;
      if (googlePopupTimeoutRef.current) {
        clearTimeout(googlePopupTimeoutRef.current);
        googlePopupTimeoutRef.current = null;
      }
      window.focus();
    };

    window.addEventListener('message', handleOAuthMessage);
    return () => window.removeEventListener('message', handleOAuthMessage);
  }, []);

  const handleStartDeviceFlow = useCallback(async () => {
    setMode('device-flow');
    await startLogin();
  }, [startLogin]);

  const handleCopyCode = useCallback(async () => {
    if (deviceCode?.userCode) {
      const success = await copyToClipboard(deviceCode.userCode);
      if (success) {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    }
  }, [deviceCode?.userCode]);

  const handleCopyInstall = useCallback(async () => {
    const success = await copyToClipboard(INSTALL_COMMAND);
    if (success) {
      setInstallCopied(true);
      setTimeout(() => setInstallCopied(false), 2000);
    }
  }, []);

  const handleBackToHuman = useCallback(() => {
    cancelLogin();
    setMode('human');
    setCredentialsError(null);
  }, [cancelLogin]);

  const handleCredentialsSubmit = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    setCredentialsError(null);
    setIsSubmitting(true);

    try {
      await loginWithClientCredentials(clientId, clientSecret);
      navigate(from, { replace: true });
    } catch (err) {
      setCredentialsError(
        err instanceof Error ? err.message : 'Authentication failed',
      );
    } finally {
      setIsSubmitting(false);
    }
  }, [clientId, clientSecret, loginWithClientCredentials, navigate, from]);

  const openGooglePopup = useCallback((url: string): boolean => {
    const width = 520;
    const height = 720;
    const left = window.screenX + Math.max((window.outerWidth - width) / 2, 0);
    const top = window.screenY + Math.max((window.outerHeight - height) / 2, 0);
    const features = [
      `width=${width}`,
      `height=${height}`,
      `left=${Math.round(left)}`,
      `top=${Math.round(top)}`,
      'resizable=yes',
      'scrollbars=yes',
    ].join(',');

    const popup = window.open(url, OAUTH_GOOGLE_POPUP_NAME, features);
    if (!popup) {
      return false;
    }

    googlePopupRef.current = popup;
    setGooglePopupPending(true);
    popup.focus();

    if (googlePopupTimeoutRef.current) {
      clearTimeout(googlePopupTimeoutRef.current);
    }

    // Avoid polling `popup.closed` while the popup is on a cross-origin provider page.
    // Browsers increasingly warn on that access under COOP/COEP. We clear pending
    // state on our own postMessage callback and fall back to a timeout for cancelled flows.
    googlePopupTimeoutRef.current = setTimeout(() => {
      setGooglePopupPending(false);
      googlePopupRef.current = null;
      googlePopupTimeoutRef.current = null;
    }, 120_000);

    return true;
  }, []);

  const handleSocialLogin = useCallback((provider: 'github' | 'google') => {
    const redirectUri = `${window.location.origin}/auth/callback`;
    const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8080').replace(/\/+$/, '');
    const apiBaseUrl = rawBaseUrl.endsWith('/api') ? rawBaseUrl : `${rawBaseUrl}/api`;
    const usePopup = provider === 'google';
    const state = createOAuthState({
      provider,
      returnTo: from,
      popup: usePopup,
    });
    const authUrl = `${apiBaseUrl}/v1/auth/oauth/${provider}/authorize?redirect_uri=${encodeURIComponent(redirectUri)}&state=${encodeURIComponent(state)}`;

    if (usePopup) {
      const opened = openGooglePopup(authUrl);
      if (opened) {
        return;
      }
    }

    window.location.href = authUrl;
  }, [from, openGooglePopup]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (mode === 'device-flow' && (e.metaKey || e.ctrlKey) && e.key === 'c') {
        if (document.getSelection()?.toString() === '') {
          void handleCopyCode();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [mode, handleCopyCode]);

  let panelEyebrow = 'Welcome back';
  let panelTitle = `Sign in to ${PRODUCT_DISPLAY_NAME}`;
  let panelSubtitle = 'Capture what works from reasoning traces. Coordinate agents, plan multi-step workflows, and cut inference costs as your behavioral playbook evolves.';

  if (mode === 'device-flow') {
    panelEyebrow = 'Device flow';
    panelTitle = 'Authorize this session';
    panelSubtitle = 'Finish in the browser, then return here.';
  } else if (mode === 'agent-credentials') {
    panelEyebrow = 'Service access';
    panelTitle = 'Sign in with client credentials';
    panelSubtitle = 'For service accounts and automation.';
  }

  return (
    <AuthStage
      panelEyebrow={panelEyebrow}
      panelTitle={panelTitle}
      panelSubtitle={panelSubtitle}
      footer={(
        <footer className="login-footer">
          <p>
            By signing in, you agree to our{' '}
            <a href="/terms">Terms of Service</a> and{' '}
            <a href="/privacy">Privacy Policy</a>.
          </p>
        </footer>
      )}
    >
      {mode === 'human' && (
        <div className="login-home animate-fade-in-up">
          {/* ── Two side-by-side entry buttons ──────────────────────────── */}
          <div className="login-entry-row">
            <button
              type="button"
              className={`login-entry-button${entrySection === 'install' ? ' login-entry-button--active' : ''}`}
              onClick={() => setEntrySection('install')}
              aria-pressed={entrySection === 'install'}
            >
              <Sparkles size={16} strokeWidth={2} aria-hidden="true" />
              <span>Install in repo</span>
            </button>
            <button
              type="button"
              className={`login-entry-button${entrySection === 'sign-in' ? ' login-entry-button--active' : ''}`}
              onClick={() => setEntrySection('sign-in')}
              aria-pressed={entrySection === 'sign-in'}
            >
              <span>Sign in</span>
              <ArrowRight size={14} strokeWidth={2} aria-hidden="true" />
            </button>
          </div>

          {/* ── Install with AI section ─────────────────────────────────── */}
          {entrySection === 'install' && (
            <div
              className="login-install-section animate-fade-in-up"
              role="region"
              aria-label="Install in repo"
              data-install-command={INSTALL_COMMAND}
              data-install-method="npx"
            >
              <p className="login-install-desc">
                Add {PRODUCT_DISPLAY_NAME} to the repo you’re in with the setup wizard.
              </p>
              <div className="login-install-command-row">
                <button
                  type="button"
                  className="login-install-command"
                  onClick={() => void handleCopyInstall()}
                  aria-label={`Copy command: ${INSTALL_COMMAND}`}
                  data-command={INSTALL_COMMAND}
                >
                  <span className="login-install-prompt" aria-hidden="true">{'>'}</span>
                  <code className="login-install-code">
                    <span className="login-install-bin">npx</span>{' '}
                    <span className="login-install-pkg">@amprealize/cli</span>{' '}
                    <span className="login-install-arg">wizard</span>
                  </code>
                  <span className="login-install-copy-icon" aria-hidden="true">
                    {installCopied ? <Check size={15} strokeWidth={2} /> : <Copy size={15} strokeWidth={2} />}
                  </span>
                </button>
                <a href={DOCS_URL} className="login-install-learn-more">Learn more</a>
              </div>

              {/* Hidden structured data for AI agents parsing the page */}
              <script
                type="application/ld+json"
                dangerouslySetInnerHTML={{
                  __html: JSON.stringify({
                    '@context': 'https://schema.org',
                    '@type': 'SoftwareApplication',
                    name: 'Amprealize CLI',
                    operatingSystem: 'macOS, Linux, Windows',
                    applicationCategory: 'DeveloperApplication',
                    installUrl: 'https://www.npmjs.com/package/@amprealize/cli',
                    softwareRequirements: 'Node.js 18+, Python 3.10+',
                    description:
                      'AI-powered developer tooling and task orchestration. Install via: ' +
                      INSTALL_COMMAND,
                  }),
                }}
              />
            </div>
          )}

          {/* ── Sign in section ────────────────────────────────────────── */}
          {entrySection === 'sign-in' && (
            <div className="login-signin-section animate-fade-in-up">
              <div className="login-social-stack">
                <button
                  type="button"
                  className="login-social-button login-social-button-primary login-social-button-github"
                  onClick={() => handleSocialLogin('github')}
                  aria-label="Continue with GitHub"
                >
                  <span className="login-social-icon-wrap" aria-hidden="true">
                    <GitHubLogo />
                  </span>
                  <span className="login-social-copy">
                    <strong>Continue with GitHub</strong>
                    <span>Use your GitHub identity and connect repos when needed.</span>
                  </span>
                  <ArrowRight className="login-action-arrow" size={18} strokeWidth={2} aria-hidden="true" />
                </button>

                <button
                  type="button"
                  className="login-social-button login-social-button-primary login-social-button-google"
                  onClick={() => handleSocialLogin('google')}
                  aria-label="Continue with Google"
                  disabled={googlePopupPending}
                >
                  <span className="login-social-icon-wrap login-social-icon-wrap-google" aria-hidden="true">
                    <GoogleLogo />
                  </span>
                  <span className="login-social-copy">
                    <strong>Continue with Google</strong>
                    <span>{googlePopupPending ? 'Waiting…' : `Use your Google identity with ${PRODUCT_DISPLAY_NAME}`}</span>
                  </span>
                  <ArrowRight className="login-action-arrow" size={18} strokeWidth={2} aria-hidden="true" />
                </button>
              </div>

              <div className="login-secondary-actions">
                <button
                  type="button"
                  className="login-secondary-action"
                  onClick={() => void handleStartDeviceFlow()}
                >
                  <LaptopMinimal size={16} strokeWidth={2} aria-hidden="true" />
                  <span>Use browser code</span>
                </button>
                <button
                  type="button"
                  className="login-secondary-action"
                  onClick={() => setMode('agent-credentials')}
                >
                  <Bot size={16} strokeWidth={2} aria-hidden="true" />
                  <span>Use client credentials</span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {mode === 'device-flow' && (
        <div className="login-device-flow animate-fade-in-up">
          <div className="login-device-steps" aria-label="Device flow steps">
            <div className="login-step">
              <span className="login-step-number">1</span>
              <div className="login-step-copy">
                <strong>Open the verification page</strong>
                <span>
                  Visit{' '}
                  <a
                    href={deviceCode?.verificationUri ?? '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="login-verification-link"
                  >
                    {deviceCode?.verificationUri ?? 'the verification link'}
                  </a>
                  {' '}in a browser.
                </span>
              </div>
            </div>

            <div className="login-step">
              <span className="login-step-number">2</span>
              <div className="login-step-copy">
                <strong>Enter the code</strong>
                <span>We’ll continue here once it’s approved.</span>
              </div>
            </div>
          </div>

          {deviceFlowStatus === 'pending' && !deviceCode && (
            <div className="login-polling" aria-live="polite">
              <div className="login-status-spinner large" aria-hidden="true" />
              <p>Preparing your code…</p>
            </div>
          )}

          {deviceCode && (deviceFlowStatus === 'pending' || deviceFlowStatus === 'polling') && (
            <>
              <button
                type="button"
                className="login-code-display"
                onClick={() => void handleCopyCode()}
                aria-label={`Copy code ${deviceCode.userCode}`}
              >
                <span className="login-code-label">Your sign-in code</span>
                <span className="login-code-value">{deviceCode.userCode}</span>
                <span className="login-code-hint">{copied ? 'Copied' : 'Click to copy'}</span>
              </button>

              {deviceCode.verificationUriComplete && (
                <a
                  className="login-direct-link"
                  href={deviceCode.verificationUriComplete}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Link2 size={18} strokeWidth={2} aria-hidden="true" />
                  <span>Open with code attached</span>
                </a>
              )}

              <div className="login-status-card" aria-live="polite">
                <div className="login-status">
                  <div className="login-status-spinner" aria-hidden="true" />
                  <span>Waiting for approval…</span>
                </div>
                {timeRemaining !== null && timeRemaining > 0 && (
                  <p className="login-timer">Code expires in {formatTime(timeRemaining)}</p>
                )}
              </div>

              {timeRemaining === 0 && (
                <div className="login-error" role="alert">
                  <p>That code expired before it was approved.</p>
                  <button
                    type="button"
                    className="login-inline-button"
                    onClick={() => void handleStartDeviceFlow()}
                  >
                    Get a new code
                  </button>
                </div>
              )}
            </>
          )}

          {deviceFlowStatus === 'expired' && (
            <div className="login-error" role="alert">
              <p>Device code expired. Request a fresh code and try again.</p>
              <button
                type="button"
                className="login-inline-button"
                onClick={() => void handleStartDeviceFlow()}
              >
                Get new code
              </button>
            </div>
          )}

          {deviceFlowStatus === 'denied' && (
            <div className="login-error" role="alert">
              <p>Authorization was denied. You can restart the sign-in flow at any time.</p>
              <button
                type="button"
                className="login-inline-button"
                onClick={() => void handleStartDeviceFlow()}
              >
                Try again
              </button>
            </div>
          )}

          {deviceFlowStatus === 'error' && (
            <div className="login-error" role="alert">
              <p>{authError ?? 'Authentication failed'}</p>
              <button
                type="button"
                className="login-inline-button"
                onClick={() => void handleStartDeviceFlow()}
              >
                Try again
              </button>
            </div>
          )}

          <button
            type="button"
            className="login-back-button"
            onClick={handleBackToHuman}
          >
            <ArrowLeft size={16} strokeWidth={2} aria-hidden="true" />
            <span>Back to human sign in</span>
          </button>
        </div>
      )}

      {mode === 'agent-credentials' && (
        <form
          className="login-credentials-form animate-fade-in-up"
          onSubmit={handleCredentialsSubmit}
        >
          <div className="login-agent-banner">
            <div className="login-agent-banner-icon" aria-hidden="true">
              <KeyRound size={18} strokeWidth={2} />
            </div>
            <div className="login-agent-banner-copy">
              <strong>Direct access</strong>
              <span>For agents, CI jobs, and service automation.</span>
            </div>
          </div>

          <div className="login-field">
            <label htmlFor="client-id" className="login-label">
              Client ID
            </label>
            <input
              id="client-id"
              type="text"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="login-input"
              placeholder="Enter your client ID"
              autoComplete="username"
              autoFocus
              required
            />
          </div>

          <div className="login-field">
            <label htmlFor="client-secret" className="login-label">
              Client secret
            </label>
            <input
              id="client-secret"
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              className="login-input"
              placeholder="Enter your client secret"
              autoComplete="current-password"
              required
            />
          </div>

          {credentialsError && (
            <div className="login-credentials-error" role="alert">
              {credentialsError}
            </div>
          )}

          <button
            type="submit"
            className="login-submit-button"
            disabled={isSubmitting || !clientId || !clientSecret}
          >
            {isSubmitting ? (
              <>
                <span className="login-status-spinner small" aria-hidden="true" />
                Signing in...
              </>
            ) : (
              'Sign in with credentials'
            )}
          </button>

          <button
            type="button"
            className="login-back-button"
            onClick={handleBackToHuman}
          >
            <ArrowLeft size={16} strokeWidth={2} aria-hidden="true" />
            <span>Back to human sign in</span>
          </button>
        </form>
      )}
    </AuthStage>
  );
}

export default LoginPage;
