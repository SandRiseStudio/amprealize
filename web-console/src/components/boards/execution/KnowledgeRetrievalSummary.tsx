import React, { useId, useMemo } from 'react';

export interface KnowledgeRetrievalSummaryProps {
  data?: Record<string, unknown> | null;
  className?: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/**
 * Shows ``trace_summary.knowledge_retrieval`` from execution status (OSS web-console).
 */
export function KnowledgeRetrievalSummary({
  data,
  className,
}: KnowledgeRetrievalSummaryProps): React.JSX.Element | null {
  const slice = useMemo(() => asRecord(data), [data]);
  const count = typeof slice?.span_count === 'number' ? slice.span_count : 0;
  const spans = Array.isArray(slice?.spans) ? (slice!.spans as unknown[]) : [];
  const baseId = useId();
  const panelId = `${baseId}-kr-panel`;
  const btnId = `${baseId}-kr-btn`;

  if (!slice || count === 0 || spans.length === 0) {
    return null;
  }

  return (
    <div className={`execution-knowledge-receipt ${className ?? ''}`.trim()}>
      <details className="execution-knowledge-receipt-details">
        <summary id={btnId} className="execution-knowledge-receipt-summary" aria-controls={panelId}>
          <span className="execution-knowledge-receipt-heading">Knowledge sources</span>
          <span className="execution-knowledge-receipt-count" aria-hidden="true">
            ({count})
          </span>
        </summary>
        <div id={panelId} role="region" aria-labelledby={btnId} className="execution-knowledge-receipt-panel">
          <ul className="execution-knowledge-receipt-list">
            {spans.map((row, idx) => {
              const s = asRecord(row);
              if (!s) return null;
              const title = String(s.title ?? s.anchor ?? 'source');
              const channel = s.channel != null ? String(s.channel) : '';
              const phase = s.phase != null ? String(s.phase) : '';
              const meta = [channel, phase].filter(Boolean).join(' · ');
              return (
                <li key={String(s.span_id ?? idx)} className="execution-knowledge-receipt-item">
                  <span className="execution-knowledge-receipt-title">{title}</span>
                  {meta ? <span className="execution-knowledge-receipt-meta">{meta}</span> : null}
                </li>
              );
            })}
          </ul>
        </div>
      </details>
    </div>
  );
}
