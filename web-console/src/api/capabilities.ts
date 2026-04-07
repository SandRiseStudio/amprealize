import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';

export interface ApiRouteCapabilities {
  projects: boolean;
  participants: boolean;
  orgs: boolean;
  settings: boolean;
  executions: boolean;
}

export interface ApiCapabilitiesResponse {
  routes: ApiRouteCapabilities;
  services: {
    project_service: boolean;
    org_service: boolean;
    settings_service: boolean;
    execution_service: boolean;
    execution_enabled: boolean;
  };
}

/**
 * Conservative fallback when the capabilities endpoint is unavailable (old backend).
 * All flags default to false so the frontend does not probe routes that may not exist.
 */
const LEGACY_FALLBACK: ApiCapabilitiesResponse = {
  routes: {
    projects: false,
    participants: false,
    orgs: false,
    settings: false,
    executions: false,
  },
  services: {
    project_service: false,
    org_service: false,
    settings_service: false,
    execution_service: false,
    execution_enabled: false,
  },
};

const CAPABILITIES_QUERY_KEY = ['api', 'capabilities'] as const;

async function fetchCapabilities(): Promise<ApiCapabilitiesResponse> {
  try {
    return await apiClient.get<ApiCapabilitiesResponse>('/v1/capabilities', { skipRetry: true });
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404) {
      return LEGACY_FALLBACK;
    }
    throw error;
  }
}

/**
 * React Query hook — the single source of truth for capabilities.
 * All consumers should use this hook or getApiCapabilities() which reads from
 * the same React Query cache.
 */
export function useApiCapabilities() {
  return useQuery({
    queryKey: CAPABILITIES_QUERY_KEY,
    queryFn: fetchCapabilities,
    staleTime: 60_000,
  });
}

/**
 * Imperative accessor that reads/populates the React Query cache.
 * Use inside queryFn callbacks where hooks are not available.
 */
export async function getApiCapabilities(
  queryClient?: ReturnType<typeof useQueryClient>
): Promise<ApiCapabilitiesResponse> {
  if (queryClient) {
    return queryClient.fetchQuery({
      queryKey: CAPABILITIES_QUERY_KEY,
      queryFn: fetchCapabilities,
      staleTime: 60_000,
    });
  }
  // Without a queryClient, fall back to a direct fetch (still no module cache).
  return fetchCapabilities();
}
