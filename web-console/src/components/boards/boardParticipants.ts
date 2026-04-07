import type { ActorPresenceState, ActorViewModel } from '../../types/actor';

export interface BoardParticipant {
  id: string;
  kind: 'human' | 'agent';
  actor: ActorViewModel;
  subtitle?: string;
  roleLabel?: string;
  statusLine?: string;
  isCurrentUser?: boolean;
}

export interface BoardParticipantSummary {
  total: number;
  humans: number;
  agents: number;
}

export function summarizeBoardParticipants(participants: BoardParticipant[]): BoardParticipantSummary {
  return {
    total: participants.length,
    humans: participants.filter((participant) => participant.kind === 'human').length,
    agents: participants.filter((participant) => participant.kind === 'agent').length,
  };
}

const AGENT_PRESENCE_ORDER: Record<ActorPresenceState, number> = {
  working: 0,
  available: 1,
  finished_recently: 2,
  at_capacity: 3,
  paused: 4,
  offline: 5,
};

export function rankBoardParticipants(participants: BoardParticipant[]): BoardParticipant[] {
  return [...participants].sort((a, b) => {
    if (a.kind !== b.kind) {
      if (a.kind === 'human') return -1;
      return 1;
    }

    if (a.kind === 'human' && b.kind === 'human') {
      if (a.isCurrentUser && !b.isCurrentUser) return -1;
      if (!a.isCurrentUser && b.isCurrentUser) return 1;
      return a.actor.displayName.localeCompare(b.actor.displayName);
    }

    const presenceDiff = AGENT_PRESENCE_ORDER[a.actor.presenceState] - AGENT_PRESENCE_ORDER[b.actor.presenceState];
    if (presenceDiff !== 0) return presenceDiff;
    return a.actor.displayName.localeCompare(b.actor.displayName);
  });
}
