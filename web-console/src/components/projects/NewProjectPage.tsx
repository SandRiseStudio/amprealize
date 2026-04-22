/**
 * New Project Page
 *
 * Create-project flow entrypoint from Dashboard.
 *
 * Note: COLLAB_SAAS_REQUIREMENTS.md mentions subtle gradients/shadows for beauty,
 * but repo design constraints explicitly disable gradients/shadows; this page
 * follows the repo constraints.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useShellTitle } from '../workspace/useShell';
import { useOrganizations } from '../../api/dashboard';
import { useCreateProject } from '../../api/projects';
import { CREATE_PROJECT_CTA, SCOPE_LABEL } from '../../copy/scopeLabels';
import { orgContextStore, useOrgContext } from '../../store/orgContextStore';
import './NewProjectPage.css';

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
  if (!trimmed) return 'Project name is required';
  if (trimmed.length < 3) return 'Project name must be at least 3 characters';
  if (trimmed.length > 80) return 'Project name must be 80 characters or less';
  return null;
}

export function NewProjectPage(): React.JSX.Element {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { currentOrgId } = useOrgContext();
  const { data: organizations = [], isFetched: organizationsFetched } = useOrganizations();
  const mutation = useCreateProject();

  const orgFromQuery = searchParams.get('org');

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [localPath, setLocalPath] = useState('');
  const [githubRepo, setGithubRepo] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'internal' | 'public'>('private');
  const [step, setStep] = useState<1 | 2 | 3>(1);

  const nameError = useMemo(() => validateName(name), [name]);
  const suggestedSlug = useMemo(() => slugify(name), [name]);
  useEffect(() => {
    if (!organizationsFetched) return;
    if (!orgFromQuery) return;
    const orgExists = organizations.some((org) => org.id === orgFromQuery);
    if (!orgExists) {
      if (currentOrgId !== null) {
        orgContextStore.setCurrentOrgId(null);
      }
      const next = new URLSearchParams(searchParams);
      next.delete('org');
      setSearchParams(next, { replace: true });
      return;
    }
    if (orgFromQuery !== currentOrgId) {
      orgContextStore.setCurrentOrgId(orgFromQuery);
    }
  }, [currentOrgId, orgFromQuery, organizations, organizationsFetched, searchParams, setSearchParams]);

  const canContinue = useMemo(() => {
    if (step === 1) return !nameError;
    if (step === 2) return true;
    return true;
  }, [nameError, step]);

  const handleNext = useCallback(() => {
    if (!canContinue) return;
    setStep((s) => (s === 1 ? 2 : s === 2 ? 3 : 3));
  }, [canContinue]);

  const handleBack = useCallback(() => {
    setStep((s) => (s === 3 ? 2 : s === 2 ? 1 : 1));
  }, []);

  const handleCreate = useCallback(async () => {
    if (nameError) return;

    const payload = {
      name: name.trim(),
      description: description.trim() ? description.trim() : undefined,
      visibility,
      slug: suggestedSlug || undefined,
      local_path: localPath.trim() ? localPath.trim() : undefined,
      github_repo: githubRepo.trim() ? githubRepo.trim() : undefined,
    };

    await mutation.mutateAsync({ orgId: currentOrgId ?? undefined, payload });
    const nextPath = currentOrgId ? `/projects?org=${encodeURIComponent(currentOrgId)}` : '/projects';
    navigate(nextPath, { replace: true });
  }, [currentOrgId, description, githubRepo, localPath, mutation, name, nameError, navigate, suggestedSlug, visibility]);

  useShellTitle('New Project');

  return (
      <div className="new-project-page">
        <header className="new-project-header">
          <div className="new-project-header-left">
            <button
              type="button"
              className="new-project-back pressable"
              onClick={() => navigate('/')}
              data-haptic="light"
            >
              Back
            </button>
            <div>
              <h1 className="new-project-title animate-fade-in-up">Create a new project</h1>
              <p className="new-project-subtitle animate-fade-in-up">
                Set up a project with the right {SCOPE_LABEL.toLowerCase()}, visibility, and collaboration-ready structure.
              </p>
            </div>
          </div>

        </header>

        <section className="new-project-stepper" aria-label="Project creation steps">
          <div className={`stepper-pill ${step === 1 ? 'active' : ''}`}>1 · Details</div>
          <div className={`stepper-pill ${step === 2 ? 'active' : ''}`}>2 · Visibility</div>
          <div className={`stepper-pill ${step === 3 ? 'active' : ''}`}>3 · Review</div>
        </section>

        <section className="new-project-card" aria-label="Create project form">
          {step === 1 && (
            <div className="new-project-panel animate-fade-in-up">
              <label className="field">
                <span className="field-label">Project name</span>
                <input
                  className={`field-input ${nameError ? 'error' : ''}`}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Collab Console"
                  autoFocus
                  aria-invalid={Boolean(nameError)}
                />
                <span className="field-hint">
                  Slug preview: <code className="mono">{suggestedSlug || '—'}</code>
                </span>
                {nameError && <span className="field-error">{nameError}</span>}
              </label>

              <label className="field">
                <span className="field-label">Description (optional)</span>
                <textarea
                  className="field-textarea"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What is this project for?"
                  rows={4}
                />
              </label>

              <label className="field">
                <span className="field-label">Local project path (optional)</span>
                <input
                  className="field-input"
                  value={localPath}
                  onChange={(e) => setLocalPath(e.target.value)}
                  placeholder="/path/to/your/project"
                />
                <span className="field-hint">
                  Absolute path to the project folder. Used for IDE integrations.
                </span>
              </label>

              <label className="field">
                <span className="field-label">GitHub repository (optional)</span>
                <input
                  className="field-input"
                  value={githubRepo}
                  onChange={(e) => setGithubRepo(e.target.value)}
                  placeholder="https://github.com/owner/repo"
                />
                <span className="field-hint">
                  Link your project to a GitHub repository. You can configure branches later in settings.
                </span>
              </label>
            </div>
          )}

          {step === 2 && (
            <div className="new-project-panel animate-fade-in-up">
              <div className="field">
                <span className="field-label">Visibility</span>
                <div className="segmented" role="radiogroup" aria-label="Project visibility">
                  {(['private', 'internal', 'public'] as const).map((v) => (
                    <button
                      key={v}
                      type="button"
                      className={`segmented-item pressable ${visibility === v ? 'selected' : ''}`}
                      role="radio"
                      aria-checked={visibility === v}
                      onClick={() => setVisibility(v)}
                      data-haptic="light"
                    >
                      {v}
                    </button>
                  ))}
                </div>
                <span className="field-hint">
                  {visibility === 'private' && 'Only you (and explicitly added members) can access this project.'}
                  {visibility === 'internal' && 'Anyone in the organization can discover and access this project.'}
                  {visibility === 'public' && 'Anyone with the link can access this project (use with care).'}
                </span>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="new-project-panel animate-fade-in-up">
              <div className="review">
                <div className="review-row">
                  <span className="review-label">Name</span>
                  <span className="review-value">{name.trim() || '—'}</span>
                </div>
                <div className="review-row">
                  <span className="review-label">Slug</span>
                  <span className="review-value mono">{suggestedSlug || '—'}</span>
                </div>
                <div className="review-row">
                  <span className="review-label">Visibility</span>
                  <span className="review-value">{visibility}</span>
                </div>
                {description.trim() && (
                  <div className="review-row">
                    <span className="review-label">Description</span>
                    <span className="review-value">{description.trim()}</span>
                  </div>
                )}
                {localPath.trim() && (
                  <div className="review-row">
                    <span className="review-label">Local path</span>
                    <span className="review-value mono">{localPath.trim()}</span>
                  </div>
                )}
                {githubRepo.trim() && (
                  <div className="review-row">
                    <span className="review-label">GitHub repo</span>
                    <span className="review-value">{githubRepo.trim()}</span>
                  </div>
                )}
              </div>

              {mutation.isError && (
                <div className="submit-error" role="alert">
                  {mutation.error instanceof Error ? mutation.error.message : 'Failed to create project'}
                </div>
              )}
            </div>
          )}

          <div className="new-project-actions">
            <button type="button" className="action secondary pressable" onClick={handleBack} disabled={step === 1}>
              Back
            </button>

            {step < 3 ? (
              <button
                type="button"
                className="action primary pressable"
                onClick={handleNext}
                disabled={!canContinue}
                data-haptic="light"
              >
                Next
              </button>
            ) : (
              <button
                type="button"
                className="action primary pressable"
                onClick={() => void handleCreate()}
                disabled={mutation.isPending || Boolean(nameError)}
                data-haptic="medium"
              >
                {mutation.isPending ? 'Creating…' : CREATE_PROJECT_CTA}
              </button>
            )}
          </div>
        </section>
      </div>
  );
}
