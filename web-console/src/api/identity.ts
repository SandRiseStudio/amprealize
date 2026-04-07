/**
 * Identity & MFA API hooks
 *
 * API integration for:
 * - Social login (GitHub, Google)
 * - Identity linking/unlinking
 * - MFA setup and verification
 * - Email verification
 *
 * Following:
 * - behavior_design_api_contract (Teacher)
 * - behavior_validate_cross_surface_parity (Student)
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from './client';
import type {
  OAuthProvider,
  LinkIdentityResponse,
  LinkedProvidersResponse,
  MfaSetupResponse,
  MfaStatusResponse,
  MfaDevice,
  EmailVerificationStatus,
} from '../types/auth';

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

export const identityKeys = {
  all: ['identity'] as const,
  providers: (userId: string) => [...identityKeys.all, 'providers', userId] as const,
  mfaStatus: (userId: string) => [...identityKeys.all, 'mfa', userId] as const,
  mfaDevices: (userId: string) => [...identityKeys.all, 'mfa', 'devices', userId] as const,
  emailStatus: (userId: string) => [...identityKeys.all, 'email', userId] as const,
};

// ---------------------------------------------------------------------------
// Identity Linking
// ---------------------------------------------------------------------------

/**
 * Link an OAuth identity to the user's account
 */
export function useLinkIdentity() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (params: {
      provider: OAuthProvider;
      oauthAccessToken: string;
      oauthRefreshToken?: string;
      passwordConfirmation?: string;
      targetUserId?: string;
    }): Promise<LinkIdentityResponse> => {
      return apiClient.post('/v1/auth/identity/link', {
        provider: params.provider,
        oauth_access_token: params.oauthAccessToken,
        oauth_refresh_token: params.oauthRefreshToken,
        password_confirmation: params.passwordConfirmation,
        target_user_id: params.targetUserId,
      });
    },
    onSuccess: (_, variables) => {
      if (variables.targetUserId) {
        queryClient.invalidateQueries({
          queryKey: identityKeys.providers(variables.targetUserId),
        });
      }
    },
  });
}

/**
 * Unlink an OAuth identity from the user's account
 */
export function useUnlinkIdentity() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (params: {
      userId: string;
      provider: OAuthProvider;
      passwordConfirmation: string;
    }): Promise<{ status: string; message: string; provider: string }> => {
      return apiClient.post('/v1/auth/identity/unlink', {
        user_id: params.userId,
        provider: params.provider,
        password_confirmation: params.passwordConfirmation,
      });
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: identityKeys.providers(variables.userId),
      });
    },
  });
}

/**
 * Get all linked OAuth providers for a user
 */
export function useLinkedProviders(userId: string | undefined) {
  return useQuery({
    queryKey: identityKeys.providers(userId || ''),
    queryFn: async (): Promise<LinkedProvidersResponse> => {
      const response = await apiClient.get<{
        user_id: string;
        has_password: boolean;
        linked_providers: Array<{
          id: string;
          provider: OAuthProvider;
          provider_user_id: string;
          provider_email?: string;
          provider_username?: string;
          provider_display_name?: string;
          provider_avatar_url?: string;
          created_at?: string;
        }>;
        provider_count: number;
      }>(`/v1/auth/identity/providers?user_id=${userId}`);

      // Transform snake_case to camelCase
      return {
        userId: response.user_id,
        hasPassword: response.has_password,
        linkedProviders: response.linked_providers.map((p) => ({
          id: p.id,
          provider: p.provider,
          providerUserId: p.provider_user_id,
          providerEmail: p.provider_email,
          providerUsername: p.provider_username,
          providerDisplayName: p.provider_display_name,
          providerAvatarUrl: p.provider_avatar_url,
          createdAt: p.created_at || '',
        })),
        providerCount: response.provider_count,
      };
    },
    enabled: !!userId,
  });
}

// ---------------------------------------------------------------------------
// MFA Management
// ---------------------------------------------------------------------------

/**
 * Start MFA setup - generates QR code and secret
 */
export function useMfaSetup() {
  return useMutation({
    mutationFn: async (params: {
      userId: string;
      deviceName?: string;
    }): Promise<MfaSetupResponse> => {
      const response = await apiClient.post<{
        setup_id: string;
        secret: string;
        provisioning_uri: string;
        qr_code_base64: string;
        backup_codes?: string[];
      }>('/v1/auth/mfa/setup', {
        user_id: params.userId,
        device_name: params.deviceName || 'Authenticator App',
      });

      return {
        setupId: response.setup_id,
        secret: response.secret,
        provisioningUri: response.provisioning_uri,
        qrCodeBase64: response.qr_code_base64,
        backupCodes: response.backup_codes,
      };
    },
  });
}

/**
 * Verify MFA setup with a code from authenticator
 */
export function useVerifyMfaSetup() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (params: {
      setupId: string;
      code: string;
      userId: string;
    }): Promise<{ status: string; deviceId: string; backupCodes: string[] }> => {
      const response = await apiClient.post<{
        status: string;
        device_id: string;
        backup_codes: string[];
      }>('/v1/auth/mfa/verify-setup', {
        setup_id: params.setupId,
        code: params.code,
      });

      return {
        status: response.status,
        deviceId: response.device_id,
        backupCodes: response.backup_codes,
      };
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: identityKeys.mfaStatus(variables.userId),
      });
      queryClient.invalidateQueries({
        queryKey: identityKeys.mfaDevices(variables.userId),
      });
    },
  });
}

/**
 * Verify MFA code during login
 */
export function useVerifyMfa() {
  return useMutation({
    mutationFn: async (params: {
      userId: string;
      code: string;
      deviceId?: string;
    }): Promise<{ valid: boolean; deviceId: string }> => {
      const response = await apiClient.post<{
        valid: boolean;
        device_id: string;
      }>('/v1/auth/mfa/verify', {
        user_id: params.userId,
        code: params.code,
        device_id: params.deviceId,
      });

      return {
        valid: response.valid,
        deviceId: response.device_id,
      };
    },
  });
}

/**
 * Get MFA status for a user
 */
export function useMfaStatus(userId: string | undefined) {
  return useQuery({
    queryKey: identityKeys.mfaStatus(userId || ''),
    queryFn: async (): Promise<MfaStatusResponse> => {
      const response = await apiClient.get<{
        user_id: string;
        mfa_enabled: boolean;
        device_count: number;
        primary_device?: {
          id: string;
          device_type: string;
          device_name: string;
          is_primary: boolean;
          created_at: string;
          last_used_at?: string;
        };
      }>(`/v1/auth/mfa/status?user_id=${userId}`);

      return {
        userId: response.user_id,
        mfaEnabled: response.mfa_enabled,
        deviceCount: response.device_count,
        primaryDevice: response.primary_device
          ? {
              id: response.primary_device.id,
              deviceType: response.primary_device.device_type as 'totp',
              deviceName: response.primary_device.device_name,
              isPrimary: response.primary_device.is_primary,
              createdAt: response.primary_device.created_at,
              lastUsedAt: response.primary_device.last_used_at,
            }
          : undefined,
      };
    },
    enabled: !!userId,
  });
}

/**
 * Get all MFA devices for a user
 */
export function useMfaDevices(userId: string | undefined) {
  return useQuery({
    queryKey: identityKeys.mfaDevices(userId || ''),
    queryFn: async (): Promise<MfaDevice[]> => {
      const response = await apiClient.get<{
        user_id: string;
        devices: Array<{
          id: string;
          device_type: string;
          device_name: string;
          is_primary: boolean;
          created_at: string;
          last_used_at?: string;
        }>;
      }>(`/v1/auth/mfa/devices?user_id=${userId}`);

      return response.devices.map((d) => ({
        id: d.id,
        deviceType: d.device_type as 'totp',
        deviceName: d.device_name,
        isPrimary: d.is_primary,
        createdAt: d.created_at,
        lastUsedAt: d.last_used_at,
      }));
    },
    enabled: !!userId,
  });
}

/**
 * Delete an MFA device
 */
export function useDeleteMfaDevice() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (params: {
      deviceId: string;
      userId: string;
      password: string;
    }): Promise<{ status: string; mfaStillEnabled: boolean }> => {
      // Use POST to /revoke endpoint since DELETE with body is non-standard
      const response = await apiClient.post<{
        status: string;
        mfa_still_enabled: boolean;
      }>(`/v1/auth/mfa/devices/${params.deviceId}/revoke`, {
        user_id: params.userId,
        password: params.password,
      });

      return {
        status: response.status,
        mfaStillEnabled: response.mfa_still_enabled,
      };
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: identityKeys.mfaStatus(variables.userId),
      });
      queryClient.invalidateQueries({
        queryKey: identityKeys.mfaDevices(variables.userId),
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Email Verification
// ---------------------------------------------------------------------------

/**
 * Send email verification link
 */
export function useSendVerificationEmail() {
  return useMutation({
    mutationFn: async (userId: string): Promise<{ status: string; message: string }> => {
      return apiClient.post('/v1/auth/email/send-verification', {
        user_id: userId,
      });
    },
  });
}

/**
 * Verify email with token
 */
export function useVerifyEmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (params: {
      userId: string;
      token: string;
    }): Promise<{ status: string; message: string }> => {
      return apiClient.post('/v1/auth/email/verify', {
        user_id: params.userId,
        token: params.token,
      });
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: identityKeys.emailStatus(variables.userId),
      });
    },
  });
}

/**
 * Get email verification status
 */
export function useEmailVerificationStatus(userId: string | undefined) {
  return useQuery({
    queryKey: identityKeys.emailStatus(userId || ''),
    queryFn: async (): Promise<EmailVerificationStatus> => {
      const response = await apiClient.get<{
        user_id: string;
        email?: string;
        email_verified: boolean;
        verification_pending: boolean;
      }>(`/v1/auth/email/status?user_id=${userId}`);

      return {
        userId: response.user_id,
        email: response.email,
        emailVerified: response.email_verified,
        verificationPending: response.verification_pending,
      };
    },
    enabled: !!userId,
  });
}
