import React from 'react';
import type { PhaseRowModel } from './selectPhaseModel';

export interface PhaseStepperProps {
  phases: PhaseRowModel[];
  /** Index in GEP_PHASE_ORDER for aria-current, or -1 */
  currentPhaseIndex: number;
}

function statusClass(status: PhaseRowModel['status']): string {
  switch (status) {
    case 'done':
      return 'execution-phase-step--done';
    case 'running':
      return 'execution-phase-step--running';
    case 'failed':
      return 'execution-phase-step--failed';
    case 'skipped':
      return 'execution-phase-step--skipped';
    default:
      return 'execution-phase-step--idle';
  }
}

/**
 * Horizontal GEP phase stepper with motion preference support via CSS.
 */
export function PhaseStepper({ phases, currentPhaseIndex }: PhaseStepperProps): React.JSX.Element {
  return (
    <nav className="execution-phase-stepper" aria-label="Execution phases">
      <ol className="execution-phase-stepper-list">
        {phases.map((phase, index) => {
          const isCurrent = index === currentPhaseIndex && (phase.status === 'running' || phase.status === 'failed');
          const isFailed = phase.status === 'failed';
          return (
            <li
              key={phase.id}
              className={`execution-phase-step ${statusClass(phase.status)}`}
              aria-current={isCurrent ? 'step' : undefined}
              role={isFailed ? 'alert' : undefined}
            >
              <span className="execution-phase-step-track" aria-hidden="true">
                <span className="execution-phase-step-dot" />
              </span>
              <span className="execution-phase-step-label">{phase.label}</span>
              {phase.durationMs != null && phase.durationMs > 0 ? (
                <span className="execution-phase-step-duration">
                  {phase.durationMs < 1000 ? `${Math.round(phase.durationMs)}ms` : `${(phase.durationMs / 1000).toFixed(1)}s`}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
