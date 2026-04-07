/**
 * UnifiedConversationWindow — single floating draggable shell for project room + DMs.
 *
 * Board-scoped: sidebar (ConversationSidebar) + thread. Drag header to reposition.
 */

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { ConversationSidebar } from './ConversationSidebar';
import { MessageList } from './MessageList';
import { MessageComposer } from './MessageComposer';
import { MessageSearch } from './MessageSearch';
import { BottomSheet } from './BottomSheet';
import { useConversation, useConversations, useConversationSocket } from '../../api/conversations';
import { ConnectionState, ConversationScope } from '../../lib/collab-client';
import './ConversationPanel.css';
import './UnifiedConversationWindow.css';


const MOBILE_BREAKPOINT = 768;

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < MOBILE_BREAKPOINT : false,
  );

  useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    }
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return isMobile;
}

type Phase = 'entering' | 'open' | 'closing';

export type UnifiedConversationInitialTarget =
  | { mode: 'conversation'; conversationId: string }
  | { mode: 'firstProjectRoom' };

export interface UnifiedConversationWindowProps {
  projectId: string;
  orgId?: string | null;
  currentUserId?: string;
  /** Applied when the window mounts or when this reference changes (see initialTargetKey). */
  initialTarget: UnifiedConversationInitialTarget;
  /** Bump to re-apply initialTarget (e.g. new DM from dock). */
  initialTargetKey: number;
  onClose: () => void;
}

interface DragState {
  active: boolean;
  startX: number;
  startY: number;
  offsetX: number;
  offsetY: number;
}

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
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest('button, a, input, textarea, select')) {
      return;
    }
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

  const handleKeyDown = useCallback((e: ReactKeyboardEvent<HTMLElement>) => {
    if (!e.shiftKey) return;
    const step = 20;
    let dx = 0;
    let dy = 0;
    switch (e.key) {
      case 'ArrowLeft':
        dx = step;
        break;
      case 'ArrowRight':
        dx = -step;
        break;
      case 'ArrowUp':
        dy = step;
        break;
      case 'ArrowDown':
        dy = -step;
        break;
      default:
        return;
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

function CloseIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg className="conversation-panel-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

function SearchToggleIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5L14 14" />
    </svg>
  );
}

export const UnifiedConversationWindow = memo(function UnifiedConversationWindow({
  projectId,
  orgId,
  currentUserId,
  initialTarget,
  initialTargetKey,
  onClose,
}: UnifiedConversationWindowProps) {
  const [phase, setPhase] = useState<Phase>('entering');
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const panelBodyRef = useRef<HTMLDivElement>(null);
  const scrollPosRef = useRef(0);
  const shellRef = useRef<HTMLDivElement>(null);
  const closeOnceRef = useRef(false);
  const isMobile = useIsMobile();

  const { position, panelRef, isDragging, dragHandlers } = useFloatingDrag();

  const { data: convList } = useConversations({ projectId, enabled: !!projectId });
  const { data: activeConv } = useConversation(activeConversationId ?? undefined);

  const { connectionState } = useConversationSocket(activeConversationId ?? undefined, currentUserId);

  const headerTitle = useMemo(() => {
    if (!activeConversationId) return 'Messages';
    if (activeConv?.title) return activeConv.title;
    if (activeConv?.scope === ConversationScope.ProjectRoom) return 'Project room';
    return 'Direct message';
  }, [activeConversationId, activeConv?.title, activeConv?.scope]);

  useEffect(() => {
    setSearchOpen(false);
  }, [activeConversationId]);

  const conversationIdFromTarget =
    initialTarget.mode === 'conversation' ? initialTarget.conversationId : null;

  // When opening / remount intent changes, set or clear selection for project-room entry
  useEffect(() => {
    if (initialTarget.mode === 'conversation' && conversationIdFromTarget) {
      setActiveConversationId(conversationIdFromTarget);
      return;
    }
    setActiveConversationId(null);
  }, [initialTargetKey, initialTarget.mode, conversationIdFromTarget]);

  // Pick first project room once list loads (only after first-room entry cleared selection)
  useEffect(() => {
    if (initialTarget.mode !== 'firstProjectRoom') return;
    const rooms =
      convList?.items.filter((c) => c.scope === ConversationScope.ProjectRoom) ?? [];
    if (rooms[0]) {
      setActiveConversationId((prev) => prev ?? rooms[0]!.id);
    }
  }, [initialTarget.mode, convList?.items]);

  useLayoutEffect(() => {
    if (phase === 'entering') {
      const raf = requestAnimationFrame(() => setPhase('open'));
      return () => cancelAnimationFrame(raf);
    }
  }, [phase]);

  const finishClose = useCallback(() => {
    if (closeOnceRef.current) return;
    closeOnceRef.current = true;
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (phase !== 'closing') return;
    const t = window.setTimeout(finishClose, 450);
    return () => window.clearTimeout(t);
  }, [phase, finishClose]);

  const handleClose = useCallback(() => {
    if (phase === 'closing') return;
    if (panelBodyRef.current) {
      scrollPosRef.current = panelBodyRef.current.scrollTop;
    }
    setPhase('closing');
  }, [phase]);

  const handleTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLDivElement>) => {
      if (e.target !== e.currentTarget) return;
      if (phase !== 'closing') return;
      if (e.propertyName !== 'opacity' && e.propertyName !== 'transform') return;
      finishClose();
    },
    [phase, finishClose],
  );

  useEffect(() => {
    if (phase === 'open') {
      panelRef.current?.focus();
    }
  }, [phase, panelRef]);

  // Focus trap when expanded desktop shell is open
  useEffect(() => {
    if (isMobile || phase !== 'open') return;
    const shell = shellRef.current;
    if (!shell) return;

    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !shell) return;
      const focusables = shell.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleTab, true);
    return () => {
      document.removeEventListener('keydown', handleTab, true);
    };
  }, [isMobile, phase]);

  const handlePanelKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        handleClose();
      }
      if (e.shiftKey && e.key.startsWith('Arrow')) {
        dragHandlers.onKeyDown(e);
      }
    },
    [handleClose, dragHandlers],
  );

  const threadContent = activeConversationId ? (
    <div className="conversation-panel-thread">
      {searchOpen && (
        <MessageSearch conversationId={activeConversationId} onClose={() => setSearchOpen(false)} />
      )}
      <MessageList conversationId={activeConversationId} currentUserId={currentUserId} />
      <MessageComposer conversationId={activeConversationId} />
    </div>
  ) : (
    <div className="conversation-panel-empty">
      <ChatIcon />
      <span className="conversation-panel-empty-label">
        Select a conversation
        <br />
        or start a new one
      </span>
    </div>
  );

  const sidebar = (
    <ConversationSidebar
      projectId={projectId}
      orgId={orgId}
      activeConversationId={activeConversationId}
      onSelect={setActiveConversationId}
    />
  );

  const requestMobileClose = useCallback(() => {
    onClose();
  }, [onClose]);

  const phaseClass =
    phase === 'entering'
      ? 'conversation-floating--entering'
      : phase === 'open'
        ? 'conversation-floating--open'
        : phase === 'closing'
          ? 'conversation-floating--closing'
          : '';

  const draggingClass = isDragging ? 'conversation-floating--dragging' : '';

  const bindShellRef = useCallback(
    (el: HTMLDivElement | null) => {
      (panelRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
      shellRef.current = el;
    },
    [panelRef],
  );

  const desktopShell = (
    <div
      ref={bindShellRef}
      className={`conversation-floating unified-conversation-floating ${phaseClass} ${draggingClass}`}
      style={{
        transform: `translate(${position.x}px, ${position.y}px)`,
      }}
      role="dialog"
      aria-label={`Messages — ${headerTitle}`}
      aria-modal="false"
      tabIndex={-1}
      onKeyDown={handlePanelKeyDown}
      onTransitionEnd={handleTransitionEnd}
    >
      <div
        className="conversation-floating-header unified-conversation-header"
        {...dragHandlers}
        tabIndex={0}
        role="toolbar"
        aria-label="Messages window — drag to reposition"
      >
        <div className="conversation-floating-header-text unified-conversation-header-text">
          <span className="conversation-floating-name">{headerTitle}</span>
          <span className="conversation-floating-status">
            {activeConversationId
              ? connectionState === ConnectionState.Connected
                ? 'Live'
                : connectionState === ConnectionState.Reconnecting
                  ? 'Reconnecting…'
                  : 'Offline'
              : ' '}
          </span>
        </div>
        <div
          className="conversation-floating-header-actions"
          onPointerDown={(e) => e.stopPropagation()}
        >
          {activeConversationId && (
            <button
              type="button"
              className="conversation-panel-search-toggle pressable conversation-floating-action"
              onClick={() => setSearchOpen((v) => !v)}
              aria-label={searchOpen ? 'Close search' : 'Search messages'}
              aria-pressed={searchOpen}
              data-haptic="light"
            >
              <SearchToggleIcon />
            </button>
          )}
          <button
            type="button"
            className="conversation-floating-action pressable"
            onClick={handleClose}
            aria-label="Close messages — reopen from the dock when you need chat"
            title="Close"
            data-haptic="light"
          >
            <CloseIcon />
          </button>
        </div>
      </div>

      <div className="unified-conversation-panel-body">
        <div className="conversation-panel-sidebar">{sidebar}</div>
        <div className="conversation-panel-view">
          <div className="conversation-floating-body unified-conversation-thread" ref={panelBodyRef}>
            {threadContent}
          </div>
        </div>
      </div>
    </div>
  );

  if (isMobile) {
    return (
      <BottomSheet onRequestClose={requestMobileClose} title="Messages" maxHeight="90vh">
        <div className="conversation-panel-mobile unified-conversation-mobile">
          {activeConversationId ? (
            <>
              <button
                type="button"
                className="conversation-panel-back pressable"
                onClick={() => setActiveConversationId(null)}
                data-haptic="light"
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
                  <path d="M10 12L6 8l4-4" />
                </svg>
                <span>Conversations</span>
              </button>
              {threadContent}
            </>
          ) : (
            sidebar
          )}
        </div>
      </BottomSheet>
    );
  }

  return desktopShell;
});
