import React from 'react';
import type { ActorViewModel } from '../../types/actor';
import { ActorAvatar } from './ActorAvatar';

export interface ActorIdentityRowProps {
  actor: ActorViewModel;
  subtitle?: string;
  size?: 'sm' | 'md' | 'lg';
  surfaceType?: 'drawer' | 'summary' | 'chip' | 'inline';
}

export function ActorIdentityRow({
  actor,
  subtitle,
  size = 'md',
  surfaceType = 'inline',
}: ActorIdentityRowProps): React.JSX.Element {
  return (
    <span className="actor-identity-row">
      <ActorAvatar actor={actor} size={size} surfaceType={surfaceType} />
      <span className="actor-identity-row__text">
        <span className="actor-identity-row__name">{actor.displayName}</span>
        <span className="actor-identity-row__subtitle">{subtitle ?? actor.subtitle ?? actor.presenceLabel}</span>
      </span>
    </span>
  );
}
