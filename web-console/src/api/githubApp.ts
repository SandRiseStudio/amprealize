/**
 * GitHub App API hooks
 *
 * Provides React Query hooks for GitHub App installation management.
 * GitHub App is the recommended way to connect repositories - better security,
 * shorter token lifetimes, and no user secrets to manage.
 *
 * Following:
 * - behavior_design_api_contract (Student)
 * - COLLAB_SAAS_REQUIREMENTS.md: Cross-surface parity
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from './client';

// ---------------------------------------------------------------------------
// Types (aligned with backend github_app_installation_repository.py)
// ---------------------------------------------------------------------------

export interface GitHubAppInstallation {
  id: string;
  installation_id: number;
  app_id: number | null;
  account_type: 'User' | 'Organization';
  account_login: string;
  account_id: number;
  account_avatar_url: string | null;
  scope_type: 'org' | 'project';
  scope_id: string;
  repository_selection: 'all' | 'selected' | null;
  selected_repository_ids: number[];
  permissions: Record<string, string>;
  events: string[];
  has_required_permissions: boolean;
  permission_warning: string | null;
  is_active: boolean;
  suspended_at: string | null;
  suspended_reason: string | null;
  installed_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  metadata: Record<string, unknown>;
}

export interface GitHubAppStatus {
  configured: boolean;
  message: string;
}

export interface GitHubAppInstallationSummary {
  installation_id: number;
  account_login: string;
  account_type: 'User' | 'Organization';
  account_avatar_url?: string | null;
  repository_selection?: 'all' | 'selected' | null;
  html_url?: string | null;
  app_slug?: string | null;
}

export interface GitHubAppInstallUrlResponse {
  url: string;
  state: string;
}

export interface GitHubAppConfigureUrlResponse {
  url: string;
}

// ---------------------------------------------------------------------------
// Status Hook
// ---------------------------------------------------------------------------

/**
 * Check if GitHub App is configured on the backend
 */
export function useGitHubAppStatus() {
  return useQuery({
    queryKey: ['github-app', 'status'],
    queryFn: async () => {
      return await apiClient.get<GitHubAppStatus>('/v1/github-app/status');
    },
    staleTime: 60000, // 1 minute
  });
}

/**
 * Fetch GitHub App installations available to the app
 */
export function useGitHubAppInstallations() {
  return useQuery({
    queryKey: ['github-app', 'installations'],
    queryFn: async () => {
      return await apiClient.get<GitHubAppInstallationSummary[]>(
        '/v1/github-app/installations'
      );
    },
    staleTime: 30000,
  });
}

// ---------------------------------------------------------------------------
// Project Installation Hooks
// ---------------------------------------------------------------------------

/**
 * Fetch the GitHub App installation for a project
 */
export function useProjectGitHubAppInstallation(projectId: string | undefined) {
  return useQuery({
    queryKey: ['github-app', 'project', projectId],
    queryFn: async () => {
      if (!projectId) return null;
      // Backend returns null (not 404) when no installation exists
      return await apiClient.get<GitHubAppInstallation | null>(
        `/v1/projects/${projectId}/github-app-installation`
      );
    },
    enabled: !!projectId,
    staleTime: 30000, // 30 seconds
  });
}

/**
 * Get URL to install/configure GitHub App for a project
 */
export function useGitHubAppInstallUrl() {
  return useMutation({
    mutationFn: async ({
      scopeType,
      scopeId,
      redirectUri,
    }: {
      scopeType: 'project' | 'org';
      scopeId: string;
      redirectUri?: string;
    }) => {
      const params = new URLSearchParams({
        scope_type: scopeType,
        scope_id: scopeId,
      });
      if (redirectUri) {
        params.set('redirect_uri', redirectUri);
      }
      return apiClient.get<GitHubAppInstallUrlResponse>(
        `/v1/github-app/install-url?${params.toString()}`
      );
    },
  });
}

/**
 * Link a project to an existing GitHub App installation
 */
export function useLinkProjectToGitHubAppInstallation(
  projectId: string | undefined,
  actorId?: string
) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (installationId: number) => {
      if (!projectId) throw new Error('Project ID required');
      const actor = actorId || 'web-user';
      return apiClient.post<GitHubAppInstallation>(
        `/v1/projects/${projectId}/github-app-installation/link?actor_id=${encodeURIComponent(actor)}`,
        { installation_id: installationId }
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['github-app', 'project', projectId],
      });
    },
  });
}

/**
 * Unlink GitHub App installation from a project
 */
export function useUnlinkProjectGitHubAppInstallation(
  projectId: string | undefined,
  actorId?: string
) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error('Project ID required');
      const actor = actorId || 'web-user';
      return apiClient.delete(
        `/v1/projects/${projectId}/github-app-installation?actor_id=${encodeURIComponent(actor)}`
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['github-app', 'project', projectId],
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Organization Installation Hooks
// ---------------------------------------------------------------------------

/**
 * Fetch the GitHub App installation for an organization
 */
export function useOrgGitHubAppInstallation(orgId: string | undefined) {
  return useQuery({
    queryKey: ['github-app', 'org', orgId],
    queryFn: async () => {
      if (!orgId) return null;
      return await apiClient.get<GitHubAppInstallation | null>(
        `/v1/orgs/${orgId}/github-app-installation`
      );
    },
    enabled: !!orgId,
    staleTime: 30000,
  });
}

/**
 * Unlink GitHub App installation from an organization
 */
export function useUnlinkOrgGitHubAppInstallation(
  orgId: string | undefined,
  actorId?: string
) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      if (!orgId) throw new Error('Organization ID required');
      const actor = actorId || 'web-user';
      return apiClient.delete(
        `/v1/orgs/${orgId}/github-app-installation?actor_id=${encodeURIComponent(actor)}`
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['github-app', 'org', orgId],
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Configuration URL Hook
// ---------------------------------------------------------------------------

/**
 * Get URL to configure an existing installation's repo access
 */
export function useGitHubAppConfigureUrl() {
  return useMutation({
    mutationFn: async (installationId: number) => {
      return apiClient.get<GitHubAppConfigureUrlResponse>(
        `/v1/github-app/installation/${installationId}/configure-url`
      );
    },
  });
}
