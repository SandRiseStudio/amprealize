import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';

export interface PlatformRuntimeMetadataResponse {
  version: string;
  distribution: 'oss' | 'enterprise';
  edition: 'starter' | 'premium' | null;
  context_name: string;
}

/** Used when the runtime endpoint is missing (older API) or before first fetch. */
const LEGACY_FALLBACK: PlatformRuntimeMetadataResponse = {
  version: '0.1.0',
  distribution: 'oss',
  edition: null,
  context_name: 'unknown',
};

const PLATFORM_RUNTIME_QUERY_KEY = ['api', 'platform', 'runtime'] as const;

async function fetchPlatformRuntime(): Promise<PlatformRuntimeMetadataResponse> {
  try {
    return await apiClient.get<PlatformRuntimeMetadataResponse>('/v1/platform/runtime', { skipRetry: true });
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404) {
      return LEGACY_FALLBACK;
    }
    throw error;
  }
}

export function useApiPlatformRuntime() {
  return useQuery({
    queryKey: PLATFORM_RUNTIME_QUERY_KEY,
    queryFn: fetchPlatformRuntime,
    staleTime: 60_000,
    placeholderData: LEGACY_FALLBACK,
  });
}

export async function getApiPlatformRuntime(
  queryClient?: ReturnType<typeof useQueryClient>
): Promise<PlatformRuntimeMetadataResponse> {
  if (queryClient) {
    return queryClient.fetchQuery({
      queryKey: PLATFORM_RUNTIME_QUERY_KEY,
      queryFn: fetchPlatformRuntime,
      staleTime: 60_000,
    });
  }
  return fetchPlatformRuntime();
}
