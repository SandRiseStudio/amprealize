import React from 'react';
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion';
import type { ActorViewModel } from '../../types/actor';
import { presenceToActivity, type ActorActivity, type ActorSurfaceType } from '../../utils/presenceActivity';
import './ActorAvatar.css';

type ActorAvatarSize = 'sm' | 'md' | 'lg' | 'xl';

export interface ActorAvatarProps {
  actor: ActorViewModel;
  size?: ActorAvatarSize;
  className?: string;
  style?: React.CSSProperties;
  decorative?: boolean;
  showPresenceDot?: boolean;
  surfaceType?: ActorSurfaceType;
  activity?: ActorActivity;
}

function joinClassNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ');
}

export function ActorAvatar({
  actor,
  size = 'md',
  className,
  style,
  decorative = false,
  showPresenceDot,
  surfaceType = 'inline',
  activity,
}: ActorAvatarProps): React.JSX.Element {
  const prefersReducedMotion = usePrefersReducedMotion();
  const resolvedActivity = activity ?? presenceToActivity(actor.presenceState, surfaceType, prefersReducedMotion);
  const shouldShowPresenceDot = showPresenceDot ?? actor.kind !== 'human';
  const {
    palette,
    accessory,
    persona,
    hairStyle,
    eyeShape,
    mouthShape,
    shellShape,
  } = actor.avatarVariant;

  return (
    <span
      className={joinClassNames(
        'actor-avatar',
        `actor-avatar--${size}`,
        `actor-avatar--kind-${actor.kind}`,
        `actor-avatar--persona-${persona}`,
        `actor-avatar--hair-${hairStyle}`,
        `actor-avatar--${resolvedActivity}`,
        `actor-avatar--eye-${eyeShape}`,
        `actor-avatar--mouth-${mouthShape}`,
        `actor-avatar--shape-${shellShape}`,
        className,
      )}
      style={{
        ['--actor-surface' as string]: palette.surface,
        ['--actor-shell' as string]: palette.shell,
        ['--actor-shell-muted' as string]: palette.shellMuted,
        ['--actor-face' as string]: palette.face,
        ['--actor-hair' as string]: palette.hair,
        ['--actor-accent' as string]: palette.accent,
        ['--actor-accent-muted' as string]: palette.accentMuted,
        ['--actor-line' as string]: palette.line,
        ['--actor-status' as string]: actor.statusAccent,
        ...style,
      }}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : `${actor.displayName} — ${actor.presenceLabel}`}
      title={decorative ? undefined : `${actor.displayName} · ${actor.presenceLabel}`}
    >
      <span className="actor-avatar__layer actor-avatar__bg" aria-hidden="true" />
      <span className="actor-avatar__body" aria-hidden="true" />
      <span className="actor-avatar__head" aria-hidden="true">
        <span className="actor-avatar__ears" />
        <span className="actor-avatar__hair" />
        <span className="actor-avatar__snout" />
        <span className="actor-avatar__eye actor-avatar__eye--left" />
        <span className="actor-avatar__eye actor-avatar__eye--right" />
        <span className="actor-avatar__mouth" />
      </span>
      {accessory !== 'none' && (
        <span className={`actor-avatar__accessory actor-avatar__accessory--${accessory}`} aria-hidden="true" />
      )}
      <span className="actor-avatar__kind-mark" aria-hidden="true" />
      {actor.avatarUrl ? (
        <img
          className="actor-avatar__image"
          src={actor.avatarUrl}
          alt=""
          aria-hidden="true"
        />
      ) : null}
      {shouldShowPresenceDot ? <span className="actor-avatar__dot" aria-hidden="true" /> : null}
    </span>
  );
}
