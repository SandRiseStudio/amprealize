/**
 * Boards grid placeholder — uses `board-card skeleton` from `ProjectPage.css` (page must import it).
 */

import type { JSX } from 'react';

export interface ProjectBoardCardGridSkeletonProps {
  count?: number;
}

export function ProjectBoardCardGridSkeleton({ count = 3 }: ProjectBoardCardGridSkeletonProps): JSX.Element {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="board-card skeleton animate-shimmer" aria-hidden />
      ))}
    </>
  );
}
