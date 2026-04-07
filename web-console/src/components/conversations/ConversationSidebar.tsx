/**
 * ConversationSidebar — conversation list inside ConversationPanel.
 *
 * Groups conversations by scope (Rooms / Direct Messages).
 * Shows unread badges. Supports creating a new conversation and quick search.
 */

import React, { memo, useCallback, useMemo, useState } from 'react';
import {
  ConversationScope,
  type Conversation,
} from '../../lib/collab-client';
import { useConversations, useCreateConversation } from '../../api/conversations';

// ── Inline icons ─────────────────────────────────────────────────────────────

function HashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" aria-hidden="true">
      <path d="M3.5 6h9M3.5 10h9M6 3l-1 10M11 3l-1 10" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="8" cy="5" r="3" />
      <path d="M2 14c0-3.3 2.7-5 6-5s6 1.7 6 5" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <path d="M8 3v10M3 8h10" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="7" cy="7" r="5" />
      <path d="M11 11l3.5 3.5" />
    </svg>
  );
}

// ── Styles (scoped via BEM-style class naming) ───────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  },
  searchWrap: {
    padding: '8px 8px 4px',
    flexShrink: 0,
  },
  searchInput: {
    width: '100%',
    height: 28,
    padding: '0 8px 0 26px',
    border: '1px solid rgba(0,0,0,0.06)',
    borderRadius: 8,
    background: 'rgba(255,255,255,0.5)',
    fontSize: 12,
    color: 'var(--color-text-primary)',
    outline: 'none',
    transition: 'border var(--duration-fast) ease, box-shadow var(--duration-fast) ease',
  },
  searchIcon: {
    position: 'absolute' as const,
    left: 16,
    top: 14,
    pointerEvents: 'none' as const,
    color: 'var(--color-text-quaternary)',
  },
  list: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: '4px 0',
  },
  groupLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    padding: '10px 12px 4px',
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.06em',
    color: 'var(--color-text-quaternary)',
    userSelect: 'none' as const,
  },
  item: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    width: '100%',
    padding: '6px 12px',
    border: 'none',
    borderRadius: 0,
    background: 'transparent',
    fontSize: 13,
    color: 'var(--color-text-secondary)',
    cursor: 'pointer',
    textAlign: 'left' as const,
    lineHeight: 1.3,
    transition: 'background var(--duration-fast) ease',
  },
  itemActive: {
    background: 'rgba(0,0,0,0.05)',
    color: 'var(--color-text-primary)',
    fontWeight: 500,
  },
  itemTitle: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: 16,
    height: 16,
    padding: '0 4px',
    borderRadius: 8,
    background: 'var(--color-accent-primary)',
    color: '#fff',
    fontSize: 10,
    fontWeight: 600,
    lineHeight: 1,
    flexShrink: 0,
  },
  footer: {
    padding: '6px 8px',
    borderTop: '1px solid rgba(0,0,0,0.05)',
    flexShrink: 0,
  },
  newBtn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    width: '100%',
    height: 28,
    border: '1px solid rgba(0,0,0,0.06)',
    borderRadius: 8,
    background: 'rgba(255,255,255,0.5)',
    color: 'var(--color-text-secondary)',
    fontSize: 12,
    fontWeight: 500,
    cursor: 'pointer',
    transition: 'background var(--duration-fast) ease, border-color var(--duration-fast) ease',
  },
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
    fontSize: 12,
    color: 'var(--color-text-quaternary)',
    padding: 16,
    textAlign: 'center' as const,
  },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function groupConversations(items: Conversation[]) {
  const rooms: Conversation[] = [];
  const dms: Conversation[] = [];
  for (const c of items) {
    if (c.scope === ConversationScope.ProjectRoom) rooms.push(c);
    else dms.push(c);
  }
  return { rooms, dms };
}

function displayTitle(c: Conversation): string {
  if (c.title) return c.title;
  if (c.scope === ConversationScope.ProjectRoom) return 'General';
  return 'Direct Message';
}

// ── Props ────────────────────────────────────────────────────────────────────

export interface ConversationSidebarProps {
  projectId: string;
  orgId?: string | null;
  activeConversationId: string | null;
  onSelect: (conversationId: string) => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export const ConversationSidebar = memo(function ConversationSidebar(props: ConversationSidebarProps) {
  const { projectId, activeConversationId, onSelect } = props;
  const [search, setSearch] = useState('');
  const { data, isLoading } = useConversations({ projectId, enabled: !!projectId });
  const createConversation = useCreateConversation();

  const items = useMemo(() => data?.items ?? [], [data?.items]);

  const filtered = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter((c) => displayTitle(c).toLowerCase().includes(q));
  }, [items, search]);

  const { rooms, dms } = useMemo(() => groupConversations(filtered), [filtered]);

  const handleCreate = useCallback(() => {
    createConversation.mutate(
      { projectId, scope: ConversationScope.ProjectRoom },
      { onSuccess: (created) => onSelect(created.id) },
    );
  }, [createConversation, projectId, onSelect]);

  const renderItem = useCallback(
    (c: Conversation, icon: React.ReactNode) => {
      const isActive = c.id === activeConversationId;
      return (
        <button
          key={c.id}
          type="button"
          className="pressable"
          style={{ ...styles.item, ...(isActive ? styles.itemActive : {}) }}
          onClick={() => onSelect(c.id)}
          aria-current={isActive ? 'true' : undefined}
          data-haptic="light"
        >
          {icon}
          <span style={styles.itemTitle}>{displayTitle(c)}</span>
          {c.unread_count > 0 && (
            <span style={styles.badge} aria-label={`${c.unread_count} unread`}>
              {c.unread_count > 99 ? '99+' : c.unread_count}
            </span>
          )}
        </button>
      );
    },
    [activeConversationId, onSelect],
  );

  return (
    <div style={styles.root}>
      {/* Search */}
      <div style={styles.searchWrap}>
        <div style={{ position: 'relative' }}>
          <span style={styles.searchIcon}><SearchIcon /></span>
          <input
            type="text"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={styles.searchInput}
            aria-label="Search conversations"
          />
        </div>
      </div>

      {/* Conversation list */}
      <div style={styles.list} role="listbox" aria-label="Conversations">
        {isLoading && <div style={styles.empty}>Loading…</div>}

        {!isLoading && items.length === 0 && (
          <div style={styles.empty}>No conversations yet</div>
        )}

        {!isLoading && filtered.length === 0 && items.length > 0 && (
          <div style={styles.empty}>No matches</div>
        )}

        {rooms.length > 0 && (
          <>
            <div style={styles.groupLabel}><HashIcon /> Rooms</div>
            {rooms.map((c) => renderItem(c, <HashIcon />))}
          </>
        )}

        {dms.length > 0 && (
          <>
            <div style={styles.groupLabel}><UserIcon /> Direct</div>
            {dms.map((c) => renderItem(c, <UserIcon />))}
          </>
        )}
      </div>

      {/* New conversation */}
      <div style={styles.footer}>
        <button
          type="button"
          className="pressable"
          style={styles.newBtn}
          onClick={handleCreate}
          disabled={createConversation.isPending}
          aria-label="New conversation"
          data-haptic="light"
        >
          <PlusIcon />
          {createConversation.isPending ? 'Creating…' : 'New conversation'}
        </button>
      </div>
    </div>
  );
});
