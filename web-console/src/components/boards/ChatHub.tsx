/**
 * ChatHub — collaboration dock: member launcher, avatars, overflow, collab connection.
 *
 * Member count opens the members sheet; avatar taps start or restore a DM in the unified
 * messages window (wired from BoardPage).
 */

import { MessagesSquare } from 'lucide-react';
import { memo, type Ref } from 'react';
import { ActorAvatar } from '../actors/ActorAvatar';
import { rankBoardParticipants, type BoardParticipant } from './boardParticipants';
import './ChatHub.css';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

export interface ChatHubProps {
  participants: BoardParticipant[];
  /** Opens members sheet (dock control). */
  onOpenMembersSheet?: () => void;
  /** Overflow / secondary entry to members sheet */
  onOpen?: () => void;
  onParticipantClick?: (participant: BoardParticipant) => void;
  /** Ref for the members launcher (focus return). */
  membersLauncherRef?: Ref<HTMLButtonElement>;
  /** Maximum avatars to show before overflow chip */
  maxVisible?: number;
  /** Connection state for real-time collab */
  connectionState?: ConnectionState;
  /** Dock visual state */
  active?: boolean;
  /** When set with onOpenMembersSheet, renders an accessible launcher before avatars. */
  memberCount?: number;
}

const DEFAULT_MAX_VISIBLE = 6;

export const ChatHub = memo(function ChatHub({
  participants,
  onOpenMembersSheet,
  onOpen,
  onParticipantClick,
  membersLauncherRef,
  maxVisible = DEFAULT_MAX_VISIBLE,
  connectionState,
  active = false,
  memberCount,
}: ChatHubProps) {
  if (participants.length === 0 && !connectionState) return null;

  const openSheet = onOpenMembersSheet ?? onOpen;
  const memberLabel =
    memberCount !== undefined
      ? `${memberCount} ${memberCount === 1 ? 'member' : 'members'}`
      : null;

  const ranked = rankBoardParticipants(participants);
  const visible = ranked.slice(0, maxVisible);
  const overflow = participants.length - visible.length;

  const connectionLabel =
    connectionState === 'connected'
      ? 'Live'
      : connectionState === 'reconnecting'
      ? 'Reconnecting'
      : connectionState === 'connecting'
      ? 'Connecting'
      : connectionState === 'disconnected'
      ? 'Offline'
      : null;

  return (
    <div
      className={`chathub${active ? ' chathub--active' : ''}`}
      role="region"
      aria-label="Project chat and team presence"
    >
      {memberLabel && onOpenMembersSheet && (
        <button
          ref={membersLauncherRef}
          type="button"
          className="chathub-members-launcher pressable"
          onClick={onOpenMembersSheet}
          aria-label={`Open project chat and members — ${memberLabel}`}
          data-haptic="light"
        >
          <MessagesSquare className="chathub-members-launcher-icon" size={15} strokeWidth={2} aria-hidden />
          <span className="chathub-members-launcher-copy">
            <span className="chathub-members-launcher-verb">Chat</span>
            <span className="chathub-members-launcher-sep" aria-hidden>
              {' · '}
            </span>
            <span className="chathub-members-launcher-meta">{memberLabel}</span>
          </span>
        </button>
      )}
      {connectionState && (
        <div
          className={`chathub-connection chathub-connection-${connectionState}`}
          aria-live="polite"
          aria-label={`Connection status: ${connectionLabel}`}
        >
          <span className="chathub-connection-dot" />
          <span className="chathub-connection-label">{connectionLabel}</span>
        </div>
      )}
      {participants.length > 0 && (
        <div className="chathub-avatars" role="list">
          {visible.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`chathub-avatar pressable${p.isCurrentUser ? ' chathub-avatar--self' : ''}`}
              onClick={() => (onParticipantClick ? onParticipantClick(p) : openSheet?.())}
              aria-label={
                onParticipantClick
                  ? `Open chat — ${p.actor.displayName}${p.isCurrentUser ? ' (you)' : ''}${p.kind === 'agent' ? ', agent' : ''}`
                  : `${p.actor.displayName}${p.isCurrentUser ? ' (you)' : ''} – ${p.kind === 'agent' ? 'Agent' : 'Person'}`
              }
              title={p.actor.displayName}
              data-haptic="light"
              role="listitem"
            >
              <span className="chathub-avatar-inner">
                <ActorAvatar
                  actor={p.actor}
                  size="sm"
                  decorative
                  showPresenceDot={p.kind === 'agent'}
                  surfaceType="badge"
                />
                {p.isCurrentUser ? (
                  <span className="chathub-avatar-you-mark" aria-hidden="true">
                    you
                  </span>
                ) : null}
              </span>
            </button>
          ))}
          {overflow > 0 && (
            <button
              type="button"
              className="chathub-overflow pressable"
              onClick={() => openSheet?.()}
              aria-label={`Open member list and chat — ${overflow} more`}
              title={`${overflow} more — members and chat`}
              data-haptic="light"
            >
              +{overflow}
            </button>
          )}
        </div>
      )}
    </div>
  );
});
