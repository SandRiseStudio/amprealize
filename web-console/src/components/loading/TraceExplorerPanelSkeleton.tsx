/**
 * Shimmer placeholder for observability trace panels (list + span tree).
 */

import type { JSX } from 'react';
import './loading.css';

export interface TraceExplorerPanelSkeletonProps {
  /** Screen-reader label (visible copy is shimmer-only). */
  label: string;
}

export function TraceExplorerPanelSkeleton({ label }: TraceExplorerPanelSkeletonProps): JSX.Element {
  return (
    <div className="ar-trace-panel-skeleton" role="status" aria-live="polite" aria-busy="true" aria-label={label}>
      <div className="ar-loading-block ar-loading-block--line animate-shimmer" aria-hidden />
      <div
        className="ar-loading-block ar-loading-block--line ar-loading-block--line-short animate-shimmer"
        aria-hidden
      />
    </div>
  );
}
