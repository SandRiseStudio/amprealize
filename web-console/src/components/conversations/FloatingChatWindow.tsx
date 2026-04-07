/**
 * FloatingChatWindow — board‑scoped floating DM chat window.
 *
 * Renders inside the board container (absolute positioned) with:
 * - Draggable header (pointer-capture based)
 * - Minimize → pill, restore, close
 * - MessageList + MessageComposer body
 * - Phase state machine for enter/open/close animations
 * - State preservation (scroll position, draft) across minimize/restore
 *
 * Following behavior_integrate_vscode_extension (Student) — component architecture
 * Following behavior_validate_accessibility (Student) — keyboard + reduced-motion
 */

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { ActorAvatar } from '../actors/ActorAvatar';
import { MessageList } from './MessageList';
import { MessageComposer } from './MessageComposer';
import { useConversationSocket } from '../../api/conversations';
import type { BoardParticipant } from '../boards/boardParticipants';
import type { Conversation } from '../../lib/collab-client';

// ── Types ────────────────────────────────────────────────────────────────────

type Phase = 'entering' | 'open' | 'closing' | 'closed';

export interface FloatingChatWindowProps {
  conversation: Conversation;
  targetParticipant: BoardParticipant;
  currentUserId?: string;
  minimized: boolean;
  onMinimize: () => void;
  onRestore: () => void;
  onClose: () => void;
}

interface DragState {
  active: boolean;
  startX: number;
  startY: number;
  offsetX: number;
  offsetY: number;
}

// ── Drag hook ────────────────────────────────────────────────────────────────

function useFloatingDrag() {
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<DragState>({
    active: false,
    startX: 0,
    startY: 0,
    offsetX: 0,
    offsetY: 0,
  });
  const panelRef = useRef<HTMLDivElement>(null);

  const handlePointerDown = useCallback((e: ReactPointerEvent<HTMLElement>) => {
    // Only primary button
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = {
      active: true,
      startX: e.clientX,
      startY: e.clientY,
      offsetX: position.x,
      offsetY: position.y,
    };
    setIsDragging(true);
  }, [position]);

  const handlePointerMove = useCallback((e: ReactPointerEvent<HTMLElement>) => {
    if (!dragRef.current.active) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    let nextX = dragRef.current.offsetX + dx;
    let nextY = dragRef.current.offsetY + dy;

    // Clamp to parent bounds
    const panel = panelRef.current;
    const parent = panel?.parentElement;
    if (panel && parent) {
      const pRect = parent.getBoundingClientRect();
      const elRect = panel.getBoundingClientRect();
      const maxX = pRect.width - elRect.width;
      const maxY = pRect.height - elRect.height;
      nextX = Math.max(-maxX, Math.min(0, nextX));
      nextY = Math.max(-maxY, Math.min(0, nextY));
    }

    setPosition({ x: nextX, y: nextY });
  }, []);

  const handlePointerUp = useCallback((e: ReactPointerEvent<HTMLElement>) => {
    if (!dragRef.current.active) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    dragRef.current.active = false;
    setIsDragging(false);
  }, []);

  // Keyboard drag: Shift+Arrow keys
  const handleKeyDown = useCallback((e: ReactKeyboardEvent<HTMLElement>) => {
    if (!e.shiftKey) return;
    const step = 20;
    let dx = 0;
    let dy = 0;
    switch (e.key) {
      case 'ArrowLeft':  dx = step; break;
      case 'ArrowRight': dx = -step; break;
      case 'ArrowUp':    dy = step; break;
      case 'ArrowDown':  dy = -step; break;
      default: return;
    }
    e.preventDefault();
    setPosition((prev) => {
      let nextX = prev.x + dx;
      let nextY = prev.y + dy;
      const panel = panelRef.current;
      const parent = panel?.parentElement;
      if (panel && parent) {
        const pRect = parent.getBoundingClientRect();
        const elRect = panel.getBoundingClientRect();
        const maxX = pRect.width - elRect.width;
        const maxY = pRect.height - elRect.height;
        nextX = Math.max(-maxX, Math.min(0, nextX));
        nextY = Math.max(-maxY, Math.min(0, nextY));
      }
      return { x: nextX, y: nextY };
    });
  }, []);

  return {
    position,
    panelRef,
    isDragging,
    dragHandlers: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: handlePointerUp,
      onKeyDown: handleKeyDown,
    },
  };
}

// ── Component ────────────────────────────────────────────────────────────────

export const FloatingChatWindow = memo(function FloatingChatWindow({
  conversation,
  targetParticipant,
  currentUserId,
  minimized,
  onMinimize,
  onRestore,
  onClose,
}: FloatingChatWindowProps) {
  const [phase, setPhase] = useState<Phase>('entering');
  const [unreadCount, setUnreadCount] = useState(0);
  const panelBodyRef = useRef<HTMLDivElement>(null);
  const scrollPosRef = useRef<number>(0);

  const { position, panelRef, isDragging, dragHandlers } = useFloatingDrag();

  // WebSocket for live messages
  const { connectionState } = useConversationSocket(
    conversation.id,
    currentUserId,
  );

  // ── Phase state machine ────────────────────────────────────────────────

  // Enter animation
  useLayoutEffect(() => {
    if (phase === 'entering') {
      const raf = requestAnimationFrame(() => setPhase('open'));
      return () => cancelAnimationFrame(raf);
    }
  }, [phase]);

  // Close animation
  const handleClose = useCallback(() => {
    // Save scroll position before closing
    if (panelBodyRef.current) {
      scrollPosRef.current = panelBodyRef.current.scrollTop;
    }
    setPhase('closing');
  }, []);

  const handleTransitionEnd = useCallback(() => {
    if (phase === 'closing') {
      setPhase('closed');
      onClose();
    }
  }, [phase, onClose]);

  // ── Minimize / Restore ─────────────────────────────────────────────────

  const handleMinimize = useCallback(() => {
    // Save scroll position before minimizing
    if (panelBodyRef.current) {
      scrollPosRef.current = panelBodyRef.current.scrollTop;
    }
    onMinimize();
  }, [onMinimize]);

  const handleRestore = useCallback(() => {
    setUnreadCount(0);
    onRestore();
  }, [onRestore]);

  // Restore scroll position after restore
  useEffect(() => {
    if (!minimized && panelBodyRef.current && scrollPosRef.current > 0) {
      panelBodyRef.current.scrollTop = scrollPosRef.current;
    }
  }, [minimized]);

  // ── Focus management ───────────────────────────────────────────────────

  useEffect(() => {
    if (phase === 'open' && !minimized) {
      // Focus the panel so keyboard shortcuts work
      panelRef.current?.focus();
    }
  }, [phase, minimized, panelRef]);

  // ── Keyboard shortcuts ─────────────────────────────────────────────────

  const handlePanelKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        handleMinimize();
      }
      // Delegate shift+arrow to drag handler
      if (e.shiftKey && e.key.startsWith('Arrow')) {
        dragHandlers.onKeyDown(e);
      }
    },
    [handleMinimize, dragHandlers],
  );

  // ── Minimized pill ─────────────────────────────────────────────────────

  if (minimized) {
    return (
      <button
        type="button"
        className="conversation-pill"
        onClick={handleRestore}
        aria-label={`Open chat with ${targetParticipant.actor.displayName}${unreadCount > 0 ? ` — ${unreadCount} new messages` : ''}`}
        data-haptic="light"
      >
        <ActorAvatar
          actor={targetParticipant.actor}
          size="sm"
          decorative
          showPresenceDot={targetParticipant.kind === 'agent'}
          surfaceType="badge"
        />
        <span className="conversation-pill-name">
          {targetParticipant.actor.displayName}
        </span>
        {unreadCount > 0 && (
          <span className="conversation-pill-badge" aria-hidden="true">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>
    );
  }

  // ── Floating panel ─────────────────────────────────────────────────────

  const phaseClass =
    phase === 'entering'
      ? 'conversation-floating--entering'
      : phase === 'open'
        ? 'conversation-floating--open'
        : phase === 'closing'
          ? 'conversation-floating--closing'
          : '';

  const draggingClass = isDragging ? 'conversation-floating--dragging' : '';

  return (
    <div
      ref={panelRef}
      className={`conversation-floating ${phaseClass} ${draggingClass}`}
      style={{
        transform: `translate(${position.x}px, ${position.y}px)`,
      }}
      role="dialog"
      aria-label={`Chat with ${targetParticipant.actor.displayName}`}
      aria-modal="false"
      tabIndex={-1}
      onKeyDown={handlePanelKeyDown}
      onTransitionEnd={handleTransitionEnd}
    >
      {/* ── Header / Drag Handle ──────────────────────────────────────── */}
      <div
        className="conversation-floating-header"
        {...dragHandlers}
        tabIndex={0}
        role="toolbar"
        aria-label="Chat window header — drag to reposition"
      >
        <div className="conversation-floating-header-info">
          <div
            className={`conversation-floating-avatar conversation-floating-avatar--${targetParticipant.kind}`}
          >
            <ActorAvatar
              actor={targetParticipant.actor}
              size="sm"
              decorative
              showPresenceDot={targetParticipant.kind === 'agent'}
              surfaceType="badge"
            />
          </div>
          <div className="conversation-floating-header-text">
            <span className="conversation-floating-name">
              {targetParticipant.actor.displayName}
            </span>
            <span className="conversation-floating-status">
              {targetParticipant.kind === 'agent'
                ? targetParticipant.actor.presenceLabel
                : connectionState === 'connected'
                  ? 'Online'
                  : 'Offline'}
            </span>
          </div>
        </div>

        <div className="conversation-floating-header-actions">
          <button
            type="button"
            className="conversation-floating-action pressable"
            onClick={handleMinimize}
            aria-label="Minimize chat"
            data-haptic="light"
          >
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M3 12h10" />
            </svg>
          </button>
          <button
            type="button"
            className="conversation-floating-action pressable"
            onClick={handleClose}
            aria-label="Close chat"
            data-haptic="light"
          >
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── Message body ──────────────────────────────────────────────── */}
      <div className="conversation-floating-body" ref={panelBodyRef}>
        <MessageList
          conversationId={conversation.id}
          currentUserId={currentUserId}
        />
      </div>

      {/* ── Composer ──────────────────────────────────────────────────── */}
      <div className="conversation-floating-footer">
        <MessageComposer
          conversationId={conversation.id}
          placeholder={`Message ${targetParticipant.actor.displayName}...`}
        />
      </div>
    </div>
  );
});
