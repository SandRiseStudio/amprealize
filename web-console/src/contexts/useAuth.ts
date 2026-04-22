import { useContext } from 'react';
import { AuthContext, type AuthContextValue } from './auth-context';
import type { ActorIdentity } from '../types/auth';

/**
 * Hook to access authentication context.
 * Must be used within an AuthProvider.
 */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

/**
 * Hook that returns true if the current user is authenticated.
 */
export function useIsLoggedIn(): boolean {
  const { isAuthenticated, isInitialized } = useAuth();
  return isInitialized && isAuthenticated;
}

/**
 * Hook that returns the current actor's identity.
 * Returns null if not authenticated.
 */
export function useCurrentActor(): ActorIdentity | null {
  const { actor, isAuthenticated } = useAuth();
  return isAuthenticated ? actor : null;
}

/**
 * Hook to check if user has a specific role.
 */
export function useHasRole(role: ActorIdentity['role']): boolean {
  const actor = useCurrentActor();
  return actor?.role === role;
}
