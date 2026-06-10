import { useCallback, useMemo, useState } from 'react';
import {
  LLM_PROVIDERS,
  useAddUserCredential,
  useDeleteUserCredential,
  useReEnableUserCredential,
  useUserCredentials,
  type LLMCredential,
  type LLMProvider,
} from '../api/credentials';
import { PRODUCT_DISPLAY_NAME } from '../config/branding';

interface UserLLMCredentialsSectionProps {
  userId: string;
}

export function UserLLMCredentialsSection({ userId }: UserLLMCredentialsSectionProps) {
  const [provider, setProvider] = useState<LLMProvider>('nvidia');
  const [apiKey, setApiKey] = useState('');
  const [name, setName] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [reEnableCredentialId, setReEnableCredentialId] = useState<string | null>(null);
  const [reEnableApiKey, setReEnableApiKey] = useState('');

  const {
    data: credentials,
    isLoading: credentialsLoading,
    isError: credentialsError,
  } = useUserCredentials(userId);
  const addCredential = useAddUserCredential(userId);
  const deleteCredential = useDeleteUserCredential(userId);
  const reEnableCredential = useReEnableUserCredential(userId);

  const selectedProvider = useMemo(
    () => LLM_PROVIDERS.find((item) => item.id === provider) ?? LLM_PROVIDERS[0],
    [provider],
  );

  const handleAddCredential = useCallback(async () => {
    const trimmedKey = apiKey.trim();
    if (!trimmedKey) return;

    setFormError(null);
    setSuccessMessage(null);
    try {
      await addCredential.mutateAsync({
        provider,
        api_key: trimmedKey,
        name: name.trim() || undefined,
      });
      setApiKey('');
      setName('');
      setSuccessMessage(`${selectedProvider.name} key saved.`);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Failed to save API key.');
    }
  }, [addCredential, apiKey, name, provider, selectedProvider.name]);

  const handleDeleteCredential = useCallback(async (credential: LLMCredential) => {
    const providerName = LLM_PROVIDERS.find((item) => item.id === credential.provider)?.name ?? credential.provider;
    const confirmed = window.confirm(`Delete the ${providerName} API key "${credential.name}"?`);
    if (!confirmed) return;

    setFormError(null);
    setSuccessMessage(null);
    try {
      await deleteCredential.mutateAsync(credential.id);
      setSuccessMessage(`${providerName} key deleted.`);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Failed to delete API key.');
    }
  }, [deleteCredential]);

  const handleReEnableCredential = useCallback(async (credential: LLMCredential) => {
    const trimmedKey = reEnableApiKey.trim();
    if (!trimmedKey) return;

    setFormError(null);
    setSuccessMessage(null);
    try {
      await reEnableCredential.mutateAsync({
        credentialId: credential.id,
        apiKey: trimmedKey,
      });
      setReEnableCredentialId(null);
      setReEnableApiKey('');
      setSuccessMessage(`${credential.name} re-enabled.`);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Failed to re-enable API key.');
    }
  }, [reEnableApiKey, reEnableCredential]);

  return (
    <section className="settings-section byok-section">
      <h2>LLM API Keys</h2>
      <p className="section-description">
        Add your own model provider keys for personal and global chat. Keys are encrypted at rest,
        never shown after saving, and used before {PRODUCT_DISPLAY_NAME} platform defaults.
      </p>

      <div className="byok-form" aria-label="Add LLM API key">
        <label className="byok-field">
          <span className="byok-label">Provider</span>
          <select
            className="byok-select"
            value={provider}
            onChange={(event) => setProvider(event.target.value as LLMProvider)}
          >
            {LLM_PROVIDERS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <span className="byok-help">{selectedProvider.description}</span>
        </label>

        <label className="byok-field">
          <span className="byok-label">API key</span>
          <input
            type="password"
            className="byok-input"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={selectedProvider.placeholder}
            autoComplete="off"
          />
        </label>

        <label className="byok-field">
          <span className="byok-label">Name</span>
          <input
            className="byok-input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={`${selectedProvider.name} API key`}
          />
          <span className="byok-help">Optional label to help you recognize this key.</span>
        </label>

        <button
          type="button"
          className="btn-primary byok-add-button"
          onClick={() => void handleAddCredential()}
          disabled={!apiKey.trim() || addCredential.isPending}
        >
          {addCredential.isPending ? 'Saving...' : 'Save key'}
        </button>
      </div>

      <p className="byok-help byok-security-note">
        Use dedicated provider keys for {PRODUCT_DISPLAY_NAME}. Deleting a key removes it from future
        model routing but does not rotate it at the provider.
      </p>

      {formError && <div className="byok-alert byok-alert-error" role="alert">{formError}</div>}
      {successMessage && <div className="byok-alert byok-alert-success" role="status">{successMessage}</div>}

      <div className="byok-credential-list">
        {credentialsLoading ? (
          <div className="loading-state">Loading API keys...</div>
        ) : credentialsError ? (
          <div className="byok-alert byok-alert-error" role="alert">
            Could not load your saved API keys.
          </div>
        ) : credentials && credentials.length > 0 ? (
          credentials.map((credential) => (
            <div className="byok-credential-card" key={credential.id}>
              <div className="byok-credential-main">
                <div className="byok-credential-header">
                  <strong>
                    {LLM_PROVIDERS.find((item) => item.id === credential.provider)?.name ?? credential.provider}
                  </strong>
                  <span className={`status-badge ${credential.is_valid ? 'enabled' : 'disabled'}`}>
                    {credential.is_valid ? 'Active' : 'Disabled'}
                  </span>
                </div>
                <div className="byok-credential-name">{credential.name}</div>
                <div className="byok-credential-meta">
                  <span>{credential.masked_key}</span>
                  <span>Added {new Date(credential.created_at).toLocaleDateString()}</span>
                  {credential.last_used_at && (
                    <span>Last used {new Date(credential.last_used_at).toLocaleDateString()}</span>
                  )}
                </div>
                {!credential.is_valid && (
                  <div className="byok-reenable">
                    <input
                      type="password"
                      className="byok-input"
                      value={reEnableCredentialId === credential.id ? reEnableApiKey : ''}
                      onFocus={() => setReEnableCredentialId(credential.id)}
                      onChange={(event) => {
                        setReEnableCredentialId(credential.id);
                        setReEnableApiKey(event.target.value);
                      }}
                      placeholder="New API key"
                      autoComplete="off"
                      aria-label={`New API key for ${credential.name}`}
                    />
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={
                        reEnableCredentialId !== credential.id ||
                        !reEnableApiKey.trim() ||
                        reEnableCredential.isPending
                      }
                      onClick={() => void handleReEnableCredential(credential)}
                    >
                      Re-enable
                    </button>
                  </div>
                )}
              </div>
              <button
                type="button"
                className="btn-secondary byok-delete-button"
                onClick={() => void handleDeleteCredential(credential)}
                disabled={deleteCredential.isPending}
              >
                Delete
              </button>
            </div>
          ))
        ) : (
          <div className="byok-empty-state">
            No personal API keys saved yet. Add your NVIDIA NIM key to unlock the free/open model plan in global chat.
          </div>
        )}
      </div>
    </section>
  );
}
