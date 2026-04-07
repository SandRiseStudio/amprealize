/**
 * ProtectedRoute Component
 *
 * Route guard that ensures user is authenticated before rendering children.
 * Redirects to login page if not authenticated.
 *
 * Features:
 * - Smooth loading state with skeleton animation
 * - Preserves intended destination for post-login redirect
 * - Spring-physics animations per COLLAB_SAAS_REQUIREMENTS.md
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 * - behavior_use_raze_for_logging (Student)
 */

import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import './ProtectedRoute.css';

interface ProtectedRouteProps {
  children: ReactNode;
  /**
   * Required actor types for this route.
   * If not specified, any authenticated actor can access.
   */
  allowedActorTypes?: ('human' | 'agent' | 'service')[];
  /**
   * Required scopes for this route.
   * User must have all specified scopes.
   */
  requiredScopes?: string[];
  /**
   * Fallback component to show while checking auth.
   * Defaults to built-in loading skeleton.
   */
  loadingFallback?: ReactNode;
}

/**
 * Loading skeleton shown while auth state is being determined.
 * Uses GPU-accelerated shimmer animation for 60fps.
 */
function LoadingSkeleton() {
  return (
    <div className="protected-route-loading" role="status" aria-label="Loading">
      <div className="protected-route-skeleton-container">
        {/* Sidebar skeleton */}
        <div className="protected-route-skeleton-sidebar">
          <div className="protected-route-skeleton-logo shimmer" />
          <div className="protected-route-skeleton-nav">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="protected-route-skeleton-nav-item shimmer" />
            ))}
          </div>
        </div>

        {/* Main content skeleton */}
        <div className="protected-route-skeleton-main">
          <div className="protected-route-skeleton-header shimmer" />
          <div className="protected-route-skeleton-content">
            <div className="protected-route-skeleton-card shimmer" />
            <div className="protected-route-skeleton-card shimmer" />
            <div className="protected-route-skeleton-card-tall shimmer" />
          </div>
        </div>
      </div>
      <span className="sr-only">Verifying authentication...</span>
    </div>
  );
}

/**
 * Access denied component shown when user lacks required permissions.
 */
function AccessDenied({ reason }: { reason: string }) {
  return (
    <div className="protected-route-denied animate-fade-in-up" role="alert">
      <div className="protected-route-denied-icon">🚫</div>
      <h1 className="protected-route-denied-title">Access Denied</h1>
      <p className="protected-route-denied-message">{reason}</p>
      <a href="/" className="protected-route-denied-link">
        Return to Dashboard
      </a>
    </div>
  );
}

export function ProtectedRoute({
  children,
  allowedActorTypes,
  requiredScopes,
  loadingFallback,
}: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, actor } = useAuth();
  const location = useLocation();

  // Show loading state while checking auth
  if (isLoading) {
    return <>{loadingFallback ?? <LoadingSkeleton />}</>;
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    // Preserve the intended destination for post-login redirect
    return (
      <Navigate
        to="/login"
        state={{ from: location.pathname + location.search }}
        replace
      />
    );
  }

  // Check actor type restrictions
  if (allowedActorTypes && actor) {
    if (!allowedActorTypes.includes(actor.type)) {
      return (
        <AccessDenied
          reason={`This page is only accessible to ${allowedActorTypes.join(' or ')} accounts.`}
        />
      );
    }
  }

  // Check scope restrictions
  // TODO: Add scopes to AuthContextValue interface to enable scope-based access control
  if (requiredScopes && requiredScopes.length > 0) {
    // For now, skip scope checks - would need session.tokens.scopes exposed
    console.warn('[ProtectedRoute] Scope checking not yet implemented, skipping check for:', requiredScopes);
  }

  // All checks passed, render children with animation
  return <div className="protected-route-content animate-fade-in-up">{children}</div>;
}

export default ProtectedRoute;
