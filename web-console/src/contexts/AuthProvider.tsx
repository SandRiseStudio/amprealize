/**
 * Amprealize web console authentication context
 *
 * React context provider that wraps authStore and provides:
 * - Device flow login/logout actions
 * - Auto token refresh (background)
 * - Consent flow handlers
 * - Telemetry integration (via RazeClient)
 *
 * Usage:
 *   <AuthProvider>
 *     <App />
 *   </AuthProvider>
 *
 *   const { isAuthenticated, actor, login, logout } = useAuth();
 *
 * Following:
 * - behavior_use_raze_for_logging (Student)
 * - behavior_integrate_vscode_extension (Teacher) - matching extension patterns
 */

import {
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from 'react';
import { AuthContext, type AuthContextValue } from './auth-context';
import { OAUTH_WEB_CLIENT_ID } from '../config/branding';
import { authStore, useAuthStore, AUTH_STORE_INSTANCE_ID } from '../stores/authStore';
import { apiClient, ApiError } from '../api/client';
import { orgContextStore } from '../store/orgContextStore';
import type {
  AuthSession,
  AuthTokens,
  DeviceCodeResponse,
  ConsentDecision,
  ConsentResponse,
  ActorIdentity,
  AuthTelemetryEvent,
  AuthTelemetryPayload,
} from '../types/auth';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TOKEN_REFRESH_MARGIN_MS = 2 * 60 * 1000; // Refresh 2 minutes before expiry
const DEVICE_POLL_INTERVAL_MS = 5000; // Poll every 5 seconds
const MAX_POLL_ATTEMPTS = 60; // 5 minutes max polling

// ---------------------------------------------------------------------------
// Telemetry Helper
// ---------------------------------------------------------------------------

function emitAuthTelemetry(event: AuthTelemetryEvent, extra?: Partial<AuthTelemetryPayload>): void {
  // TODO: Wire to RazeClient when available
  console.debug('[Auth Telemetry]', event, extra);
}

// ---------------------------------------------------------------------------
// Provider Component
// ---------------------------------------------------------------------------

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps): React.JSX.Element {
  const store = useAuthStore();

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const refreshTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep API client and auth state in sync when the backend rejects auth entirely.
  // Following `behavior_lock_down_security_surface` (Student): fail closed on 401s.
  useEffect(() => {
    apiClient.setOnUnauthorized(() => {
      orgContextStore.setCurrentOrgId(null);
      authStore.clearSession();
      authStore.setError('Session expired. Please sign in again.');
    });
    return () => apiClient.setOnUnauthorized(null);
  }, []);

  // Keep ApiClient's in-memory token cache synchronized with AuthStore.
  useEffect(() => {
    const accessToken = store.session?.tokens?.accessToken ?? null;
    const refreshToken = store.session?.tokens?.refreshToken ?? null;
    apiClient.setToken(accessToken);
    apiClient.setRefreshToken(refreshToken);
  }, [store.session?.tokens?.accessToken, store.session?.tokens?.refreshToken]);

  // ---------------------------------------------------------------------------
  // Token Refresh Logic
  // ---------------------------------------------------------------------------

  const refreshToken = useCallback(async (): Promise<boolean> => {
    const session = authStore.getState().session;
    if (!session?.tokens?.refreshToken) {
      return false;
    }

    authStore.setRefreshing(true);
    const startTime = Date.now();

    try {
      // Prefer the modern endpoint, but fall back for older backends.
      // Important: `skipAuth` prevents attaching a potentially expired access token,
      // and `skipRetry` prevents recursive refresh attempts on 401s.
      const endpoints = ['/v1/auth/token/refresh', '/v1/auth/device/refresh'];
      let response: { access_token: string; refresh_token: string; expires_in: number; token_type: string } | null = null;
      for (const endpoint of endpoints) {
        try {
          response = await apiClient.post<{
            access_token: string;
            refresh_token: string;
            expires_in: number;
            token_type: string;
          }>(
            endpoint,
            { refresh_token: session.tokens.refreshToken },
            { skipAuth: true, skipRetry: true }
          );
          break;
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            continue;
          }
          throw error;
        }
      }
      if (!response) {
        authStore.setRefreshing(false);
        return false;
      }

      const newTokens: AuthTokens = {
        accessToken: response.access_token,
        refreshToken: response.refresh_token,
        tokenType: 'Bearer',
        expiresAt: Date.now() + response.expires_in * 1000,
        scopes: session.tokens.scopes,
      };

      authStore.updateTokens(newTokens);
      apiClient.setToken(newTokens.accessToken);
      apiClient.setRefreshToken(newTokens.refreshToken ?? null);
      emitAuthTelemetry('auth_token_refreshed', {
        durationMs: Date.now() - startTime,
      });

      return true;
    } catch (error) {
      console.error('[AuthContext] Token refresh failed:', error);
      emitAuthTelemetry('auth_token_refresh_failed', {
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      authStore.setRefreshing(false);
      // Don't clear session on refresh failure - let 401 handler do it
      return false;
    }
  }, []);

  // Schedule token refresh before expiry
  const scheduleTokenRefresh = useCallback(() => {
    if (refreshTimeoutRef.current) {
      clearTimeout(refreshTimeoutRef.current);
    }

    const session = authStore.getState().session;
    if (!session?.tokens?.expiresAt) return;

    const expiresIn = session.tokens.expiresAt - Date.now();
    const refreshIn = Math.max(expiresIn - TOKEN_REFRESH_MARGIN_MS, 0);

    if (refreshIn > 0) {
      refreshTimeoutRef.current = setTimeout(() => {
        refreshToken();
      }, refreshIn);
    } else {
      // Token already expired or about to expire
      refreshToken();
    }
  }, [refreshToken]);

  // ---------------------------------------------------------------------------
  // Device Flow Login
  // ---------------------------------------------------------------------------

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const startLogin = useCallback(async (): Promise<void> => {
    if (import.meta.env.DEV) {
      console.log('[AuthContext] AUTH_STORE_INSTANCE_ID', AUTH_STORE_INSTANCE_ID);
    }
    // Ensure any previous device-flow interval is cleared before starting again.
    // Otherwise a stale interval can keep polling with an old device_code while
    // the UI has been reset to `pending` (no deviceCode), making it look like
    // the authorize response never arrived.
    stopPolling();
    authStore.startDeviceFlow();
    emitAuthTelemetry('auth_login_started', { surface: 'WEB' });

    try {
      // Request device code - backend returns snake_case, we need camelCase
      // Use skipAuth since device flow doesn't require existing authentication
      const rawResponse = await apiClient.post<{
        device_code: string;
        user_code: string;
        verification_uri: string;
        verification_uri_complete: string;
        expires_in: number;
        interval: number;
        status: string;
      }>(
        '/v1/auth/device/authorize',
        {
          client_id: OAUTH_WEB_CLIENT_ID,
          scopes: ['openid', 'profile', 'email', 'offline_access'],
          surface: 'WEB',
        },
        { skipAuth: true }
      );

      // Transform to camelCase for frontend.
      // Be tolerant of either snake_case (FastAPI) or camelCase (other backends/proxies)
      // to avoid silently rendering an empty code/URI.
      const anyResponse = rawResponse as unknown as Record<string, unknown>;
      const deviceCode = (anyResponse.device_code ?? anyResponse.deviceCode) as string | undefined;
      const userCode = (anyResponse.user_code ?? anyResponse.userCode) as string | undefined;
      const verificationUri = (anyResponse.verification_uri ?? anyResponse.verificationUri) as string | undefined;
      const verificationUriComplete = (anyResponse.verification_uri_complete ?? anyResponse.verificationUriComplete) as string | undefined;
      const expiresIn = (anyResponse.expires_in ?? anyResponse.expiresIn) as number | undefined;
      const interval = (anyResponse.interval ?? anyResponse.pollInterval ?? anyResponse.poll_interval) as number | undefined;

      if (!deviceCode || !userCode || !verificationUri || !expiresIn) {
        throw new Error('Invalid device authorization response (missing device code/user code/verification URI)');
      }

      const deviceCodeResponse: DeviceCodeResponse = {
        deviceCode,
        userCode,
        verificationUri,
        verificationUriComplete: verificationUriComplete ?? verificationUri,
        expiresIn,
        interval: interval ?? 5,
      };

      authStore.setDeviceCode(deviceCodeResponse);
      console.log('[AuthContext] Device code received', deviceCodeResponse);
      if (import.meta.env.DEV) {
        console.log('[AuthContext] store.deviceFlow after setDeviceCode', authStore.getState().deviceFlow);
      }

      // Start polling for authorization
      const pollIntervalMs = Math.max(
        DEVICE_POLL_INTERVAL_MS,
        (deviceCodeResponse.interval || 5) * 1000
      );

      pollIntervalRef.current = setInterval(async () => {
        const state = authStore.getState();
        const { deviceFlow } = state;

        if (deviceFlow.pollCount >= MAX_POLL_ATTEMPTS) {
          authStore.setDeviceFlowStatus('expired', 'Authorization timed out');
          stopPolling();
          return;
        }

        authStore.incrementPollCount();

        try {
          // Poll for token - skipAuth since we're trying to obtain tokens
          const tokenResponse = await apiClient.post<{
            access_token: string;
            refresh_token: string;
            expires_in: number;
            token_type: string;
            id_token?: string;
          }>('/v1/auth/device/token', {
            grant_type: 'urn:ietf:params:oauth:grant-type:device_code',
            device_code: deviceCodeResponse.deviceCode,
            client_id: OAUTH_WEB_CLIENT_ID,
          }, { skipAuth: true });

          // Authorization successful!
          stopPolling();
          authStore.setDeviceFlowStatus('authorized');

          // Fetch user info with the new access token
          // Use skipAuth to prevent the client from using any stale stored token
          const userInfo = await apiClient.get<{
            sub: string;
            name?: string;
            email?: string;
            picture?: string;
            roles?: string[];
          }>('/v1/auth/me', {
            skipAuth: true,
            headers: {
              Authorization: `Bearer ${tokenResponse.access_token}`,
            },
          });

          const actor: ActorIdentity = {
            id: userInfo.sub,
            type: 'human',
            role: (userInfo.roles?.[0] as ActorIdentity['role']) ?? 'STUDENT',
            surface: 'WEB',
            displayName: userInfo.name,
            email: userInfo.email,
            avatarUrl: userInfo.picture,
          };

          const session: AuthSession = {
            id: `session_${Date.now()}`,
            actor,
            tokens: {
              accessToken: tokenResponse.access_token,
              refreshToken: tokenResponse.refresh_token,
              tokenType: 'Bearer',
              expiresAt: Date.now() + tokenResponse.expires_in * 1000,
              scopes: ['openid', 'profile', 'email', 'offline_access'],
            },
            createdAt: Date.now(),
            lastActiveAt: Date.now(),
          };

          authStore.setSession(session);
          apiClient.setToken(tokenResponse.access_token);
          apiClient.setRefreshToken(tokenResponse.refresh_token ?? null);
          emitAuthTelemetry('auth_login_completed', {
            actorId: actor.id,
            actorType: actor.type,
            surface: 'WEB',
          });
        } catch (error: unknown) {
          // Check for pending authorization (expected during polling)
          const apiError = error instanceof ApiError ? error : (error as { status?: number; code?: string; details?: unknown; message?: string });
          const details = (apiError instanceof ApiError ? apiError.details : apiError.details) as unknown;
          const detailsObj = typeof details === 'object' && details !== null ? (details as Record<string, unknown>) : null;

          const status = (apiError instanceof ApiError ? apiError.status : apiError.status) as number | undefined;
          const errorCode =
            (apiError instanceof ApiError ? apiError.code : apiError.code) ||
            (typeof detailsObj?.error === 'string' ? (detailsObj.error as string) : undefined);

          // RFC 8628 expected states during polling: keep polling, don't spam console.
          if (status === 400 && (errorCode === 'authorization_pending' || errorCode === 'slow_down')) {
            return;
          }
          // Some backends may omit `error` but provide an interval + pending description.
          if (
            status === 400 &&
            typeof detailsObj?.interval === 'number' &&
            typeof apiError.message === 'string' &&
            apiError.message.toLowerCase().includes('pending')
          ) {
            return;
          }

          if (status === 404) {
            authStore.setDeviceFlowStatus('expired', 'Device code not found. Please get a new code.');
            stopPolling();
            emitAuthTelemetry('auth_login_failed', { error: 'device_code_not_found' });
            return;
          }

          if (errorCode === 'access_denied') {
            authStore.setDeviceFlowStatus('denied', 'Authorization denied');
            stopPolling();
            emitAuthTelemetry('auth_login_failed', { error: 'access_denied' });
            return;
          }
          if (errorCode === 'expired_token') {
            authStore.setDeviceFlowStatus('expired', 'Device code expired');
            stopPolling();
            emitAuthTelemetry('auth_login_failed', { error: 'expired_token' });
            return;
          }
          // Other error - log but don't throw to avoid breaking the polling loop
          console.warn('[AuthContext] Token poll error', {
            status,
            code: errorCode,
            message: apiError instanceof Error ? apiError.message : String(apiError),
          });
        }
      }, pollIntervalMs);
    } catch (error) {
      console.error('[AuthContext] Device flow error:', error);
      stopPolling();
      authStore.setDeviceFlowStatus('error', error instanceof Error ? error.message : 'Login failed');
      emitAuthTelemetry('auth_login_failed', {
        error: error instanceof Error ? error.message : 'Unknown error',
      });
    }
  }, [stopPolling]);

  const cancelLogin = useCallback(() => {
    stopPolling();
    authStore.resetDeviceFlow();
  }, [stopPolling]);

  // ---------------------------------------------------------------------------
  // Client Credentials Login (for agents/services)
  // ---------------------------------------------------------------------------

  const loginWithClientCredentials = useCallback(async (clientId: string, clientSecret: string): Promise<void> => {
    try {
      emitAuthTelemetry('auth_login_started', {
        surface: 'WEB',
      });

      // Exchange client credentials for access token
      const tokenResponse = await apiClient.post<{
        access_token: string;
        token_type: string;
        expires_in: number;
        refresh_token?: string;
        scope?: string;
      }>('/v1/auth/token', {
        grant_type: 'client_credentials',
        client_id: clientId,
        client_secret: clientSecret,
      });

      // Create actor identity for agent/service
      const actor: ActorIdentity = {
        id: clientId,
        type: 'agent',
        role: 'STUDENT',
        surface: 'WEB',
        displayName: `Agent ${clientId.substring(0, 8)}`,
      };

      const session: AuthSession = {
        id: `session_${Date.now()}`,
        actor,
        tokens: {
          accessToken: tokenResponse.access_token,
          refreshToken: tokenResponse.refresh_token,
          tokenType: 'Bearer',
          expiresAt: Date.now() + tokenResponse.expires_in * 1000,
          scopes: tokenResponse.scope?.split(' ') || ['agent'],
        },
        createdAt: Date.now(),
        lastActiveAt: Date.now(),
      };

      authStore.setSession(session);
      emitAuthTelemetry('auth_login_completed', {
        actorId: actor.id,
        actorType: actor.type,
        surface: 'WEB',
      });
    } catch (error) {
      console.error('[AuthContext] Client credentials login failed:', error);
      emitAuthTelemetry('auth_login_failed', {
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      throw error;
    }
  }, []);

  // ---------------------------------------------------------------------------
  // OAuth Social Login (GitHub, Google)
  // ---------------------------------------------------------------------------

  const completeOAuthLogin = useCallback(async (code: string, state?: string): Promise<void> => {
    try {
      emitAuthTelemetry('auth_login_started', {
        surface: 'WEB',
      });

      // Exchange authorization code for tokens
      const redirectUri = `${window.location.origin}/auth/callback`;
      const tokenResponse = await apiClient.post<{
        access_token: string;
        token_type: string;
        expires_in: number;
        refresh_token?: string;
        scope?: string;
        user: {
          id: string;
          email?: string;
          display_name?: string;
          provider: string;
        };
      }>('/v1/auth/oauth/callback', {
        code,
        state,
        redirect_uri: redirectUri,
      });

      // Create actor identity from OAuth user info
      const actor: ActorIdentity = {
        id: tokenResponse.user.id,
        type: 'human',
        role: 'STUDENT',
        surface: 'WEB',
        displayName: tokenResponse.user.display_name ?? tokenResponse.user.email ?? tokenResponse.user.id,
      };

      const session: AuthSession = {
        id: `session_${Date.now()}`,
        actor,
        tokens: {
          accessToken: tokenResponse.access_token,
          refreshToken: tokenResponse.refresh_token,
          tokenType: 'Bearer',
          expiresAt: Date.now() + tokenResponse.expires_in * 1000,
          scopes: tokenResponse.scope?.split(' ') || ['profile', 'email'],
        },
        createdAt: Date.now(),
        lastActiveAt: Date.now(),
      };

      authStore.setSession(session);
      // Keep API client + localStorage in sync; otherwise subsequent requests
      // will use stale tokens and trigger a refresh/logout loop.
      apiClient.setToken(tokenResponse.access_token);
      apiClient.setRefreshToken(tokenResponse.refresh_token ?? null);
      emitAuthTelemetry('auth_login_completed', {
        actorId: actor.id,
        actorType: actor.type,
        surface: 'WEB',
      });
    } catch (error) {
      console.error('[AuthContext] OAuth login failed:', error);
      emitAuthTelemetry('auth_login_failed', {
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      throw error;
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Logout
  // ---------------------------------------------------------------------------

  const logout = useCallback(async (): Promise<void> => {
    const actorId = authStore.actor?.id;

    try {
      // Call logout endpoint if we have a token
      const token = authStore.accessToken;
      if (token) {
        await apiClient.post('/v1/auth/logout', {}, {
          headers: { Authorization: `Bearer ${token}` },
        }).catch(() => {
          // Ignore logout API errors
        });
      }
    } finally {
      orgContextStore.setCurrentOrgId(null);
      authStore.clearSession();
      apiClient.clearTokens();
      stopPolling();
      if (refreshTimeoutRef.current) {
        clearTimeout(refreshTimeoutRef.current);
      }
      emitAuthTelemetry('auth_logout', { actorId });
    }
  }, [stopPolling]);

  // ---------------------------------------------------------------------------
  // Consent Flow
  // ---------------------------------------------------------------------------

  const respondToConsent = useCallback(
    async (requestId: string, decision: ConsentDecision, note?: string): Promise<void> => {
      const request = store.pendingConsents.find((c) => c.id === requestId);
      if (!request) return;

      // Telemetry event name
      const eventMap: Record<ConsentDecision, AuthTelemetryEvent> = {
        approve: 'auth_consent_approved',
        deny: 'auth_consent_denied',
        snooze: 'auth_consent_snoozed',
      };

      emitAuthTelemetry(eventMap[decision], {
        toolName: request.toolName,
        scopes: request.scopes.map((s) => s.name),
      });

      if (decision === 'snooze') {
        if (request.snoozeCount >= request.maxSnoozes) {
          // Max snoozes reached, treat as deny
          authStore.removeConsentRequest(requestId);
          return;
        }
        authStore.snoozeConsentRequest(requestId);
        return;
      }

      // Send decision to backend
      const response: ConsentResponse = {
        requestId,
        decision,
        note,
      };

      try {
        await apiClient.post('/v1/auth/consent/respond', response);
        authStore.removeConsentRequest(requestId);
      } catch (error) {
        console.error('[AuthContext] Consent response failed:', error);
        authStore.setError('Failed to submit consent decision');
      }
    },
    [store.pendingConsents]
  );

  // ---------------------------------------------------------------------------
  // Token Accessors
  // ---------------------------------------------------------------------------

  const getAccessToken = useCallback((): string | null => {
    return authStore.accessToken;
  }, []);

  const getValidAccessToken = useCallback(async (): Promise<string | null> => {
    if (authStore.hasValidToken) {
      return authStore.accessToken;
    }

    // Try to refresh
    const refreshed = await refreshToken();
    if (refreshed) {
      return authStore.accessToken;
    }

    return null;
  }, [refreshToken]);

  // ---------------------------------------------------------------------------
  // Effects
  // ---------------------------------------------------------------------------

  // Schedule token refresh on mount and when session changes
  useEffect(() => {
    if (store.session?.tokens?.expiresAt) {
      scheduleTokenRefresh();
    }

    return () => {
      if (refreshTimeoutRef.current) {
        clearTimeout(refreshTimeoutRef.current);
      }
    };
  }, [store.session?.tokens?.expiresAt, scheduleTokenRefresh]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  // ---------------------------------------------------------------------------
  // Context Value
  // ---------------------------------------------------------------------------

  const contextValue: AuthContextValue = {
    // State
    isAuthenticated: store.isAuthenticated,
    isInitialized: store.initialized,
    isLoading: store.isRefreshing,
    actor: store.actor,
    error: store.error,

    // Device Flow
    deviceFlowStatus: store.deviceFlow.status,
    deviceCode: store.deviceFlow.deviceCode,
    startLogin,
    cancelLogin,

    // Client Credentials
    loginWithClientCredentials,

    // OAuth Social Login
    completeOAuthLogin,

    // Session
    logout,
    refreshToken,

    // Consent
    hasPendingConsent: store.hasPendingConsent,
    nextConsentRequest: store.nextConsentRequest,
    respondToConsent,

    // Token access
    getAccessToken,
    getValidAccessToken,
  };

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}
