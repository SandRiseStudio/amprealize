/**
 * Stat row placeholder — relies on Dashboard.css (parent page imports it).
 */

import type { JSX } from 'react';

export function DashboardStatCardSkeleton(): JSX.Element {
  return (
    <div className="stat-card skeleton">
      <div className="skeleton-icon animate-shimmer" />
      <div className="stat-card-content">
        <span className="skeleton-text skeleton-value animate-shimmer" />
        <span className="skeleton-text skeleton-label animate-shimmer" />
      </div>
    </div>
  );
}
