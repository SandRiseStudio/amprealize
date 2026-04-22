/**
 * Project Settings Page
 *
 * Configure project settings including local project path, GitHub repository,
 * and LLM API keys (BYOK - Bring Your Own Key).
 *
 * Following:
 * - behavior_design_api_contract (Student)
 * - behavior_use_raze_for_logging (Student)
 * - COLLAB_SAAS_REQUIREMENTS.md (Student): fast, floaty, animated, 60fps
 * - behavior_prevent_secret_leaks (Student): secure key handling
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { PRODUCT_DISPLAY_NAME } from '../../config/branding';
import { useNavigate, useParams } from 'react-router-dom';
import { useProject } from '../../api/dashboard';
import { apiClient } from '../../api/client';
import { razeLog } from '../../telemetry/raze';
import { useAuth } from '../../auth';
import {
  useProjectCredentials,
  useAddProjectCredential,
  useDeleteProjectCredential,
  useReEnableProjectCredential,
  LLM_PROVIDERS,
  type LLMCredential,
  type LLMProvider,
} from '../../api/credentials';
import { GitHubAppConnection } from './GitHubAppConnection';
import './ProjectSettingsPage.css';

// ---------------------------------------------------------------------------
// Types (aligned with backend settings_api.py)
// ---------------------------------------------------------------------------

interface ProjectSettings {
  local_project_path?: string;
  github_repo_url?: string;
  github_default_branch?: string;
  workflow?: Record<string, unknown>;
  agents?: Record<string, unknown>;
  branding?: Record<string, unknown>;
  agent_presence?: {
    enabled?: boolean;
    poll_interval_s?: number;
    show_on_board?: boolean;
  };
}

interface GitHubBranchInfo {
  name: string;
  sha?: string;
  protected?: boolean;
}

interface GitHubRepoValidationResponse {
  valid: boolean;
  owner?: string;
  repo?: string;
  default_branch?: string;
  visibility?: 'private' | 'public';
  description?: string;
  error?: string;
}

interface GitHubBranchListResponse {
  branches: GitHubBranchInfo[];
  total_count?: number;
  page: number;
  per_page: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ProjectSettingsContent({ projectId }: { projectId: string }): React.JSX.Element {
  const { data: project, isLoading: projectLoading } = useProject(projectId);
  const { actor } = useAuth();

  // Form state
  const [localPath, setLocalPath] = useState('');
  const [githubUrl, setGithubUrl] = useState('');
  const [selectedBranch, setSelectedBranch] = useState('');

  // GitHub validation state
  const [isValidatingGithub, setIsValidatingGithub] = useState(false);
  const [githubValidation, setGithubValidation] = useState<GitHubRepoValidationResponse | null>(null);
  const [githubError, setGithubError] = useState<string | null>(null);

  // Branch list state
  const [branches, setBranches] = useState<GitHubBranchInfo[]>([]);
  const [isLoadingBranches, setIsLoadingBranches] = useState(false);

  // Save state
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Credentials (BYOK) state
  const [credProvider, setCredProvider] = useState<LLMProvider>('anthropic');
  const [credApiKey, setCredApiKey] = useState('');
  const [credName, setCredName] = useState('');
  const [credToReEnable, setCredToReEnable] = useState<LLMCredential | null>(null);
  const [showReEnableModal, setShowReEnableModal] = useState(false);

  // Agent presence settings
  const [presenceEnabled, setPresenceEnabled] = useState(true);
  const [presencePollInterval, setPresencePollInterval] = useState(30);
  const [presenceShowOnBoard, setPresenceShowOnBoard] = useState(true);

  // Credentials hooks
  const {
    data: credentials,
    isLoading: credentialsLoading,
    refetch: refetchCredentials,
  } = useProjectCredentials(projectId ?? '');
  const addCredential = useAddProjectCredential(projectId ?? '', actor?.id);
  const deleteCredential = useDeleteProjectCredential(projectId ?? '', actor?.id);
  const reEnableCredential = useReEnableProjectCredential(projectId ?? '', actor?.id);

  // Load GitHub branches
  const loadBranches = useCallback(async () => {
    if (!projectId) return;

    setIsLoadingBranches(true);

    try {
      const response = await apiClient.get<GitHubBranchListResponse>(
        `/v1/projects/${projectId}/settings/repository/branches`
      );
      setBranches(response.branches);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load branches';
      await razeLog('WARN', 'Failed to load GitHub branches', { project_id: projectId, error: message });
      // Don't show error to user, branches are optional
    } finally {
      setIsLoadingBranches(false);
    }
  }, [projectId]);

  // Validate GitHub repository
  const validateGithubRepo = useCallback(async (url: string) => {
    if (!url.trim() || !projectId) return;

    setIsValidatingGithub(true);
    setGithubError(null);
    setGithubValidation(null);
    setBranches([]);

    try {
      await razeLog('INFO', 'Validating GitHub repository', { project_id: projectId, url });

      const response = await apiClient.post<GitHubRepoValidationResponse>(
        `/v1/projects/${projectId}/settings/repository/validate`,
        { repository_url: url }
      );

      setGithubValidation(response);

      if (response.valid) {
        await razeLog('INFO', 'GitHub repository validated', {
          project_id: projectId,
          owner: response.owner,
          repo: response.repo,
        });

        // If valid, auto-select default branch and load branch list
        if (response.default_branch) {
          setSelectedBranch((prev) => prev || response.default_branch!);
        }
        await loadBranches();
      } else {
        setGithubError(response.error ?? 'Repository validation failed');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to validate repository';
      setGithubError(message);
      await razeLog('ERROR', 'GitHub validation failed', { project_id: projectId, error: message });
    } finally {
      setIsValidatingGithub(false);
    }
  }, [projectId, loadBranches]);

  // Load existing settings
  useEffect(() => {
    if (project?.settings) {
      const settings = project.settings as ProjectSettings;
      setLocalPath(settings.local_project_path ?? '');
      setGithubUrl(settings.github_repo_url ?? '');
      setSelectedBranch(settings.github_default_branch ?? '');

      // Agent presence settings
      if (settings.agent_presence) {
        setPresenceEnabled(settings.agent_presence.enabled ?? true);
        setPresencePollInterval(settings.agent_presence.poll_interval_s ?? 30);
        setPresenceShowOnBoard(settings.agent_presence.show_on_board ?? true);
      }

      // If GitHub URL is already set, validate it to load branches
      if (settings.github_repo_url) {
        void validateGithubRepo(settings.github_repo_url);
      }
    }
  }, [project, validateGithubRepo]);

  // Save settings
  const handleSave = useCallback(async () => {
    if (!projectId) return;

    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      await razeLog('INFO', 'Saving project settings', { project_id: projectId });

      await apiClient.patch(`/v1/projects/${projectId}/settings`, {
        local_project_path: localPath.trim() || null,
        github_repo_url: githubUrl.trim() || null,
        github_default_branch: selectedBranch || null,
        agent_presence: {
          enabled: presenceEnabled,
          poll_interval_s: presencePollInterval,
          show_on_board: presenceShowOnBoard,
        },
      });

      setSaveSuccess(true);
      await razeLog('INFO', 'Project settings saved', { project_id: projectId });

      // Clear success message after 3 seconds
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save settings';
      setSaveError(message);
      await razeLog('ERROR', 'Failed to save project settings', { project_id: projectId, error: message });
    } finally {
      setIsSaving(false);
    }
  }, [projectId, localPath, githubUrl, selectedBranch, presenceEnabled, presencePollInterval, presenceShowOnBoard]);

  // Add credential
  const handleAddCredential = useCallback(async () => {
    if (!credApiKey.trim()) return;

    try {
      await razeLog('INFO', 'Adding credential', { project_id: projectId, provider: credProvider });
      await addCredential.mutateAsync({
        provider: credProvider,
        api_key: credApiKey.trim(),
        name: credName.trim() || undefined,
      });
      // Reset form
      setCredApiKey('');
      setCredName('');
      await refetchCredentials();
      await razeLog('INFO', 'Credential added', { project_id: projectId, provider: credProvider });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to add credential';
      await razeLog('ERROR', 'Failed to add credential', { project_id: projectId, error: message });
    }
  }, [projectId, credProvider, credApiKey, credName, addCredential, refetchCredentials]);

  // Delete credential
  const handleDeleteCredential = useCallback(async (credentialId: string) => {
    try {
      await razeLog('INFO', 'Deleting credential', { project_id: projectId, credential_id: credentialId });
      await deleteCredential.mutateAsync(credentialId);
      await refetchCredentials();
      await razeLog('INFO', 'Credential deleted', { project_id: projectId, credential_id: credentialId });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to delete credential';
      await razeLog('ERROR', 'Failed to delete credential', { project_id: projectId, error: message });
    }
  }, [projectId, deleteCredential, refetchCredentials]);

  // Re-enable credential
  const handleReEnableCredential = useCallback(async (newApiKey: string) => {
    if (!credToReEnable || !newApiKey.trim()) return;

    try {
      await razeLog('INFO', 'Re-enabling credential', { project_id: projectId, credential_id: credToReEnable.id });
      await reEnableCredential.mutateAsync({
        credentialId: credToReEnable.id,
        apiKey: newApiKey.trim(),
      });
      setShowReEnableModal(false);
      setCredToReEnable(null);
      await refetchCredentials();
      await razeLog('INFO', 'Credential re-enabled', { project_id: projectId, credential_id: credToReEnable.id });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to re-enable credential';
      await razeLog('ERROR', 'Failed to re-enable credential', { project_id: projectId, error: message });
    }
  }, [projectId, credToReEnable, reEnableCredential, refetchCredentials]);

  // Validation status
  const isGithubValid = useMemo(() => githubValidation?.valid === true, [githubValidation]);
  const githubRepoLabel = useMemo(() => {
    if (githubValidation?.owner && githubValidation?.repo) {
      return `${githubValidation.owner}/${githubValidation.repo}`;
    }
    return githubUrl.trim();
  }, [githubValidation?.owner, githubValidation?.repo, githubUrl]);

  if (projectLoading) {
    return (
        <div className="project-settings-content">
          <div className="loading-state">Loading settings...</div>
        </div>
    );
  }

  if (!project) {
    return (
        <div className="project-settings-content">
          <div className="error-state">Project not found</div>
        </div>
    );
  }

  return (
      <div className="project-settings-content">
        <section className="project-settings-card" aria-label="Project settings form">
          {/* Local Project Path */}
          <div className="settings-section">
            <h2 className="settings-section-title">Local Project Path</h2>
            <p className="settings-section-description">
              Optional: The local filesystem path where this project is located.
              VS Code can auto-detect this from your current folder.
            </p>

            <label className="field">
              <span className="field-label">Path</span>
              <input
                className="field-input"
                value={localPath}
                onChange={(e) => setLocalPath(e.target.value)}
                placeholder="/Users/you/projects/my-project"
              />
              <span className="field-hint">
                Example: <code className="mono">/Users/you/amprealize</code>
              </span>
            </label>
          </div>

          {/* GitHub Repository */}
          <div className="settings-section">
            <h2 className="settings-section-title">GitHub Repository</h2>
            <p className="settings-section-description">
              Optional: Connect a GitHub repository for branch selection and integration features.
              For private repos, sign in with GitHub or add a project token below.
            </p>

            <label className="field">
              <span className="field-label">Repository URL</span>
              <div className="field-input-group">
                <input
                  className={`field-input ${githubError ? 'error' : ''} ${isGithubValid ? 'valid' : ''}`}
                  value={githubUrl}
                  onChange={(e) => {
                    setGithubUrl(e.target.value);
                    setGithubValidation(null);
                    setGithubError(null);
                    setBranches([]);
                  }}
                  placeholder="https://github.com/owner/repo"
                  aria-invalid={Boolean(githubError)}
                />
                <button
                  type="button"
                  className="validate-button pressable"
                  onClick={() => void validateGithubRepo(githubUrl)}
                  disabled={!githubUrl.trim() || isValidatingGithub}
                  data-haptic="light"
                >
                  {isValidatingGithub ? 'Validating…' : 'Validate'}
                </button>
              </div>
              {githubError && <span className="field-error">{githubError}</span>}
              {isGithubValid && githubValidation && (
                <div className="github-validation-success">
                  <span className="validation-icon">✓</span>
                  <span className="validation-text">
                    <strong>{githubRepoLabel}</strong>
                    {githubValidation.visibility === 'private' && <span className="badge private">Private</span>}
                    {githubValidation.description && (
                      <span className="validation-description">{githubValidation.description}</span>
                    )}
                  </span>
                </div>
              )}
            </label>

            {/* Branch Selection */}
            {isGithubValid && (
              <label className="field animate-fade-in-up">
                <span className="field-label">Default Branch</span>
                <select
                  className="field-select"
                  value={selectedBranch}
                  onChange={(e) => setSelectedBranch(e.target.value)}
                  disabled={isLoadingBranches}
                >
                  {branches.length === 0 && !isLoadingBranches && (
                    <option value="">Select a branch</option>
                  )}
                  {isLoadingBranches && <option value="">Loading branches…</option>}
                  {branches.map((branch) => {
                    const isDefaultBranch = branch.name === githubValidation?.default_branch;
                    return (
                      <option key={branch.name} value={branch.name}>
                        {branch.name}
                        {isDefaultBranch && ' (default)'}
                        {branch.protected && ' 🔒'}
                      </option>
                    );
                  })}
                </select>
                <span className="field-hint">
                  Select the branch to use for this project. Default branch is auto-selected.
                </span>
              </label>
            )}

            {/* GitHub Connection (App or PAT) */}
            {projectId && (
              <GitHubAppConnection projectId={projectId} />
            )}
          </div>

          {/* LLM API Keys (BYOK) */}
          <div className="settings-section credentials-section">
            <h2 className="settings-section-title">LLM API Keys (BYOK)</h2>
            <p className="settings-section-description">
              Add your own API keys for LLM providers. Keys are encrypted at rest and never leave your project.
            </p>

            {/* Add Credential Form */}
            <div className="credential-form animate-fade-in-up">
              <div className="credential-form-row">
                <label className="field credential-provider-field">
                  <span className="field-label">Provider</span>
                  <select
                    className="field-select"
                    value={credProvider}
                    onChange={(e) => setCredProvider(e.target.value as LLMProvider)}
                  >
                    {LLM_PROVIDERS.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field credential-key-field">
                  <span className="field-label">API Key</span>
                  <input
                    type="password"
                    className="field-input"
                    value={credApiKey}
                    onChange={(e) => setCredApiKey(e.target.value)}
                    placeholder="sk-..."
                    autoComplete="off"
                  />
                </label>

                <label className="field credential-name-field">
                  <span className="field-label">Name (optional)</span>
                  <input
                    className="field-input"
                    value={credName}
                    onChange={(e) => setCredName(e.target.value)}
                    placeholder="Personal key"
                  />
                </label>

                <button
                  type="button"
                  className="action primary pressable credential-add-btn"
                  onClick={() => void handleAddCredential()}
                  disabled={!credApiKey.trim() || addCredential.isPending}
                  data-haptic="light"
                >
                  {addCredential.isPending ? 'Adding…' : 'Add Key'}
                </button>
              </div>
              <span className="field-hint credential-hint">
                Your API key is encrypted before storage. We recommend using a dedicated key for {PRODUCT_DISPLAY_NAME}.
              </span>
            </div>

            {/* Credentials List */}
            <div className="credentials-list">
              {credentialsLoading ? (
                <div className="credentials-loading">Loading credentials…</div>
              ) : credentials && credentials.length > 0 ? (
                credentials.map((cred, index) => (
                  <div
                    key={cred.id}
                    className="credential-card animate-scale-in"
                    style={{ animationDelay: `${index * 50}ms` }}
                  >
                    <div className="credential-info">
                      <div className="credential-header">
                        <span className="credential-provider">
                          {LLM_PROVIDERS.find((p) => p.id === cred.provider)?.name ?? cred.provider}
                        </span>
                        <span
                          className={`credential-status ${cred.is_valid ? 'active' : 'disabled'}`}
                          title={cred.is_valid ? 'Active' : 'Disabled - Re-enable required'}
                        >
                          {cred.is_valid ? '● Active' : '○ Disabled'}
                        </span>
                      </div>
                      {cred.name && <div className="credential-name">{cred.name}</div>}
                      <div className="credential-meta">
                        <span className="credential-key-preview">
                          {cred.masked_key}
                        </span>
                        <span className="credential-created">
                          Added {new Date(cred.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                    <div className="credential-actions">
                      {!cred.is_valid && (
                        <button
                          type="button"
                          className="action secondary pressable credential-reenable-btn"
                          onClick={() => {
                            setCredToReEnable(cred);
                            setShowReEnableModal(true);
                          }}
                          data-haptic="light"
                        >
                          Re-enable
                        </button>
                      )}
                      <button
                        type="button"
                        className="action danger pressable credential-delete-btn"
                        onClick={() => void handleDeleteCredential(cred.id)}
                        disabled={deleteCredential.isPending}
                        data-haptic="medium"
                        aria-label={`Delete ${cred.name ?? cred.provider} credential`}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="credentials-empty">
                  <span className="credentials-empty-icon">🔑</span>
                  <span className="credentials-empty-text">
                    No API keys configured yet. Add your first key above.
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Agent Presence */}
          <div className="settings-section agent-presence-section">
            <h2 className="settings-section-title">Agent Presence</h2>
            <p className="settings-section-description">
              Configure how agent availability and status are displayed on your boards.
            </p>

            <div className="agent-presence-form">
              <label className="field field-toggle">
                <span className="field-label">Enable presence tracking</span>
                <input
                  type="checkbox"
                  className="field-checkbox"
                  checked={presenceEnabled}
                  onChange={(e) => setPresenceEnabled(e.target.checked)}
                />
                <span className="field-hint">
                  When enabled, agent status (available, working, paused) is polled and displayed.
                </span>
              </label>

              <label className="field field-toggle">
                <span className="field-label">Show presence rail on board</span>
                <input
                  type="checkbox"
                  className="field-checkbox"
                  checked={presenceShowOnBoard}
                  onChange={(e) => setPresenceShowOnBoard(e.target.checked)}
                  disabled={!presenceEnabled}
                />
                <span className="field-hint">
                  Display the agent presence bar at the top of the board view.
                </span>
              </label>

              <label className="field">
                <span className="field-label">Poll interval (seconds)</span>
                <input
                  type="number"
                  className="field-input"
                  min={10}
                  max={300}
                  step={5}
                  value={presencePollInterval}
                  onChange={(e) => setPresencePollInterval(Number(e.target.value) || 30)}
                  disabled={!presenceEnabled}
                />
                <span className="field-hint">
                  How often to refresh agent status. Lower values use more resources (10–300s).
                </span>
              </label>
            </div>
          </div>

          {/* Re-enable Modal */}
          {showReEnableModal && credToReEnable && (
            <div className="modal-overlay animate-fade-in" onClick={() => setShowReEnableModal(false)}>
              <div
                className="modal-content animate-scale-in"
                onClick={(e) => e.stopPropagation()}
                role="dialog"
                aria-labelledby="reenable-modal-title"
                aria-modal="true"
              >
                <h3 id="reenable-modal-title" className="modal-title">
                  Re-enable {credToReEnable.name ?? credToReEnable.provider}
                </h3>
                <p className="modal-description">
                  This credential was disabled due to repeated failures.
                  Enter a new API key to re-enable it.
                </p>
                <label className="field">
                  <span className="field-label">New API Key</span>
                  <input
                    type="password"
                    className="field-input"
                    id="reenable-api-key"
                    placeholder="sk-..."
                    autoComplete="off"
                    autoFocus
                  />
                </label>
                <div className="modal-actions">
                  <button
                    type="button"
                    className="action secondary pressable"
                    onClick={() => setShowReEnableModal(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="action primary pressable"
                    onClick={() => {
                      const input = document.getElementById('reenable-api-key') as HTMLInputElement;
                      void handleReEnableCredential(input?.value ?? '');
                    }}
                    disabled={reEnableCredential.isPending}
                    data-haptic="medium"
                  >
                    {reEnableCredential.isPending ? 'Re-enabling…' : 'Re-enable'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Save Actions */}
          <div className="settings-actions">
            {saveError && (
              <div className="save-error" role="alert">
                {saveError}
              </div>
            )}
            {saveSuccess && (
              <div className="save-success" role="status">
                Settings saved successfully!
              </div>
            )}

            <button
              type="button"
              className="action primary pressable"
              onClick={() => void handleSave()}
              disabled={isSaving}
              data-haptic="medium"
            >
              {isSaving ? 'Saving…' : 'Save Settings'}
            </button>
          </div>
        </section>
      </div>
  );
}

/**
 * Standalone settings page (backwards-compat route wrapper).
 */
export function ProjectSettingsPage(): React.JSX.Element {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  useEffect(() => {
    if (projectId) {
      navigate(`/projects/${projectId}?tab=settings`, { replace: true });
    }
  }, [projectId, navigate]);

  return <div className="project-settings-page"><div className="loading-state">Redirecting…</div></div>;
}
