import type { Agent } from '../api/dashboard';
import type { OrgMember } from '../api/organizations';
import type { ActorIdentity } from '../types/auth';
import {
  ACTOR_PRESENCE_ACCENTS,
  ACTOR_PRESENCE_LABELS,
  type ActorKind,
  type ActorPresenceState,
  type ActorViewModel,
} from '../types/actor';
import { generateAvatarVariant } from './avatarGen';

export interface CollabParticipantLike {
  user_id: string;
  display_name?: string;
  color?: string;
  status?: 'active' | 'idle' | 'away';
}

interface ActorViewModelOverrides {
  id?: string;
  kind?: ActorKind;
  subtitle?: string;
  avatarSeed?: string;
  avatarUrl?: string;
  avatarStyleVersion?: number;
  presenceState?: ActorPresenceState;
  presenceLabel?: string;
  isCurrentUser?: boolean;
}

function shortenId(value: string | undefined | null): string {
  if (value == null || typeof value !== 'string') return 'unknown';
  return value.length <= 8 ? value : value.slice(0, 8);
}

function isAgent(value: unknown): value is Agent {
  return typeof value === 'object'
    && value !== null
    && 'agent_type' in value
    && 'status' in value
    && 'id' in value;
}

function isOrgMember(value: unknown): value is OrgMember {
  return typeof value === 'object'
    && value !== null
    && 'user_id' in value
    && 'role' in value
    && 'org_id' in value;
}

function isActorIdentity(value: unknown): value is ActorIdentity {
  return typeof value === 'object'
    && value !== null
    && 'surface' in value
    && 'type' in value
    && 'role' in value
    && 'id' in value;
}

function isCollabParticipant(value: unknown): value is CollabParticipantLike {
  return typeof value === 'object'
    && value !== null
    && 'user_id' in value
    && !('org_id' in value);
}

export function presenceStateFromAgentStatus(status?: string | null): ActorPresenceState {
  switch ((status ?? '').toLowerCase()) {
    case 'busy':
      return 'working';
    case 'paused':
      return 'paused';
    case 'active':
    case 'idle':
      return 'available';
    case 'disabled':
    case 'archived':
      return 'offline';
    default:
      return 'offline';
  }
}

function presenceStateFromParticipantStatus(status?: string | null): ActorPresenceState {
  switch ((status ?? '').toLowerCase()) {
    case 'active':
      return 'working';
    case 'idle':
      return 'available';
    default:
      return 'paused';
  }
}

function resolveDisplayName(raw: Agent | OrgMember | ActorIdentity | CollabParticipantLike): string {
  if (isAgent(raw)) return raw.name || `Agent ${shortenId(raw.id)}`;
  if (isActorIdentity(raw)) return raw.displayName || raw.email || `Actor ${shortenId(raw.id)}`;
  if (isOrgMember(raw)) return `Member ${shortenId(raw.user_id)}`;
  if (isCollabParticipant(raw)) {
    return raw.display_name || `Participant ${shortenId(raw.user_id)}`;
  }
  // Project-agent assignment API shape (agent_id, role) without agent_type — not an Agent in TS sense
  const loose = raw as Record<string, unknown>;
  if (typeof loose.agent_id === 'string') {
    const nm = typeof loose.name === 'string' ? loose.name : '';
    const agentNm = typeof loose.agent_name === 'string' ? loose.agent_name : '';
    return nm || agentNm || `Agent ${shortenId(loose.agent_id)}`;
  }
  if (typeof loose.user_id === 'string') {
    const dn = typeof loose.display_name === 'string' ? loose.display_name : '';
    return dn || `Participant ${shortenId(loose.user_id)}`;
  }
  if (typeof loose.id === 'string') {
    const nm = typeof loose.name === 'string' ? loose.name : '';
    return nm || `Actor ${shortenId(loose.id)}`;
  }
  return 'Unknown';
}

export function toActorViewModel(
  raw: Agent | OrgMember | ActorIdentity | CollabParticipantLike,
  overrides: ActorViewModelOverrides = {},
): ActorViewModel {
  const displayName = resolveDisplayName(raw);
  const kind: ActorKind = overrides.kind
    ?? (isAgent(raw) ? 'agent' : isActorIdentity(raw) ? raw.type : 'human');
  const id = overrides.id
    ?? (isAgent(raw)
      ? ((raw.config?.registry_agent_id as string | undefined) || raw.id)
      : isOrgMember(raw)
        ? raw.user_id
        : isActorIdentity(raw)
          ? raw.id
          : isCollabParticipant(raw)
            ? raw.user_id
            : (() => {
                const loose = raw as Record<string, unknown>;
                if (typeof loose.agent_id === 'string') return loose.agent_id;
                if (typeof loose.id === 'string') return loose.id;
                return 'unknown';
              })());
  const presenceState = overrides.presenceState
    ?? (isAgent(raw)
      ? presenceStateFromAgentStatus(raw.status)
      : isCollabParticipant(raw)
        ? presenceStateFromParticipantStatus(raw.status)
        : 'available');
  const presenceLabel = overrides.presenceLabel ?? ACTOR_PRESENCE_LABELS[presenceState];
  const subtitle = overrides.subtitle
    ?? (isAgent(raw)
      ? raw.agent_type || 'Agent'
      : isActorIdentity(raw)
        ? raw.role
        : isOrgMember(raw)
          ? raw.role.toLowerCase().replace(/_/g, ' ')
          : 'Collaborator');
  const avatarUrl = overrides.avatarUrl
    ?? (isActorIdentity(raw) ? raw.avatarUrl : undefined);
  const avatarStyleVersion = overrides.avatarStyleVersion ?? 1;
  const avatarSeed = overrides.avatarSeed ?? `${kind}:${id}:${displayName}`;

  return {
    id,
    kind,
    displayName,
    subtitle,
    avatarSeed,
    avatarVariant: generateAvatarVariant(avatarSeed, kind, avatarStyleVersion),
    avatarUrl,
    avatarStyleVersion,
    presenceState,
    presenceLabel,
    statusAccent: ACTOR_PRESENCE_ACCENTS[presenceState],
    isCurrentUser: overrides.isCurrentUser ?? false,
  };
}
