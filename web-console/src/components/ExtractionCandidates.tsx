/**
 * ExtractionCandidates - UI for reviewing and approving extracted behavior candidates
 * Implements auto-accept for candidates with confidence >= 0.8 (per PRD requirement)
 */

import { useState, useEffect } from 'react';
import {
  useReflectionExtract,
  useApproveCandidate,
  useRejectCandidate,
  categorizeCandidates,
  AUTO_ACCEPT_THRESHOLD,
  type ReflectionCandidate,
  type ReflectRequest,
} from '../api/reflection';
import { CitationHighlighter } from './CitationHighlighter';
import './ExtractionCandidates.css';

interface ExtractionCandidatesProps {
  onAutoApproved?: (candidates: ReflectionCandidate[]) => void;
  onCandidateApproved?: (candidate: ReflectionCandidate, behaviorId: string) => void;
}

export function ExtractionCandidates({
  onAutoApproved,
  onCandidateApproved
}: ExtractionCandidatesProps) {
  const [traceText, setTraceText] = useState('');
  const [traceFormat, setTraceFormat] = useState<'chain_of_thought' | 'structured_log' | 'markdown'>('chain_of_thought');
  const [minScore, setMinScore] = useState(0.6);
  const [maxCandidates, setMaxCandidates] = useState(10);
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});

  const extractMutation = useReflectionExtract();
  const approveMutation = useApproveCandidate();
  const rejectMutation = useRejectCandidate();

  // Categorize candidates when extraction completes
  const categorized = extractMutation.data
    ? categorizeCandidates(extractMutation.data.candidates)
    : null;

  // Auto-approve high-confidence candidates when extraction results change
  // We intentionally use extractMutation.data.candidates.length as the dependency
  // to avoid re-running when callbacks change
  const autoApprovedCount = categorized?.autoApproved.length ?? 0;
  useEffect(() => {
    if (autoApprovedCount > 0 && categorized?.autoApproved) {
      onAutoApproved?.(categorized.autoApproved);

      // Automatically submit approvals for auto-accepted candidates
      for (const candidate of categorized.autoApproved) {
        approveMutation.mutate({
          slug: candidate.slug,
          status: 'auto_approved',
          reviewer_notes: `Auto-approved: confidence ${candidate.confidence.toFixed(2)} >= ${AUTO_ACCEPT_THRESHOLD}`,
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoApprovedCount]);

  const handleExtract = (e: React.FormEvent) => {
    e.preventDefault();
    if (!traceText.trim()) return;

    const request: ReflectRequest = {
      trace_text: traceText.trim(),
      trace_format: traceFormat,
      min_quality_score: minScore,
      max_candidates: maxCandidates,
      include_examples: true,
    };

    extractMutation.mutate(request);
  };

  const handleApprove = async (candidate: ReflectionCandidate) => {
    const result = await approveMutation.mutateAsync({
      slug: candidate.slug,
      status: 'approved',
      reviewer_notes: reviewNotes[candidate.slug] || 'Manually approved',
    });

    if (result.behavior_id && onCandidateApproved) {
      onCandidateApproved(candidate, result.behavior_id);
    }
  };

  const handleReject = (candidate: ReflectionCandidate) => {
    rejectMutation.mutate({
      slug: candidate.slug,
      reason: reviewNotes[candidate.slug] || 'Not suitable for handbook',
    });
  };

  return (
    <div className="extraction-panel">
      <div className="panel-header">
        <h2>Behavior Extraction</h2>
        <span className="threshold-badge">
          Auto-accept threshold: {AUTO_ACCEPT_THRESHOLD * 100}%
        </span>
      </div>

      <form onSubmit={handleExtract} className="extraction-form">
        <div className="form-group">
          <label htmlFor="trace-input">Trace / Reasoning Output</label>
          <textarea
            id="trace-input"
            value={traceText}
            onChange={(e) => setTraceText(e.target.value)}
            placeholder="Paste a chain-of-thought trace, structured log, or markdown reasoning output to extract reusable behaviors..."
            rows={8}
          />
        </div>

        <div className="form-options">
          <div className="form-group">
            <label htmlFor="trace-format">Format</label>
            <select
              id="trace-format"
              value={traceFormat}
              onChange={(e) => setTraceFormat(e.target.value as typeof traceFormat)}
            >
              <option value="chain_of_thought">Chain of Thought</option>
              <option value="structured_log">Structured Log</option>
              <option value="markdown">Markdown</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="min-score">Min Quality Score</label>
            <input
              id="min-score"
              type="number"
              min={0}
              max={1}
              step={0.1}
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
            />
          </div>

          <div className="form-group">
            <label htmlFor="max-candidates">Max Candidates</label>
            <input
              id="max-candidates"
              type="number"
              min={1}
              max={50}
              value={maxCandidates}
              onChange={(e) => setMaxCandidates(Number(e.target.value))}
            />
          </div>
        </div>

        <button
          type="submit"
          className="extract-btn"
          disabled={extractMutation.isPending || !traceText.trim()}
        >
          {extractMutation.isPending ? 'Extracting...' : 'Extract Behaviors'}
        </button>
      </form>

      {extractMutation.error && (
        <div className="error-message">
          Error: {extractMutation.error instanceof Error ? extractMutation.error.message : 'Extraction failed'}
        </div>
      )}

      {extractMutation.data && categorized && (
        <div className="results-section">
          <div className="results-summary">
            <h3>Extraction Results</h3>
            <p>{extractMutation.data.summary}</p>
            <div className="summary-stats">
              <span className="stat">
                <strong>{extractMutation.data.trace_step_count}</strong> trace steps analyzed
              </span>
              <span className="stat">
                <strong>{extractMutation.data.candidates.length}</strong> candidates found
              </span>
              <span className="stat auto">
                <strong>{categorized.autoApproved.length}</strong> auto-approved
              </span>
              <span className="stat pending">
                <strong>{categorized.pendingReview.length}</strong> pending review
              </span>
              <span className="stat duplicate">
                <strong>{categorized.duplicates.length}</strong> duplicates
              </span>
            </div>
          </div>

          {/* Auto-approved candidates */}
          {categorized.autoApproved.length > 0 && (
            <div className="candidate-section auto-approved">
              <h4>✓ Auto-Approved (confidence ≥ {AUTO_ACCEPT_THRESHOLD * 100}%)</h4>
              <div className="candidate-list">
                {categorized.autoApproved.map((candidate) => (
                  <CandidateCard
                    key={candidate.slug}
                    candidate={candidate}
                    status="auto_approved"
                  />
                ))}
              </div>
            </div>
          )}

          {/* Pending review candidates */}
          {categorized.pendingReview.length > 0 && (
            <div className="candidate-section pending-review">
              <h4>⏳ Pending Review</h4>
              <div className="candidate-list">
                {categorized.pendingReview.map((candidate) => (
                  <CandidateCard
                    key={candidate.slug}
                    candidate={candidate}
                    status="pending"
                    onApprove={() => handleApprove(candidate)}
                    onReject={() => handleReject(candidate)}
                    notes={reviewNotes[candidate.slug] || ''}
                    onNotesChange={(notes) => setReviewNotes((prev) => ({ ...prev, [candidate.slug]: notes }))}
                    isSubmitting={approveMutation.isPending || rejectMutation.isPending}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Duplicate candidates */}
          {categorized.duplicates.length > 0 && (
            <div className="candidate-section duplicates">
              <h4>⚠️ Duplicates Detected</h4>
              <div className="candidate-list">
                {categorized.duplicates.map((candidate) => (
                  <CandidateCard
                    key={candidate.slug}
                    candidate={candidate}
                    status="duplicate"
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {!extractMutation.data && !extractMutation.isPending && (
        <div className="empty-state">
          <p>Paste a reasoning trace to extract reusable behavior patterns.</p>
          <p className="hint">
            The reflection pipeline analyzes traces, identifies procedural patterns,
            and proposes candidates for the behavior handbook. Candidates with
            confidence ≥ {AUTO_ACCEPT_THRESHOLD * 100}% are automatically approved.
          </p>
        </div>
      )}
    </div>
  );
}

// Sub-component for individual candidates
interface CandidateCardProps {
  candidate: ReflectionCandidate;
  status: 'auto_approved' | 'pending' | 'duplicate' | 'approved' | 'rejected';
  onApprove?: () => void;
  onReject?: () => void;
  notes?: string;
  onNotesChange?: (notes: string) => void;
  isSubmitting?: boolean;
}

function CandidateCard({
  candidate,
  status,
  onApprove,
  onReject,
  notes,
  onNotesChange,
  isSubmitting,
}: CandidateCardProps) {
  const confidencePercent = (candidate.confidence * 100).toFixed(0);
  const qualityScores = candidate.quality_scores;

  return (
    <div className={`candidate-card status-${status}`}>
      <div className="candidate-header">
        <span className="candidate-name">{candidate.display_name}</span>
        <div className="candidate-badges">
          <span className={`confidence-badge ${candidate.confidence >= AUTO_ACCEPT_THRESHOLD ? 'high' : 'medium'}`}>
            {confidencePercent}% confidence
          </span>
          {status === 'auto_approved' && (
            <span className="status-badge auto">Auto-Approved</span>
          )}
          {status === 'duplicate' && candidate.duplicate_behavior_name && (
            <span className="status-badge duplicate">
              Duplicate of {candidate.duplicate_behavior_name}
            </span>
          )}
        </div>
      </div>

      <div className="candidate-slug">
        <code>{candidate.slug}</code>
      </div>

      <div className="candidate-instruction">
        <CitationHighlighter text={candidate.instruction} />
      </div>

      {candidate.summary && (
        <div className="candidate-summary">
          <strong>Summary:</strong> {candidate.summary}
        </div>
      )}

      <div className="quality-scores">
        <span className="score" title="Clarity">
          📝 {(qualityScores.clarity * 100).toFixed(0)}%
        </span>
        <span className="score" title="Generality">
          🌐 {(qualityScores.generality * 100).toFixed(0)}%
        </span>
        <span className="score" title="Reusability">
          ♻️ {(qualityScores.reusability * 100).toFixed(0)}%
        </span>
        <span className="score" title="Correctness">
          ✓ {(qualityScores.correctness * 100).toFixed(0)}%
        </span>
      </div>

      {candidate.tags.length > 0 && (
        <div className="candidate-tags">
          {candidate.tags.map((tag) => (
            <span key={tag} className="tag">{tag}</span>
          ))}
        </div>
      )}

      {candidate.examples.length > 0 && (
        <details className="candidate-examples">
          <summary>Supporting Examples ({candidate.examples.length})</summary>
          <div className="examples-list">
            {candidate.examples.map((ex, i) => (
              <div key={i} className="example">
                <strong>{ex.title}</strong>
                <p>{ex.body}</p>
              </div>
            ))}
          </div>
        </details>
      )}

      {status === 'pending' && (
        <div className="candidate-actions">
          <input
            type="text"
            placeholder="Reviewer notes (optional)"
            value={notes || ''}
            onChange={(e) => onNotesChange?.(e.target.value)}
            className="notes-input"
          />
          <div className="action-buttons">
            <button
              onClick={onApprove}
              disabled={isSubmitting}
              className="btn approve"
            >
              ✓ Approve
            </button>
            <button
              onClick={onReject}
              disabled={isSubmitting}
              className="btn reject"
            >
              ✗ Reject
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ExtractionCandidates;
