/**
 * SecuritySettings Component
 *
 * User security settings page including:
 * - Linked identities (GitHub, Google)
 * - MFA setup and management
 * - Email verification
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 * - behavior_prototype_consent_ux (Teacher)
 * - COLLAB_SAAS_REQUIREMENTS.md animation specs
 */

import { useState, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import {
  useLinkedProviders,
  useLinkIdentity,
  useUnlinkIdentity,
  useMfaStatus,
  useMfaDevices,
  useMfaSetup,
  useVerifyMfaSetup,
  useDeleteMfaDevice,
  useEmailVerificationStatus,
  useSendVerificationEmail,
} from '../api/identity';
import type { OAuthProvider, MfaDevice } from '../types/auth';
import './SecuritySettings.css';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface ProviderCardProps {
  provider: OAuthProvider;
  linked: boolean;
  providerEmail?: string;
  providerUsername?: string;
  onLink: () => void;
  onUnlink: () => void;
  isLoading: boolean;
}

function ProviderCard({
  provider,
  linked,
  providerEmail,
  providerUsername,
  onLink,
  onUnlink,
  isLoading,
}: ProviderCardProps) {
  const providerInfo: Record<OAuthProvider, { name: string; icon: string; color: string }> = {
    github: { name: 'GitHub', icon: '🐙', color: '#24292e' },
    google: { name: 'Google', icon: '🔵', color: '#4285f4' },
  };

  const info = providerInfo[provider];

  return (
    <div className={`provider-card ${linked ? 'linked' : ''}`}>
      <div className="provider-info">
        <span className="provider-icon">{info.icon}</span>
        <div className="provider-details">
          <strong>{info.name}</strong>
          {linked && (
            <span className="provider-account">
              {providerUsername || providerEmail || 'Connected'}
            </span>
          )}
        </div>
      </div>
      <button
        type="button"
        className={`provider-action ${linked ? 'unlink' : 'link'}`}
        onClick={linked ? onUnlink : onLink}
        disabled={isLoading}
      >
        {isLoading ? '...' : linked ? 'Disconnect' : 'Connect'}
      </button>
    </div>
  );
}

interface MfaDeviceCardProps {
  device: MfaDevice;
  onDelete: (deviceId: string) => void;
  isDeleting: boolean;
}

function MfaDeviceCard({ device, onDelete, isDeleting }: MfaDeviceCardProps) {
  return (
    <div className="mfa-device-card">
      <div className="device-info">
        <span className="device-icon">🔐</span>
        <div className="device-details">
          <strong>{device.deviceName}</strong>
          <span className="device-meta">
            Added {new Date(device.createdAt).toLocaleDateString()}
            {device.isPrimary && <span className="device-badge">Primary</span>}
          </span>
        </div>
      </div>
      <button
        type="button"
        className="device-remove"
        onClick={() => onDelete(device.id)}
        disabled={isDeleting}
        aria-label={`Remove ${device.deviceName}`}
      >
        {isDeleting ? '...' : '✕'}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MFA Setup Modal
// ---------------------------------------------------------------------------

interface MfaSetupModalProps {
  isOpen: boolean;
  onClose: () => void;
  userId: string;
}

function MfaSetupModal({ isOpen, onClose, userId }: MfaSetupModalProps) {
  const [step, setStep] = useState<'qr' | 'verify' | 'backup'>('qr');
  const [verificationCode, setVerificationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[]>([]);

  const setupMutation = useMfaSetup();
  const verifyMutation = useVerifyMfaSetup();

  // Start setup when modal opens
  const handleStartSetup = useCallback(async () => {
    setError(null);
    try {
      await setupMutation.mutateAsync({ userId });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start MFA setup');
    }
  }, [setupMutation, userId]);

  const handleVerify = useCallback(async () => {
    if (!setupMutation.data?.setupId || verificationCode.length !== 6) return;

    setError(null);
    try {
      const result = await verifyMutation.mutateAsync({
        setupId: setupMutation.data.setupId,
        code: verificationCode,
        userId,
      });
      setBackupCodes(result.backupCodes);
      setStep('backup');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid verification code');
    }
  }, [verifyMutation, setupMutation.data?.setupId, verificationCode, userId]);

  const handleClose = useCallback(() => {
    setStep('qr');
    setVerificationCode('');
    setError(null);
    setBackupCodes([]);
    setupMutation.reset();
    verifyMutation.reset();
    onClose();
  }, [onClose, setupMutation, verifyMutation]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div
        className="modal-content mfa-setup-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="mfa-setup-title"
      >
        <header className="modal-header">
          <h2 id="mfa-setup-title">
            {step === 'qr' && 'Set Up Two-Factor Authentication'}
            {step === 'verify' && 'Verify Your Authenticator'}
            {step === 'backup' && 'Save Your Backup Codes'}
          </h2>
          <button
            type="button"
            className="modal-close"
            onClick={handleClose}
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        <div className="modal-body">
          {step === 'qr' && (
            <>
              {!setupMutation.data ? (
                <div className="mfa-setup-start">
                  <p>
                    Add an extra layer of security to your account by enabling
                    two-factor authentication using an authenticator app.
                  </p>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={handleStartSetup}
                    disabled={setupMutation.isPending}
                  >
                    {setupMutation.isPending ? 'Starting...' : 'Begin Setup'}
                  </button>
                </div>
              ) : (
                <div className="mfa-qr-step">
                  <p>Scan this QR code with your authenticator app:</p>
                  <div className="qr-code-container">
                    <img
                      src={`data:image/png;base64,${setupMutation.data.qrCodeBase64}`}
                      alt="QR Code for authenticator app"
                      className="qr-code-image"
                    />
                  </div>
                  <div className="manual-entry">
                    <p>Can't scan? Enter this code manually:</p>
                    <code className="secret-code">{setupMutation.data.secret}</code>
                  </div>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => setStep('verify')}
                  >
                    I've Added It →
                  </button>
                </div>
              )}
            </>
          )}

          {step === 'verify' && (
            <div className="mfa-verify-step">
              <p>Enter the 6-digit code from your authenticator app:</p>
              <input
                type="text"
                className="verification-input"
                value={verificationCode}
                onChange={(e) => {
                  const value = e.target.value.replace(/\D/g, '').slice(0, 6);
                  setVerificationCode(value);
                }}
                placeholder="000000"
                maxLength={6}
                autoFocus
                aria-label="Verification code"
              />
              {error && <p className="error-message">{error}</p>}
              <div className="button-group">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setStep('qr')}
                >
                  ← Back
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={handleVerify}
                  disabled={verificationCode.length !== 6 || verifyMutation.isPending}
                >
                  {verifyMutation.isPending ? 'Verifying...' : 'Verify'}
                </button>
              </div>
            </div>
          )}

          {step === 'backup' && (
            <div className="mfa-backup-step">
              <p className="backup-warning">
                ⚠️ Save these backup codes in a safe place. You can use each code
                once if you lose access to your authenticator app.
              </p>
              <div className="backup-codes-grid">
                {backupCodes.map((code, index) => (
                  <code key={index} className="backup-code">
                    {code}
                  </code>
                ))}
              </div>
              <button
                type="button"
                className="btn-primary"
                onClick={handleClose}
              >
                I've Saved My Codes
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Password Confirmation Modal
// ---------------------------------------------------------------------------

interface PasswordModalProps {
  isOpen: boolean;
  title: string;
  message: string;
  onConfirm: (password: string) => void;
  onCancel: () => void;
  isLoading: boolean;
  error?: string | null;
}

function PasswordModal({
  isOpen,
  title,
  message,
  onConfirm,
  onCancel,
  isLoading,
  error,
}: PasswordModalProps) {
  const [password, setPassword] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onConfirm(password);
  };

  const handleClose = () => {
    setPassword('');
    onCancel();
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div
        className="modal-content password-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="password-modal-title"
      >
        <header className="modal-header">
          <h2 id="password-modal-title">{title}</h2>
          <button
            type="button"
            className="modal-close"
            onClick={handleClose}
            aria-label="Close"
          >
            ✕
          </button>
        </header>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <p>{message}</p>
            <input
              type="password"
              className="password-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoFocus
              required
            />
            {error && <p className="error-message">{error}</p>}
          </div>
          <div className="modal-footer">
            <button
              type="button"
              className="btn-secondary"
              onClick={handleClose}
              disabled={isLoading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary btn-danger"
              disabled={!password || isLoading}
            >
              {isLoading ? 'Confirming...' : 'Confirm'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function SecuritySettings() {
  const { actor } = useAuth();
  const userId = actor?.id;

  // API hooks
  const { data: providers, isLoading: loadingProviders } = useLinkedProviders(userId);
  const { data: mfaStatus, isLoading: loadingMfa } = useMfaStatus(userId);
  const { data: mfaDevices } = useMfaDevices(userId);
  const { data: emailStatus, isLoading: loadingEmail } = useEmailVerificationStatus(userId);

  const linkMutation = useLinkIdentity();
  const unlinkMutation = useUnlinkIdentity();
  const deleteMfaMutation = useDeleteMfaDevice();
  const sendVerificationMutation = useSendVerificationEmail();

  // Modal state
  const [mfaSetupOpen, setMfaSetupOpen] = useState(false);
  const [passwordModalConfig, setPasswordModalConfig] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    action: ((password: string) => Promise<void>) | null;
    error: string | null;
  }>({
    isOpen: false,
    title: '',
    message: '',
    action: null,
    error: null,
  });

  // Handle OAuth link (redirect to provider)
  const handleLinkProvider = useCallback((provider: OAuthProvider) => {
    // In production, this would redirect to the OAuth provider
    // For now, show a placeholder
    const oauthUrls: Record<OAuthProvider, string> = {
      github: '/api/v1/auth/oauth/github/authorize',
      google: '/api/v1/auth/oauth/google/authorize',
    };
    window.location.href = oauthUrls[provider];
  }, []);

  // Handle OAuth unlink (requires password)
  const handleUnlinkProvider = useCallback(
    (provider: OAuthProvider) => {
      if (!userId) return;

      setPasswordModalConfig({
        isOpen: true,
        title: 'Disconnect Account',
        message: `To disconnect your ${provider === 'github' ? 'GitHub' : 'Google'} account, please enter your password.`,
        action: async (password: string) => {
          try {
            await unlinkMutation.mutateAsync({
              userId,
              provider,
              passwordConfirmation: password,
            });
            setPasswordModalConfig((prev) => ({ ...prev, isOpen: false }));
          } catch (err) {
            setPasswordModalConfig((prev) => ({
              ...prev,
              error: err instanceof Error ? err.message : 'Failed to disconnect',
            }));
          }
        },
        error: null,
      });
    },
    [userId, unlinkMutation]
  );

  // Handle MFA device deletion
  const handleDeleteMfaDevice = useCallback(
    (deviceId: string) => {
      if (!userId) return;

      setPasswordModalConfig({
        isOpen: true,
        title: 'Remove Authenticator',
        message: 'To remove this authenticator, please enter your password.',
        action: async (password: string) => {
          try {
            await deleteMfaMutation.mutateAsync({
              deviceId,
              userId,
              password,
            });
            setPasswordModalConfig((prev) => ({ ...prev, isOpen: false }));
          } catch (err) {
            setPasswordModalConfig((prev) => ({
              ...prev,
              error: err instanceof Error ? err.message : 'Failed to remove device',
            }));
          }
        },
        error: null,
      });
    },
    [userId, deleteMfaMutation]
  );

  // Handle send verification email
  const handleSendVerification = useCallback(async () => {
    if (!userId) return;
    try {
      await sendVerificationMutation.mutateAsync(userId);
    } catch (err) {
      console.error('Failed to send verification email:', err);
    }
  }, [userId, sendVerificationMutation]);

  if (!userId) {
    return <div className="security-settings loading">Loading...</div>;
  }

  return (
    <div className="security-settings">
      <header className="settings-header">
        <h1>Security Settings</h1>
        <p>Manage your account security and connected services</p>
      </header>

      {/* Email Verification Section */}
      <section className="settings-section">
        <h2>Email Verification</h2>
        {loadingEmail ? (
          <div className="loading-state">Loading...</div>
        ) : emailStatus ? (
          <div className="email-status">
            {emailStatus.email ? (
              <>
                <p>
                  <strong>Email:</strong> {emailStatus.email}
                </p>
                {emailStatus.emailVerified ? (
                  <span className="status-badge verified">✓ Verified</span>
                ) : (
                  <div className="verification-action">
                    <span className="status-badge unverified">Not verified</span>
                    <button
                      type="button"
                      className="btn-link"
                      onClick={handleSendVerification}
                      disabled={sendVerificationMutation.isPending}
                    >
                      {sendVerificationMutation.isPending
                        ? 'Sending...'
                        : 'Send verification email'}
                    </button>
                  </div>
                )}
              </>
            ) : (
              <p className="no-email">No email address on file</p>
            )}
          </div>
        ) : null}
      </section>

      {/* Connected Accounts Section */}
      <section className="settings-section">
        <h2>Connected Accounts</h2>
        <p className="section-description">
          Link your accounts for easier sign-in and additional features
        </p>
        {loadingProviders ? (
          <div className="loading-state">Loading...</div>
        ) : (
          <div className="providers-list">
            {(['github', 'google'] as OAuthProvider[]).map((provider) => {
              const linked = providers?.linkedProviders.find(
                (p) => p.provider === provider
              );
              return (
                <ProviderCard
                  key={provider}
                  provider={provider}
                  linked={!!linked}
                  providerEmail={linked?.providerEmail}
                  providerUsername={linked?.providerUsername}
                  onLink={() => handleLinkProvider(provider)}
                  onUnlink={() => handleUnlinkProvider(provider)}
                  isLoading={
                    linkMutation.isPending || unlinkMutation.isPending
                  }
                />
              );
            })}
          </div>
        )}
      </section>

      {/* Two-Factor Authentication Section */}
      <section className="settings-section">
        <h2>Two-Factor Authentication</h2>
        <p className="section-description">
          Add an extra layer of security to your account
        </p>
        {loadingMfa ? (
          <div className="loading-state">Loading...</div>
        ) : (
          <>
            <div className="mfa-status">
              {mfaStatus?.mfaEnabled ? (
                <span className="status-badge enabled">✓ Enabled</span>
              ) : (
                <span className="status-badge disabled">Not enabled</span>
              )}
            </div>

            {mfaDevices && mfaDevices.length > 0 && (
              <div className="mfa-devices-list">
                {mfaDevices.map((device) => (
                  <MfaDeviceCard
                    key={device.id}
                    device={device}
                    onDelete={handleDeleteMfaDevice}
                    isDeleting={deleteMfaMutation.isPending}
                  />
                ))}
              </div>
            )}

            <button
              type="button"
              className="btn-primary"
              onClick={() => setMfaSetupOpen(true)}
            >
              {mfaStatus?.mfaEnabled ? 'Add Another Device' : 'Set Up 2FA'}
            </button>
          </>
        )}
      </section>

      {/* Modals */}
      <MfaSetupModal
        isOpen={mfaSetupOpen}
        onClose={() => setMfaSetupOpen(false)}
        userId={userId}
      />

      <PasswordModal
        isOpen={passwordModalConfig.isOpen}
        title={passwordModalConfig.title}
        message={passwordModalConfig.message}
        onConfirm={(password) => passwordModalConfig.action?.(password)}
        onCancel={() =>
          setPasswordModalConfig((prev) => ({ ...prev, isOpen: false }))
        }
        isLoading={unlinkMutation.isPending || deleteMfaMutation.isPending}
        error={passwordModalConfig.error}
      />
    </div>
  );
}

export default SecuritySettings;
