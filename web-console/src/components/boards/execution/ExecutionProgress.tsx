import React, { useMemo } from 'react';
import type { WorkItemType } from '../../../api/boards';
import { ConnectionState, type ClarificationQuestion, type ExecutionStatus, type ExecutionStep } from '../../../lib/collab-client';
import { KnowledgeRetrievalSummary } from './KnowledgeRetrievalSummary';
import { ExecutionConnectionPill } from './ExecutionConnectionPill';
import { ExecutionFailureCard } from './ExecutionFailureCard';
import { InlineGatePanel } from './InlineGatePanel';
import { LiveActivityStrip } from './LiveActivityStrip';
import { PhaseStepper } from './PhaseStepper';
import { PhaseTimeline } from './PhaseTimeline';
import { selectPhaseModel } from './selectPhaseModel';
import './ExecutionProgress.css';

function toTitleCase(input: string): string {
  return input.replace(/\b\w/g, (char) => char.toUpperCase());
}

function toStatusLabel(status: string): string {
  return status.replace(/_/g, ' ');
}

export interface ExecutionProgressProps {
  variant: 'embedded' | 'default';
  status: ExecutionStatus | null;
  steps: readonly ExecutionStep[];
  connectionState: ConnectionState;
  streamConnected: boolean;
  /** True while the work item may be on REST polling (e.g. 2s) for status */
  isStatusPolling: boolean;
  isStatusLoading: boolean;
  /** Card header (non-embedded) */
  summary?: string | null;
  hint?: string | null;
  hasExecution: boolean;
  stateLabel?: string | null;
  clarificationCount?: number;
  clarificationQuestions: ClarificationQuestion[];
  onClarifySubmit: (questionId: string, response: string) => void;
  clarifySubmitting: boolean;
  onApproveGate: () => void;
  approveGatePending: boolean;
  onCancel: () => void;
  onRefresh: () => void;
  onRetry: () => void;
  cancelPending: boolean;
  refreshPending: boolean;
  retryPending: boolean;
  canCancel: boolean;
  cancelLabel: string;
  refreshLabel: string;
  /** Shown in default variant header actions row */
  startSlot?: React.ReactNode;
  embedInHero?: boolean;
  rawRunHref?: string | null;
  /** Research work items use the research pipeline phase ladder instead of GEP. */
  workItemType?: WorkItemType | null;
}

/**
 * Phase-aware execution stack for the work item drawer.
 */
export function ExecutionProgress({
  variant,
  status,
  steps,
  connectionState,
  streamConnected,
  isStatusPolling,
  isStatusLoading,
  summary,
  hint,
  hasExecution,
  stateLabel,
  clarificationCount = 0,
  clarificationQuestions,
  onClarifySubmit,
  clarifySubmitting,
  onApproveGate,
  approveGatePending,
  onCancel,
  onRefresh,
  onRetry,
  cancelPending,
  refreshPending,
  retryPending,
  canCancel,
  cancelLabel,
  refreshLabel,
  startSlot,
  embedInHero = false,
  rawRunHref,
  workItemType = null,
}: ExecutionProgressProps): React.JSX.Element {
  const executionPipeline = workItemType === 'research' ? 'research' : 'gep';
  const model = useMemo(
    () => selectPhaseModel(status, steps, { pipeline: executionPipeline }),
    [status, steps, executionPipeline],
  );
  const state = status?.state ? String(status.state).toLowerCase() : '';
  const isActive = state === 'running' || state === 'paused' || state === 'pending';
  const phaseStripLabel = status?.phase ? toTitleCase(toStatusLabel(status.phase)) : model.currentGepPhase ? toTitleCase(toStatusLabel(model.currentGepPhase)) : 'Run';
  const failed = state === 'failed';

  const defaultVariant = variant === 'default';

  return (
    <div className={`execution-progress execution-progress--${variant}`}>
      {!embedInHero && defaultVariant ? (
        <div className="execution-progress-header">
          <div>
            <div className="execution-progress-eyebrow">Execution</div>
            <div className="execution-progress-title">{summary ?? 'Execution'}</div>
            {hint ? <div className="execution-progress-hint">{hint}</div> : null}
          </div>
          <div className="execution-progress-header-badges">
            {stateLabel ? (
              <span className={`activity-badge activity-badge-system activity-badge-state-${state}`}>{stateLabel}</span>
            ) : null}
            {clarificationCount > 0 ? (
              <span className="activity-badge activity-badge-warning">{clarificationCount} needs input</span>
            ) : null}
          </div>
        </div>
      ) : null}

      {embedInHero && clarificationCount > 0 ? (
        <div className="execution-progress-hero-badges" role="status">
          <span className="activity-badge activity-badge-warning">{clarificationCount} needs input</span>
        </div>
      ) : null}

      <div className="execution-progress-actions">
        {startSlot}
        <button
          type="button"
          className="execution-action-button execution-action-secondary pressable"
          onClick={onCancel}
          disabled={!canCancel || cancelPending}
          aria-label={cancelLabel}
        >
          {cancelPending ? 'Cancelling…' : cancelLabel}
        </button>
        <button
          type="button"
          className="execution-action-button execution-action-ghost pressable"
          onClick={onRefresh}
          disabled={refreshPending}
          aria-label={refreshLabel}
        >
          {refreshPending ? 'Refreshing…' : refreshLabel}
        </button>
      </div>

      {isStatusLoading ? (
        <div className="execution-progress-loading" role="status">
          Loading execution…
        </div>
      ) : hasExecution ? (
        <>
          <PhaseStepper phases={model.phases} currentPhaseIndex={model.currentPhaseIndex} />
          <LiveActivityStrip
            phaseLabel={phaseStripLabel}
            stepLabel={model.currentStepLabel}
            elapsedMs={model.elapsedMs}
            isRunning={isActive}
            startedAtIso={status?.startedAt ?? null}
          />
          <InlineGatePanel
            state={status?.state ?? null}
            questions={clarificationQuestions}
            onClarifySubmit={onClarifySubmit}
            clarifySubmitting={clarifySubmitting}
            onApproveGate={onApproveGate}
            approveGatePending={approveGatePending}
          />
          <KnowledgeRetrievalSummary data={status?.traceSummary?.knowledge_retrieval ?? null} />
          {failed ? (
            <ExecutionFailureCard
              failingPhase={model.failingPhase}
              errorClass={model.errorClass}
              errorMessage={model.errorMessage}
              runId={status?.runId ?? null}
              rawRunHref={rawRunHref ?? undefined}
              onRetry={onRetry}
              retryPending={retryPending}
            />
          ) : null}
          <PhaseTimeline steps={steps} pipeline={executionPipeline} />
          <div className="execution-progress-footer">
            <ExecutionConnectionPill
              connectionState={connectionState}
              isConnected={streamConnected}
              isPolling={Boolean(isActive && !streamConnected && isStatusPolling)}
            />
          </div>
        </>
      ) : (
        <div className="execution-progress-idle" role="status">
          {hint ?? 'Assign an agent and start execution when you are ready.'}
        </div>
      )}
    </div>
  );
}
