import React, { memo, useState } from 'react';
import type { ExecutionState, ExecutionStatus } from '../vendor/collab-client-dist/index.js';

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

function toTitleLabel(value?: string | null): string {
  if (!value) return 'Unknown';
  return value.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function ExecutionStatusBadge({
  state,
  phase,
  statusLabel,
  phaseLabel,
  progressPct,
  showPhase = true,
  showProgress = false,
  className,
}: ExecutionStatusBadgeProps): React.JSX.Element {
  return (
    <span className={className ?? 'execution-status-badge'} title={phase ? `${toTitleLabel(state)} • ${toTitleLabel(phase)}` : toTitleLabel(state)}>
      <span>{statusLabel ?? toTitleLabel(state)}</span>
      {showPhase && phase ? <span>{` • ${phaseLabel ?? toTitleLabel(phase)}`}</span> : null}
      {showProgress && progressPct != null ? <span>{` • ${Math.round(progressPct)}%`}</span> : null}
    </span>
  );
}

export interface ExecutionStatusCardProps {
  status?: ExecutionStatus | null;
  isLoading?: boolean;
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
  emptyLabel?: string;
  className?: string;
}

export const ExecutionStatusCard = memo(function ExecutionStatusCard({
  status,
  isLoading = false,
  title = 'Execution',
  subtitle,
  actions,
  emptyLabel = 'No execution yet',
  className,
}: ExecutionStatusCardProps): React.JSX.Element {
  const statusText = status?.state ? toTitleLabel(status.state) : emptyLabel;
  return (
    <div className={className ?? 'execution-status-card'}>
      <div>
        <strong>{title}</strong>
        <div>{statusText}</div>
        {subtitle ? <div>{subtitle}</div> : null}
        {status?.phase ? <div>{toTitleLabel(status.phase)}</div> : null}
      </div>
      {isLoading ? <div>Loading…</div> : null}
      {actions ? <div>{actions}</div> : null}
    </div>
  );
});

export interface ClarificationQuestion {
  id: string;
  question: string;
  context?: string | null;
  required?: boolean;
}

export interface ClarificationPanelProps {
  questions: ClarificationQuestion[];
  onSubmit: (questionId: string, response: string) => void;
  isSubmitting?: boolean;
  className?: string;
  title?: string;
  emptyMessage?: string;
  expanded?: boolean;
}

export const ClarificationPanel = memo(function ClarificationPanel({
  questions,
  onSubmit,
  isSubmitting = false,
  className,
  title = 'Clarifications',
  emptyMessage = 'No clarification needed',
}: ClarificationPanelProps): React.JSX.Element {
  const [responses, setResponses] = useState<Record<string, string>>({});

  if (!questions.length) {
    return <div className={className}>{emptyMessage}</div>;
  }

  return (
    <div className={className}>
      <div><strong>{title}</strong></div>
      {questions.map((question) => (
        <div key={question.id}>
          <div>{question.question}</div>
          {question.context ? <div>{question.context}</div> : null}
          <textarea
            value={responses[question.id] ?? ''}
            onChange={(event) => setResponses((prev) => ({ ...prev, [question.id]: event.target.value }))}
            placeholder="Type your answer"
          />
          <button
            type="button"
            onClick={() => onSubmit(question.id, responses[question.id] ?? '')}
            disabled={isSubmitting || !(responses[question.id] ?? '').trim()}
          >
            {isSubmitting ? 'Submitting…' : 'Submit'}
          </button>
        </div>
      ))}
    </div>
  );
});
