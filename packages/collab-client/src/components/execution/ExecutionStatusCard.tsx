import React, { useEffect, useMemo } from 'react';
import type { ExecutionStatus } from '../../types.js';
import { ensureExecutionStyles } from './executionStyles.js';
import { clampProgress, formatRelativeTime, formatExecutionStateLabel, normalizeExecutionState } from './executionUtils.js';
import { ExecutionStatusBadge } from './ExecutionStatusBadge.js';

export interface ExecutionStatusCardProps {
  status?: ExecutionStatus | null;
  isLoading?: boolean;
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
  emptyLabel?: string;
  className?: string;
}

export function ExecutionStatusCard({
  status,
  isLoading = false,
  title = 'Execution',
  subtitle,
  actions,
  emptyLabel = 'No execution has started yet.',
  className,
}: ExecutionStatusCardProps): React.JSX.Element {
  useEffect(() => {
    ensureExecutionStyles();
  }, []);

  const hasExecution = Boolean(status?.hasExecution);
  const normalizedState = useMemo(() => normalizeExecutionState(status?.state ?? undefined), [status?.state]);
  const stateLabel = useMemo(() => formatExecutionStateLabel(normalizedState), [normalizedState]);
  const progress = useMemo(() => clampProgress(status?.progressPct ?? 0), [status?.progressPct]);
  const startedLabel = useMemo(() => formatRelativeTime(status?.startedAt ?? undefined), [status?.startedAt]);
  const tokenLabel = useMemo(() => {
    if (typeof status?.totalTokens === 'number') return status.totalTokens.toLocaleString();
    return '--';
  }, [status?.totalTokens]);
  const costLabel = useMemo(() => {
    if (typeof status?.totalCostUsd === 'number') return `$${status.totalCostUsd.toFixed(3)}`;
    return '--';
  }, [status?.totalCostUsd]);

  return (
    <section className={`ga-exec-panel ${className ?? ''}`.trim()} aria-live="polite">
      <header className="ga-exec-panel-header">
        <div>
          <div className="ga-exec-panel-title">{title}</div>
          {subtitle && <div className="ga-exec-panel-subtitle">{subtitle}</div>}
        </div>
        {actions && <div className="ga-exec-actions">{actions}</div>}
      </header>

      {isLoading && (
        <div className="ga-exec-empty" aria-label="Loading execution status">
          Loading execution status...
        </div>
      )}

      {!isLoading && !hasExecution && (
        <div className="ga-exec-empty" aria-label="No execution">
          {emptyLabel}
        </div>
      )}

      {!isLoading && hasExecution && (
        <div className="ga-exec-panel-body">
          <div className="ga-exec-status-row">
            <ExecutionStatusBadge
              state={normalizedState}
              phase={status?.phase ?? null}
              progressPct={progress}
              showPhase
              showProgress={false}
            />
          </div>

          <div className="ga-exec-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
            <span
              className={`ga-exec-progress-fill ${normalizedState === 'running' ? 'ga-exec-progress-running' : ''}`}
              style={{ transform: `scaleX(${progress / 100})` }}
            />
          </div>

          {status?.currentStep && (
            <div className="ga-exec-current-step">
              <strong>{stateLabel}:</strong> {status.currentStep}
            </div>
          )}

          <div className="ga-exec-meta">
            <div className="ga-exec-meta-item">
              <div className="ga-exec-meta-label">Started</div>
              <div className="ga-exec-meta-value">{startedLabel}</div>
            </div>
            <div className="ga-exec-meta-item">
              <div className="ga-exec-meta-label">Progress</div>
              <div className="ga-exec-meta-value">{progress.toFixed(0)}%</div>
            </div>
            <div className="ga-exec-meta-item">
              <div className="ga-exec-meta-label">Tokens</div>
              <div className="ga-exec-meta-value">{tokenLabel}</div>
            </div>
            <div className="ga-exec-meta-item">
              <div className="ga-exec-meta-label">Cost</div>
              <div className="ga-exec-meta-value">{costLabel}</div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
