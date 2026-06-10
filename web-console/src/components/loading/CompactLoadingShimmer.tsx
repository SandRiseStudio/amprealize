/**
 * Single-line shimmer for inline / dense surfaces (cards, activity feed, execution widgets).
 */

import type { JSX } from 'react';
import './loading.css';

export interface CompactLoadingShimmerProps {
  /** Accessible name; visible UI is shimmer-only. */
  label: string;
}

export function CompactLoadingShimmer({ label }: CompactLoadingShimmerProps): JSX.Element {
  return (
    <div
      className="ar-compact-loading"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={label}
    >
      <div className="ar-loading-block ar-loading-block--line ar-loading-block--line-short animate-shimmer" aria-hidden />
    </div>
  );
}
