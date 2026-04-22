/**
 * ConversationPanel — overlay drawer for project conversations.
 *
 * Mirrors WorkItemDrawer animation pattern (entering → open → closing).
 * Houses a sidebar (conversation list) + a main view slot for messages.
 * Keyboard: Escape to close, Cmd+Shift+M to toggle from board.
 */

import React, { memo, useCallback, useEffect, useRef, useState } from 'react';
import { ConversationSidebar } from './ConversationSidebar';
import { MessageList } from './MessageList';
import { MessageComposer } from './MessageComposer';
import { BottomSheet } from './BottomSheet';
import { MessageSearch } from './MessageSearch';
import './ConversationPanel.css';

// ── Mobile breakpoint hook ───────────────────────────────────────────────────

const MOBILE_BREAKPOINT = 768;

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < MOBILE_BREAKPOINT : false
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

// ── Types ────────────────────────────────────────────────────────────────────

type DrawerPhase = 'entering' | 'open' | 'closing';

export interface ConversationPanelProps {
  projectId: string;
  orgId?: string | null;
  onRequestClose: () => void;
}

// ── Close icon (inline SVG to avoid dependency) ──────────────────────────────

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

// ── Component ────────────────────────────────────────────────────────────────

export const ConversationPanel = memo(function ConversationPanel({
  projectId,
  orgId,
  onRequestClose,
}: ConversationPanelProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const prevFocusRef = useRef<HTMLElement | null>(null);
  const [phase, setPhase] = useState<DrawerPhase>('entering');
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const isMobile = useIsMobile();

  // Close search when switching conversations
  useEffect(() => {
    queueMicrotask(() => setSearchOpen(false));
  }, [activeConversationId]);

  // ── Animate in ─────────────────────────────────────────────────────────────
  useEffect(() => {
    prevFocusRef.current = document.activeElement as HTMLElement;
    const id = requestAnimationFrame(() => setPhase('open'));
    return () => cancelAnimationFrame(id);
  }, []);

  // ── Restore focus on unmount ───────────────────────────────────────────────
  useEffect(() => {
    return () => {
      prevFocusRef.current?.focus?.();
    };
  }, []);

  // ── Close handler with exit animation ──────────────────────────────────────
  const requestClose = useCallback(() => {
    if (phase === 'closing') return;
    setPhase('closing');
    setTimeout(() => onRequestClose(), 220);
  }, [onRequestClose, phase]);

  // ── Escape key ─────────────────────────────────────────────────────────────
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        requestClose();
      }
    }
    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [requestClose]);

  // ── Focus trap ─────────────────────────────────────────────────────────────
  useEffect(() => {
    function handleTab(e: KeyboardEvent) {
      if (e.key !== 'Tab' || !overlayRef.current) return;
      const focusables = overlayRef.current.querySelectorAll<HTMLElement>(
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
    }
    document.addEventListener('keydown', handleTab, true);
    return () => document.removeEventListener('keydown', handleTab, true);
  }, []);

  // ── Scrim click = close ────────────────────────────────────────────────────
  const handleOverlayClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === overlayRef.current) requestClose();
    },
    [requestClose],
  );

  const phaseClass = phase === 'entering' ? '' : phase;

  // ── Shared content ─────────────────────────────────────────────────────────
  const sidebarContent = (
    <ConversationSidebar
      projectId={projectId}
      orgId={orgId}
      activeConversationId={activeConversationId}
      onSelect={setActiveConversationId}
    />
  );

  const threadContent = activeConversationId ? (
    <div className="conversation-panel-thread">
      {searchOpen && (
        <MessageSearch
          conversationId={activeConversationId}
          onClose={() => setSearchOpen(false)}
        />
      )}
      <MessageList conversationId={activeConversationId} />
      <MessageComposer conversationId={activeConversationId} />
    </div>
  ) : (
    <div className="conversation-panel-empty">
      <ChatIcon />
      <span className="conversation-panel-empty-label">
        Select a conversation<br />or start a new one
      </span>
      <span className="conversation-panel-kbd">
        <kbd>⌘</kbd><kbd>⇧</kbd><kbd>M</kbd> to toggle
      </span>
    </div>
  );

  // ── Mobile: BottomSheet ────────────────────────────────────────────────────
  if (isMobile) {
    return (
      <BottomSheet onRequestClose={requestClose} title="Conversations" maxHeight="85vh">
        <div className="conversation-panel-mobile">
          {/* On mobile: show sidebar if no conversation selected, else show thread */}
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
                <span>Back</span>
              </button>
              {threadContent}
            </>
          ) : (
            sidebarContent
          )}
        </div>
      </BottomSheet>
    );
  }

  // ── Desktop: Side drawer ───────────────────────────────────────────────────
  return (
    <div
      ref={overlayRef}
      className={`conversation-panel-overlay ${phaseClass}`}
      onClick={handleOverlayClick}
      role="dialog"
      aria-modal="true"
      aria-label="Conversations"
    >
      <div className="conversation-panel">
        {/* Header */}
        <div className="conversation-panel-header" style={{ position: 'absolute', top: 0, left: 0, right: 0, zIndex: 1 }}>
          <h2 className="conversation-panel-title">Conversations</h2>
          <div className="conversation-panel-header-actions">
            {activeConversationId && (
              <button
                type="button"
                className="conversation-panel-search-toggle pressable"
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
              className="conversation-panel-close pressable"
              onClick={requestClose}
              aria-label="Close conversations"
              data-haptic="light"
            >
              <CloseIcon />
            </button>
          </div>
        </div>

        {/* Body (below header) */}
        <div className="conversation-panel-body" style={{ marginTop: 52 }}>
          {/* Sidebar — conversation list */}
          <div className="conversation-panel-sidebar">
            {sidebarContent}
          </div>

          {/* Main view — message thread or empty state */}
          <div className="conversation-panel-view">
            {threadContent}
          </div>
        </div>
      </div>
    </div>
  );
});
