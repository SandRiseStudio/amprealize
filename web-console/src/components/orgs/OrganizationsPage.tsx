/**
 * Organizations Page
 *
 * Entry point for managing org membership and navigation.
 * Following COLLAB_SAAS_REQUIREMENTS.md for fast, floaty UX.
 */

import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useShellTitle } from '../workspace/useShell';
import { useOrganizations } from '../../api/dashboard';
import { useCreateOrganization } from '../../api/organizations';
import { PERSONAL_SCOPE_DESCRIPTION, PERSONAL_SCOPE_LABEL } from '../../copy/scopeLabels';
import { orgContextStore } from '../../store/orgContextStore';
import './OrganizationsPage.css';

function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\\s-]/g, '')
    .replace(/\\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

function validateName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return 'Organization name is required';
  if (trimmed.length < 3) return 'Organization name must be at least 3 characters';
  if (trimmed.length > 80) return 'Organization name must be 80 characters or less';
  return null;
}

function validateSlug(slug: string): string | null {
  const trimmed = slug.trim();
  if (!trimmed) return 'Slug is required';
  if (!/^[a-z0-9-]+$/.test(trimmed)) return 'Slug can only use lowercase letters, numbers, and dashes';
  return null;
}

function formatRelativeTime(dateString?: string): string {
  if (!dateString) return 'Recently';
  const updated = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - updated.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return updated.toLocaleDateString();
}

export function OrganizationsPage(): React.JSX.Element {
  const navigate = useNavigate();
  const { data: organizations = [] } = useOrganizations();
  const createMutation = useCreateOrganization();

  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugEdited, setSlugEdited] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nameError = useMemo(() => validateName(name), [name]);
  const slugError = useMemo(() => validateSlug(slug), [slug]);
  const canCreate = useMemo(
    () => !nameError && !slugError && !createMutation.isPending,
    [nameError, slugError, createMutation.isPending]
  );

  const handleNameChange = useCallback(
    (next: string) => {
      setName(next);
      if (!slugEdited) {
        setSlug(slugify(next));
      }
    },
    [slugEdited]
  );

  const handleSlugChange = useCallback((next: string) => {
    setSlugEdited(true);
    setSlug(next.toLowerCase());
  }, []);

  const handleCreate = useCallback(async () => {
    if (nameError || slugError) {
      setError(nameError ?? slugError ?? null);
      return;
    }
    setError(null);

    try {
      const created = await createMutation.mutateAsync({
        name: name.trim(),
        slug: slug.trim(),
      });
      orgContextStore.setCurrentOrgId(created.id);
      setName('');
      setSlug('');
      setSlugEdited(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create organization');
    }
  }, [createMutation, name, nameError, slug, slugError]);

  const handleOpenOrgProjects = useCallback(
    (orgId: string) => {
      orgContextStore.setCurrentOrgId(orgId);
      navigate('/projects');
    },
    [navigate]
  );

  const handleOpenMyProjects = useCallback(() => {
    orgContextStore.setCurrentOrgId(null);
    navigate('/projects');
  }, [navigate]);

  const sortedOrganizations = useMemo(
    () => [...organizations].sort((a, b) => a.name.localeCompare(b.name)),
    [organizations]
  );

  useShellTitle('Organizations');

  return (
      <div className="orgs-page">
        <header className="orgs-header">
          <div className="orgs-header-left">
            <h1 className="orgs-title animate-fade-in-up">Organizations</h1>
            <p className="orgs-subtitle animate-fade-in-up">
              Keep your own projects separate, or group work under an organization to collaborate at scale.
            </p>
          </div>
          <div className="orgs-header-right">
            <button
              type="button"
              className="orgs-primary-button pressable"
              onClick={handleCreate}
              disabled={!canCreate}
              data-haptic="light"
            >
              Create Organization
            </button>
          </div>
        </header>

        <section className="orgs-create" aria-label="Create organization">
          <div className="orgs-create-card">
            <div>
              <h2 className="orgs-section-title">Start a new organization</h2>
              <p className="orgs-section-subtitle">
                Organize teams, projects, and agents with shared membership controls and project access.
              </p>
            </div>
            <div className="orgs-create-fields">
              <label className="orgs-field">
                <span className="orgs-field-label">Organization name</span>
                <input
                  className="orgs-field-input"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="Acme Labs"
                  autoComplete="off"
                />
              </label>
              <label className="orgs-field">
                <span className="orgs-field-label">Slug</span>
                <input
                  className="orgs-field-input"
                  value={slug}
                  onChange={(e) => handleSlugChange(e.target.value)}
                  placeholder="acme-labs"
                  autoComplete="off"
                />
              </label>
            </div>
            {(nameError || slugError || error) && (
              <div className="orgs-create-error" role="status" aria-live="polite">
                {error ?? nameError ?? slugError}
              </div>
            )}
            <div className="orgs-create-actions">
              <button
                type="button"
                className="orgs-secondary-button pressable"
                onClick={handleOpenMyProjects}
                data-haptic="light"
              >
                Open my projects
              </button>
            </div>
          </div>
        </section>

        <section className="orgs-grid" aria-label="Organization list">
          <OrganizationCard
            title={PERSONAL_SCOPE_LABEL}
            subtitle={PERSONAL_SCOPE_DESCRIPTION}
            meta={PERSONAL_SCOPE_LABEL}
            onOpen={handleOpenMyProjects}
            isPersonal
          />
          {sortedOrganizations.length === 0 ? (
            <div className="orgs-empty animate-fade-in-up">
              <h2 className="orgs-empty-title">No organizations yet</h2>
              <p className="orgs-empty-description">
                Create an organization to invite teammates, share projects, and manage access in one place.
              </p>
            </div>
          ) : (
            sortedOrganizations.map((org) => (
              <OrganizationCard
                key={org.id}
                title={org.name}
                subtitle={org.slug}
                meta={`${formatMemberCount(org.member_count)} · Updated ${formatRelativeTime(org.updated_at)}`}
                onOpen={() => handleOpenOrgProjects(org.id)}
              />
            ))
          )}
        </section>
      </div>
  );
}

function formatMemberCount(memberCount?: number): string {
  if (memberCount == null) return 'Members unknown';
  return `${memberCount} member${memberCount === 1 ? '' : 's'}`;
}

function OrganizationCard({
  title,
  subtitle,
  meta,
  onOpen,
  isPersonal = false,
}: {
  title: string;
  subtitle: string;
  meta: string;
  onOpen: () => void;
  isPersonal?: boolean;
}): React.JSX.Element {
  return (
    <div className={`org-card ${isPersonal ? 'org-card-personal' : ''} animate-fade-in-up`}>
      <div>
        <div className="org-card-header">
          <h3 className="org-card-title">{title}</h3>
          <span className={`org-badge ${isPersonal ? 'org-badge-personal' : ''}`}>{isPersonal ? 'Personal' : 'Org'}</span>
        </div>
        <p className="org-card-subtitle">{subtitle}</p>
        <p className="org-card-meta">{meta}</p>
      </div>
      <button
        type="button"
        className="org-card-action pressable"
        onClick={onOpen}
        data-haptic="light"
        aria-label={`Open projects for ${title}`}
      >
        Open projects
      </button>
    </div>
  );
}
