/**
 * AgentPresenceBadge
 *
 * Compact, reusable badge/capsule for a single agent's presence state.
 * Shows avatar + presence dot + optional micro-label.
 * Used in board rail, project overview, dashboard cards, and assignment picker.
 *
 * GPU-only animations (transform, opacity). No shadows per design system.
 */

import React from 'react';
import type { AgentPresence } from '../../hooks/useAgentPresence';
import { ActorPresenceBadge as SharedActorPresenceBadge } from '../actors/ActorPresenceBadge';

export interface AgentPresenceBadgeProps {
  agent: AgentPresence;
  /** Show the micro-label next to the avatar (default true on wide screens) */
  showLabel?: boolean;
  /** Compact mode: smaller avatar, no label */
  compact?: boolean;
  onClick?: (agent: AgentPresence) => void;
}

export const AgentPresenceBadge: React.FC<AgentPresenceBadgeProps> = ({
  agent,
  showLabel = true,
  compact = false,
  onClick,
}) => {
  return (
    <SharedActorPresenceBadge
      actor={agent.actor}
      showLabel={showLabel}
      compact={compact}
      onClick={onClick ? () => onClick(agent) : undefined}
    />
  );
};
