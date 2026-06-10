import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { ConversationScope, type Conversation } from '../../lib/collab-client';
import { useConversations, useCreateConversation, useEnsureGlobalHomeConversation } from '../../api/conversations';
import { UnifiedConversationWindow, type UnifiedConversationInitialTarget } from './UnifiedConversationWindow';
import './AmprealizeChatDock.css';

type ChatContextKind = 'global' | 'project';

interface OpenChatState {
  contextKind: ChatContextKind;
  initialTarget: UnifiedConversationInitialTarget;
  key: number;
}

export interface AmprealizeChatDockProps {
  projectId?: string | null;
  orgId?: string | null;
  projectName?: string | null;
  currentUserId?: string;
}

function ChatDockIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4.2 14.7A7 7 0 1117 10.8c0 3.4-3.1 6.2-7 6.2a8 8 0 01-2.7-.5L3 17.2l1.2-2.5z" />
      <path d="M7 9.5h6M7 12h4" />
    </svg>
  );
}

function getProjectRoom(items: Conversation[]): Conversation | null {
  return (
    items.find((item) => item.scope === ConversationScope.ProjectRoom || item.scope === ConversationScope.ProjectSpace) ?? null
  );
}

const GLOBAL_CHAT_LAST_KEY = 'amprealize.globalChat.activeConversationId';

type ChatDockToWindowBridgeProps = {
  visible: boolean;
  dockRef: RefObject<HTMLButtonElement | null>;
  /** Default chat slot (CSS-positioned); vertical guide aligns to its right edge. */
  anchorRef: RefObject<HTMLDivElement | null>;
  layoutKey: number;
  accent: ChatContextKind;
};

/** Straight vertical segment: right edge of default chat slot down to dock top (hidden while dragging the header). */
function ChatDockToWindowBridge({ visible, dockRef, anchorRef, layoutKey, accent }: ChatDockToWindowBridgeProps) {
  const [geo, setGeo] = useState<{
    w: number;
    h: number;
    x: number;
    yTop: number;
    yBottom: number;
    ok: boolean;
  }>({ w: 0, h: 0, x: 0, yTop: 0, yBottom: 0, ok: false });

  const update = useCallback(() => {
    if (!visible || typeof window === 'undefined') {
      setGeo({ w: 0, h: 0, x: 0, yTop: 0, yBottom: 0, ok: false });
      return;
    }
    const dock = dockRef.current;
    const anchor = anchorRef.current;
    if (!dock || !anchor) {
      setGeo({ w: 0, h: 0, x: 0, yTop: 0, yBottom: 0, ok: false });
      return;
    }
    const w = window.innerWidth;
    const h = window.innerHeight;
    const dr = dock.getBoundingClientRect();
    const ar = anchor.getBoundingClientRect();
    const inset = 8;
    const x = Math.round(ar.right - inset);
    const yTop = Math.round(ar.bottom);
    const yBottom = Math.round(dr.top);
    const ok = yBottom > yTop && yBottom - yTop >= 3 && x >= 0 && x <= w;
    setGeo({ w, h, x, yTop, yBottom, ok });
  }, [visible, dockRef, anchorRef]);

  useLayoutEffect(() => {
    if (!visible) {
      setGeo({ w: 0, h: 0, x: 0, yTop: 0, yBottom: 0, ok: false });
      return undefined;
    }
    let cancelled = false;
    let raf = 0;
    const runUpdate = () => {
      if (!cancelled) update();
    };
    runUpdate();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(runUpdate) : null;
    try {
      if (dockRef.current) ro?.observe(dockRef.current);
      if (anchorRef.current) ro?.observe(anchorRef.current);
    } catch {
      /* ignore */
    }
    window.addEventListener('resize', runUpdate);
    window.addEventListener('scroll', runUpdate, true);
    let n = 0;
    const burst = () => {
      if (cancelled) return;
      runUpdate();
      n += 1;
      if (n < 24) raf = requestAnimationFrame(burst);
    };
    raf = requestAnimationFrame(burst);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      ro?.disconnect();
      window.removeEventListener('resize', runUpdate);
      window.removeEventListener('scroll', runUpdate, true);
    };
  }, [visible, dockRef, anchorRef, layoutKey, update]);

  if (!visible || !geo.ok || geo.w < 16 || geo.h < 16) return null;

  return (
    <svg
      className={`amp-chat-bridge amp-chat-bridge--${accent}`}
      aria-hidden="true"
      width={geo.w}
      height={geo.h}
      viewBox={`0 0 ${geo.w} ${geo.h}`}
      preserveAspectRatio="none"
    >
      <line
        className="amp-chat-bridge__line"
        x1={geo.x}
        y1={geo.yTop}
        x2={geo.x}
        y2={geo.yBottom}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export const AmprealizeChatDock = memo(function AmprealizeChatDock({
  projectId,
  orgId,
  projectName,
  currentUserId,
}: AmprealizeChatDockProps) {
  const [openChat, setOpenChat] = useState<OpenChatState | null>(null);
  const [chatDragging, setChatDragging] = useState(false);
  const [bridgeSuppressedAfterDrag, setBridgeSuppressedAfterDrag] = useState(false);
  const windowAnchorRef = useRef<HTMLDivElement>(null);
  const [desktopLayout, setDesktopLayout] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : true,
  );
  const dockRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const mq = window.matchMedia('(min-width: 768px)');
    const sync = () => setDesktopLayout(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);

  useEffect(() => {
    if (!openChat) {
      setChatDragging(false);
      setBridgeSuppressedAfterDrag(false);
    }
  }, [openChat]);

  const handleFloatingPointerDragCommitted = useCallback((detail: { moved: boolean }) => {
    if (detail.moved) setBridgeSuppressedAfterDrag(true);
  }, []);
  const ensureGlobalHome = useEnsureGlobalHomeConversation();
  const createConversation = useCreateConversation();
  const projectConversations = useConversations({
    projectId,
    includeTotal: false,
    enabled: !!projectId,
  });

  const activeContextKind: ChatContextKind = projectId ? 'project' : 'global';
  /** Shown in the floating window chrome and assistive labels */
  const contextLabel = useMemo(() => {
    if (activeContextKind === 'project') {
      return projectName ? `${projectName}` : 'Project';
    }
    return 'Workspace';
  }, [activeContextKind, projectName]);

  const dockTitle = activeContextKind === 'project' ? (projectName?.trim() || 'Project') : 'Chat';
  const dockScope = activeContextKind === 'project' ? 'This project' : 'Workspace-wide';
  const openChatAria = useMemo(() => {
    if (activeContextKind === 'project') {
      return projectName ? `Open team chat for ${projectName}` : 'Open project team chat';
    }
    return 'Open workspace chat';
  }, [activeContextKind, projectName]);

  const openGlobalChat = useCallback(() => {
    const last =
      typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(GLOBAL_CHAT_LAST_KEY) : null;
    if (last) {
      setOpenChat({
        contextKind: 'global',
        initialTarget: { mode: 'conversation', conversationId: last },
        key: Date.now(),
      });
      return;
    }
    setOpenChat({
      contextKind: 'global',
      initialTarget: { mode: 'none' },
      key: Date.now(),
    });
    ensureGlobalHome.mutate(undefined, {
      onSuccess: (payload) => {
        setOpenChat({
          contextKind: 'global',
          initialTarget: { mode: 'conversation', conversationId: payload.conversation.id },
          key: Date.now(),
        });
      },
    });
  }, [ensureGlobalHome]);

  const openProjectChat = useCallback(() => {
    if (!projectId) {
      openGlobalChat();
      return;
    }

    const existingRoom = getProjectRoom(projectConversations.data?.items ?? []);
    if (existingRoom) {
      setOpenChat({
        contextKind: 'project',
        initialTarget: { mode: 'conversation', conversationId: existingRoom.id },
        key: Date.now(),
      });
      return;
    }

    createConversation.mutate(
      { projectId, scope: ConversationScope.ProjectRoom, title: 'Project room' },
      {
        onSuccess: (conversation) => {
          setOpenChat({
            contextKind: 'project',
            initialTarget: { mode: 'conversation', conversationId: conversation.id },
            key: Date.now(),
          });
        },
      },
    );
  }, [createConversation, openGlobalChat, projectConversations.data?.items, projectId]);

  const handleDockClick = useCallback(() => {
    if (openChat) {
      setOpenChat(null);
      return;
    }
    if (activeContextKind === 'project') {
      openProjectChat();
    } else {
      openGlobalChat();
    }
  }, [openChat, activeContextKind, openProjectChat, openGlobalChat]);

  const isBusy = ensureGlobalHome.isPending || createConversation.isPending || projectConversations.isFetching;

  const bridgeVisible =
    !!openChat && desktopLayout && !chatDragging && !bridgeSuppressedAfterDrag;

  return (
    <div className="amp-chat-root" aria-live="polite">
      {openChat && (
        <>
          <div className="amp-chat-backdrop" aria-hidden="true" />
          <ChatDockToWindowBridge
            visible={bridgeVisible}
            dockRef={dockRef}
            anchorRef={windowAnchorRef}
            layoutKey={openChat.key}
            accent={openChat.contextKind}
          />
          <div ref={windowAnchorRef} className="amp-chat-window-anchor">
            <UnifiedConversationWindow
              projectId={openChat.contextKind === 'project' ? projectId : null}
              orgId={orgId}
              currentUserId={currentUserId}
              contextKind={openChat.contextKind}
              contextLabel={openChat.contextKind === 'project' ? contextLabel : undefined}
              initialTarget={openChat.initialTarget}
              initialTargetKey={openChat.key}
              onClose={() => setOpenChat(null)}
              onDragStateChange={setChatDragging}
              onFloatingPointerDragCommitted={handleFloatingPointerDragCommitted}
            />
          </div>
        </>
      )}

      <button
        type="button"
        ref={dockRef}
        className={`amp-chat-dock pressable amp-chat-dock--${activeContextKind}`}
        onClick={handleDockClick}
        disabled={isBusy && !openChat}
        aria-label={openChat ? 'Close chat' : openChatAria}
        aria-expanded={!!openChat}
        data-haptic="medium"
      >
        <span className="amp-chat-dock__icon"><ChatDockIcon /></span>
        <span className="amp-chat-dock__copy">
          <span className="amp-chat-dock__title">{dockTitle}</span>
          <span className="amp-chat-dock__scope">{dockScope}</span>
        </span>
      </button>
    </div>
  );
});
