import React, { useCallback, useState } from 'react';

export interface ExecutionFailureCardProps {
  failingPhase: string | null;
  errorClass: string | null;
  errorMessage: string | null;
  runId: string | null;
  rawRunHref?: string | null;
  onRetry: () => void;
  retryPending: boolean;
}

function toTitleCase(input: string): string {
  return input.replace(/\b\w/g, (char) => char.toUpperCase());
}

function toStatusLabel(status: string): string {
  return status.replace(/_/g, ' ');
}

/**
 * First-class failure surface for drawer execution UX.
 */
export function ExecutionFailureCard({
  failingPhase,
  errorClass,
  errorMessage,
  runId,
  rawRunHref,
  onRetry,
  retryPending,
}: ExecutionFailureCardProps): React.JSX.Element {
  const [copied, setCopied] = useState(false);

  const handleCopyRun = useCallback(async () => {
    if (!runId) return;
    try {
      await navigator.clipboard.writeText(runId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [runId]);

  return (
    <section className="execution-failure-card" role="alert" aria-label="Execution failed">
      <div className="execution-failure-card-header">
        <h3 className="execution-failure-card-title">Execution failed</h3>
        {failingPhase ? (
          <span className="execution-failure-phase">Phase: {toTitleCase(toStatusLabel(failingPhase))}</span>
        ) : null}
      </div>
      {errorClass ? (
        <div className="execution-failure-class">
          <span className="execution-failure-class-label">Class</span>
          <code>{errorClass}</code>
        </div>
      ) : null}
      {errorMessage ? <p className="execution-failure-message">{errorMessage}</p> : null}
      {runId ? (
        <div className="execution-failure-run">
          <span className="execution-failure-run-label">Run ID</span>
          <code className="execution-failure-run-id">{runId}</code>
        </div>
      ) : null}
      <div className="execution-failure-actions">
        <button
          type="button"
          className="execution-action-button pressable"
          onClick={onRetry}
          disabled={retryPending}
          aria-label="Retry execution"
        >
          {retryPending ? 'Retrying…' : 'Retry'}
        </button>
        {runId ? (
          <button
            type="button"
            className="execution-action-button execution-action-secondary pressable"
            onClick={handleCopyRun}
            aria-label="Copy run ID to clipboard"
          >
            {copied ? 'Copied' : 'Copy run ID'}
          </button>
        ) : null}
        {rawRunHref ? (
          <a className="execution-action-button execution-action-ghost" href={rawRunHref}>
            View raw run
          </a>
        ) : null}
      </div>
    </section>
  );
}
