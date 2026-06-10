/**
 * User profile — account summary + agent workspace / local connector preferences.
 */

import { Link } from 'react-router-dom';
import { useAuth } from '../../auth';
import { LocalExecutionWorkspaceSettings } from './LocalExecutionWorkspaceSettings';
import { CompactLoadingShimmer } from '../loading';
import '../SecuritySettings.css';
import './ProfilePages.css';

export function UserProfilePage() {
  const { actor } = useAuth();
  const userId = actor?.id;
  const displayName = actor?.displayName ?? actor?.email ?? userId ?? 'User';

  if (!userId) {
    return (
      <div className="profile-page loading">
        <CompactLoadingShimmer label="Loading profile" />
      </div>
    );
  }

  return (
    <div className="profile-page">
      <header className="settings-header">
        <h1>Profile</h1>
        <p>Your account and agent workspace preferences</p>
      </header>

      <section className="settings-section profile-account-section" aria-labelledby="profile-account-heading">
        <h2 id="profile-account-heading">Account</h2>
        <p className="profile-account-line">
          <strong>Name:</strong> {displayName}
        </p>
        {actor?.email && (
          <p className="profile-account-line">
            <strong>Email:</strong> {actor.email}
          </p>
        )}
      </section>

      <LocalExecutionWorkspaceSettings />

      <nav className="profile-footer-nav" aria-label="Related settings">
        <Link to="/settings/security" className="profile-related-link">
          Security &amp; privacy (MFA, connected accounts, API keys) →
        </Link>
        <Link to="/settings" className="profile-related-link profile-related-link-secondary">
          All settings →
        </Link>
      </nav>
    </div>
  );
}
