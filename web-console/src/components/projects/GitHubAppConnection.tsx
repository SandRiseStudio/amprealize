/**
 * GitHub App Connection Component
 *
 * Provides a tabbed interface for connecting GitHub repositories:
 * - GitHub App (Recommended): OAuth-like flow, short-lived tokens
 * - Personal Access Token: Manual token entry (legacy)
 *
 * Following:
 * - behavior_design_api_contract (Student)
 * - COLLAB_SAAS_REQUIREMENTS.md: fast, floaty, animated, 60fps
 * - behavior_prevent_secret_leaks (Student): secure token handling
 */

import { useCallback, useState } from 'react';
import { PRODUCT_DISPLAY_NAME } from '../../config/branding';
import { razeLog } from '../../telemetry/raze';
import { useAuth } from '../../auth';
import {
  useGitHubAppStatus,
  useProjectGitHubAppInstallation,
  useGitHubAppInstallUrl,
  useUnlinkProjectGitHubAppInstallation,
  useGitHubAppConfigureUrl,
  useLinkProjectToGitHubAppInstallation,
  useGitHubAppInstallations,
} from '../../api/githubApp';
import {
  useProjectGitHubCredential,
  useAddProjectGitHubCredential,
  useDeleteProjectGitHubCredential,
} from '../../api/credentials';
import './GitHubAppConnection.css';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GitHubAppConnectionProps {
  projectId: string;
}

type TabId = 'app' | 'pat';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GitHubAppConnection({ projectId }: GitHubAppConnectionProps): React.JSX.Element {
  const { actor } = useAuth();
  const [activeTab, setActiveTab] = useState<TabId>('app');

  // GitHub App status and installation
  const { data: appStatus, isLoading: statusLoading } = useGitHubAppStatus();
  const {
    data: appInstallation,
    isLoading: installationLoading,
    isFetching: installationFetching,
    refetch: refetchInstallation,
  } = useProjectGitHubAppInstallation(projectId);

  // PAT credential (legacy)
  const { data: patCredential, isLoading: patLoading } = useProjectGitHubCredential(projectId);

  // Determine if GitHub App is available
  const appConfigured = appStatus?.configured ?? false;

  // If app not configured, default to PAT tab
  const effectiveTab = !appConfigured ? 'pat' : activeTab;

  return (
    <div className="github-app-connection">
      <div className="github-app-connection-header">
        <h3 className="github-app-connection-title">GitHub Connection</h3>
        <p className="github-app-connection-description">
          Connect GitHub to enable agents to create branches, commits, and pull requests.
        </p>
      </div>

      {/* Tab selector */}
      <div className="github-app-tabs" role="tablist" aria-label="GitHub connection methods">
        <button
          type="button"
          className={`github-app-tab ${effectiveTab === 'app' ? 'active' : ''} ${!appConfigured ? 'disabled' : ''}`}
          onClick={() => appConfigured && setActiveTab('app')}
          disabled={!appConfigured}
          role="tab"
          aria-selected={effectiveTab === 'app'}
          aria-controls="github-connection-tabpanel-app"
          id="github-connection-tab-app"
        >
          <span className="tab-icon">🔐</span>
          <span className="tab-label">GitHub App</span>
          <span className="tab-badge recommended">Recommended</span>
        </button>
        <button
          type="button"
          className={`github-app-tab ${effectiveTab === 'pat' ? 'active' : ''}`}
          onClick={() => setActiveTab('pat')}
          role="tab"
          aria-selected={effectiveTab === 'pat'}
          aria-controls="github-connection-tabpanel-pat"
          id="github-connection-tab-pat"
        >
          <span className="tab-icon">🔑</span>
          <span className="tab-label">Personal Access Token</span>
        </button>
      </div>

      {/* Tab content */}
      <div className="github-app-tab-content">
        {effectiveTab === 'app' ? (
          <div
            role="tabpanel"
            id="github-connection-tabpanel-app"
            aria-labelledby="github-connection-tab-app"
          >
            <GitHubAppTab
            projectId={projectId}
            actorId={actor?.id}
            installation={appInstallation}
            isLoading={statusLoading || installationLoading || installationFetching}
            onRefreshInstallation={refetchInstallation}
            />
          </div>
        ) : (
          <div
            role="tabpanel"
            id="github-connection-tabpanel-pat"
            aria-labelledby="github-connection-tab-pat"
          >
            <GitHubPATTab
            projectId={projectId}
            actorId={actor?.id}
            credential={patCredential}
            isLoading={patLoading}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// GitHub App Tab
// ---------------------------------------------------------------------------

interface GitHubAppTabProps {
  projectId: string;
  actorId?: string;
  installation: Awaited<ReturnType<typeof useProjectGitHubAppInstallation>['data']>;
  isLoading: boolean;
  onRefreshInstallation: () => Promise<unknown>;
}

function GitHubAppTab({
  projectId,
  actorId,
  installation,
  isLoading,
  onRefreshInstallation,
}: GitHubAppTabProps): React.JSX.Element {
  const getInstallUrl = useGitHubAppInstallUrl();
  const linkInstallation = useLinkProjectToGitHubAppInstallation(projectId, actorId);
  const { data: availableInstallations, isLoading: installationsLoading, refetch: refetchInstallations } =
    useGitHubAppInstallations();
  const unlinkInstallation = useUnlinkProjectGitHubAppInstallation(projectId, actorId);
  const getConfigureUrl = useGitHubAppConfigureUrl();
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linkSuccess, setLinkSuccess] = useState(false);
  const callbackUrl = `${window.location.origin}/auth/github-app/callback`;

  const hasInstallations = Boolean(availableInstallations && availableInstallations.length > 0);
  const primaryInstallation = availableInstallations?.[0];
  const hasMultipleInstallations = (availableInstallations?.length ?? 0) > 1;
  const detectionStatus = installationsLoading
    ? 'Checking for existing installations…'
    : hasInstallations
      ? 'Installation found — link it to this project.'
      : 'No installation found yet.';
  const shouldShowInstall = !hasInstallations;

  const handleInstallApp = useCallback(async () => {
    try {
      await razeLog('INFO', 'Initiating GitHub App installation', { project_id: projectId });
      const { url } = await getInstallUrl.mutateAsync({
        scopeType: 'project',
        scopeId: projectId,
        redirectUri: window.location.href,
      });
      // Redirect in the same tab to avoid duplicate GitHub installs
      window.location.href = url;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to get install URL';
      await razeLog('ERROR', 'GitHub App install URL failed', { project_id: projectId, error: message });
    }
  }, [getInstallUrl, projectId]);

  const handleCheckInstallation = useCallback(async () => {
    try {
      await razeLog('INFO', 'Checking GitHub App installation status', { project_id: projectId });
      await onRefreshInstallation();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to refresh installation status';
      await razeLog('WARN', 'GitHub App installation refresh failed', { project_id: projectId, error: message });
    }
  }, [onRefreshInstallation, projectId]);

  const handleLinkExistingInstallation = useCallback(
    async (installationId: number) => {
      setLinkError(null);
      setLinkSuccess(false);

      try {
        await razeLog('INFO', 'Linking existing GitHub App installation', {
          project_id: projectId,
          installation_id: installationId,
        });
        await linkInstallation.mutateAsync(installationId);
        setLinkSuccess(true);
        await onRefreshInstallation();
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to link installation';
        setLinkError(message);
        await razeLog('ERROR', 'Link GitHub App installation failed', {
          project_id: projectId,
          error: message,
        });
      }
    },
    [linkInstallation, onRefreshInstallation, projectId]
  );

  const handleCopySetupUrl = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(callbackUrl);
      await razeLog('INFO', 'Copied GitHub App setup URL', { project_id: projectId });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to copy setup URL';
      await razeLog('WARN', 'Copy GitHub App setup URL failed', { project_id: projectId, error: message });
    }
  }, [callbackUrl, projectId]);

  const handleConfigureRepos = useCallback(async () => {
    if (!installation?.installation_id) return;
    try {
      const { url } = await getConfigureUrl.mutateAsync(installation.installation_id);
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to get configure URL';
      await razeLog('ERROR', 'GitHub App configure URL failed', { error: message });
    }
  }, [getConfigureUrl, installation]);

  const handleDisconnect = useCallback(async () => {
    try {
      await razeLog('INFO', 'Disconnecting GitHub App', { project_id: projectId });
      await unlinkInstallation.mutateAsync();
      await razeLog('INFO', 'GitHub App disconnected', { project_id: projectId });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to disconnect';
      await razeLog('ERROR', 'GitHub App disconnect failed', { project_id: projectId, error: message });
    }
  }, [unlinkInstallation, projectId]);

  if (isLoading) {
    return <div className="github-app-loading">Loading GitHub App status...</div>;
  }

  if (installation && installation.is_active) {
    // Connected state
    return (
      <div className="github-app-connected animate-fade-in-up">
        <div className="github-app-connected-header">
          <span className="connected-icon">✓</span>
          <span className="connected-label">GitHub App Connected</span>
        </div>

        <div className="github-app-account">
          {installation.account_avatar_url && (
            <img
              src={installation.account_avatar_url}
              alt={installation.account_login}
              className="account-avatar"
            />
          )}
          <div className="account-info">
            <div className="account-login">
              @{installation.account_login}
              <span className={`account-type ${installation.account_type.toLowerCase()}`}>
                {installation.account_type}
              </span>
            </div>
            <div className="account-repos">
              {installation.repository_selection === 'all' ? (
                'All repositories'
              ) : (
                `${installation.selected_repository_ids.length} selected repositories`
              )}
            </div>
          </div>
        </div>

        {installation.permission_warning && (
          <div className="github-app-warning">
            ⚠️ {installation.permission_warning}
          </div>
        )}

        <div className="github-app-permissions">
          <span className="permissions-label">Permissions:</span>
          <span className="permissions-list">
            {Object.entries(installation.permissions).map(([key, value]) => (
              <span key={key} className="permission-badge">
                {key}: {value}
              </span>
            ))}
          </span>
        </div>

        <div className="github-app-actions">
          <button
            type="button"
            className="action secondary pressable"
            onClick={() => void handleConfigureRepos()}
            data-haptic="light"
          >
            Configure Repos
          </button>
          <button
            type="button"
            className="action danger pressable"
            onClick={() => void handleDisconnect()}
            disabled={unlinkInstallation.isPending}
            data-haptic="medium"
          >
            {unlinkInstallation.isPending ? 'Disconnecting...' : 'Disconnect'}
          </button>
        </div>

        <p className="github-app-note">
          Note: Disconnecting only removes the link from this project.
          To fully uninstall, visit GitHub App settings.
        </p>
      </div>
    );
  }

  // Not connected state
  return (
    <div className="github-app-not-connected animate-fade-in-up">
      <div className="github-app-intro">
        <div className="github-app-benefits">
          <h4>GitHub App</h4>
          <p className="github-app-benefits-summary">
            {hasInstallations
              ? 'We found your installation. Link it to start creating branches and pull requests.'
              : 'Secure, short-lived access with repo-level permissions — no secrets to manage.'}
          </p>
        </div>
        {shouldShowInstall && (
          <div className="github-app-install-card">
            <div className="install-card-title">Install the {PRODUCT_DISPLAY_NAME} GitHub App</div>
            <div className="install-card-subtitle">Install once, link instantly.</div>
            <button
              type="button"
              className="github-app-install-button pressable"
              onClick={() => void handleInstallApp()}
              disabled={getInstallUrl.isPending}
              data-haptic="medium"
            >
              {getInstallUrl.isPending ? (
                'Redirecting to GitHub...'
              ) : (
                <>
                  <span className="github-icon">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                      <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                    </svg>
                  </span>
                  Install {PRODUCT_DISPLAY_NAME} GitHub App
                </>
              )}
            </button>
            <div className="install-card-note">
              You’ll choose your account and repos on GitHub.
            </div>
          </div>
        )}
      </div>

      <div className="github-app-link-existing">
        <div className="link-existing-header">
          <span className="link-existing-title">
            {hasInstallations ? 'Installation detected' : 'Auto-detect installations'}
          </span>
          <span className="link-existing-subtitle">
            {hasInstallations
              ? 'We found a GitHub App installation you can link right now.'
              : detectionStatus}
          </span>
        </div>

        {hasInstallations && primaryInstallation && (
          <div className="link-existing-hero">
            <div className="link-hero-badge">Ready to link</div>
            <div className="link-hero-body">
              <div className="link-hero-identity">
                {primaryInstallation.account_avatar_url && (
                  <img
                    src={primaryInstallation.account_avatar_url}
                    alt={primaryInstallation.account_login}
                    className="link-hero-avatar"
                  />
                )}
                <div className="link-hero-meta">
                  <div className="link-hero-title">
                    @{primaryInstallation.account_login}
                    <span className="link-hero-pill">{primaryInstallation.account_type}</span>
                  </div>
                  <div className="link-hero-subtitle">
                    {primaryInstallation.repository_selection === 'all'
                      ? 'All repositories selected'
                      : 'Selected repositories only'}
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="action primary pressable"
                onClick={() => void handleLinkExistingInstallation(primaryInstallation.installation_id)}
                disabled={linkInstallation.isPending}
                data-haptic="medium"
              >
                {linkInstallation.isPending ? 'Linking…' : 'Link GitHub App'}
              </button>
            </div>
          </div>
        )}

        <div className="link-existing-actions">
          <button
            type="button"
            className="action secondary pressable"
            onClick={() => void refetchInstallations()}
            disabled={installationsLoading}
            data-haptic="light"
          >
            {installationsLoading ? 'Checking…' : 'Refresh'}
          </button>
          {!hasInstallations && (
            <button
              type="button"
              className="action secondary pressable"
              onClick={() => void handleCheckInstallation()}
              data-haptic="light"
            >
              Check again
            </button>
          )}
        </div>

        {installationsLoading && (
          <div className="link-existing-loading">Looking for installations…</div>
        )}

        {!installationsLoading && availableInstallations?.length === 0 && (
          <div className="link-existing-empty">
            No installations found yet.
          </div>
        )}

        {availableInstallations && hasMultipleInstallations && (
          <div className="link-existing-list">
            <div className="link-existing-list-header">Other installations</div>
            {availableInstallations.slice(1).map((item) => (
              <div key={item.installation_id} className="link-existing-card">
                <div className="link-existing-info">
                  {item.account_avatar_url && (
                    <img
                      src={item.account_avatar_url}
                      alt={item.account_login}
                      className="link-existing-avatar"
                    />
                  )}
                  <div className="link-existing-meta">
                    <div className="link-existing-account">
                      @{item.account_login}
                      <span className="link-existing-type">{item.account_type}</span>
                    </div>
                    <div className="link-existing-repos">
                      {item.repository_selection === 'all' ? 'All repositories' : 'Selected repositories'}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="action secondary pressable"
                  onClick={() => void handleLinkExistingInstallation(item.installation_id)}
                  disabled={linkInstallation.isPending}
                  data-haptic="light"
                >
                  {linkInstallation.isPending ? 'Linking…' : 'Link'}
                </button>
              </div>
            ))}
          </div>
        )}

        {linkError && <div className="link-existing-error">{linkError}</div>}
        {linkSuccess && <div className="link-existing-success">Linked! Refreshing status…</div>}
      </div>

      {!hasInstallations && (
        <div className="github-app-install-help animate-fade-in">
          <div className="install-help-title">Need a redirect?</div>
          <p className="install-help-note">
            Ensure your GitHub App “Setup URL” is set to
            <span className="install-help-url">{callbackUrl}</span>.
          </p>
          <div className="install-help-actions">
            <button
              type="button"
              className="action secondary pressable"
              onClick={() => void handleCopySetupUrl()}
              data-haptic="light"
            >
              Copy setup URL
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PAT Tab (Legacy)
// ---------------------------------------------------------------------------

interface GitHubPATTabProps {
  projectId: string;
  actorId?: string;
  credential: Awaited<ReturnType<typeof useProjectGitHubCredential>['data']>;
  isLoading: boolean;
}

function GitHubPATTab({ projectId, actorId, credential, isLoading }: GitHubPATTabProps): React.JSX.Element {
  const [token, setToken] = useState('');
  const [tokenName, setTokenName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const addCredential = useAddProjectGitHubCredential(projectId, actorId);
  const deleteCredential = useDeleteProjectGitHubCredential(projectId, actorId);

  const handleSave = useCallback(async () => {
    if (!token.trim()) return;

    setError(null);
    setSuccess(false);

    try {
      await razeLog('INFO', 'Saving GitHub PAT', { project_id: projectId });
      await addCredential.mutateAsync({
        token: token.trim(),
        name: tokenName.trim() || undefined,
      });
      setToken('');
      setTokenName('');
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
      await razeLog('INFO', 'GitHub PAT saved', { project_id: projectId });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save token';
      setError(message);
      await razeLog('ERROR', 'GitHub PAT save failed', { project_id: projectId, error: message });
    }
  }, [addCredential, projectId, token, tokenName]);

  const handleDelete = useCallback(async () => {
    setError(null);
    setSuccess(false);

    try {
      await razeLog('INFO', 'Deleting GitHub PAT', { project_id: projectId });
      await deleteCredential.mutateAsync();
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
      await razeLog('INFO', 'GitHub PAT deleted', { project_id: projectId });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to delete token';
      setError(message);
      await razeLog('ERROR', 'GitHub PAT delete failed', { project_id: projectId, error: message });
    }
  }, [deleteCredential, projectId]);

  if (isLoading) {
    return <div className="github-pat-loading">Loading token status...</div>;
  }

  return (
    <div className="github-pat-content animate-fade-in-up">
      <div className="github-pat-notice">
        <span className="notice-icon">ℹ️</span>
        <span>
          Personal Access Tokens require manual management. Consider using
          <strong> GitHub App</strong> for automatic token rotation.
        </span>
      </div>

      {credential && (
        <div className="github-pat-existing">
          <div className="credential-card">
            <div className="credential-info">
              <div className="credential-header">
                <span className="credential-name">{credential.name || 'GitHub Token'}</span>
                <span className={`credential-status ${credential.is_valid ? 'active' : 'disabled'}`}>
                  {credential.is_valid ? 'Active' : 'Disabled'}
                </span>
              </div>
              <div className="credential-meta">
                <span className="credential-masked">{credential.masked_token}</span>
                {credential.github_username && (
                  <span className="credential-user">@{credential.github_username}</span>
                )}
              </div>
              {(credential.scope_warning || credential.warning) && (
                <div className="credential-warning">
                  ⚠️ {credential.scope_warning || credential.warning}
                </div>
              )}
            </div>
            <div className="credential-actions">
              <button
                type="button"
                className="action danger pressable"
                onClick={() => void handleDelete()}
                disabled={deleteCredential.isPending}
                data-haptic="medium"
              >
                {deleteCredential.isPending ? 'Removing...' : 'Remove'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="github-pat-form">
        <label className="field">
          <span className="field-label">Personal Access Token</span>
          <div className="field-input-group">
            <input
              type="password"
              className={`field-input ${error ? 'error' : ''}`}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="ghp_... or github_pat_..."
              aria-invalid={Boolean(error)}
            />
            <button
              type="button"
              className="action primary pressable"
              onClick={() => void handleSave()}
              disabled={!token.trim() || addCredential.isPending}
              data-haptic="light"
            >
              {addCredential.isPending ? 'Saving...' : credential ? 'Replace' : 'Save'}
            </button>
          </div>
        </label>

        <label className="field">
          <span className="field-label">Label (optional)</span>
          <input
            type="text"
            className="field-input"
            value={tokenName}
            onChange={(e) => setTokenName(e.target.value)}
            placeholder="e.g. personal-dev"
          />
        </label>

        <p className="field-hint">
          Required scopes: Classic PAT with <strong>repo</strong>, or fine-grained PAT with{' '}
          <strong>Contents: Read and write</strong> + <strong>Pull requests: Read and write</strong>.
        </p>

        {error && <div className="field-error">{error}</div>}
        {success && <div className="field-success">✓ Token saved successfully</div>}
      </div>
    </div>
  );
}
