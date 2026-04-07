/**
 * BCIResponsePanel - Query input and behavior retrieval display
 */

import { useState } from 'react';
import { useBCIRetrieve, useBCIStatus, type BehaviorMatch } from '../api/bci';
import { CitationHighlighter } from './CitationHighlighter';
import './BCIResponsePanel.css';

interface BCIResponsePanelProps {
  onBehaviorSelect?: (behavior: BehaviorMatch) => void;
}

export function BCIResponsePanel({ onBehaviorSelect }: BCIResponsePanelProps) {
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(5);

  const { data: status } = useBCIStatus();
  const retrieveMutation = useBCIRetrieve();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    retrieveMutation.mutate({
      query: query.trim(),
      top_k: topK,
    });
  };

  return (
    <div className="bci-panel">
      <div className="panel-header">
        <h2>Behavior Search</h2>
        {status && (
          <div className="status-badge">
            <span className={`status-dot ${status.index_built ? 'active' : 'inactive'}`} />
            {status.behavior_count} behaviors indexed
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="query-form">
        <div className="form-row">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Describe the task or query for behavior retrieval..."
            className="query-input"
          />
          <div className="topk-selector">
            <label htmlFor="topk">Top-K:</label>
            <input
              id="topk"
              type="number"
              min={1}
              max={20}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            />
          </div>
          <button
            type="submit"
            className="retrieve-btn"
            disabled={retrieveMutation.isPending || !query.trim()}
          >
            {retrieveMutation.isPending ? 'Retrieving...' : 'Retrieve'}
          </button>
        </div>
      </form>

      {retrieveMutation.error && (
        <div className="error-message">
          Error: {retrieveMutation.error instanceof Error ? retrieveMutation.error.message : 'Failed to retrieve behaviors'}
        </div>
      )}

      {retrieveMutation.data && (
        <div className="results-section">
          <div className="results-header">
            <span className="results-count">
              {retrieveMutation.data.matches.length} behaviors found
            </span>
            <span className="results-meta">
              Searched {retrieveMutation.data.total_behaviors_searched} behaviors
              in {retrieveMutation.data.retrieval_time_ms.toFixed(0)}ms
            </span>
          </div>

          <div className="behavior-list">
            {retrieveMutation.data.matches.map((behavior) => (
              <div
                key={behavior.behavior_id}
                className="behavior-card"
                onClick={() => onBehaviorSelect?.(behavior)}
                role="button"
                tabIndex={0}
              >
                <div className="behavior-header">
                  <span className="behavior-name">{behavior.name}</span>
                  <span className="behavior-score">
                    {(behavior.score * 100).toFixed(0)}% match
                  </span>
                </div>
                <div className="behavior-instruction">
                  <CitationHighlighter text={behavior.instruction} />
                </div>
                {behavior.tags.length > 0 && (
                  <div className="behavior-tags">
                    {behavior.tags.map((tag) => (
                      <span key={tag} className="tag">{tag}</span>
                    ))}
                  </div>
                )}
                {behavior.relevance_explanation && (
                  <div className="behavior-relevance">
                    {behavior.relevance_explanation}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {!retrieveMutation.data && !retrieveMutation.isPending && (
        <div className="empty-state">
          <p>Enter a query to retrieve relevant behaviors from the handbook.</p>
          <p className="hint">
            The BCI retriever uses hybrid semantic + keyword search to find the most
            relevant procedures for your task.
          </p>
        </div>
      )}
    </div>
  );
}

export default BCIResponsePanel;
