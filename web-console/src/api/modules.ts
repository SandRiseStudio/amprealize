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
    if (error instanceof ApiError && error.status === 404) {
      return LEGACY_FALLBACK;
    }
    throw error;
  }
}

/**
 * React Query hook for module availability.
 * Provides `isModuleEnabled(name)` helper for conditional rendering.
 */
export function useModules() {
  const query = useQuery({
    queryKey: MODULES_QUERY_KEY,
    queryFn: fetchModules,
    staleTime: 60_000,
  });

  const enabledSet = new Set(query.data?.enabled_modules ?? LEGACY_FALLBACK.enabled_modules);

  return {
    ...query,
    isModuleEnabled: (name: string) => enabledSet.has(name),
    enabledModules: query.data?.enabled_modules ?? LEGACY_FALLBACK.enabled_modules,
  };
}
