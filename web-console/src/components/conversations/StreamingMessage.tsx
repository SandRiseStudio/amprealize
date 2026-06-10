/**
 * StreamingMessage — Streaming AI message with thinking indicator.
 *
 * Shows a pulsing "thinking" indicator while waiting for tokens,
 * then renders incoming tokens progressively via react-markdown (GFM, breaks, fenced highlight).
 * Crossfades to final state when streaming completes.
 */

import { memo, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { ChatMarkdownWithArtifacts } from './chatArtifactChips';
import { refsFromStructuredPayloadRows } from './chatArtifactRefsFromRows';
import { useMessageStream } from '../../api/conversations';

/** Map internal SSE phases to short user-facing labels (never show raw snake_case tags). */
const PHASE_DISPLAY: Record<string, string> = {
  connecting: 'Connecting',
  context: 'Reading context',
  context_ready: 'Context ready',
  planning: 'Planning',
  planning_ready: 'Ready',
  planning_fallback: 'Broader view',
  planning_fallback_timeout: 'Planner timed out',
  fetching: 'Gathering tasks',
  fetch_ready: 'Tasks loaded',
  fetch_failed: 'Could not load tasks',
  fetch_empty: 'No matches',
  tool_call: 'Calling tool',
  generation: 'Drafting',
  complete: 'Done',
  persisting: 'Saving',
  direct_answer: 'Answer',
  platform_action: 'Action',
  chat_execution: 'Execution',
};

function formatPhaseForDisplay(phase: string | null): string | null {
  if (!phase) return null;
  return PHASE_DISPLAY[phase] ?? phase.replace(/_/g, ' ');
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface StreamingMessageProps {
  conversationId: string;
  messageId: string;
  onComplete?: () => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export const StreamingMessage = memo(function StreamingMessage({
  conversationId,
  messageId,
  onComplete,
}: StreamingMessageProps) {
  const { fullText, isStreaming, error, statusLabel, phase, sourceCounts, traceSteps, sourceRows, badge } = useMessageStream(conversationId, messageId);

  const streamArtifactRefs = useMemo(
    () => refsFromStructuredPayloadRows({ rows: sourceRows }),
    [sourceRows],
  );
  const [displayText, setDisplayText] = useState('');
  const [showTrace, setShowTrace] = useState(false);
  const completeNotifiedRef = useRef(false);
  const prefersReducedMotion = useMemo(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }, []);

  useEffect(() => {
    if (prefersReducedMotion || !isStreaming || fullText.length < 24) {
      setDisplayText(fullText);
      return undefined;
    }

    if (displayText.length > fullText.length) {
      setDisplayText(fullText);
      return undefined;
    }

    const timer = window.setInterval(() => {
      setDisplayText((current) => {
        if (current.length >= fullText.length) {
          window.clearInterval(timer);
          return current;
        }
        return fullText.slice(0, Math.min(current.length + 3, fullText.length));
      });
    }, 16);

    return () => window.clearInterval(timer);
  }, [displayText.length, fullText, isStreaming, prefersReducedMotion]);

  useEffect(() => {
    if (completeNotifiedRef.current) return;
    if (!isStreaming && (fullText.length > 0 || error)) {
      completeNotifiedRef.current = true;
      onComplete?.();
    }
  }, [error, fullText.length, isStreaming, onComplete]);

  // Progressive glass tint: opacity 0.3 → 0.72 based on character count
  const glassOpacity = useMemo(() => {
    const base = 0.3;
    const max = 0.72;
    const chars = displayText.length;
    // Reach max opacity around 500 chars
    const progress = Math.min(chars / 500, 1);
    return base + (max - base) * progress;
  }, [displayText.length]);

  const plannerTimeoutFootnote = useMemo(() => {
    if (isStreaming) {
      return null;
    }
    for (let i = traceSteps.length - 1; i >= 0; i -= 1) {
      const step = traceSteps[i];
      if (step && step.failure_reason === 'planner_timeout') {
        return 'The task planner took too long, so this answer uses your workspace summary instead of pulling fresh tasks per project.';
      }
    }
    return null;
  }, [isStreaming, traceSteps]);

  // Error state
  if (error) {
    return (
      <div className="streaming-msg streaming-msg--error">
        <div className="streaming-error-icon">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
            <circle cx="8" cy="8" r="6" />
            <path d="M8 5v4M8 11v.5" />
          </svg>
        </div>
        <span className="streaming-error-text">{error || 'Connection lost'}</span>
        <button type="button" className="streaming-retry-btn pressable" disabled>
          Retry
        </button>
      </div>
    );
  }

  // Thinking indicator (no tokens yet)
  if (isStreaming && fullText.length === 0) {
    return (
      <div className="streaming-msg streaming-msg--thinking">
        <ThinkingIndicator label={statusLabel} />
        <div className="streaming-thinking-copy">
          <span className="streaming-thinking-label">{statusLabel}</span>
          <TraceSummary
            badge={badge}
            phase={phase}
            sourceCounts={sourceCounts}
            traceSteps={traceSteps}
            sourceRows={sourceRows}
            isStreaming={isStreaming}
            expanded={showTrace}
            onToggle={() => setShowTrace((value) => !value)}
          />
        </div>
      </div>
    );
  }

  // Streaming content
  return (
    <div
      className={`streaming-msg ${!isStreaming ? 'streaming-msg--complete' : ''}`}
      style={{
        '--glass-opacity': glassOpacity,
      } as CSSProperties}
      aria-busy={isStreaming}
    >
      <div className="streaming-avatar">
        <AgentAvatar />
      </div>
      <div className="streaming-content">
        <div className="streaming-status-line" role="status" aria-live="polite">
          {badge ? <span className="streaming-fast-badge">{badge}</span> : null}
          {statusLabel}
          {phase ? (
            <span className="streaming-status-phase"> · {formatPhaseForDisplay(phase)}</span>
          ) : null}
        </div>
        <TraceSummary
          badge={badge}
          phase={phase}
          sourceCounts={sourceCounts}
          traceSteps={traceSteps}
          sourceRows={sourceRows}
          isStreaming={isStreaming}
          expanded={showTrace}
          onToggle={() => setShowTrace((value) => !value)}
        />
        <div className="streaming-markdown">
          <ChatMarkdownWithArtifacts markdown={displayText} refs={streamArtifactRefs} />
        </div>
        {!isStreaming && plannerTimeoutFootnote ? (
          <p className="streaming-planner-timeout-hint" role="note">
            {plannerTimeoutFootnote}
          </p>
        ) : null}
        {isStreaming && <span className="streaming-cursor" />}
      </div>
    </div>
  );
});

// ── ThinkingIndicator ────────────────────────────────────────────────────────

function ThinkingIndicator({ label }: { label: string }) {
  return (
    <div className="thinking-indicator" aria-label={label} role="status">
      <span className="thinking-dot" />
      <span className="thinking-dot" />
      <span className="thinking-dot" />
    </div>
  );
}

function TraceSummary({
  badge,
  phase,
  sourceCounts,
  traceSteps,
  sourceRows,
  isStreaming,
  expanded,
  onToggle,
}: {
  badge: string | null;
  phase: string | null;
  sourceCounts: Record<string, number> | null;
  traceSteps: Array<Record<string, unknown>>;
  sourceRows: Array<Record<string, unknown>>;
  isStreaming: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  const totalSources = useMemo(() => {
    if (!sourceCounts) return 0;
    return Object.values(sourceCounts).reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0);
  }, [sourceCounts]);

  if (!badge && !phase && totalSources === 0 && traceSteps.length === 0 && sourceRows.length === 0) {
    return null;
  }

  const label = isStreaming ? 'Live trace' : 'Show work';
  return (
    <div className={`streaming-trace ${expanded ? 'streaming-trace--expanded' : ''}`}>
      <button type="button" className="streaming-trace-toggle" onClick={onToggle}>
        {label}
        {badge ? <span>{badge}</span> : null}
        {totalSources > 0 ? <span>{totalSources} sources</span> : null}
      </button>
      {expanded && (
        <div className="streaming-trace-panel">
          {traceSteps.length > 0 && (
            <div className="streaming-trace-section">
              <div className="streaming-trace-heading">Steps</div>
              {traceSteps.slice(-8).map((step, index) => {
                const p = step.phase != null ? String(step.phase) : null;
                const title = String(step.label ?? step.phase ?? 'Step');
                const ms = step.latency_ms;
                const latency =
                  typeof ms === 'number' && Number.isFinite(ms)
                    ? ms < 2000
                      ? `${Math.round(ms)}ms`
                      : `${(ms / 1000).toFixed(1)}s`
                    : '';
                const phaseTag = p ? formatPhaseForDisplay(p) : null;
                return (
                  <div className="streaming-trace-row" key={`${p ?? 'step'}-${index}`}>
                    {phaseTag ? <span className="streaming-trace-phase-tag">{phaseTag}</span> : null}
                    <span className="streaming-trace-step-title">{title}</span>
                    {typeof step.row_count === 'number' ? <span>{step.row_count} tasks</span> : null}
                    {typeof step.queries_planned === 'number' ? (
                      <span>
                        {step.queries_planned} {step.queries_planned === 1 ? 'check' : 'checks'}
                      </span>
                    ) : null}
                    {typeof step.rows_fetched === 'number' ? (
                      <span>{step.rows_fetched} tasks</span>
                    ) : null}
                    {latency ? <span className="streaming-trace-latency">{latency}</span> : null}
                  </div>
                );
              })}
            </div>
          )}
          {sourceCounts && (
            <div className="streaming-trace-section">
              <div className="streaming-trace-heading">Sources</div>
              {Object.entries(sourceCounts).slice(0, 8).map(([key, value]) => (
                <div className="streaming-trace-row" key={key}>
                  <span>{key}</span>
                  <span>{value}</span>
                </div>
              ))}
            </div>
          )}
          {sourceRows.length > 0 && (
            <div className="streaming-trace-section">
              <div className="streaming-trace-heading">Samples</div>
              {sourceRows.slice(0, 6).map((row, index) => (
                <div className="streaming-trace-row" key={`${String(row.id ?? row.name ?? 'row')}-${index}`}>
                  <span>{String(row.name ?? row.title ?? row.label ?? row.id ?? 'Source row')}</span>
                  {row.status ? <span>{String(row.status)}</span> : null}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Agent Avatar (simple inline) ─────────────────────────────────────────────

function AgentAvatar() {
  return (
    <span className="streaming-agent-avatar" data-sender-type="Agent">
      AI
    </span>
  );
}
