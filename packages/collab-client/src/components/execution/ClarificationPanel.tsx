/**
 * ClarificationPanel - First-class UX for agent clarification requests
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md:
 * - 60fps animations via GPU-accelerated transforms
 * - Floaty spring animations on state changes
 * - Accessible keyboard interactions
 * - Shared across web-console and VS Code webview
 */

import React, { useCallback, useState, useRef, useEffect, useMemo, memo } from 'react';
import { ensureExecutionStyles } from './executionStyles.js';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ClarificationQuestion {
  /** Unique identifier for the question */
  id: string;
  /** The question prompt from the agent */
  question: string;
  /** Optional context about why this is being asked */
  context?: string | null;
  /** Whether a response is required to continue */
  required?: boolean;
}

export interface ClarificationPanelProps {
  /** List of clarification questions from the agent */
  questions: ClarificationQuestion[];
  /** Callback when user submits a response */
  onSubmit: (questionId: string, response: string) => void;
  /** Whether submission is in progress */
  isSubmitting?: boolean;
  /** Optional className for styling overrides */
  className?: string;
  /** Title shown above questions */
  title?: string;
  /** Empty state message when no questions */
  emptyMessage?: string;
  /** Whether to show the panel in an expanded state */
  expanded?: boolean;
}

// ---------------------------------------------------------------------------
// Styles (injected once)
// ---------------------------------------------------------------------------

const CLARIFICATION_STYLE_ID = 'ga-clarification-ui-styles';

const CLARIFICATION_STYLES = `
.ga-clar-panel {
  border-radius: var(--radius-xl, 12px);
  border: 1px solid rgba(245, 158, 11, 0.25);
  background: linear-gradient(
    135deg,
    rgba(255, 251, 235, 0.95) 0%,
    rgba(254, 243, 199, 0.85) 100%
  );
  backdrop-filter: blur(12px);
  padding: var(--space-4, 16px);
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
  opacity: 0;
  transform: translateY(8px);
  animation: ga-clar-fade-in 0.3s var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1)) forwards;
}

@keyframes ga-clar-fade-in {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.ga-clar-header {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
}

.ga-clar-icon {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-full, 9999px);
  background: rgba(245, 158, 11, 0.2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.ga-clar-title {
  font-size: var(--text-sm, 0.8125rem);
  font-weight: var(--font-semibold, 600);
  color: var(--color-text-primary, #0f172a);
}

.ga-clar-subtitle {
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-tertiary, #64748b);
  margin-left: auto;
}

.ga-clar-questions {
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
}

.ga-clar-card {
  border-radius: var(--radius-lg, 8px);
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: rgba(255, 255, 255, 0.9);
  padding: var(--space-4, 16px);
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
  opacity: 0;
  transform: translateY(6px);
  animation: ga-clar-card-in 0.25s var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1)) forwards;
}

.ga-clar-card:nth-child(1) { animation-delay: 0.05s; }
.ga-clar-card:nth-child(2) { animation-delay: 0.1s; }
.ga-clar-card:nth-child(3) { animation-delay: 0.15s; }
.ga-clar-card:nth-child(4) { animation-delay: 0.2s; }

@keyframes ga-clar-card-in {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.ga-clar-question-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2, 8px);
}

.ga-clar-question-number {
  width: 22px;
  height: 22px;
  border-radius: var(--radius-full, 9999px);
  background: rgba(59, 130, 246, 0.15);
  color: var(--color-accent, #3b82f6);
  font-size: 11px;
  font-weight: var(--font-semibold, 600);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ga-clar-question-text {
  font-size: var(--text-sm, 0.8125rem);
  color: var(--color-text-primary, #0f172a);
  line-height: var(--leading-relaxed, 1.625);
  flex: 1;
}

.ga-clar-question-text strong {
  font-weight: var(--font-semibold, 600);
}

.ga-clar-context {
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-tertiary, #64748b);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  border-radius: var(--radius-md, 6px);
  background: rgba(15, 23, 42, 0.04);
  border-left: 2px solid rgba(59, 130, 246, 0.4);
}

.ga-clar-input-wrapper {
  position: relative;
}

.ga-clar-input {
  width: 100%;
  border-radius: var(--radius-lg, 8px);
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: rgba(255, 255, 255, 0.95);
  padding: var(--space-3, 12px);
  padding-right: 100px;
  color: var(--color-text-primary, #0f172a);
  font-size: var(--text-sm, 0.8125rem);
  line-height: var(--leading-relaxed, 1.625);
  resize: vertical;
  min-height: 80px;
  transition:
    border-color 0.15s cubic-bezier(0.16, 1, 0.3, 1),
    box-shadow 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}

.ga-clar-input::placeholder {
  color: var(--color-text-disabled, #94a3b8);
}

.ga-clar-input:hover {
  border-color: rgba(15, 23, 42, 0.2);
}

.ga-clar-input:focus {
  outline: none;
  border-color: var(--color-accent, #3b82f6);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.ga-clar-actions {
  position: absolute;
  bottom: var(--space-2, 8px);
  right: var(--space-2, 8px);
  display: flex;
  gap: var(--space-2, 8px);
}

.ga-clar-submit {
  border-radius: var(--radius-lg, 8px);
  border: none;
  background: var(--color-accent, #3b82f6);
  color: white;
  padding: var(--space-2, 8px) var(--space-3, 12px);
  font-size: var(--text-xs, 0.75rem);
  font-weight: var(--font-medium, 500);
  cursor: pointer;
  transition:
    background-color 0.1s cubic-bezier(0.16, 1, 0.3, 1),
    transform 0.15s cubic-bezier(0.34, 1.56, 0.64, 1),
    opacity 0.1s;
  will-change: transform;
}

.ga-clar-submit:hover:not(:disabled) {
  background: var(--color-accent-hover, #60a5fa);
  transform: translateY(-1px);
}

.ga-clar-submit:active:not(:disabled) {
  transform: translateY(0) scale(0.98);
}

.ga-clar-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ga-clar-submit.ga-clar-submitting {
  position: relative;
  color: transparent;
}

.ga-clar-submit.ga-clar-submitting::after {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: ga-clar-spin 0.6s linear infinite;
  left: 50%;
  top: 50%;
  margin-left: -7px;
  margin-top: -7px;
}

@keyframes ga-clar-spin {
  to { transform: rotate(360deg); }
}

.ga-clar-hint {
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-tertiary, #64748b);
  display: flex;
  align-items: center;
  gap: var(--space-1, 4px);
}

.ga-clar-hint kbd {
  border-radius: var(--radius-sm, 4px);
  border: 1px solid rgba(15, 23, 42, 0.15);
  background: rgba(15, 23, 42, 0.04);
  padding: 1px 4px;
  font-family: var(--font-mono, monospace);
  font-size: 10px;
}

.ga-clar-empty {
  border-radius: var(--radius-xl, 12px);
  border: 1px dashed rgba(15, 23, 42, 0.15);
  background: rgba(255, 255, 255, 0.6);
  padding: var(--space-4, 16px);
  color: var(--color-text-tertiary, #64748b);
  font-size: var(--text-sm, 0.8125rem);
  text-align: center;
}

.ga-clar-success {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  border-radius: var(--radius-lg, 8px);
  background: rgba(34, 197, 94, 0.12);
  border: 1px solid rgba(34, 197, 94, 0.25);
  color: var(--color-text-primary, #0f172a);
  font-size: var(--text-sm, 0.8125rem);
  opacity: 0;
  transform: translateY(-4px);
  animation: ga-clar-success-in 0.3s var(--ease-spring, cubic-bezier(0.34, 1.56, 0.64, 1)) forwards;
}

@keyframes ga-clar-success-in {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.ga-clar-success-icon {
  width: 18px;
  height: 18px;
  border-radius: var(--radius-full, 9999px);
  background: rgba(34, 197, 94, 0.2);
  color: var(--color-success, #22c55e);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
`;

function ensureClarificationStyles(): void {
  if (typeof document === 'undefined') return;
  if (document.getElementById(CLARIFICATION_STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = CLARIFICATION_STYLE_ID;
  style.textContent = CLARIFICATION_STYLES;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract a concise question from potentially long LLM response */
function extractConciseQuestion(text: string): { summary: string; details: string | null } {
  // Look for explicit question markers
  const questionPatterns = [
    /\*\*Clarifications? Needed\*\*:?\s*([\s\S]*?)(?:\n\n|\n##|$)/i,
    /(?:^|\n)(?:before (?:i |we )?proceed(?:ing)?)[,:]?\s*([\s\S]*?)(?:\n\n|$)/i,
    /(?:^|\n)(?:i need to (?:know|understand))[,:]?\s*([\s\S]*?)(?:\n\n|$)/i,
    /(?:^|\n)(?:could you (?:please )?(?:clarify|explain|provide))[,:]?\s*([\s\S]*?)(?:\n\n|$)/i,
    /(?:^|\n)\d+\.\s*\*\*([^*]+)\*\*:?\s*([^\n]+)/gm, // Numbered bold questions
  ];

  // Try to extract numbered questions (like "1. **Question**: ...")
  const numberedPattern = /\d+\.\s*\*\*([^*]+)\*\*:?\s*([^\n]+)/g;
  const numberedMatches = [...text.matchAll(numberedPattern)];
  if (numberedMatches.length > 0) {
    const questions = numberedMatches.map(m => `**${m[1].trim()}**: ${m[2].trim()}`).join('\n');
    return { summary: questions, details: null };
  }

  // Look for "Clarifications Needed" section
  const clarSection = text.match(/##\s*Clarifications? Needed\s*([\s\S]*?)(?:\n##|$)/i);
  if (clarSection) {
    const content = clarSection[1].trim();
    // Extract just the questions
    const lines = content.split('\n').filter(l => l.trim().startsWith('-') || l.trim().match(/^\d+\./));
    if (lines.length > 0) {
      return { summary: lines.join('\n'), details: null };
    }
    return { summary: content.slice(0, 500), details: content.length > 500 ? content : null };
  }

  // If text is short enough, use as-is
  if (text.length <= 300) {
    return { summary: text, details: null };
  }

  // Otherwise truncate with "show more"
  return { summary: text.slice(0, 280) + '…', details: text };
}

/** Format question text with basic markdown-like styling */
function formatQuestionText(text: string): React.ReactNode {
  // Simple bold handling
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface ClarificationCardProps {
  question: ClarificationQuestion;
  index: number;
  draft: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
}

const ClarificationCard = memo(function ClarificationCard({
  question,
  index,
  draft,
  onChange,
  onSubmit,
  isSubmitting,
}: ClarificationCardProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showDetails, setShowDetails] = useState(false);

  const { summary, details } = useMemo(
    () => extractConciseQuestion(question.question),
    [question.question]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        if (draft.trim()) {
          onSubmit();
        }
      }
    },
    [draft, onSubmit]
  );

  const canSubmit = draft.trim().length > 0 && !isSubmitting;

  return (
    <div className="ga-clar-card">
      <div className="ga-clar-question-header">
        <span className="ga-clar-question-number">{index + 1}</span>
        <div className="ga-clar-question-text">
          {formatQuestionText(summary)}
          {details && (
            <button
              type="button"
              onClick={() => setShowDetails(!showDetails)}
              style={{
                marginLeft: 4,
                background: 'none',
                border: 'none',
                color: 'var(--color-accent, #3b82f6)',
                fontSize: 'var(--text-xs, 0.75rem)',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              {showDetails ? 'Show less' : 'Show more'}
            </button>
          )}
        </div>
      </div>

      {showDetails && details && (
        <div className="ga-clar-context" style={{ whiteSpace: 'pre-wrap' }}>
          {details}
        </div>
      )}

      {question.context && !showDetails && (
        <div className="ga-clar-context">{question.context}</div>
      )}

      <div className="ga-clar-input-wrapper">
        <textarea
          ref={textareaRef}
          className="ga-clar-input"
          value={draft}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your response…"
          rows={3}
          disabled={isSubmitting}
          aria-label={`Response to question ${index + 1}`}
        />
        <div className="ga-clar-actions">
          <button
            type="button"
            className={`ga-clar-submit ${isSubmitting ? 'ga-clar-submitting' : ''}`}
            onClick={onSubmit}
            disabled={!canSubmit}
            data-haptic="medium"
          >
            {isSubmitting ? 'Sending…' : 'Send'}
          </button>
        </div>
      </div>

      <div className="ga-clar-hint">
        <kbd>⌘</kbd>+<kbd>Enter</kbd> to send
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export const ClarificationPanel = memo(function ClarificationPanel({
  questions,
  onSubmit,
  isSubmitting = false,
  className,
  title = 'Agent needs your input',
  emptyMessage = 'No clarifications pending.',
}: ClarificationPanelProps) {
  // Inject styles on first render
  useEffect(() => {
    ensureExecutionStyles();
    ensureClarificationStyles();
  }, []);

  // Track drafts per question
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState<Set<string>>(new Set());

  const handleChange = useCallback((questionId: string, value: string) => {
    setDrafts((prev) => ({ ...prev, [questionId]: value }));
  }, []);

  const handleSubmit = useCallback(
    (questionId: string) => {
      const response = drafts[questionId]?.trim();
      if (!response) return;
      onSubmit(questionId, response);
      setSubmitted((prev) => new Set(prev).add(questionId));
    },
    [drafts, onSubmit]
  );

  // Filter out already-submitted questions
  const pendingQuestions = useMemo(
    () => questions.filter((q) => !submitted.has(q.id)),
    [questions, submitted]
  );

  if (pendingQuestions.length === 0 && questions.length === 0) {
    return null; // Don't show empty panel
  }

  const panelClassName = ['ga-clar-panel', className].filter(Boolean).join(' ');

  return (
    <div className={panelClassName} role="region" aria-label="Clarification requests">
      <div className="ga-clar-header">
        <span className="ga-clar-icon" aria-hidden="true">💬</span>
        <span className="ga-clar-title">{title}</span>
        {pendingQuestions.length > 0 && (
          <span className="ga-clar-subtitle">
            {pendingQuestions.length} {pendingQuestions.length === 1 ? 'question' : 'questions'}
          </span>
        )}
      </div>

      {pendingQuestions.length === 0 && questions.length > 0 && (
        <div className="ga-clar-success">
          <span className="ga-clar-success-icon">✓</span>
          <span>Responses sent! The agent will continue shortly.</span>
        </div>
      )}

      {pendingQuestions.length > 0 && (
        <div className="ga-clar-questions">
          {pendingQuestions.map((question, index) => (
            <ClarificationCard
              key={question.id}
              question={question}
              index={index}
              draft={drafts[question.id] ?? ''}
              onChange={(value) => handleChange(question.id, value)}
              onSubmit={() => handleSubmit(question.id)}
              isSubmitting={isSubmitting}
            />
          ))}
        </div>
      )}
    </div>
  );
});

export type { ClarificationPanelProps as ClarificationPanelPropsType };
