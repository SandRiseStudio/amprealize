/**
 * Amprealize web console authentication store
 *
 * Zustand-like state management for authentication state,
 * following the pattern in collabStore.ts (no external deps).
 *
 * Features:
 * - Session management with actor identity model
 * - Device flow state for human login
 * - Token storage in localStorage (15m expiry)
 * - Consent request queue
 * - Auto-persist to localStorage
 *
 * Following:
 * - behavior_use_raze_for_logging (Student)
 * - behavior_design_api_contract (Teacher)
 */

import { useSyncExternalStore } from 'react';
import type {
  AuthState,
  AuthActions,
  AuthSession,
  AuthTokens,
  DeviceCodeResponse,
  DeviceFlowStatus,
  ConsentRequest,
} from '../types/auth';
import { STORAGE_KEYS } from '../config/storageKeys';

// Diagnostic: helps detect module duplication / multiple store instances during Vite HMR.
export const AUTH_STORE_INSTANCE_ID = `authStore_${Math.random().toString(36).slice(2)}`;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STORAGE_KEY = STORAGE_KEYS.authState;
const TOKEN_STORAGE_KEY = STORAGE_KEYS.accessToken;
const REFRESH_TOKEN_STORAGE_KEY = STORAGE_KEYS.refreshToken;

// ---------------------------------------------------------------------------
// Initial State
// ---------------------------------------------------------------------------

const initialDeviceFlowState = {
  status: 'idle' as DeviceFlowStatus,
  deviceCode: null,
  error: null,
  pollCount: 0,
};

const initialState: AuthState = {
  initialized: false,
  session: null,
  // Clone to avoid sharing a single object reference across resets/initialization.
  deviceFlow: { ...initialDeviceFlowState },
  pendingConsents: [],
  isRefreshing: false,
  error: null,
};

// ---------------------------------------------------------------------------
// Store Implementation (Zustand-like pattern without external deps)
// ---------------------------------------------------------------------------

type Listener = () => void;

class AuthStore implements AuthActions {
  private state: AuthState;
  private listeners: Set<Listener> = new Set();
  private readonly handleStorageEvent = (event: StorageEvent): void => {
    if (event.key !== STORAGE_KEY) {
      return;
    }
    this.loadFromStorage();
  };

  constructor() {
    this.state = { ...initialState };
    this.loadFromStorage();
    if (typeof window !== 'undefined') {
      window.addEventListener('storage', this.handleStorageEvent);
    }
  }

  // ---------------------------------------------------------------------------
  // Subscription (for useSyncExternalStore)
  // ---------------------------------------------------------------------------

  getState = (): AuthState => {
    return this.state;
  };

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private setState(partial: Partial<AuthState>): void {
    this.state = { ...this.state, ...partial };
    this.notify();
    this.persistToStorage();
  }

  private notify(): void {
    this.listeners.forEach((listener) => listener());
  }

  // ---------------------------------------------------------------------------
  // Persistence
  // ---------------------------------------------------------------------------

  private loadFromStorage(): void {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored) as Partial<AuthState>;
        // Validate session expiry
        if (parsed.session?.tokens?.expiresAt) {
          const now = Date.now();
          if (parsed.session.tokens.expiresAt < now) {
            // Token expired, clear session
            console.warn('[AuthStore] Session expired, clearing');
            parsed.session = null;
          }
        }
        this.state = {
          ...this.state,
          session: parsed.session ?? null,
          pendingConsents: parsed.pendingConsents ?? [],
          initialized: true,
        };
      } else {
        this.state = { ...this.state, initialized: true };
      }
      // Also sync legacy token key for API client
      if (this.state.session?.tokens?.accessToken) {
        localStorage.setItem(TOKEN_STORAGE_KEY, this.state.session.tokens.accessToken);
      }
      if (this.state.session?.tokens?.refreshToken) {
        localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, this.state.session.tokens.refreshToken);
      }
    } catch (error) {
      console.error('[AuthStore] Failed to load from storage:', error);
      this.state = { ...this.state, initialized: true };
    }
    this.notify();
  }

  private persistToStorage(): void {
    try {
      // Only persist session and pending consents
      const toPersist = {
        session: this.state.session,
        pendingConsents: this.state.pendingConsents,
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toPersist));
      // Also sync legacy token key for API client
      if (this.state.session?.tokens?.accessToken) {
        localStorage.setItem(TOKEN_STORAGE_KEY, this.state.session.tokens.accessToken);
      } else {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
      }
      if (this.state.session?.tokens?.refreshToken) {
        localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, this.state.session.tokens.refreshToken);
      } else {
        localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
      }
    } catch (error) {
      console.error('[AuthStore] Failed to persist to storage:', error);
    }
  }

  // ---------------------------------------------------------------------------
  // Session Actions
  // ---------------------------------------------------------------------------

  setSession = (session: AuthSession | null): void => {
    this.setState({
      session,
      error: null,
      deviceFlow: initialDeviceFlowState,
    });
  };

  updateTokens = (tokens: AuthTokens): void => {
    if (!this.state.session) {
      console.warn('[AuthStore] Cannot update tokens: no active session');
      return;
    }
    this.setState({
      session: {
        ...this.state.session,
        tokens,
        lastActiveAt: Date.now(),
      },
      isRefreshing: false,
    });
  };

  clearSession = (): void => {
    this.setState({
      session: null,
      pendingConsents: [],
      error: null,
    });
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
    localStorage.removeItem('amprealize_token');
    localStorage.removeItem('amprealize_refresh_token');
    localStorage.removeItem('amprealize_auth');
  };

  // ---------------------------------------------------------------------------
  // Device Flow Actions
  // ---------------------------------------------------------------------------

  startDeviceFlow = (): void => {
    this.setState({
      deviceFlow: {
        status: 'pending',
        deviceCode: null,
        error: null,
        pollCount: 0,
      },
      error: null,
    });
  };

  setDeviceCode = (code: DeviceCodeResponse): void => {
    this.setState({
      deviceFlow: {
        ...this.state.deviceFlow,
        deviceCode: code,
        status: 'polling',
      },
    });
  };

  setDeviceFlowStatus = (status: DeviceFlowStatus, error?: string): void => {
    this.setState({
      deviceFlow: {
        ...this.state.deviceFlow,
        status,
        error: error ?? null,
      },
      error: error ?? this.state.error,
    });
  };

  incrementPollCount = (): void => {
    this.setState({
      deviceFlow: {
        ...this.state.deviceFlow,
        pollCount: this.state.deviceFlow.pollCount + 1,
      },
    });
  };

  resetDeviceFlow = (): void => {
    this.setState({
      // Clone to ensure snapshots change by reference for subscribers.
      deviceFlow: { ...initialDeviceFlowState },
    });
  };

  // ---------------------------------------------------------------------------
  // Consent Actions
  // ---------------------------------------------------------------------------

  addConsentRequest = (request: ConsentRequest): void => {
    // Avoid duplicates
    const exists = this.state.pendingConsents.some((c) => c.id === request.id);
    if (exists) return;

    this.setState({
      pendingConsents: [...this.state.pendingConsents, request],
    });
  };

  removeConsentRequest = (requestId: string): void => {
    this.setState({
      pendingConsents: this.state.pendingConsents.filter((c) => c.id !== requestId),
    });
  };

  snoozeConsentRequest = (requestId: string): void => {
    this.setState({
      pendingConsents: this.state.pendingConsents.map((c) =>
        c.id === requestId
          ? { ...c, snoozeCount: c.snoozeCount + 1 }
          : c
      ),
    });
  };

  // ---------------------------------------------------------------------------
  // State Actions
  // ---------------------------------------------------------------------------

  setRefreshing = (isRefreshing: boolean): void => {
    this.setState({ isRefreshing });
  };

  setError = (error: string | null): void => {
    this.setState({ error });
  };

  setInitialized = (initialized: boolean): void => {
    this.setState({ initialized });
  };

  // ---------------------------------------------------------------------------
  // Selectors (computed properties)
  // ---------------------------------------------------------------------------

  get isAuthenticated(): boolean {
    if (!this.state.session) return false;
    return this.state.session.tokens.expiresAt > Date.now();
  }

  get actor() {
    return this.state.session?.actor ?? null;
  }

  get accessToken(): string | null {
    return this.state.session?.tokens?.accessToken ?? null;
  }

  get tokenExpiresAt(): number | null {
    return this.state.session?.tokens?.expiresAt ?? null;
  }

  get hasValidToken(): boolean {
    const expiresAt = this.tokenExpiresAt;
    if (!expiresAt) return false;
    // Consider invalid if expires within 60 seconds
    return expiresAt > Date.now() + 60_000;
  }

  get hasPendingConsent(): boolean {
    return this.state.pendingConsents.length > 0;
  }

  get nextConsentRequest(): ConsentRequest | null {
    return this.state.pendingConsents[0] ?? null;
  }
}

// ---------------------------------------------------------------------------
// Singleton Instance
// ---------------------------------------------------------------------------

export const authStore = new AuthStore();

// ---------------------------------------------------------------------------
// React Hook
// ---------------------------------------------------------------------------

/**
 * Hook to access auth state with automatic re-renders on state changes.
 * Uses useSyncExternalStore for concurrent-safe subscriptions.
 */
export function useAuthStore(): AuthState & AuthActions & {
  isAuthenticated: boolean;
  actor: AuthState['session'] extends null ? null : NonNullable<AuthState['session']>['actor'] | null;
  accessToken: string | null;
  hasValidToken: boolean;
  hasPendingConsent: boolean;
  nextConsentRequest: ConsentRequest | null;
} {
  const state = useSyncExternalStore(authStore.subscribe, authStore.getState);

  return {
    // State
    ...state,
    // Actions
    setSession: authStore.setSession,
    updateTokens: authStore.updateTokens,
    clearSession: authStore.clearSession,
    startDeviceFlow: authStore.startDeviceFlow,
    setDeviceCode: authStore.setDeviceCode,
    setDeviceFlowStatus: authStore.setDeviceFlowStatus,
    incrementPollCount: authStore.incrementPollCount,
    resetDeviceFlow: authStore.resetDeviceFlow,
    addConsentRequest: authStore.addConsentRequest,
    removeConsentRequest: authStore.removeConsentRequest,
    snoozeConsentRequest: authStore.snoozeConsentRequest,
    setRefreshing: authStore.setRefreshing,
    setError: authStore.setError,
    setInitialized: authStore.setInitialized,
    // Computed
    isAuthenticated: authStore.isAuthenticated,
    actor: authStore.actor,
    accessToken: authStore.accessToken,
    hasValidToken: authStore.hasValidToken,
    hasPendingConsent: authStore.hasPendingConsent,
    nextConsentRequest: authStore.nextConsentRequest,
  };
}

/**
 * Selector hook for device-flow only.
 * Helps avoid any incidental staleness from consuming the entire auth state.
 */
export function useDeviceFlow() {
  const deviceFlow = useSyncExternalStore(
    authStore.subscribe,
    () => authStore.getState().deviceFlow
  );

  return {
    deviceFlow,
    startDeviceFlow: authStore.startDeviceFlow,
    setDeviceCode: authStore.setDeviceCode,
    setDeviceFlowStatus: authStore.setDeviceFlowStatus,
    incrementPollCount: authStore.incrementPollCount,
    resetDeviceFlow: authStore.resetDeviceFlow,
  };
}

// ---------------------------------------------------------------------------
// Selector Hooks (for performance-sensitive components)
// ---------------------------------------------------------------------------

/** Use when you only need to know if user is authenticated */
export function useIsAuthenticated(): boolean {
  useSyncExternalStore(authStore.subscribe, authStore.getState);
  return authStore.isAuthenticated;
}

/** Use when you only need the actor identity */
export function useActor() {
  useSyncExternalStore(authStore.subscribe, authStore.getState);
  return authStore.actor;
}

/** Use when you only need the access token */
export function useAccessToken(): string | null {
  useSyncExternalStore(authStore.subscribe, authStore.getState);
  return authStore.accessToken;
}

/** Use to check if there are pending consent requests */
export function usePendingConsent() {
  const state = useSyncExternalStore(authStore.subscribe, authStore.getState);
  return {
    hasPending: authStore.hasPendingConsent,
    nextRequest: authStore.nextConsentRequest,
    count: state.pendingConsents.length,
  };
}
