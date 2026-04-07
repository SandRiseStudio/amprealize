/**
 * ProjectAgentPresenceSummary
 *
 * Compact card for the project overview that shows assigned agent readiness
 * at a glance: inline roster of up to 5 capsules, summary chips, and actions.
 *
 * Following behavior_prefer_mcp_tools (Student): agent presence on project surface.
 */

import { useNavigate, useParams } from 'react-router-dom';
import type { AgentPresence, PresenceSummary } from '../../hooks/useAgentPresence';
import { PRESENCE_COLORS, PRESENCE_LABELS } from '../../hooks/useAgentPresence';
import { ActorAvatar } from '../actors/ActorAvatar';
import './ProjectAgentPresenceSummary.css';

/* ── Constants ─────────────────────────────────────────────────── */

const MAX_INLINE = 5;

const PRESENCE_DISPLAY_ORDER: AgentPresence['presence'][] = [
  'working',
  'available',
  'finished_recently',
  'at_capacity',
  'paused',
  'offline',
];

/* ── Props ─────────────────────────────────────────────────────── */

interface Props {
  presences: AgentPresence[];
  summary: PresenceSummary;
}

/* ── Helpers ───────────────────────────────────────────────────── */

function rankPresences(presences: AgentPresence[]): AgentPresence[] {
  const order: Record<AgentPresence['presence'], number> = {
    working: 0,
    available: 1,
    finished_recently: 2,
    at_capacity: 3,
    paused: 4,
    offline: 5,
  };
  return [...presences].sort(
    (a, b) => (order[a.presence] ?? 99) - (order[b.presence] ?? 99)
  );
}

/* ── Component ─────────────────────────────────────────────────── */

export function ProjectAgentPresenceSummary({ presences, summary }: Props): React.JSX.Element | null {
  const navigate = useNavigate();
  const { projectId } = useParams();

  /* ── Empty state ─────────────────────────────────────────────── */
  if (summary.total === 0) {
    return (
      <div className="project-agents-card project-agents-card--empty animate-fade-in-up">
        <div className="project-agents-card-header">
          <h3 className="project-agents-card-title">Assigned agents</h3>
        </div>
        <p className="project-agents-card-empty">No agents assigned yet</p>
        <button
          type="button"
          className="project-agents-card-action pressable"
          onClick={() => navigate(`/projects/${projectId}/settings`)}
          data-haptic="light"
        >
          Assign agents
        </button>
      </div>
    );
  }

  const ranked = rankPresences(presences);
  const visible = ranked.slice(0, MAX_INLINE);
  const overflow = ranked.length - MAX_INLINE;

  /* ── Summary chips ───────────────────────────────────────────── */
  const chips: { label: string; count: number; presence: AgentPresence['presence'] }[] = [];
  for (const state of PRESENCE_DISPLAY_ORDER) {
    const count = presences.filter((p) => p.presence === state).length;
    if (count > 0) {
      chips.push({ label: PRESENCE_LABELS[state], count, presence: state });
    }
  }

  return (
    <div className="project-agents-card animate-fade-in-up">
      <div className="project-agents-card-header">
        <div>
          <h3 className="project-agents-card-title">Assigned agents</h3>
          <p className="project-agents-card-supporting">Who can work in this project right now</p>
        </div>
      </div>

      {/* Inline roster */}
      <div className="project-agents-roster" aria-label="Agent roster">
        {visible.map((agent) => (
          <div key={agent.agentId} className="project-agents-capsule">
            <ActorAvatar
              actor={agent.actor}
              size="sm"
              surfaceType="summary"
              className="project-agents-avatar"
              decorative
            />
            <span
              className="project-agents-dot"
              style={{ backgroundColor: PRESENCE_COLORS[agent.presence] }}
              aria-label={PRESENCE_LABELS[agent.presence]}
            />
            <span className="project-agents-label">
              <span className="project-agents-name">{agent.name}</span>
              <span className="project-agents-status">{agent.statusLine}</span>
            </span>
          </div>
        ))}
        {overflow > 0 && (
          <span className="project-agents-overflow" aria-label={`${overflow} more agents`}>
            +{overflow}
          </span>
        )}
      </div>

      {/* Summary chips */}
      <div className="project-agents-chips" aria-label="Agent summary">
        {chips.map(({ label, count, presence }) => (
          <span key={presence} className="project-agents-chip">
            <span
              className="project-agents-chip-dot"
              style={{ backgroundColor: PRESENCE_COLORS[presence] }}
              aria-hidden="true"
            />
            {count} {label.toLowerCase()}
          </span>
        ))}
      </div>

      {/* Actions */}
      <div className="project-agents-card-actions">
        <button
          type="button"
          className="project-agents-card-action pressable"
          onClick={() => navigate(`/projects/${projectId}/settings`)}
          data-haptic="light"
        >
          Manage agents
        </button>
        <button
          type="button"
          className="project-agents-card-action project-agents-card-action--tertiary pressable"
          onClick={() => navigate('/agents')}
          data-haptic="light"
        >
          View registry
        </button>
      </div>
    </div>
  );
}
