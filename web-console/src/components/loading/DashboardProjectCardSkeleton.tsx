/**
 * Project grid placeholder — relies on Dashboard.css (parent page imports it).
 */

import type { JSX } from 'react';

export function DashboardProjectCardSkeleton(): JSX.Element {
  return (
    <div className="project-card skeleton">
      <div className="project-card-header">
        <span className="skeleton-text skeleton-title animate-shimmer" />
      </div>
      <span className="skeleton-text skeleton-description animate-shimmer" />
      <span className="skeleton-text skeleton-meta animate-shimmer" />
    </div>
  );
}
