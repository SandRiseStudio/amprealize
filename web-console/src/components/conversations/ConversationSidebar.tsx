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
import { hapticNewConversation } from '../../utils/haptics';

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

// ── Helpers ─────────────────────────────────────────────────────────────────-

function groupConversations(items: Conversation[]) {
  const globalHome: Conversation[] = [];
  const globalThreads: Conversation[] = [];
  const rooms: Conversation[] = [];
  const dms: Conversation[] = [];
  const groups: Conversation[] = [];
  for (const c of items) {
    if (c.scope === ConversationScope.GlobalUserHome) globalHome.push(c);
    else if (c.scope === ConversationScope.GlobalPersonalThread) globalThreads.push(c);
    else if (c.scope === ConversationScope.ProjectRoom || c.scope === ConversationScope.ProjectSpace) rooms.push(c);
    else if (c.scope === ConversationScope.GroupChat) groups.push(c);
    else dms.push(c);
  }
  globalThreads.sort((a, b) => {
    const ta = a.updated_at ? Date.parse(a.updated_at) : 0;
    const tb = b.updated_at ? Date.parse(b.updated_at) : 0;
    return tb - ta;
  });
  return { globalHome, globalThreads, rooms, dms, groups };
}

function displayTitle(c: Conversation): string {
  const titled = c.title?.trim();
  if (titled) return titled;
  if (c.scope === ConversationScope.GlobalUserHome) return 'Home';
  if (c.scope === ConversationScope.GlobalPersonalThread) return 'Chat';
  if (c.scope === ConversationScope.ProjectRoom || c.scope === ConversationScope.ProjectSpace) return 'Project room';
  if (c.scope === ConversationScope.GroupChat) return 'Group';
  return 'Direct message';
}

function defaultPersonalThreadTitle(): string {
  const d = new Date();
  return `Chat ${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`;
}

// ── Props ────────────────────────────────────────────────────────────────────

export interface ConversationSidebarProps {
  projectId?: string | null;
  orgId?: string | null;
  contextKind?: 'project' | 'global';
  activeConversationId: string | null;
  onSelect: (conversationId: string) => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export const ConversationSidebar = memo(function ConversationSidebar(props: ConversationSidebarProps) {
  const { projectId, contextKind = projectId ? 'project' : 'global', activeConversationId, onSelect } = props;
  const [search, setSearch] = useState('');

  const globalWorkspaceQuery = useConversations({
    scopes: [ConversationScope.GlobalUserHome, ConversationScope.GlobalPersonalThread],
    includeTotal: false,
    enabled: contextKind === 'global',
  });

  const globalWorkspaceProjectQuery = useConversations({
    scopes: [ConversationScope.GlobalUserHome, ConversationScope.GlobalPersonalThread],
    includeTotal: false,
    enabled: contextKind === 'project' && !!projectId,
  });
  const projectQuery = useConversations({
    projectId: projectId ?? undefined,
    includeTotal: false,
    enabled: contextKind === 'project' && !!projectId,
  });

  const createConversation = useCreateConversation();

  const items = useMemo(() => {
    if (contextKind === 'global') {
      return globalWorkspaceQuery.data?.items ?? [];
    }
    const merged: Conversation[] = [];
    const seen = new Set<string>();
    for (const c of globalWorkspaceProjectQuery.data?.items ?? []) {
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      merged.push(c);
    }
    for (const c of projectQuery.data?.items ?? []) {
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      merged.push(c);
    }
    return merged;
  }, [
    contextKind,
    globalWorkspaceQuery.data?.items,
    globalWorkspaceProjectQuery.data?.items,
    projectQuery.data?.items,
  ]);

  const isLoading =
    contextKind === 'global'
      ? globalWorkspaceQuery.isLoading
      : globalWorkspaceProjectQuery.isLoading || projectQuery.isLoading;

  const filtered = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter((c) => displayTitle(c).toLowerCase().includes(q));
  }, [items, search]);

  const { globalHome, globalThreads, rooms, dms, groups } = useMemo(() => groupConversations(filtered), [filtered]);

  const handleCreate = useCallback(() => {
    const canCreateProjectRoom = contextKind === 'project' && !!projectId;
    createConversation.mutate(
      canCreateProjectRoom && projectId
        ? { projectId, scope: ConversationScope.ProjectRoom, title: 'Project room' }
        : { scope: ConversationScope.GlobalPersonalThread, title: defaultPersonalThreadTitle() },
      {
        onSuccess: (created) => {
          hapticNewConversation();
          onSelect(created.id);
        },
      },
    );
  }, [contextKind, createConversation, projectId, onSelect]);

  const renderItem = useCallback(
    (c: Conversation, icon: React.ReactNode) => {
      const isActive = c.id === activeConversationId;
      return (
        <button
          key={c.id}
          type="button"
          className={`pressable conversation-sidebar-item${isActive ? ' conversation-sidebar-item--active' : ''}`}
          onClick={() => onSelect(c.id)}
          aria-current={isActive ? 'true' : undefined}
          data-haptic="light"
        >
          {icon}
          <span className="conversation-sidebar-item-title">{displayTitle(c)}</span>
          {c.unread_count > 0 && (
            <span className="conversation-sidebar-badge" aria-label={`${c.unread_count} unread`}>
              {c.unread_count > 99 ? '99+' : c.unread_count}
            </span>
          )}
        </button>
      );
    },
    [activeConversationId, onSelect],
  );

  return (
    <div className="conversation-sidebar">
      <div className="conversation-sidebar-search-wrap">
        <div className="conversation-sidebar-search-field">
          <span className="conversation-sidebar-search-icon" aria-hidden="true">
            <SearchIcon />
          </span>
          <input
            type="text"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="conversation-sidebar-search"
            aria-label="Search conversations"
          />
        </div>
      </div>

      <div className="conversation-sidebar-list" role="listbox" aria-label="Threads">
        {isLoading && <div className="conversation-sidebar-empty">Loading…</div>}

        {!isLoading && items.length === 0 && (
          <div className="conversation-sidebar-empty">No conversations yet</div>
        )}

        {!isLoading && filtered.length === 0 && items.length > 0 && (
          <div className="conversation-sidebar-empty">No matches</div>
        )}

        {globalHome.length > 0 && (
          <>
            <div className="conversation-sidebar-group-label">
              <HashIcon /> Main
            </div>
            {globalHome.map((c) => renderItem(c, <HashIcon />))}
          </>
        )}

        {globalThreads.length > 0 && (
          <>
            <div className="conversation-sidebar-group-label">
              <HashIcon /> Your chats
            </div>
            {globalThreads.map((c) => renderItem(c, <HashIcon />))}
          </>
        )}

        {rooms.length > 0 && (
          <>
            <div className="conversation-sidebar-group-label">
              <HashIcon /> Project
            </div>
            {rooms.map((c) => renderItem(c, <HashIcon />))}
          </>
        )}

        {groups.length > 0 && (
          <>
            <div className="conversation-sidebar-group-label">
              <UserIcon /> Groups
            </div>
            {groups.map((c) => renderItem(c, <UserIcon />))}
          </>
        )}

        {dms.length > 0 && (
          <>
            <div className="conversation-sidebar-group-label">
              <UserIcon /> Direct
            </div>
            {dms.map((c) => renderItem(c, <UserIcon />))}
          </>
        )}
      </div>

      <div className="conversation-sidebar-footer">
        <button
          type="button"
          className="pressable conversation-sidebar-new-btn"
          onClick={handleCreate}
          disabled={createConversation.isPending}
          aria-label="New conversation"
          data-haptic="light"
        >
          <PlusIcon />
          {createConversation.isPending ? 'Creating…' : contextKind === 'project' ? 'New project room' : 'New chat'}
        </button>
      </div>
    </div>
  );
});
