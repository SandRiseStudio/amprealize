/**
 * Settings hub — entry list for profile, security, connector, and admin tools.
 */

import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth';
import { CompactLoadingShimmer } from '../loading';
import '../SecuritySettings.css';
import './ProfilePages.css';

export function SettingsHubPage() {
  const navigate = useNavigate();
  const { actor } = useAuth();
  const userId = actor?.id;
  const isAdmin = actor?.role === 'ADMIN';

  if (!userId) {
    return (
      <div className="settings-hub-page loading">
        <CompactLoadingShimmer label="Loading settings" />
      </div>
    );
  }

  return (
    <div className="settings-hub-page">
      <header className="settings-header">
        <h1>Settings</h1>
        <p className="settings-hub-intro">Manage your profile, security, and optional local execution connector.</p>
      </header>

      <div className="settings-hub-grid">
        <button
          type="button"
          className="settings-hub-card"
          onClick={() => navigate('/settings/profile')}
          data-haptic="light"
        >
          <h2 className="settings-hub-card-title">Profile</h2>
          <p className="settings-hub-card-desc">
            Account summary and agent workspace preferences (remote vs local connector).
          </p>
        </button>

        <button
          type="button"
          className="settings-hub-card"
          onClick={() => navigate('/settings/security')}
          data-haptic="light"
        >
          <h2 className="settings-hub-card-title">Security &amp; privacy</h2>
          <p className="settings-hub-card-desc">
            Email verification, connected accounts, two-factor authentication, and LLM credentials.
          </p>
        </button>

        <button
          type="button"
          className="settings-hub-card"
          onClick={() => navigate('/settings/local-connector')}
          data-haptic="light"
        >
          <h2 className="settings-hub-card-title">Local connector pairing</h2>
          <p className="settings-hub-card-desc">
            Generate pairing codes and revoke daemon device tokens.
          </p>
        </button>

        {isAdmin && (
          <button
            type="button"
            className="settings-hub-card settings-hub-card-admin"
            onClick={() => navigate('/settings/feature-flags')}
            data-haptic="light"
          >
            <h2 className="settings-hub-card-title">Feature flags</h2>
            <p className="settings-hub-card-desc">
              Server-side boolean flags (admin).
            </p>
          </button>
        )}
      </div>
    </div>
  );
}
