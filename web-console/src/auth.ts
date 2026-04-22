/**
 * Auth Module Index
 *
 * Public exports for Amprealize web console authentication.
 *
 * This module provides:
 * - AuthProvider: Context provider for auth state
 * - useAuth: Hook for accessing auth state and actions
 * - authStore: Store for manual subscription (advanced use)
 * - Types: All auth-related type definitions
 *
 * Usage:
 * ```tsx
 * import { AuthProvider, useAuth, type AuthState } from './auth';
 *
 * // In App.tsx
 * <AuthProvider>
 *   <App />
 * </AuthProvider>
 *
 * // In components
 * function MyComponent() {
 *   const { isAuthenticated, state, logout } = useAuth();
 *   // ...
 * }
 * ```
 */

// Context and hooks
export { AuthProvider } from './contexts/AuthProvider';
export { useAuth, useIsLoggedIn, useCurrentActor, useHasRole } from './contexts/useAuth';
export type { AuthContextValue } from './contexts/auth-context';

// Store (for advanced usage outside React)
export { authStore } from './stores/authStore';

// Types - re-export from types/auth
export type {
  AuthState,
  ActorIdentity,
  AuthTokens,
  DeviceFlowState,
  ConsentRequest,
  ConsentDecision,
} from './types/auth';
