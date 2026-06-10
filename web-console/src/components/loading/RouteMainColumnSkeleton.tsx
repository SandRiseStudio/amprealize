/**
 * Full-viewport placeholder for lazy route chunks (Suspense fallback).
 * Mirrors workspace main column padding so route transitions feel stable.
 */

import type { JSX } from 'react';
import './loading.css';

export function RouteMainColumnSkeleton(): JSX.Element {
  return (
    <div className="ar-loading-route" role="status" aria-busy="true" aria-label="Loading page">
      <div className="ar-loading-route-inner animate-fade-in-up">
        <div className="ar-loading-block ar-loading-block--title animate-shimmer" aria-hidden />
        <div className="ar-loading-block ar-loading-block--line animate-shimmer" aria-hidden />
        <div className="ar-loading-block ar-loading-block--line ar-loading-block--line-short animate-shimmer" aria-hidden />
        <div className="ar-loading-grid" aria-hidden>
          <div className="ar-loading-card animate-shimmer" />
          <div className="ar-loading-card animate-shimmer" />
          <div className="ar-loading-card animate-shimmer" />
        </div>
      </div>
      <span className="ar-loading-sr-only">Loading page content</span>
    </div>
  );
}
