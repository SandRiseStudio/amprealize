import React from 'react';
import { ClarificationPanel, type ClarificationQuestion } from '../../../lib/collab-client';

export interface InlineGatePanelProps {
  state: string | null | undefined;
  questions: ClarificationQuestion[];
  onClarifySubmit: (questionId: string, response: string) => void;
  clarifySubmitting: boolean;
  onApproveGate: () => void;
  approveGatePending: boolean;
}

/**
 * Clarifications plus strict-gate approval when paused with no pending questions.
 */
export function InlineGatePanel({
  state,
  questions,
  onClarifySubmit,
  clarifySubmitting,
  onApproveGate,
  approveGatePending,
}: InlineGatePanelProps): React.JSX.Element {
  const normalized = state ? String(state).toLowerCase() : '';
  const showStrictGate = normalized === 'paused' && questions.length === 0;

  if (questions.length === 0 && !showStrictGate) {
    return <></>;
  }

  return (
    <div className="execution-inline-gate">
      {questions.length > 0 ? (
        <ClarificationPanel
          questions={questions}
          onSubmit={onClarifySubmit}
          isSubmitting={clarifySubmitting}
          title="Agent needs your input"
          className="execution-clarification-panel"
        />
      ) : null}
      {showStrictGate ? (
        <div className="execution-strict-gate" role="region" aria-label="Strict gate approval">
          <p className="execution-strict-gate-copy">
            This run is paused at a strict gate. Approve to let the agent continue.
          </p>
          <button
            type="button"
            className="execution-action-button pressable"
            onClick={onApproveGate}
            disabled={approveGatePending}
            aria-label="Approve strict gate and resume execution"
          >
            {approveGatePending ? 'Approving…' : 'Approve gate'}
          </button>
        </div>
      ) : null}
    </div>
  );
}
