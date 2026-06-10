import type { WorkItemProgressRollup } from '../../api/boards';

export function formatProgressPercent(value: number): string {
  if (!Number.isFinite(value)) return '0%';
  return `${Math.round(value)}%`;
}

/** Visible fill width for the rollup pill pseudo-element (matches board cards). */
export function getRollupProgressFillWidth(progressPercentValue: number): string {
  return progressPercentValue <= 0 ? '4px' : `${progressPercentValue}%`;
}

export function formatRemainingSummary(rollup: WorkItemProgressRollup): string {
  const parts: string[] = [`${rollup.remaining.items_remaining} left`];
  if (rollup.remaining.estimated_hours_remaining != null) {
    parts.push(`${rollup.remaining.estimated_hours_remaining.toFixed(1)}h`);
  }
  if (rollup.remaining.points_remaining != null) {
    parts.push(`${rollup.remaining.points_remaining} pts`);
  }
  return parts.join(' • ');
}
