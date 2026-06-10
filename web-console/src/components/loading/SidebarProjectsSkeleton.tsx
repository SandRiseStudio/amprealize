/**
 * Placeholder rows for the sidebar Projects section while the projects query is pending.
 */

import type { JSX } from 'react';
import './loading.css';

const ROW_KEYS = ['s1', 's2', 's3', 's4', 's5'] as const;

export function SidebarProjectsSkeleton(): JSX.Element {
  return (
    <div className="ar-sidebar-projects-skeleton" role="status" aria-label="Loading projects" aria-busy="true">
      {ROW_KEYS.map((key) => (
        <div key={key} className="ar-loading-sidebar-row" aria-hidden>
          <div className="ar-loading-sidebar-icon animate-shimmer" />
          <div className="ar-loading-sidebar-label animate-shimmer" />
        </div>
      ))}
      <span className="ar-loading-sr-only">Loading projects</span>
    </div>
  );
}
