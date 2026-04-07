import type { ActorPresenceState } from '../types/actor';

export type ActorSurfaceType =
  | 'badge'
  | 'rail'
  | 'drawer'
  | 'summary'
  | 'dashboard'
  | 'chip'
  | 'inline'
  | 'scene';

export type ActorActivity = 'static' | 'idle' | 'typing' | 'sleeping' | 'paused';

export function presenceToActivity(
  presenceState: ActorPresenceState,
  surfaceType: ActorSurfaceType,
  reducedMotion = false,
): ActorActivity {
  if (reducedMotion) {
    if (presenceState === 'offline') return 'sleeping';
    if (presenceState === 'paused') return 'paused';
    if (presenceState === 'working') return surfaceType === 'scene' ? 'typing' : 'static';
    return 'static';
  }

  if (presenceState === 'offline') return 'sleeping';
  if (presenceState === 'paused') return 'paused';
  if (presenceState === 'working' || presenceState === 'at_capacity') {
    return surfaceType === 'chip' || surfaceType === 'inline' ? 'static' : 'typing';
  }
  if (presenceState === 'finished_recently') return surfaceType === 'scene' ? 'idle' : 'static';
  return 'idle';
}
