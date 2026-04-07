import React, { useMemo, useState } from 'react';
import type { ActorViewModel } from '../../types/actor';
import { ActorSceneSprite } from './ActorSceneSprite';

interface ActorPresenceSceneProps {
  actors: ActorViewModel[];
  title?: string;
  defaultExpanded?: boolean;
  onActorClick?: (actor: ActorViewModel) => void;
}

export function ActorPresenceScene({
  actors,
  title = 'Activity scene',
  defaultExpanded = false,
  onActorClick,
}: ActorPresenceSceneProps): React.JSX.Element | null {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const zones = useMemo(() => {
    return {
      desks: actors.filter((actor) => actor.presenceState === 'working' || actor.presenceState === 'at_capacity'),
      lounge: actors.filter((actor) => actor.presenceState === 'available' || actor.presenceState === 'finished_recently'),
      pods: actors.filter((actor) => actor.presenceState === 'paused' || actor.presenceState === 'offline'),
    };
  }, [actors]);

  if (actors.length === 0) return null;

  return (
    <section className="actor-scene animate-fade-in-up" aria-label={title}>
      <div className="actor-scene__toolbar">
        <div>
          <strong>{title}</strong>
          <div className="actor-presence-badge__status">Opt-in pixel scene for current presence</div>
        </div>
        <button
          type="button"
          className="actor-scene__toggle pressable"
          onClick={() => setExpanded((value) => !value)}
          data-haptic="light"
        >
          {expanded ? 'Hide scene' : 'Show scene'}
        </button>
      </div>

      {expanded ? (
        <div className="actor-scene__zones">
          <SceneZone title="Focus desks" actors={zones.desks} onActorClick={onActorClick} />
          <SceneZone title="Idle floor" actors={zones.lounge} onActorClick={onActorClick} />
          <SceneZone title="Sleep pods" actors={zones.pods} onActorClick={onActorClick} />
        </div>
      ) : null}
    </section>
  );
}

function SceneZone({
  title,
  actors,
  onActorClick,
}: {
  title: string;
  actors: ActorViewModel[];
  onActorClick?: (actor: ActorViewModel) => void;
}): React.JSX.Element {
  return (
    <div className="actor-scene__zone">
      <div className="actor-scene__zone-title">{title}</div>
      <div className="actor-scene__sprites">
        {actors.length > 0 ? actors.map((actor) => (
          <ActorSceneSprite key={actor.id} actor={actor} onClick={onActorClick ? () => onActorClick(actor) : undefined} />
        )) : <div className="actor-presence-badge__status">No one here right now</div>}
      </div>
    </div>
  );
}
