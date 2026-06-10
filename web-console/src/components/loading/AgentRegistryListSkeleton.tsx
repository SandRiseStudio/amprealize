/**
 * Registry column placeholder for AgentsPage — stable height cards, no AgentsPage.css import.
 */

import type { JSX } from 'react';
import './loading.css';

export interface AgentRegistryListSkeletonProps {
  /** Number of placeholder cards (default 3). */
  count?: number;
}

export function AgentRegistryListSkeleton({ count = 3 }: AgentRegistryListSkeletonProps): JSX.Element {
  return (
    <div
      className="ar-agent-registry-skeleton-stack"
      role="status"
      aria-busy="true"
      aria-label="Loading agent registry"
    >
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="ar-agent-registry-skeleton-card animate-shimmer" aria-hidden />
      ))}
    </div>
  );
}
