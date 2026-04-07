/**
 * StreamingMessage — Streaming AI message with thinking indicator.
 *
 * Shows a pulsing "thinking" indicator while waiting for tokens,
 * then renders incoming tokens progressively via react-markdown.
 * Crossfades to final state when streaming completes.
 */

import { memo, useMemo } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useMessageStream } from '../../api/conversations';

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
}: StreamingMessageProps) {
  const { fullText, isStreaming, error } = useMessageStream(conversationId, messageId);

  // Progressive glass tint: opacity 0.3 → 0.72 based on character count
  const glassOpacity = useMemo(() => {
    const base = 0.3;
    const max = 0.72;
    const chars = fullText.length;
    // Reach max opacity around 500 chars
    const progress = Math.min(chars / 500, 1);
    return base + (max - base) * progress;
  }, [fullText.length]);

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
        <span className="streaming-error-text">Connection lost</span>
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
        <ThinkingIndicator />
        <span className="streaming-thinking-label">Thinking...</span>
      </div>
    );
  }

  // Streaming content
  return (
    <div
      className={`streaming-msg ${!isStreaming ? 'streaming-msg--complete' : ''}`}
      style={{
        '--glass-opacity': glassOpacity,
      } as React.CSSProperties}
    >
      <div className="streaming-avatar">
        <AgentAvatar />
      </div>
      <div className="streaming-content">
        <div className="streaming-markdown">
          <Markdown remarkPlugins={[remarkGfm]}>
            {fullText}
          </Markdown>
        </div>
        {isStreaming && <span className="streaming-cursor" />}
      </div>
    </div>
  );
});

// ── ThinkingIndicator ────────────────────────────────────────────────────────

function ThinkingIndicator() {
  return (
    <div className="thinking-indicator" aria-label="Thinking" role="status">
      <span className="thinking-dot" />
      <span className="thinking-dot" />
      <span className="thinking-dot" />
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
