/**
 * Agent Presence Hook
 *
 * Derives canonical presence states from existing project agent data, execution
 * streams, and work-item assignments. Shared by board rail, project overview,
 * dashboard cards, and assignment picker.
 *
 * Following behavior_use_raze_for_logging (Student)
 * Following COLLAB_SAAS_REQUIREMENTS.md: same vocabulary across all surfaces.
 */

import { useMemo } from 'react';
import type { Agent, AgentStatus } from '../api/dashboard';
import {
  ACTOR_PRESENCE_ACCENTS,
  ACTOR_PRESENCE_LABELS,
  actorInitials,
  type ActorPresenceState,
  type ActorViewModel,
} from '../types/actor';
import { toActorViewModel } from '../utils/actorViewModel';

// ---------------------------------------------------------------------------
// Canonical presence vocabulary
// ---------------------------------------------------------------------------

export type PresenceState = ActorPresenceState;

export interface AgentPresence {
  agentId: string;
  name: string;
  agentType: string;
  avatar: string;
  actor: ActorViewModel;
  presence: PresenceState;
  /** Human-readable one-liner, e.g. "Working on 2 items" */
  statusLine: string;
  /** Utilization expressed as "active / max" if known */
  utilization?: string;
  /** Timestamp of last completed work (ISO string) */
  lastCompletedAt?: string;
  /** Current work-item title if working on exactly one */
  currentItemTitle?: string;
  /** Count of active items when > 1 */
  activeItemCount: number;
  /** Raw status from backend */
  rawStatus: AgentStatus;
}

export interface PresenceSummary {
  total: number;
  working: number;
  available: number;
  paused: number;
  offline: number;
  atCapacity: number;
  finishedRecently: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function derivePresence(agent: Agent): PresenceState {
  const status = agent.status;
  if (status === 'paused') return 'paused';
  if (status === 'disabled' || status === 'archived') return 'offline';

  // If last_active_at is recent (within 5 minutes), consider working or available
  if (status === 'busy') return 'working';
  if (status === 'active' || status === 'idle') return 'available';

  return 'offline';
}

function buildStatusLine(presence: PresenceState): string {
  switch (presence) {
    case 'available':
      return 'Available';
    case 'working':
      return 'Working';
    case 'finished_recently':
      return 'Finished recently';
    case 'paused':
      return 'Paused';
    case 'offline':
      return 'Offline';
    case 'at_capacity':
      return 'At capacity';
  }
}

// ---------------------------------------------------------------------------
// Hook: derive presence for a list of project agents
// ---------------------------------------------------------------------------

export function useAgentPresence(
  agents: Agent[],
  projectId?: string,
): { presences: AgentPresence[]; summary: PresenceSummary } {
  return useMemo(() => {
    const scoped = projectId
      ? agents.filter((a) => a.project_id === projectId)
      : agents;

    const presences: AgentPresence[] = scoped.map((agent) => {
      const actualId = (agent.config?.registry_agent_id as string) || agent.id;
      const presence = derivePresence(agent);
      const actor = toActorViewModel(agent, {
        id: actualId,
        subtitle: agent.agent_type || 'Agent',
        presenceState: presence,
      });
      return {
        agentId: actualId,
        name: actor.displayName,
        agentType: agent.agent_type || 'agent',
        avatar: actorInitials(actor.displayName),
        actor,
        presence,
        statusLine: buildStatusLine(presence),
        lastCompletedAt: undefined,
        currentItemTitle: undefined,
        activeItemCount: presence === 'working' ? 1 : 0,
        rawStatus: agent.status,
      };
    });

    const summary: PresenceSummary = {
      total: presences.length,
      working: presences.filter((p) => p.presence === 'working').length,
      available: presences.filter((p) => p.presence === 'available').length,
      paused: presences.filter((p) => p.presence === 'paused').length,
      offline: presences.filter((p) => p.presence === 'offline').length,
      atCapacity: presences.filter((p) => p.presence === 'at_capacity').length,
      finishedRecently: presences.filter((p) => p.presence === 'finished_recently').length,
    };

    return { presences, summary };
  }, [agents, projectId]);
}

// ---------------------------------------------------------------------------
// Presence display utilities
// ---------------------------------------------------------------------------

export const PRESENCE_LABELS: Record<PresenceState, string> = ACTOR_PRESENCE_LABELS;

export const PRESENCE_COLORS: Record<PresenceState, string> = ACTOR_PRESENCE_ACCENTS;

export function formatPresenceSummary(summary: PresenceSummary): string {
  const parts: string[] = [];
  parts.push(`${summary.total} assigned`);
  if (summary.working > 0) parts.push(`${summary.working} working`);
  if (summary.available > 0) parts.push(`${summary.available} available`);
  return parts.join(' · ');
}
