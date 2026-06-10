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
import {
  useArchiveConversation,
  useConversation,
  useConversations,
  useConversationSocket,
  useCreateConversation,
  usePatchConversation,
} from '../../api/conversations';
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
  | { mode: 'firstProjectRoom' }
  | { mode: 'none' };

export type UnifiedConversationContextKind = 'global' | 'project';

export interface UnifiedConversationWindowProps {
  projectId?: string | null;
  orgId?: string | null;
  currentUserId?: string;
  contextKind?: UnifiedConversationContextKind;
  contextLabel?: string;
  /** Applied when the window mounts or when this reference changes (see initialTargetKey). */
  initialTarget: UnifiedConversationInitialTarget;
  /** Bump to re-apply initialTarget (e.g. new DM from dock). */
  initialTargetKey: number;
  onClose: () => void;
  /** Desktop: header drag start/end (dock↔window connector hides while dragging). */
  onDragStateChange?: (isDragging: boolean) => void;
  /** Desktop: after a header pointer-drag ends, `moved` is true if the window position changed during that gesture. */
  onFloatingPointerDragCommitted?: (detail: { moved: boolean }) => void;
  /** Desktop: floating shell element for layout (dock bridge). Cleared when switching to mobile sheet. */
  onFloatingShellRef?: (el: HTMLDivElement | null) => void;
}

interface DragState {
  active: boolean;
  startX: number;
  startY: number;
  offsetX: number;
  offsetY: number;
}

function useFloatingDrag(
  onPointerDragCommittedRef?: React.MutableRefObject<((detail: { moved: boolean }) => void) | undefined>,
) {
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
  const gestureStartPosRef = useRef({ x: 0, y: 0 });
  const latestPosRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    latestPosRef.current = position;
  }, [position]);

  const handlePointerDown = useCallback((e: ReactPointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest('button, a, input, textarea, select, [data-chat-dropdown]')) {
      return;
    }
    e.currentTarget.setPointerCapture(e.pointerId);
    gestureStartPosRef.current = { x: latestPosRef.current.x, y: latestPosRef.current.y };
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
    if (panel) {
      const elRect = panel.getBoundingClientRect();
      const baseLeft = elRect.left - position.x;
      const baseTop = elRect.top - position.y;
      nextX = Math.max(-baseLeft, Math.min(window.innerWidth - baseLeft - elRect.width, nextX));
      nextY = Math.max(-baseTop, Math.min(window.innerHeight - baseTop - elRect.height, nextY));
    }

    latestPosRef.current = { x: nextX, y: nextY };
    setPosition({ x: nextX, y: nextY });
  }, [position.x, position.y]);

  const handlePointerUp = useCallback((e: ReactPointerEvent<HTMLElement>) => {
    if (!dragRef.current.active) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    dragRef.current.active = false;
    setIsDragging(false);
    const start = gestureStartPosRef.current;
    const end = latestPosRef.current;
    const moved = end.x !== start.x || end.y !== start.y;
    onPointerDragCommittedRef?.current?.({ moved });
  }, [onPointerDragCommittedRef]);

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
      if (panel) {
        const elRect = panel.getBoundingClientRect();
        const baseLeft = elRect.left - prev.x;
        const baseTop = elRect.top - prev.y;
        nextX = Math.max(-baseLeft, Math.min(window.innerWidth - baseLeft - elRect.width, nextX));
        nextY = Math.max(-baseTop, Math.min(window.innerHeight - baseTop - elRect.height, nextY));
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

function PlusChatIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <path d="M8 3v10M3 8h10" />
    </svg>
  );
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <path d="M11.5 2.5l2 2L6 12l-3 1 1-3 7.5-7.5z" />
    </svg>
  );
}

function ArchiveThreadIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <path d="M2 4h12M5 4V3h6v1M6 7v5M10 7v5M3 7h10l-1 7H4L3 7z" />
    </svg>
  );
}

const GLOBAL_CHAT_STORAGE_KEY = 'amprealize.globalChat.activeConversationId';

function defaultPersonalThreadTitle(): string {
  const d = new Date();
  return `New chat · ${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`;
}

export const UnifiedConversationWindow = memo(function UnifiedConversationWindow({
  projectId,
  orgId,
  currentUserId,
  contextKind = 'project',
  contextLabel,
  initialTarget,
  initialTargetKey,
  onClose,
  onDragStateChange,
  onFloatingPointerDragCommitted,
  onFloatingShellRef,
}: UnifiedConversationWindowProps) {
  const [phase, setPhase] = useState<Phase>('entering');
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeReplyStreamId, setActiveReplyStreamId] = useState<string | null>(null);
  const handleReplyStreamComplete = useCallback(() => {
    setActiveReplyStreamId(null);
  }, []);
  const handleReplyStreamScheduled = useCallback((streamId: string) => {
    setActiveReplyStreamId(streamId || null);
  }, []);
  const panelBodyRef = useRef<HTMLDivElement>(null);
  const scrollPosRef = useRef(0);
  const shellRef = useRef<HTMLDivElement>(null);
  const closeOnceRef = useRef(false);
  const isMobile = useIsMobile();

  const onPointerDragCommittedRef = useRef(onFloatingPointerDragCommitted);
  onPointerDragCommittedRef.current = onFloatingPointerDragCommitted;
  const { position, panelRef, isDragging, dragHandlers } = useFloatingDrag(onPointerDragCommittedRef);

  useEffect(() => {
    onDragStateChange?.(isDragging);
  }, [isDragging, onDragStateChange]);

  useEffect(() => {
    if (isMobile) {
      onFloatingShellRef?.(null);
    }
  }, [isMobile, onFloatingShellRef]);

  useEffect(() => {
    return () => {
      onFloatingShellRef?.(null);
    };
  }, [onFloatingShellRef]);

  const { data: convList } = useConversations({
    projectId,
    includeTotal: false,
    enabled: contextKind === 'project' && !!projectId,
  });
  const { data: activeConv } = useConversation(activeConversationId ?? undefined);

  const { connectionState } = useConversationSocket(activeConversationId ?? undefined, currentUserId);

  const createConversation = useCreateConversation();
  const patchConversation = usePatchConversation();
  const archiveConversation = useArchiveConversation();
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameDraft, setRenameDraft] = useState('');

  const headerTitle = useMemo(() => {
    if (!activeConversationId) return 'Chats';
    const titled = activeConv?.title?.trim();
    if (titled) return titled;
    if (activeConv?.scope === ConversationScope.GlobalUserHome) return 'Main chat';
    if (activeConv?.scope === ConversationScope.GlobalPersonalThread) return 'New chat';
    if (activeConv?.scope === ConversationScope.ProjectRoom || activeConv?.scope === ConversationScope.ProjectSpace) {
      return 'Project room';
    }
    if (activeConv?.scope === ConversationScope.GroupChat) return 'Group chat';
    return 'Direct message';
  }, [activeConversationId, activeConv?.title, activeConv?.scope]);

  const contextDisplay = contextLabel ?? (contextKind === 'global' ? 'Workspace' : 'This project');
  const contextHint = useMemo(
    () =>
      contextKind === 'global'
        ? 'Threads across orgs, projects, boards, runs, and agents.'
        : 'Threads scoped to this project.',
    [contextKind],
  );

  const connectionIssueLabel = useMemo(() => {
    if (!activeConversationId) return null;
    if (connectionState === ConnectionState.Connected) return null;
    if (connectionState === ConnectionState.Reconnecting) return 'Reconnecting…';
    if (connectionState === ConnectionState.Connecting) return 'Connecting…';
    return 'Offline';
  }, [activeConversationId, connectionState]);

  useEffect(() => {
    if (contextKind !== 'global' || !activeConversationId) return;
    try {
      sessionStorage.setItem(GLOBAL_CHAT_STORAGE_KEY, activeConversationId);
    } catch {
      /* ignore */
    }
  }, [contextKind, activeConversationId]);

  useEffect(() => {
    if (!renameOpen) return;
    setRenameDraft(activeConv?.title?.trim() ?? '');
  }, [renameOpen, activeConv?.title, activeConv?.id]);

  const handleNewGlobalChat = useCallback(() => {
    if (contextKind !== 'global') return;
    createConversation.mutate(
      { scope: ConversationScope.GlobalPersonalThread, title: defaultPersonalThreadTitle() },
      { onSuccess: (c) => setActiveConversationId(c.id) },
    );
  }, [contextKind, createConversation]);

  const handleArchiveThread = useCallback(() => {
    if (!activeConversationId || !activeConv) return;
    const isHome = activeConv.scope === ConversationScope.GlobalUserHome;
    const msg = isHome
      ? 'Archive main chat? A new main chat will be created when you next open chat from the dock.'
      : 'Archive this chat? You can start a new one anytime from New chat.';
    if (!window.confirm(msg)) return;
    archiveConversation.mutate(activeConversationId, {
      onSuccess: () => {
        setActiveConversationId(null);
        setRenameOpen(false);
        try {
          sessionStorage.removeItem(GLOBAL_CHAT_STORAGE_KEY);
        } catch {
          /* ignore */
        }
      },
    });
  }, [activeConversationId, activeConv, archiveConversation]);

  const submitRename = useCallback(() => {
    if (!activeConversationId) return;
    const next = renameDraft.trim();
    patchConversation.mutate(
      { conversationId: activeConversationId, title: next === '' ? null : next },
      { onSuccess: () => setRenameOpen(false) },
    );
  }, [activeConversationId, renameDraft, patchConversation]);

  const globalActionsBusy =
    createConversation.isPending || patchConversation.isPending || archiveConversation.isPending;

  useEffect(() => {
    queueMicrotask(() => setSearchOpen(false));
    queueMicrotask(() => setActiveReplyStreamId(null));
  }, [activeConversationId]);

  const conversationIdFromTarget =
    initialTarget.mode === 'conversation' ? initialTarget.conversationId : null;

  // When opening / remount intent changes, set or clear selection for project-room entry
  useEffect(() => {
    if (initialTarget.mode === 'conversation' && conversationIdFromTarget) {
      queueMicrotask(() => setActiveConversationId(conversationIdFromTarget));
      return;
    }
    queueMicrotask(() => setActiveConversationId(null));
  }, [initialTargetKey, initialTarget.mode, conversationIdFromTarget]);

  // Pick first project room once list loads (only after first-room entry cleared selection)
  useEffect(() => {
    if (contextKind !== 'project' || initialTarget.mode !== 'firstProjectRoom') return;
    const rooms =
      convList?.items.filter((c) => c.scope === ConversationScope.ProjectRoom) ?? [];
    if (rooms[0]) {
      queueMicrotask(() => setActiveConversationId((prev) => prev ?? rooms[0]!.id));
    }
  }, [contextKind, initialTarget.mode, convList?.items]);

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
      <MessageList
        conversationId={activeConversationId}
        currentUserId={currentUserId}
        streamingMessageId={activeReplyStreamId}
        onStreamingComplete={handleReplyStreamComplete}
      />
      <MessageComposer
        conversationId={activeConversationId}
        currentUserId={currentUserId}
        onReplyStreamScheduled={handleReplyStreamScheduled}
      />
    </div>
  ) : (
    <div className="conversation-panel-empty">
      <ChatIcon />
      <span className="conversation-panel-empty-label">
        {contextKind === 'global' ? 'Ask across your accessible work' : 'Select a conversation'}
        <br />
        {contextKind === 'global' ? 'or jump into a project space' : 'or start a new one'}
      </span>
    </div>
  );

  const sidebar = (
    <ConversationSidebar
      projectId={projectId}
      orgId={orgId}
      contextKind={contextKind}
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
      if (!isMobile) {
        onFloatingShellRef?.(el);
      }
    },
    [panelRef, isMobile, onFloatingShellRef],
  );

  const renameBarEl =
    renameOpen && contextKind === 'global' && activeConversationId ? (
      <div
        className="unified-conversation-rename-bar"
        role="dialog"
        aria-label="Rename conversation"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <input
          type="text"
          className="unified-conversation-rename-input"
          value={renameDraft}
          onChange={(e) => setRenameDraft(e.target.value)}
          placeholder="Thread title"
          aria-label="Thread title"
          maxLength={500}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              submitRename();
            }
            if (e.key === 'Escape') {
              e.preventDefault();
              setRenameOpen(false);
            }
          }}
        />
        <button
          type="button"
          className="unified-conversation-rename-save pressable"
          onClick={submitRename}
          disabled={patchConversation.isPending}
        >
          Save
        </button>
        <button
          type="button"
          className="unified-conversation-rename-cancel pressable"
          onClick={() => setRenameOpen(false)}
        >
          Cancel
        </button>
      </div>
    ) : null;

  const desktopShell = (
    <div
      ref={bindShellRef}
      className={`conversation-floating unified-conversation-floating unified-conversation-floating--${contextKind} ${phaseClass} ${draggingClass}`}
      style={{
        transform: `translate(${position.x}px, ${position.y}px)`,
      }}
      role="dialog"
      aria-label={`Chat — ${contextDisplay} — ${headerTitle}`}
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
        aria-label="Chat — drag header to move"
      >
        <div className="conversation-floating-header-text unified-conversation-header-text">
          <span
            className={`unified-conversation-context-pill unified-conversation-context-pill--${contextKind}`}
            title={contextHint}
          >
            {contextDisplay}
          </span>
          <span className="conversation-floating-name unified-conversation-thread-title">{headerTitle}</span>
          {connectionIssueLabel ? (
            <span className="conversation-floating-status unified-conversation-connection-badge" role="status">
              {connectionIssueLabel}
            </span>
          ) : null}
        </div>
        <div
          className="conversation-floating-header-actions"
          onPointerDown={(e) => e.stopPropagation()}
        >
          {contextKind === 'global' && (
            <>
              <button
                type="button"
                className="conversation-floating-action pressable"
                onClick={handleNewGlobalChat}
                disabled={globalActionsBusy}
                aria-label="Start a new chat"
                title="New chat"
                data-haptic="light"
              >
                <PlusChatIcon />
              </button>
              {activeConversationId && activeConv && (
                <>
                  <button
                    type="button"
                    className={`conversation-floating-action pressable${renameOpen ? ' conversation-floating-action--active' : ''}`}
                    onClick={() => setRenameOpen((v) => !v)}
                    disabled={globalActionsBusy}
                    aria-label={renameOpen ? 'Cancel rename' : 'Rename thread'}
                    aria-expanded={renameOpen}
                    title="Rename"
                    data-haptic="light"
                  >
                    <PencilIcon />
                  </button>
                  <button
                    type="button"
                    className="conversation-floating-action pressable"
                    onClick={handleArchiveThread}
                    disabled={globalActionsBusy}
                    aria-label="Archive thread"
                    title="Archive"
                    data-haptic="light"
                  >
                    <ArchiveThreadIcon />
                  </button>
                </>
              )}
            </>
          )}
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
            aria-label="Close chat"
            title="Close"
            data-haptic="light"
          >
            <CloseIcon />
          </button>
        </div>
      </div>

      {renameBarEl}

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
      <BottomSheet onRequestClose={requestMobileClose} title={contextDisplay} maxHeight="90vh">
        <div className="conversation-panel-mobile unified-conversation-mobile">
          {activeConversationId ? (
            <>
              <div className="conversation-panel-mobile-thread-head">
                <button
                  type="button"
                  className="conversation-panel-back pressable"
                  onClick={() => setActiveConversationId(null)}
                  data-haptic="light"
                >
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
                    <path d="M10 12L6 8l4-4" />
                  </svg>
                  <span>Threads</span>
                </button>
                {contextKind === 'global' && (
                  <div
                    className="conversation-panel-mobile-global-actions"
                    onPointerDown={(e) => e.stopPropagation()}
                  >
                    <button
                      type="button"
                      className="conversation-panel-mobile-icon-btn pressable"
                      onClick={handleNewGlobalChat}
                      disabled={globalActionsBusy}
                      aria-label="Start a new chat"
                      title="New chat"
                      data-haptic="light"
                    >
                      <PlusChatIcon />
                    </button>
                    {activeConv && (
                      <>
                        <button
                          type="button"
                          className={`conversation-panel-mobile-icon-btn pressable${renameOpen ? ' conversation-panel-mobile-icon-btn--active' : ''}`}
                          onClick={() => setRenameOpen((v) => !v)}
                          disabled={globalActionsBusy}
                          aria-label={renameOpen ? 'Cancel rename' : 'Rename thread'}
                          aria-expanded={renameOpen}
                          title="Rename"
                          data-haptic="light"
                        >
                          <PencilIcon />
                        </button>
                        <button
                          type="button"
                          className="conversation-panel-mobile-icon-btn pressable"
                          onClick={handleArchiveThread}
                          disabled={globalActionsBusy}
                          aria-label="Archive thread"
                          title="Archive"
                          data-haptic="light"
                        >
                          <ArchiveThreadIcon />
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
              {renameBarEl}
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
