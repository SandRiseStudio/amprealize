import React from 'react';
import type { ActorViewModel } from '../../types/actor';
import { ActorAvatar } from './ActorAvatar';

export interface ActorSceneSpriteProps {
  actor: ActorViewModel;
  onClick?: () => void;
}

export function ActorSceneSprite({ actor, onClick }: ActorSceneSpriteProps): React.JSX.Element {
  const content = (
    <>
      <ActorAvatar actor={actor} size="lg" surfaceType="scene" />
      <span className="actor-scene-sprite__text">
        <span className="actor-scene-sprite__name">{actor.displayName}</span>
        <span className="actor-scene-sprite__status">{actor.presenceLabel}</span>
      </span>
    </>
  );

  if (onClick) {
    return (
      <button type="button" className="actor-scene-sprite actor-scene-sprite--button pressable" onClick={onClick}>
        {content}
      </button>
    );
  }

  return <div className="actor-scene-sprite">{content}</div>;
}
