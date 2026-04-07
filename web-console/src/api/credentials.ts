/**
 * BYOK Credentials API hooks
 *
 * Provides React Query hooks for managing LLM provider credentials (BYOK).
 * Following:
 * - behavior_design_api_contract (Student)
 * - COLLAB_SAAS_REQUIREMENTS.md: Cross-surface parity
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from './client';

// ---------------------------------------------------------------------------
// Types (aligned with backend llm_credential_repository.py)
// ---------------------------------------------------------------------------

export interface LLMCredential {
  id: string;
  scope_type: 'org' | 'project';
  scope_id: string;
  provider: string;
  name: string;
  key_prefix: string;
  masked_key: string;
  is_valid: boolean;
  failure_count: number;
  last_used_at: string | null;
  last_validated_at: string | null;
  created_by: string;
  created_at: string;
  updated_at: string | null;
  metadata: Record<string, unknown>;
}

export interface CreateCredentialRequest {
  provider: string;
  api_key: string;
  name?: string;
}

export interface CredentialAuditEntry {
  audit_id: string;
  credential_id: string;
  action: string;
  actor_id: string;
  timestamp: string;
  details?: Record<string, unknown>;
}

export interface GitHubCredential {
  id: string;
  scope_type: 'org' | 'project';
  scope_id: string;
  token_type: 'classic' | 'fine_grained' | 'app' | 'unknown';
  name: string;
  token_prefix: string;
  masked_token: string;
  is_valid: boolean;
  failure_count: number;
  scopes?: string[] | null;
  has_required_scopes?: boolean;
  scope_warning?: string | null;
  rate_limit?: number | null;
  rate_limit_remaining?: number | null;
  rate_limit_reset?: string | null;
  last_used_at?: string | null;
  last_validated_at?: string | null;
  github_username?: string | null;
  github_user_id?: number | null;
  created_by?: string;
  created_at?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
  warning?: string;
}

export interface CreateGitHubCredentialRequest {
  token: string;
  name?: string;
}

// ---------------------------------------------------------------------------
// Provider display info
// ---------------------------------------------------------------------------

export const LLM_PROVIDERS = [
  {
    id: 'anthropic' as const,
    name: 'Anthropic',
    description: 'Claude models (Claude 4, Sonnet, Haiku)',
    placeholder: 'sk-ant-...',
    icon: '🤖',
  },
  {
    id: 'openai' as const,
    name: 'OpenAI',
    description: 'GPT models (GPT-4o, GPT-4, GPT-3.5)',
    placeholder: 'sk-...',
    icon: '🧠',
  },
  {
    id: 'openrouter' as const,
    name: 'OpenRouter',
    description: 'Access 100+ models via single API',
    placeholder: 'sk-or-...',
    icon: '🔀',
  },
] as const;

export type LLMProvider = (typeof LLM_PROVIDERS)[number]['id'];

// ---------------------------------------------------------------------------
// Project Credential Hooks
// ---------------------------------------------------------------------------

/**
 * Fetch all BYOK credentials for a project (keys returned as prefix only)
 */
export function useProjectCredentials(projectId: string | undefined) {
  return useQuery({
    queryKey: ['credentials', 'project', projectId],
    queryFn: async () => {
      if (!projectId) return [];
      const response = await apiClient.get<LLMCredential[] | { credentials: LLMCredential[] }>(
        `/v1/projects/${projectId}/credentials`
      );
      // Handle both array and wrapped response
      return Array.isArray(response) ? response : response.credentials ?? [];
    },
    enabled: !!projectId,
    staleTime: 30000, // 30 seconds
  });
}

/**
 * Add a new BYOK credential to a project
 */
export function useAddProjectCredential(projectId: string | undefined, actorId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: CreateCredentialRequest) => {
      if (!projectId) throw new Error('Project ID required');
      const actor = actorId || 'web-user';
      return apiClient.post<LLMCredential>(
        `/v1/projects/${projectId}/credentials?actor_id=${encodeURIComponent(actor)}`,
        request
      );
    },
    onSuccess: () => {
      // Invalidate credentials cache
      void queryClient.invalidateQueries({ queryKey: ['credentials', 'project', projectId] });
    },
  });
}

/**
 * Delete a BYOK credential from a project
 */
export function useDeleteProjectCredential(projectId: string | undefined, actorId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (credentialId: string) => {
      if (!projectId) throw new Error('Project ID required');
      const actor = actorId || 'web-user';
      return apiClient.delete(`/v1/projects/${projectId}/credentials/${credentialId}?actor_id=${encodeURIComponent(actor)}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['credentials', 'project', projectId] });
    },
  });
}

/**
 * Re-enable a disabled credential with a new API key
 */
export function useReEnableProjectCredential(projectId: string | undefined, actorId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ credentialId, apiKey }: { credentialId: string; apiKey: string }) => {
      if (!projectId) throw new Error('Project ID required');
      const actor = actorId || 'web-user';
      return apiClient.post<LLMCredential>(
        `/v1/projects/${projectId}/credentials/${credentialId}:re-enable?actor_id=${encodeURIComponent(actor)}`,
        { api_key: apiKey }
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['credentials', 'project', projectId] });
    },
  });
}

// ---------------------------------------------------------------------------
// GitHub Credential Hooks
// ---------------------------------------------------------------------------

/**
 * Fetch the BYOK GitHub credential for a project (masked token only)
 */
export function useProjectGitHubCredential(projectId: string | undefined) {
  return useQuery({
    queryKey: ['github-credential', 'project', projectId],
    queryFn: async () => {
      if (!projectId) return null;
      // Backend returns null (not 404) when no credential exists
      return await apiClient.get<GitHubCredential | null>(`/v1/projects/${projectId}/github-credential`);
    },
    enabled: !!projectId,
    staleTime: 30000,
  });
}

/**
 * Add or replace the BYOK GitHub credential for a project
 */
export function useAddProjectGitHubCredential(projectId: string | undefined, actorId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: CreateGitHubCredentialRequest) => {
      if (!projectId) throw new Error('Project ID required');
      const actor = actorId || 'web-user';
      return apiClient.post<GitHubCredential>(
        `/v1/projects/${projectId}/github-credential?actor_id=${encodeURIComponent(actor)}`,
        request
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['github-credential', 'project', projectId] });
    },
  });
}

/**
 * Delete the BYOK GitHub credential for a project
 */
export function useDeleteProjectGitHubCredential(projectId: string | undefined, actorId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error('Project ID required');
      const actor = actorId || 'web-user';
      return apiClient.delete(`/v1/projects/${projectId}/github-credential?actor_id=${encodeURIComponent(actor)}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['github-credential', 'project', projectId] });
    },
  });
}

// ---------------------------------------------------------------------------
// Organization Credential Hooks
// ---------------------------------------------------------------------------

/**
 * Fetch all BYOK credentials for an organization
 */
export function useOrgCredentials(orgId: string | undefined) {
  return useQuery({
    queryKey: ['credentials', 'org', orgId],
    queryFn: async () => {
      if (!orgId) return [];
      const response = await apiClient.get<LLMCredential[] | { credentials: LLMCredential[] }>(
        `/v1/orgs/${orgId}/credentials`
      );
      return Array.isArray(response) ? response : response.credentials ?? [];
    },
    enabled: !!orgId,
    staleTime: 30000,
  });
}

/**
 * Add a new BYOK credential to an organization
 */
export function useAddOrgCredential(orgId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: CreateCredentialRequest) => {
      if (!orgId) throw new Error('Organization ID required');
      return apiClient.post<LLMCredential>(`/v1/orgs/${orgId}/credentials`, request);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['credentials', 'org', orgId] });
    },
  });
}

/**
 * Delete a BYOK credential from an organization
 */
export function useDeleteOrgCredential(orgId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (credentialId: string) => {
      if (!orgId) throw new Error('Organization ID required');
      return apiClient.delete(`/v1/orgs/${orgId}/credentials/${credentialId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['credentials', 'org', orgId] });
    },
  });
}

/**
 * Re-enable a disabled org credential with a new API key
 */
export function useReEnableOrgCredential(orgId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ credentialId, apiKey }: { credentialId: string; apiKey: string }) => {
      if (!orgId) throw new Error('Organization ID required');
      return apiClient.post<LLMCredential>(
        `/v1/orgs/${orgId}/credentials/${credentialId}:re-enable`,
        { api_key: apiKey }
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['credentials', 'org', orgId] });
    },
  });
}
