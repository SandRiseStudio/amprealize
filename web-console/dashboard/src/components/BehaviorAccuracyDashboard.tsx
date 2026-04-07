import { FunctionalComponent } from 'preact';
import { useState, useEffect, useCallback } from 'preact/hooks';
import './BehaviorAccuracyDashboard.css';

export interface BehaviorEffectiveness {
  behavior_id: string;
  behavior_name: string;
  usage_count: number;
  token_savings_pct: number;
  accuracy_score: number;
  feedback_count: number;
  feedback_source: 'manual' | 'llm' | 'hybrid';
  last_updated: string;
}

export interface AccuracyFeedback {
  behavior_id: string;
  run_id?: string;
  query: string;
  was_helpful: boolean;
  accuracy_rating: 1 | 2 | 3 | 4 | 5;
  comment?: string;
  actor_id: string;
  submitted_at: string;
}

export interface ScoringConfig {
  mode: 'manual' | 'llm' | 'hybrid';
  llm_model?: string;
  auto_score_threshold?: number;
  require_human_review_below?: number;
}

export interface BenchmarkResult {
  benchmark_id: string;
  run_at: string;
  total_queries: number;
  avg_retrieval_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  accuracy_at_k: Record<string, number>;
  mrr: number;
  ndcg: number;
  corpus_size: number;
  model_version: string;
}

interface BehaviorAccuracyDashboardProps {
  apiBaseUrl?: string;
}

const formatPercent = (value: number): string => `${value.toFixed(1)}%`;
const formatMs = (value: number): string => `${value.toFixed(1)}ms`;

export const BehaviorAccuracyDashboard: FunctionalComponent<BehaviorAccuracyDashboardProps> = ({
  apiBaseUrl = '/api/v1'
}) => {
  const [effectiveness, setEffectiveness] = useState<BehaviorEffectiveness[]>([]);
  const [recentFeedback, setRecentFeedback] = useState<AccuracyFeedback[]>([]);
  const [config, setConfig] = useState<ScoringConfig>({ mode: 'manual' });
  const [benchmarks, setBenchmarks] = useState<BenchmarkResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedBehavior, setSelectedBehavior] = useState<string | null>(null);
  const [feedbackForm, setFeedbackForm] = useState({
    was_helpful: true,
    accuracy_rating: 3 as 1 | 2 | 3 | 4 | 5,
    query: '',
    comment: ''
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [effectivenessRes, feedbackRes, configRes, benchmarkRes] = await Promise.all([
        fetch(`${apiBaseUrl}/behaviors/effectiveness`),
        fetch(`${apiBaseUrl}/behaviors/feedback?limit=10`),
        fetch(`${apiBaseUrl}/behaviors/scoring-config`),
        fetch(`${apiBaseUrl}/benchmarks/behavior-retrieval?limit=5`)
      ]);

      if (effectivenessRes.ok) {
        const data = await effectivenessRes.json();
        setEffectiveness(data.effectiveness || []);
      }
      if (feedbackRes.ok) {
        const data = await feedbackRes.json();
        setRecentFeedback(data.feedback || []);
      }
      if (configRes.ok) {
        const data = await configRes.json();
        setConfig(data);
      }
      if (benchmarkRes.ok) {
        const data = await benchmarkRes.json();
        setBenchmarks(data.benchmarks || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const submitFeedback = async (e: Event) => {
    e.preventDefault();
    if (!selectedBehavior) return;

    try {
      const res = await fetch(`${apiBaseUrl}/behaviors/${selectedBehavior}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...feedbackForm,
          behavior_id: selectedBehavior
        })
      });

      if (res.ok) {
        setFeedbackForm({ was_helpful: true, accuracy_rating: 3, query: '', comment: '' });
        setSelectedBehavior(null);
        await fetchData();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit feedback');
    }
  };

  const updateConfig = async (newConfig: ScoringConfig) => {
    try {
      const res = await fetch(`${apiBaseUrl}/behaviors/scoring-config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig)
      });

      if (res.ok) {
        setConfig(newConfig);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update config');
    }
  };

  const triggerBenchmark = async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/benchmarks/behavior-retrieval/run`, {
        method: 'POST'
      });

      if (res.ok) {
        const data = await res.json();
        alert(`Benchmark triggered: ${data.benchmark_id}`);
        // Poll for results
        setTimeout(fetchData, 5000);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to trigger benchmark');
    }
  };

  // Calculate aggregate stats
  const totalUsage = effectiveness.reduce((sum, e) => sum + e.usage_count, 0);
  const avgTokenSavings = effectiveness.length > 0
    ? effectiveness.reduce((sum, e) => sum + e.token_savings_pct, 0) / effectiveness.length
    : 0;
  const avgAccuracy = effectiveness.length > 0
    ? effectiveness.reduce((sum, e) => sum + e.accuracy_score, 0) / effectiveness.length
    : 0;
  const totalFeedback = effectiveness.reduce((sum, e) => sum + e.feedback_count, 0);
  const latestBenchmark = benchmarks[0];

  if (loading) {
    return (
      <div class="accuracy-dashboard">
        <div class="loading-state">Loading accuracy data...</div>
      </div>
    );
  }

  return (
    <div class="accuracy-dashboard">
      <header class="dashboard-header">
        <div class="header-content">
          <h1>🎯 Behavior Accuracy Dashboard</h1>
          <p>Monitor behavior effectiveness, collect feedback, and track retrieval performance</p>
        </div>
        <div class="header-actions">
          <button class="btn btn-secondary" onClick={fetchData}>Refresh</button>
          <button class="btn btn-primary" onClick={triggerBenchmark}>Run Benchmark</button>
        </div>
      </header>

      {error && (
        <div class="error-banner">
          <span>⚠️ {error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      <section class="stats-grid">
        <div class="stat-card">
          <span class="stat-card__label">Total Usage</span>
          <span class="stat-card__value">{totalUsage.toLocaleString()}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Avg Token Savings</span>
          <span class="stat-card__value">{formatPercent(avgTokenSavings)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Avg Accuracy</span>
          <span class="stat-card__value">{formatPercent(avgAccuracy)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Total Feedback</span>
          <span class="stat-card__value">{totalFeedback}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Behaviors Tracked</span>
          <span class="stat-card__value">{effectiveness.length}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Scoring Mode</span>
          <span class="stat-card__value stat-mode">{config.mode}</span>
        </div>
        {latestBenchmark && (
          <>
            <div class="stat-card">
              <span class="stat-card__label">P95 Latency</span>
              <span class="stat-card__value">{formatMs(latestBenchmark.p95_latency_ms)}</span>
            </div>
            <div class="stat-card">
              <span class="stat-card__label">MRR Score</span>
              <span class="stat-card__value">{latestBenchmark.mrr.toFixed(3)}</span>
            </div>
          </>
        )}
      </section>

      <section class="config-section">
        <h2>⚙️ Scoring Configuration</h2>
        <div class="config-row">
          <div class="config-field">
            <label>Mode</label>
            <select
              value={config.mode}
              onChange={(e) => updateConfig({ ...config, mode: (e.target as HTMLSelectElement).value as ScoringConfig['mode'] })}
            >
              <option value="manual">Manual Only</option>
              <option value="llm">LLM-as-Judge</option>
              <option value="hybrid">Hybrid</option>
            </select>
          </div>
          {config.mode !== 'manual' && (
            <div class="config-field">
              <label>LLM Model</label>
              <input
                type="text"
                value={config.llm_model || 'gpt-4'}
                onChange={(e) => updateConfig({ ...config, llm_model: (e.target as HTMLInputElement).value })}
                placeholder="gpt-4"
              />
            </div>
          )}
          {config.mode === 'hybrid' && (
            <>
              <div class="config-field">
                <label>Auto-score Threshold</label>
                <input
                  type="number"
                  value={config.auto_score_threshold || 80}
                  min="0"
                  max="100"
                  onChange={(e) => updateConfig({ ...config, auto_score_threshold: parseInt((e.target as HTMLInputElement).value) })}
                />
              </div>
              <div class="config-field">
                <label>Require Review Below</label>
                <input
                  type="number"
                  value={config.require_human_review_below || 50}
                  min="0"
                  max="100"
                  onChange={(e) => updateConfig({ ...config, require_human_review_below: parseInt((e.target as HTMLInputElement).value) })}
                />
              </div>
            </>
          )}
        </div>
      </section>

      <div class="layout-grid">
        <section class="panel">
          <div class="panel-header">
            <h2>📊 Behavior Effectiveness</h2>
          </div>
          <div class="panel-content">
            {effectiveness.length > 0 ? (
              <table class="effectiveness-table">
                <thead>
                  <tr>
                    <th>Behavior</th>
                    <th>Usage</th>
                    <th>Token Savings</th>
                    <th>Accuracy</th>
                    <th>Feedback</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {effectiveness.map((e) => (
                    <tr key={e.behavior_id} class={selectedBehavior === e.behavior_id ? 'selected' : ''}>
                      <td class="behavior-name">{e.behavior_name}</td>
                      <td>{e.usage_count.toLocaleString()}</td>
                      <td>{formatPercent(e.token_savings_pct)}</td>
                      <td>
                        <span class={`accuracy-badge ${e.accuracy_score >= 80 ? 'high' : e.accuracy_score >= 50 ? 'medium' : 'low'}`}>
                          {formatPercent(e.accuracy_score)}
                        </span>
                      </td>
                      <td>{e.feedback_count}</td>
                      <td>
                        <button
                          class="btn btn-small"
                          onClick={() => setSelectedBehavior(e.behavior_id)}
                        >
                          Feedback
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div class="empty-state">
                <p>No effectiveness data yet</p>
                <p>Use behaviors in your workflows to start collecting metrics</p>
              </div>
            )}
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2>📝 Submit Feedback</h2>
          </div>
          <div class="panel-content">
            {selectedBehavior ? (
              <form class="feedback-form" onSubmit={submitFeedback}>
                <div class="form-group">
                  <label>Selected Behavior</label>
                  <input
                    type="text"
                    value={effectiveness.find(e => e.behavior_id === selectedBehavior)?.behavior_name || selectedBehavior}
                    disabled
                  />
                </div>

                <div class="form-group">
                  <label>Was this behavior helpful?</label>
                  <div class="helpful-toggle">
                    <button
                      type="button"
                      class={`helpful-btn ${feedbackForm.was_helpful ? 'selected' : ''}`}
                      onClick={() => setFeedbackForm({ ...feedbackForm, was_helpful: true })}
                    >
                      👍 Yes
                    </button>
                    <button
                      type="button"
                      class={`helpful-btn ${!feedbackForm.was_helpful ? 'selected' : ''}`}
                      onClick={() => setFeedbackForm({ ...feedbackForm, was_helpful: false })}
                    >
                      👎 No
                    </button>
                  </div>
                </div>

                <div class="form-group">
                  <label>Accuracy Rating (1-5)</label>
                  <div class="rating-group">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button
                        key={n}
                        type="button"
                        class={`rating-btn ${feedbackForm.accuracy_rating === n ? 'selected' : ''}`}
                        onClick={() => setFeedbackForm({ ...feedbackForm, accuracy_rating: n as 1 | 2 | 3 | 4 | 5 })}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>

                <div class="form-group">
                  <label>Query Context (optional)</label>
                  <input
                    type="text"
                    value={feedbackForm.query}
                    placeholder="What were you trying to do?"
                    onInput={(e) => setFeedbackForm({ ...feedbackForm, query: (e.target as HTMLInputElement).value })}
                  />
                </div>

                <div class="form-group">
                  <label>Additional Comments (optional)</label>
                  <textarea
                    value={feedbackForm.comment}
                    placeholder="Any additional feedback..."
                    onInput={(e) => setFeedbackForm({ ...feedbackForm, comment: (e.target as HTMLTextAreaElement).value })}
                  />
                </div>

                <div class="form-actions">
                  <button type="button" class="btn btn-secondary" onClick={() => setSelectedBehavior(null)}>
                    Cancel
                  </button>
                  <button type="submit" class="btn btn-primary">
                    Submit Feedback
                  </button>
                </div>
              </form>
            ) : (
              <div class="empty-state">
                <p>Select a behavior to submit feedback</p>
                <p>Click the "Feedback" button on any behavior in the table</p>
              </div>
            )}
          </div>
        </section>
      </div>

      {benchmarks.length > 0 && (
        <section class="panel benchmark-panel">
          <div class="panel-header">
            <h2>📈 Benchmark History</h2>
          </div>
          <div class="panel-content">
            <table class="benchmark-table">
              <thead>
                <tr>
                  <th>Run Date</th>
                  <th>Queries</th>
                  <th>Avg Latency</th>
                  <th>P95</th>
                  <th>P99</th>
                  <th>MRR</th>
                  <th>NDCG</th>
                  <th>Corpus Size</th>
                </tr>
              </thead>
              <tbody>
                {benchmarks.map((b) => (
                  <tr key={b.benchmark_id}>
                    <td>{new Date(b.run_at).toLocaleString()}</td>
                    <td>{b.total_queries}</td>
                    <td>{formatMs(b.avg_retrieval_latency_ms)}</td>
                    <td>{formatMs(b.p95_latency_ms)}</td>
                    <td>{formatMs(b.p99_latency_ms)}</td>
                    <td>{b.mrr.toFixed(3)}</td>
                    <td>{b.ndcg.toFixed(3)}</td>
                    <td>{b.corpus_size}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section class="panel">
        <div class="panel-header">
          <h2>🕐 Recent Feedback</h2>
        </div>
        <div class="panel-content">
          {recentFeedback.length > 0 ? (
            <ul class="feedback-list">
              {recentFeedback.map((f) => (
                <li key={`${f.behavior_id}-${f.submitted_at}`} class="feedback-item">
                  <div class="feedback-header">
                    <span class="feedback-behavior">{f.behavior_id}</span>
                    <span class={`feedback-helpful ${f.was_helpful ? 'yes' : 'no'}`}>
                      {f.was_helpful ? '👍' : '👎'}
                    </span>
                    <span class="feedback-rating">{'⭐'.repeat(f.accuracy_rating)}</span>
                  </div>
                  {f.query && <p class="feedback-query">Query: {f.query}</p>}
                  {f.comment && <p class="feedback-comment">{f.comment}</p>}
                  <span class="feedback-meta">
                    {f.actor_id} • {new Date(f.submitted_at).toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div class="empty-state">
              <p>No feedback submitted yet</p>
            </div>
          )}
        </div>
      </section>
    </div>
  );
};
