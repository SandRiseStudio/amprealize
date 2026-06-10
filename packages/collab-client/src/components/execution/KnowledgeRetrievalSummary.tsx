import React, { useEffect, useId, useMemo } from 'react';
import { ensureExecutionStyles } from './executionStyles.js';

export interface KnowledgeRetrievalSummaryProps {
  /** ``trace_summary.knowledge_retrieval`` from execution API */
  data?: Record<string, unknown> | null;
  className?: string;
  /** Heading text for the disclosure region */
  heading?: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/**
 * Compact list of retrieved knowledge sources (behaviors, wiki, etc.) for a run.
 */
export function KnowledgeRetrievalSummary({
  data,
  className,
  heading = 'Knowledge sources',
}: KnowledgeRetrievalSummaryProps): React.JSX.Element | null {
  const slice = useMemo(() => asRecord(data), [data]);
  const count = typeof slice?.span_count === 'number' ? slice.span_count : 0;
  const spans = Array.isArray(slice?.spans) ? (slice!.spans as unknown[]) : [];
  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const buttonId = `${baseId}-button`;

  useEffect(() => {
    ensureExecutionStyles();
  }, []);

  if (!slice || count === 0 || spans.length === 0) {
    return null;
  }

  return (
    <div className={`ga-knowledge-receipt ${className ?? ''}`.trim()}>
      <details className="ga-knowledge-receipt-details">
        <summary
          id={buttonId}
          className="ga-knowledge-receipt-summary"
          aria-controls={panelId}
        >
          <span className="ga-knowledge-receipt-heading">{heading}</span>
          <span className="ga-knowledge-receipt-count" aria-hidden="true">
            ({count})
          </span>
        </summary>
        <div id={panelId} role="region" aria-labelledby={buttonId} className="ga-knowledge-receipt-panel">
          <ul className="ga-knowledge-receipt-list">
            {spans.map((row, idx) => {
              const s = asRecord(row);
              if (!s) return null;
              const title = String(s.title ?? s.anchor ?? 'source');
              const channel = s.channel != null ? String(s.channel) : '';
              const phase = s.phase != null ? String(s.phase) : '';
              const meta = [channel, phase].filter(Boolean).join(' · ');
              return (
                <li key={String(s.span_id ?? idx)} className="ga-knowledge-receipt-item">
                  <span className="ga-knowledge-receipt-title">{title}</span>
                  {meta ? <span className="ga-knowledge-receipt-meta">{meta}</span> : null}
                </li>
              );
            })}
          </ul>
        </div>
      </details>
    </div>
  );
}
