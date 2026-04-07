export type ActorKind = 'human' | 'agent' | 'service';

export type ActorPresenceState =
  | 'available'
  | 'working'
  | 'finished_recently'
  | 'paused'
  | 'offline'
  | 'at_capacity';

export interface AvatarPalette {
  surface: string;
  shell: string;
  shellMuted: string;
  face: string;
  hair: string;
  accent: string;
  accentMuted: string;
  line: string;
}

export interface ActorAvatarVariant {
  paletteId: string;
  palette: AvatarPalette;
  accessory: 'none' | 'visor' | 'headband' | 'badge' | 'antenna' | 'glasses' | 'cap' | 'earring';
  persona: 'human' | 'robot' | 'cat' | 'dog' | 'fox' | 'owl';
  hairStyle: 'none' | 'buzz' | 'part' | 'waves' | 'curl' | 'coily' | 'bun' | 'spikes';
  eyeShape: 'dot' | 'bar' | 'wide';
  mouthShape: 'flat' | 'smile' | 'focus';
  shellShape: 'round' | 'squircle';
  spriteSeed: number;
  sceneAccent: 'desk' | 'idle' | 'sleep';
}

export interface ActorViewModel {
  id: string;
  kind: ActorKind;
  displayName: string;
  subtitle?: string;
  avatarSeed: string;
  avatarVariant: ActorAvatarVariant;
  avatarUrl?: string;
  avatarStyleVersion: number;
  presenceState: ActorPresenceState;
  presenceLabel: string;
  statusAccent: string;
  isCurrentUser: boolean;
}

export const ACTOR_PRESENCE_LABELS: Record<ActorPresenceState, string> = {
  available: 'Available',
  working: 'Working',
  finished_recently: 'Finished recently',
  paused: 'Paused',
  offline: 'Offline',
  at_capacity: 'At capacity',
};

export const ACTOR_PRESENCE_ACCENTS: Record<ActorPresenceState, string> = {
  available: 'var(--color-success-vivid)',
  working: 'var(--color-accent)',
  finished_recently: 'var(--color-accent-tertiary)',
  paused: 'var(--color-warning)',
  offline: 'var(--color-text-disabled)',
  at_capacity: 'var(--color-warning)',
};

export function actorInitials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] ?? ''}${parts[1][0] ?? ''}`.toUpperCase() || '?';
}
