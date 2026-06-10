import React, { useMemo } from 'react';
import type { ExecutionStep } from '../../../lib/collab-client';
import {
  GEP_PHASE_ORDER,
  RESEARCH_LABELS,
  RESEARCH_PHASE_ORDER,
  type GepPhaseId,
  type ResearchPhaseId,
} from './selectPhaseModel';
import { formatDurationMs, formatTokenTotal } from './formatExecution';

export type ExecutionTimelinePipeline = 'gep' | 'research';

function toTitleCase(input: string): string {
  return input.replace(/\b\w/g, (char) => char.toUpperCase());
}

function toStatusLabel(status: string): string {
  return status.replace(/_/g, ' ');
}

export interface PhaseTimelineProps {
  steps: readonly ExecutionStep[];
  /** When `research`, groups steps by research pipeline phases instead of GEP. */
  pipeline?: ExecutionTimelinePipeline;
}

function phaseDisplayName(phaseId: string, pipeline: ExecutionTimelinePipeline): string {
  if (pipeline === 'research') {
    return RESEARCH_LABELS[phaseId] ?? toTitleCase(toStatusLabel(phaseId.replace(/^research_/, '')));
  }
  return toTitleCase(toStatusLabel(phaseId));
}

/**
 * Collapsible groups of execution steps by GEP phase or research pipeline phase.
 */
export function PhaseTimeline({
  steps,
  pipeline = 'gep',
}: PhaseTimelineProps): React.JSX.Element {
  const phaseOrder = pipeline === 'research' ? RESEARCH_PHASE_ORDER : GEP_PHASE_ORDER;
  const fallbackBucket: GepPhaseId | ResearchPhaseId =
    pipeline === 'research' ? 'research_ingest' : 'executing';

  const grouped = useMemo(() => {
    const map = new Map<string, ExecutionStep[]>();
    phaseOrder.forEach((p) => map.set(p, []));
    for (const step of steps) {
      const raw = step.phase?.toLowerCase() ?? '';
      const order = phaseOrder as readonly string[];
      const match = order.includes(raw) ? raw : null;
      const key = match ?? fallbackBucket;
      const bucket = map.get(key) ?? [];
      bucket.push(step);
      map.set(key, bucket);
    }
    return map;
  }, [steps, phaseOrder, fallbackBucket]);

  if (steps.length === 0) {
    return (
      <div className="execution-phase-timeline execution-phase-timeline--empty" role="status">
        {pipeline === 'research'
          ? 'No research step log yet. Progress messages appear here as the pipeline advances.'
          : 'No step timeline yet. Steps appear as the run progresses.'}
      </div>
    );
  }

  return (
    <div className="execution-phase-timeline" aria-label="Steps by phase">
      {phaseOrder.map((phaseId) => {
        const rows = grouped.get(phaseId) ?? [];
        if (rows.length === 0) return null;
        return (
          <details key={phaseId} className="execution-phase-timeline-group">
            <summary className="execution-phase-timeline-summary">
              <span className="execution-phase-timeline-phase-name">{phaseDisplayName(phaseId, pipeline)}</span>
              <span className="execution-phase-timeline-count">{rows.length} step{rows.length === 1 ? '' : 's'}</span>
            </summary>
            <ul className="execution-phase-timeline-steps">
              {rows.map((step) => (
                <li key={step.stepId} className="execution-phase-timeline-step">
                  <div className="execution-phase-timeline-step-title">
                    <strong>{step.name ?? toTitleCase(toStatusLabel(step.stepType))}</strong>
                    <span className="execution-phase-timeline-step-meta">
                      {[formatDurationMs(step.durationMs), formatTokenTotal(step.inputTokens, step.outputTokens)]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                  </div>
                  {step.contentPreview || step.contentFull ? (
                    <pre className="execution-phase-timeline-step-body">{step.contentFull ?? step.contentPreview}</pre>
                  ) : null}
                  {step.error ? (
                    <div className="execution-phase-timeline-step-error" role="status">
                      {step.error}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}
