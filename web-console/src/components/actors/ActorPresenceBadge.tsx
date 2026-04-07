import React from 'react';
import type { ActorViewModel } from '../../types/actor';
import { ActorAvatar } from './ActorAvatar';

export interface ActorPresenceBadgeProps {
  actor: ActorViewModel;
  showLabel?: boolean;
  compact?: boolean;
  onClick?: () => void;
}

export function ActorPresenceBadge({
  actor,
  showLabel = true,
  compact = false,
  onClick,
}: ActorPresenceBadgeProps): React.JSX.Element {
  const className = `actor-presence-badge${compact ? ' actor-presence-badge--compact' : ''}${onClick ? ' actor-presence-badge--button pressable' : ''}`;
  const content = (
    <>
      <ActorAvatar actor={actor} size={compact ? 'sm' : 'md'} surfaceType="badge" />
      {showLabel && !compact ? (
        <span className="actor-presence-badge__text">
          <span className="actor-presence-badge__name">{actor.displayName}</span>
          <span className="actor-presence-badge__status">{actor.presenceLabel}</span>
        </span>
      ) : null}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className={className}
        onClick={onClick}
        aria-label={`${actor.displayName} – ${actor.presenceLabel}`}
        data-haptic="light"
      >
        {content}
      </button>
    );
  }

  return <span className={className}>{content}</span>;
}
