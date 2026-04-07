import React, { useEffect, useMemo } from 'react';
import type { ExecutionState } from '../../types.js';
import { ensureExecutionStyles } from './executionStyles.js';
import { clampProgress, formatExecutionStateLabel, formatPhaseLabel, normalizeExecutionState } from './executionUtils.js';

export interface ExecutionStatusBadgeProps {
  state?: ExecutionState | string | null;
  phase?: string | null;
  statusLabel?: string;
  phaseLabel?: string;
  progressPct?: number | null;
  showPhase?: boolean;
  showProgress?: boolean;
  className?: string;
}

export function ExecutionStatusBadge({
  state,
  phase,
  statusLabel,
  phaseLabel,
  progressPct,
  showPhase = true,
  showProgress = true,
  className,
}: ExecutionStatusBadgeProps): React.JSX.Element {
  useEffect(() => {
    ensureExecutionStyles();
  }, []);

  const normalizedState = useMemo(() => normalizeExecutionState(state ?? undefined), [state]);
  const progress = useMemo(() => clampProgress(progressPct), [progressPct]);
  const stateLabel = useMemo(
    () => statusLabel ?? formatExecutionStateLabel(normalizedState),
    [normalizedState, statusLabel]
  );
  const resolvedPhaseLabel = useMemo(() => {
    if (phaseLabel) return phaseLabel;
    if (!phase) return null;
    return formatPhaseLabel(phase);
  }, [phase, phaseLabel]);

  return (
    <div
      className={`ga-exec-status-badge ga-exec-${normalizedState} ${className ?? ''}`.trim()}
      aria-label={`Execution status ${stateLabel}`}
    >
      <span className="ga-exec-status-dot" aria-hidden="true" />
      <span>{stateLabel}</span>
      {showPhase && resolvedPhaseLabel && (
        <span className="ga-exec-phase-pill" aria-label={`Phase ${resolvedPhaseLabel}`}>
          {resolvedPhaseLabel}
        </span>
      )}
      {showProgress && (
        <span className="ga-exec-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
          <span
            className={`ga-exec-progress-fill ${normalizedState === 'running' ? 'ga-exec-progress-running' : ''}`}
            style={{ transform: `scaleX(${progress / 100})` }}
          />
        </span>
      )}
    </div>
  );
}
