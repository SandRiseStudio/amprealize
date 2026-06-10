/**
 * Project-scoped observability trace explorer (warehouse summary views + span tree).
 */

import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useShellTitle } from '../workspace/useShell';
import {
  useConversationTraceSummaries,
  useRunTraceSummaries,
  useSpanTree,
} from '../../api/observabilityTraces';
import { TraceExplorerPanelSkeleton } from '../loading';
import './TraceExplorerPage.css';

export function TraceExplorerPage(): React.JSX.Element {
  const { projectId, traceId } = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState<'runs' | 'conversations'>('runs');

  useShellTitle(traceId ? `Trace ${traceId.slice(0, 8)}…` : 'Observability traces');

  const runsQuery = useRunTraceSummaries(projectId, tab === 'runs' && !traceId);
  const convQuery = useConversationTraceSummaries(projectId, tab === 'conversations' && !traceId);
  const spanQuery = useSpanTree(projectId, traceId, Boolean(traceId));

  const summary = traceId && spanQuery.data ? spanQuery.data : null;

  return (
    <div className="trace-explorer">
      <nav className="trace-explorer-breadcrumb" aria-label="Trace navigation">
        <Link to={`/projects/${projectId}`}>Project</Link>
        <span aria-hidden> / </span>
        <Link to={`/projects/${projectId}/traces`}>Traces</Link>
        {traceId ? (
          <>
            <span aria-hidden> / </span>
            <span className="trace-explorer-crumb-current">{traceId}</span>
          </>
        ) : null}
      </nav>

      <header className="trace-explorer-header">
        <h1>{traceId ? 'Span tree' : 'Observability traces'}</h1>
        <p className="trace-explorer-lede">
          Summaries read from Timescale warehouse views (<code>observability_run_summary</code>,{' '}
          <code>observability_conversation_summary</code>). Requires telemetry Postgres (
          <code>AMPREALIZE_TELEMETRY_PG_DSN</code>) with observability migrations applied.
        </p>
      </header>

      {traceId ? (
        <section className="trace-explorer-panel" aria-live="polite">
          {spanQuery.isLoading && (
            <TraceExplorerPanelSkeleton label="Loading span tree" />
          )}
          {spanQuery.isError && (
            <p className="trace-explorer-error">Could not load spans. Check API and telemetry database.</p>
          )}
          {summary && (
            <>
              <p className="trace-explorer-meta">
                Access tier <strong>{summary.access_tier}</strong> — {summary.count} span row
                {summary.count === 1 ? '' : 's'}
                {summary.truncated ? ' (truncated)' : ''}
              </p>
              <table className="trace-explorer-table">
                <thead>
                  <tr>
                    <th>Depth</th>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Span ID</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.records.map((row) => (
                    <tr key={`${row.span_id}-${row.record_timestamp}`}>
                      <td>{row.depth}</td>
                      <td className="trace-explorer-mono">{row.name}</td>
                      <td>{row.status ?? '—'}</td>
                      <td className="trace-explorer-mono">{row.span_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button
                type="button"
                className="trace-explorer-back"
                onClick={() => navigate(`/projects/${projectId}/traces`)}
              >
                Back to summaries
              </button>
            </>
          )}
        </section>
      ) : (
        <>
          <div className="trace-explorer-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'runs'}
              className={tab === 'runs' ? 'is-active' : ''}
              onClick={() => setTab('runs')}
            >
              Runs
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'conversations'}
              className={tab === 'conversations' ? 'is-active' : ''}
              onClick={() => setTab('conversations')}
            >
              Conversations
            </button>
          </div>

          {tab === 'runs' && (
            <section className="trace-explorer-panel">
              {runsQuery.isLoading && (
                <TraceExplorerPanelSkeleton label="Loading run summaries" />
              )}
              {runsQuery.isError && (
                <p className="trace-explorer-error">Could not load run summaries.</p>
              )}
              {runsQuery.data && (
                <table className="trace-explorer-table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Last activity</th>
                      <th>Records</th>
                      <th>Primary trace</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {runsQuery.data.records.map((row) => (
                      <tr key={row.run_id}>
                        <td className="trace-explorer-mono">{row.run_id}</td>
                        <td>{row.last_event_at}</td>
                        <td>{row.record_count}</td>
                        <td className="trace-explorer-mono">
                          {row.primary_trace_id ?? '—'}
                        </td>
                        <td>
                          {row.primary_trace_id ? (
                            <Link
                              to={`/projects/${projectId}/traces/${encodeURIComponent(row.primary_trace_id)}`}
                            >
                              Open tree
                            </Link>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}

          {tab === 'conversations' && (
            <section className="trace-explorer-panel">
              {convQuery.isLoading && (
                <TraceExplorerPanelSkeleton label="Loading conversation summaries" />
              )}
              {convQuery.isError && (
                <p className="trace-explorer-error">Could not load conversation summaries.</p>
              )}
              {convQuery.data && (
                <table className="trace-explorer-table">
                  <thead>
                    <tr>
                      <th>Conversation</th>
                      <th>Traces</th>
                      <th>Records</th>
                      <th>Last activity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {convQuery.data.records.map((row) => (
                      <tr key={row.conversation_id}>
                        <td className="trace-explorer-mono">{row.conversation_id}</td>
                        <td>{row.trace_count}</td>
                        <td>{row.record_count}</td>
                        <td>{row.last_event_at}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
