/**
 * Rollup progress pill — same markup and styling as board card `work-item-rollup-chip-inline`.
 */

import React, { useMemo } from 'react';
import type { WorkItemProgressRollup } from '../../api/boards';
import {
  formatProgressPercent,
  formatRemainingSummary,
  getRollupProgressFillWidth,
} from './rollupProgressDisplay';
import './RollupProgressInline.css';

export interface RollupProgressInlineProps {
  progressRollup?: WorkItemProgressRollup | null;
  countLabel?: string;
  /** When true, show progress fill + percent (matches board `hasProgressRollup`). */
  showProgress?: boolean;
  /** Noun for aria-label on count-only chip (e.g. "goal", "feature"). */
  rollupContextNoun?: string;
  className?: string;
}

export function RollupProgressInline({
  progressRollup,
  countLabel,
  showProgress = false,
  rollupContextNoun = 'item',
  className,
}: RollupProgressInlineProps): React.JSX.Element | null {
  const countSegments = useMemo(
    () => (countLabel ? countLabel.split(' · ').filter(Boolean) : []),
    [countLabel],
  );

  const hasRolledUpChildren = Boolean(progressRollup && progressRollup.buckets.total > 0);
  const hasProgressFill = Boolean(showProgress && progressRollup && hasRolledUpChildren);
  const progressPercentValue =
    hasProgressFill && progressRollup
      ? Math.min(100, Math.max(0, progressRollup.completion_percent))
      : 0;
  const progressFillWidth = hasProgressFill ? getRollupProgressFillWidth(progressPercentValue) : undefined;

  const showChip = Boolean(countLabel || hasProgressFill);
  if (!showChip) return null;

  return (
    <span
      className={`work-item-rollup-chip-inline${hasProgressFill ? ' work-item-rollup-chip-inline-progress' : ''}${className ? ` ${className}` : ''}`}
      style={
        hasProgressFill && progressRollup
          ? ({
              ['--rollup-progress' as string]: `${progressPercentValue}%`,
              ['--rollup-progress-visual' as string]: progressFillWidth,
            } as React.CSSProperties)
          : undefined
      }
      aria-label={
        hasProgressFill && progressRollup
          ? `${countLabel ? `${countLabel}. ` : ''}${formatProgressPercent(progressRollup.completion_percent)} complete. ${formatRemainingSummary(progressRollup)}`
          : countLabel
            ? `${countLabel} roll up under this ${rollupContextNoun}`
            : undefined
      }
    >
      {countSegments.length > 0 && (
        <span className="work-item-rollup-chip-inline-count">
          {countSegments.map((segment) => (
            <span
              key={segment}
              className={`work-item-rollup-chip-inline-segment ${
                segment.includes('feature')
                  ? 'work-item-rollup-chip-inline-segment-feature'
                  : segment.includes('task')
                    ? 'work-item-rollup-chip-inline-segment-task'
                    : ''
              }`}
            >
              {segment}
            </span>
          ))}
        </span>
      )}
      {hasProgressFill && progressRollup && (
        <span className="work-item-rollup-chip-inline-percent">{formatProgressPercent(progressRollup.completion_percent)}</span>
      )}
    </span>
  );
}
