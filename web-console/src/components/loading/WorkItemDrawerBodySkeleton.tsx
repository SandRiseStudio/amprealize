/**
 * Drawer body placeholder while a work item row is loading (studio shell already visible).
 */

import type { JSX } from 'react';
import './loading.css';

export function WorkItemDrawerBodySkeleton(): JSX.Element {
  return (
    <div
      className="ar-wi-drawer-body-skeleton"
      role="status"
      aria-busy="true"
      aria-label="Loading work item"
    >
      <div className="ar-wi-drawer-skeleton-line animate-shimmer" aria-hidden />
      <div className="ar-wi-drawer-skeleton-line animate-shimmer" aria-hidden />
      <div className="ar-wi-drawer-skeleton-block animate-shimmer" aria-hidden />
    </div>
  );
}
