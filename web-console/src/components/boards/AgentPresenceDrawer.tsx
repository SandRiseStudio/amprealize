/**
 * AgentPresenceDrawer
 *
 * Right-side overlay drawer listing project participants.
 * Opens from the board participant rail "View all" button.
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md (Student):
 *   200-250ms transform + opacity for open/close.
 *   Focus trap, Escape to dismiss, focus return.
 */

import React, { useCallback, useEffect, useRef } from 'react';
import { ActorIdentityRow } from '../actors/ActorIdentityRow';
import type { BoardParticipant } from './boardParticipants';
import { rankBoardParticipants } from './boardParticipants';
import './AgentPresenceDrawer.css';

export interface AgentPresenceDrawerProps {
  participants: BoardParticipant[];
  open: boolean;
  onClose: () => void;
  onParticipantClick?: (participant: BoardParticipant) => void;
  /** Opens unified project / team chat (pinned above member list). */
  onProjectRoom?: () => void;
  onManage?: () => void;
}

function groupBy(participants: BoardParticipant[]): {
  humans: BoardParticipant[];
  agents: BoardParticipant[];
} {
  const ranked = rankBoardParticipants(participants);
  return {
    humans: ranked.filter((participant) => participant.kind === 'human'),
    agents: ranked.filter((participant) => participant.kind === 'agent'),
  };
}

export const AgentPresenceDrawer: React.FC<AgentPresenceDrawerProps> = ({
  participants,
  open,
  onClose,
  onParticipantClick,
  onProjectRoom,
  onManage,
}) => {
  const drawerRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Focus trap + escaping
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;

    // Focus first focusable element
    requestAnimationFrame(() => {
      const first = drawerRef.current?.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      first?.focus();
    });

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      // Trap focus within drawer
      if (e.key === 'Tab' && drawerRef.current) {
        const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [open, onClose]);

  const handleScrimClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  if (!open) return null;

  const { humans, agents } = groupBy(participants);

  return (
    <div
      className="agent-presence-drawer-scrim"
      onClick={handleScrimClick}
      role="presentation"
    >
      <aside
        ref={drawerRef}
        className="agent-presence-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="presence-drawer-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="presence-drawer-header">
          <h2 id="presence-drawer-title" className="presence-drawer-title">
            Project members
          </h2>
          <button
            type="button"
            className="presence-drawer-close pressable"
            onClick={onClose}
            aria-label="Close members sheet"
            data-haptic="light"
          >
            ✕
          </button>
        </div>

        <div className="presence-drawer-body">
          {onProjectRoom && (
            <div className="presence-drawer-project-room">
              <button
                type="button"
                className="presence-drawer-project-room-btn pressable"
                onClick={() => {
                  onProjectRoom();
                  onClose();
                }}
                data-haptic="light"
              >
                <span className="presence-drawer-project-room-icon" aria-hidden="true">#</span>
                <span className="presence-drawer-project-room-copy">
                  <span className="presence-drawer-project-room-title">Project room</span>
                  <span className="presence-drawer-project-room-sub">Team chat for this project</span>
                </span>
              </button>
            </div>
          )}
          <DrawerSection title="People" participants={humans} onParticipantClick={onParticipantClick} />
          <DrawerSection title="Agents" participants={agents} onParticipantClick={onParticipantClick} />
        </div>

        {onManage && (
          <div className="presence-drawer-footer">
            <button
              type="button"
              className="presence-drawer-manage pressable"
              onClick={onManage}
              data-haptic="light"
            >
              Manage agents
            </button>
          </div>
        )}
      </aside>
    </div>
  );
};

// ── Section within the drawer ────────────────────────────────────────────────

interface DrawerSectionProps {
  title: string;
  participants: BoardParticipant[];
  onParticipantClick?: (participant: BoardParticipant) => void;
}

const DrawerSection: React.FC<DrawerSectionProps> = ({ title, participants, onParticipantClick }) => {
  if (participants.length === 0) return null;

  return (
    <section className="presence-drawer-section">
      <h3 className="presence-drawer-section-title">{title}</h3>
      <ul className="presence-drawer-list" role="list">
        {participants.map((participant) => (
          <li key={participant.id} className="presence-drawer-row">
            <ActorIdentityRow actor={participant.actor} subtitle={participant.subtitle} size="sm" surfaceType="drawer" />
            <span className="presence-drawer-row-info">
              <span className="presence-drawer-row-name">
                {participant.actor.displayName}
                {participant.isCurrentUser ? <span className="presence-drawer-pill">You</span> : null}
              </span>
              <span className="presence-drawer-row-status">{participant.statusLine ?? participant.roleLabel ?? participant.actor.presenceLabel}</span>
            </span>
            <span className="presence-drawer-row-meta">
              <span className="presence-drawer-row-state-label">
                {participant.kind === 'agent' ? participant.actor.presenceLabel : (participant.roleLabel ?? 'Project member')}
              </span>
            </span>
            {onParticipantClick && (
              <button
                type="button"
                className="presence-drawer-row-action pressable"
                onClick={() => onParticipantClick(participant)}
                data-haptic="light"
              >
                View
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
};
