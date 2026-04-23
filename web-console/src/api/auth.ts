/**
 * Authentication API hooks using device flow
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from './client';

/** Response from ``GET /v1/auth/oauth/{provider}/url`` (JSON authorize URL). */
export interface OAuthAuthorizationUrlResponse {
  url: string;
}

/**
 * Fetch the provider authorization URL over CORS (no redirect).
 * Used for the Google popup flow so the popup never navigates to the API origin.
 */
export async function getOAuthUrl(
  provider: 'github' | 'google',
  redirectUri: string,
  state: string,
): Promise<string> {
  const qs = new URLSearchParams({
    redirect_uri: redirectUri,
    state,
  });
  const data = await apiClient.get<OAuthAuthorizationUrlResponse>(
    `/v1/auth/oauth/${provider}/url?${qs.toString()}`,
    { skipAuth: true, skipRetry: true },
  );
  return data.url;
}

export interface DeviceCodeResponse {
  device_code: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete: string;
  expires_in: number;
  interval: number;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token?: string;
  scope?: string;
}

export interface PollResponse {
  status: 'pending' | 'approved' | 'denied' | 'expired';
  tokens?: TokenResponse;
  error?: string;
}

export interface UserInfo {
  id: string;
  username: string;
  roles: string[];
  scopes: string[];
}

// Start device flow authorization
export function useDeviceCodeRequest() {
  return useMutation({
    mutationFn: async (scopes?: string[]): Promise<DeviceCodeResponse> => {
      return apiClient.post('/v1/auth/device/authorize', {
        scopes: scopes || ['read', 'write']
      });
    },
  });
}

// Poll for device flow completion
export function usePollDeviceCode() {
  return useMutation({
    mutationFn: async (deviceCode: string): Promise<PollResponse> => {
      return apiClient.post('/v1/auth/device/token', { device_code: deviceCode });
    },
  });
}

// Refresh token
export function useRefreshToken() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (refreshToken: string): Promise<TokenResponse> => {
      return apiClient.post('/v1/auth/token/refresh', { refresh_token: refreshToken });
    },
    onSuccess: (data) => {
      apiClient.setToken(data.access_token);
      queryClient.invalidateQueries({ queryKey: ['auth', 'user'] });
    },
  });
}

// Get current user info
export function useCurrentUser() {
  return useQuery({
    queryKey: ['auth', 'user'],
    queryFn: async (): Promise<UserInfo> => {
      return apiClient.get('/v1/auth/me');
    },
    enabled: !!apiClient.getToken(),
    retry: false,
  });
}

// Logout
export function useLogout() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (): Promise<void> => {
      apiClient.setToken(null);
    },
    onSuccess: () => {
      queryClient.clear();
    },
  });
}

// Auth context helpers
export function isAuthenticated(): boolean {
  return !!apiClient.getToken();
}

export function setAuthToken(token: string | null) {
  apiClient.setToken(token);
}
