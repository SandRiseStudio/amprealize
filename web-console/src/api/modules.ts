import { useQuery } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';

export interface ApiModulesResponse {
  enabled_modules: string[];
  capability_flags: string[];
  all_modules: string[];
}

/**
 * Fallback when modules endpoint is unavailable (old backend).
 * Defaults to everything enabled so the UI doesn't hide sections
 * for users on a pre-modular backend.
 */
const LEGACY_FALLBACK: ApiModulesResponse = {
  enabled_modules: ['goals', 'agents', 'behaviors', 'self_improving'],
  capability_flags: ['goals', 'agents', 'behaviors', 'self_improving'],
  all_modules: ['goals', 'agents', 'behaviors', 'self_improving'],
};

const MODULES_QUERY_KEY = ['api', 'modules'] as const;

async function fetchModules(): Promise<ApiModulesResponse> {
  try {
    return await apiClient.get<ApiModulesResponse>('/v1/modules', { skipRetry: true });
  } catch (error: unknown) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 0)) {
      return LEGACY_FALLBACK;
    }
    if (error instanceof TypeError) {
      // Fetch-level network failures (often surfaced as CORS/network errors in browser)
      return LEGACY_FALLBACK;
    }
    throw error;
  }
}

export type UseModulesOptions = {
  /** When false, skips the API call (e.g. on /login where there is no bearer token). */
  enabled?: boolean;
};

/**
 * React Query hook for module availability.
 * Provides `isModuleEnabled(name)` helper for conditional rendering.
 */
export function useModules(options?: UseModulesOptions) {
  const query = useQuery({
    queryKey: MODULES_QUERY_KEY,
    queryFn: fetchModules,
    staleTime: 60_000,
    retry: 1,
    enabled: options?.enabled ?? true,
  });

  const enabledSet = new Set(query.data?.enabled_modules ?? LEGACY_FALLBACK.enabled_modules);

  return {
    ...query,
    isModuleEnabled: (name: string) => enabledSet.has(name),
    enabledModules: query.data?.enabled_modules ?? LEGACY_FALLBACK.enabled_modules,
  };
}
