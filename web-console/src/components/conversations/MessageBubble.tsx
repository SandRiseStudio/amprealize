/**
 * MessageBubble — Individual message display with structured cards and reactions.
 *
 * Supports text (react-markdown + GFM, remark-breaks, fenced syntax highlight),
 * StatusCard, BlockerCard, ProgressCard,
 * CodeBlock, and system messages. Includes ReactionBar and hover MessageActions.
 */

import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { hapticReaction, hapticReceiveMessageOnce } from '../../utils/haptics';
import {
  mergeArtifactRefsUnique,
  refsFromStructuredPayloadRows,
  type ChatArtifactRef,
  type ChatArtifactKind,
} from './chatArtifactRefsFromRows';
import {
  ArtifactChipLink,
  ArtifactChipRow,
  ChatMarkdownWithArtifacts,
  getDualWorkItemTitleIdRefs,
} from './chatArtifactChips';
import { useDeleteMessage, useAddReaction, useRemoveReaction } from '../../api/conversations';
import { MessageType, ActorType, type ConversationMessage, type ConversationReaction } from '../../lib/collab-client';
import { KnowledgeRetrievalSummary } from '../boards/execution/KnowledgeRetrievalSummary';

// ── Types ────────────────────────────────────────────────────────────────────

export interface MessageBubbleProps {
  message: ConversationMessage;
  isFirstInGroup: boolean;
  isOwn: boolean;
  conversationId: string;
  currentUserId?: string;
  onReply?: (messageId: string) => void;
  onEdit?: (message: ConversationMessage) => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatTimestamp(isoStr: string | undefined | null): string {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function senderLabel(msg: ConversationMessage): string {
  if (msg.metadata?.display_name) return String(msg.metadata.display_name);
  if (msg.sender_type === ActorType.Agent) return 'Agent';
  if (msg.sender_type === ActorType.System) return 'System';
  return msg.sender_id?.slice(0, 8) ?? 'Unknown';
}

function senderInitials(msg: ConversationMessage): string {
  const name = senderLabel(msg);
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] ?? ''}${parts[1][0] ?? ''}`.toUpperCase();
}

const QUICK_EMOJIS = ['👍', '❤️', '🎉', '😂', '🤔', '👀'];

// ── Component ────────────────────────────────────────────────────────────────

export const MessageBubble = memo(function MessageBubble({
  message,
  isFirstInGroup,
  isOwn,
  conversationId,
  currentUserId,
  onReply,
  onEdit,
}: MessageBubbleProps) {
  const [showActions, setShowActions] = useState(false);
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [appear, setAppear] = useState(false);

  const deleteMessage = useDeleteMessage();
  const addReaction = useAddReaction();
  const removeReaction = useRemoveReaction();

  const isDeleted = message.is_deleted;
  const isEdited = message.is_edited;

  const msgType = message.message_type ?? MessageType.Text;
  const isSystem = msgType === MessageType.System || message.sender_type === ActorType.System;

  const handleDelete = useCallback(() => {
    deleteMessage.mutate({ conversationId, messageId: message.id });
    setShowActions(false);
  }, [deleteMessage, conversationId, message.id]);

  const handleReaction = useCallback((emoji: string) => {
    hapticReaction();
    const existing = message.reactions?.find(
      (r) => r.emoji === emoji && r.actor_id === currentUserId,
    );
    if (existing) {
      removeReaction.mutate({ conversationId, messageId: message.id, emoji });
    } else {
      addReaction.mutate({ conversationId, messageId: message.id, emoji });
    }
    setShowEmojiPicker(false);
  }, [addReaction, removeReaction, conversationId, message.id, message.reactions, currentUserId]);

  useEffect(() => {
    const id = requestAnimationFrame(() => setAppear(true));
    return () => cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    if (isOwn || isSystem) return;
    if (!isFirstInGroup) return;
    hapticReceiveMessageOnce(message.id);
  }, [isOwn, isFirstInGroup, isSystem, message.id]);

  // ── System messages ──────────────────────────────────────────────────────

  if (isSystem) {
    return (
      <div className="msg-bubble msg-bubble--system" data-appear={appear ? '1' : '0'}>
        <span className="msg-system-text">{message.content ?? 'System event'}</span>
        <span className="msg-system-time">{formatTimestamp(message.created_at)}</span>
      </div>
    );
  }

  // ── Deleted messages ─────────────────────────────────────────────────────

  if (isDeleted) {
    return (
      <div className={`msg-bubble ${isOwn ? 'msg-bubble--own' : ''}`} data-appear={appear ? '1' : '0'}>
        <span className="msg-deleted-text">This message was deleted</span>
      </div>
    );
  }

  // ── Main bubble ──────────────────────────────────────────────────────────

  return (
    <div
      className={`msg-bubble ${isOwn ? 'msg-bubble--own' : ''} ${isFirstInGroup ? 'msg-bubble--first' : ''}`}
      data-appear={appear ? '1' : '0'}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => { setShowActions(false); setShowEmojiPicker(false); }}
    >
      {/* Avatar + sender for first in group */}
      {isFirstInGroup && !isOwn && (
        <div className="msg-sender-row">
          <span className="msg-avatar" data-sender-type={message.sender_type}>
            {senderInitials(message)}
          </span>
          <span className="msg-sender-name">{senderLabel(message)}</span>
        </div>
      )}

      {/* Trailing time bottom-right inside bubble (own + peer; clock not in sender row) */}
      <div
        className={`msg-content ${isOwn ? 'msg-content--own-trail' : 'msg-content--peer-trail'}`}
      >
        <div className="msg-content-primary">
          <MessageContent message={message} msgType={msgType} />
          {isEdited && <span className="msg-edited-label">(edited)</span>}
        </div>
        {message.created_at ? (
          <time
            className="msg-timestamp msg-timestamp--trailing"
            dateTime={message.created_at}
            title={new Date(message.created_at).toLocaleString()}
          >
            {formatTimestamp(message.created_at)}
          </time>
        ) : null}
      </div>

      {/* Reactions */}
      {message.reactions && message.reactions.length > 0 && (
        <ReactionBar
          reactions={message.reactions}
          currentUserId={currentUserId}
          onToggle={handleReaction}
        />
      )}

      {/* Hover actions */}
      {showActions && (
        <div className={`msg-actions ${isOwn ? 'msg-actions--own' : ''}`}>
          {onReply && (
            <button
              type="button"
              className="msg-action-btn"
              onClick={() => onReply(message.id)}
              aria-label="Reply"
              title="Reply"
            >
              <ReplyIcon />
            </button>
          )}
          <button
            type="button"
            className="msg-action-btn"
            onClick={() => setShowEmojiPicker((v) => !v)}
            aria-label="Add reaction"
            title="React"
          >
            <EmojiIcon />
          </button>
          {isOwn && onEdit && (
            <button
              type="button"
              className="msg-action-btn"
              onClick={() => onEdit(message)}
              aria-label="Edit"
              title="Edit"
            >
              <EditIcon />
            </button>
          )}
          {isOwn && (
            <button
              type="button"
              className="msg-action-btn msg-action-btn--danger"
              onClick={handleDelete}
              aria-label="Delete"
              title="Delete"
            >
              <TrashIcon />
            </button>
          )}

          {/* Quick emoji picker */}
          {showEmojiPicker && (
            <div className="msg-emoji-picker">
              {QUICK_EMOJIS.map((emoji) => (
                <button
                  key={emoji}
                  type="button"
                  className="msg-emoji-btn"
                  onClick={() => handleReaction(emoji)}
                >
                  {emoji}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

// ── Chat artifact chips (inline navigation) ─────────────────────────────────

function pickString(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value.trim();
  return undefined;
}

function firstPresent(record: Record<string, unknown> | null | undefined, keys: string[]): string | undefined {
  if (!record) return undefined;
  for (const key of keys) {
    const v = pickString(record[key]);
    if (v) return v;
  }
  return undefined;
}

function pushUnique(out: ChatArtifactRef[], ref: ChatArtifactRef): void {
  if (out.some((r) => r.key === ref.key)) return;
  out.push(ref);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Phrases (before ":") we strip when they repeat the chip label at end of the sentence. */
const TAIL_STRIP_PHRASES: Record<ChatArtifactKind, string[]> = {
  work_item: ['work item'],
  project: ['project'],
  board: ['board'],
  agent: ['agent'],
  run: ['run', 'execution'],
  behavior: ['behavior'],
  wiki: ['wiki page', 'wiki'],
  org: ['organization', 'org'],
  resource: ['resource'],
};

function phraseToTailPattern(phrase: string): string {
  return phrase.trim().split(/\s+/).map(escapeRegExp).join('\\s+');
}

/** Drop redundant "… resource: Label." / trailing label echo before the chip when there is a single ref. */
function stripEchoedResourceTitle(raw: string, label: string, kind: ChatArtifactKind): string | undefined {
  const t = label.trim();
  if (!t) return undefined;
  const esc = escapeRegExp(t);
  let cur = raw;
  let changed = false;
  const phrases = TAIL_STRIP_PHRASES[kind] ?? [];
  for (const phrase of phrases) {
    const re = new RegExp(`\\s+${phraseToTailPattern(phrase)}:\\s*${esc}\\.?\\s*$`, 'i');
    const next = cur.replace(re, '').trimEnd();
    if (next !== cur) {
      cur = next;
      changed = true;
    }
  }
  const reColon = new RegExp(`:\\s*${esc}\\.?\\s*$`, 'i');
  const afterColon = cur.replace(reColon, '').trimEnd();
  if (afterColon !== cur) {
    cur = afterColon;
    changed = true;
  }
  if (changed) {
    const reBare = new RegExp(`\\s+${esc}\\.?\\s*$`, 'i');
    const afterBare = cur.replace(reBare, '').trimEnd();
    if (afterBare !== cur) {
      cur = afterBare;
    }
  }
  return changed && cur.length > 0 ? cur : undefined;
}

function artifactInlineDisplayBody(body: string, refs: ChatArtifactRef[]): string {
  const raw = body.trim();
  if (!raw) return body;

  if (refs.length === 1) {
    const shortened = stripEchoedResourceTitle(raw, refs[0].label, refs[0].kind);
    if (shortened !== undefined) return shortened;
  }

  if (refs.length === 2) {
    const dual = getDualWorkItemTitleIdRefs(refs);
    if (dual) {
      const shortened = stripEchoedResourceTitle(raw, dual[0].label, dual[0].kind);
      if (shortened !== undefined) return shortened;
    }
  }

  return body;
}

/**
 * Split assistant prose so title + bracketed id can be replaced by inline chips
 * (avoids duplicating the resource in plain text and chips).
 */
function splitDualWorkItemBody(
  bodyRaw: string,
  title: string,
  itemId: string,
  projectId?: string,
): { prefix: string; suffix: string } {
  const body = bodyRaw.trim();
  const t = title.trim();
  const id = itemId.trim();
  if (!t || !id || !body.includes(t)) {
    return { prefix: body, suffix: '' };
  }
  const idx = body.indexOf(t);
  const prefix = body.slice(0, idx).trimEnd();
  let after = body.slice(idx + t.length);
  after = after.replace(/^\s*/, '');
  if (after.startsWith('[')) {
    const close = after.indexOf(']');
    if (close > 0) {
      const inner = after.slice(1, close).trim();
      if (inner === id || inner.toLowerCase() === id.toLowerCase()) {
        after = after.slice(close + 1);
      }
    }
  }
  let suffix = after.trimStart();
  if (projectId) {
    const projRe = new RegExp(
      `^\\s*[-–]\\s*done\\s+in\\s+project\\s+${escapeRegExp(projectId.trim())}\\s*$`,
      'i',
    );
    suffix = suffix.replace(projRe, '').trim();
  } else {
    suffix = suffix.replace(/^[\s.:,;–-]+/, '').trim();
  }
  return { prefix, suffix };
}

/** Strip echoed title / id from body when split did not match (multi-line inventory, etc.). */
function stripEchoedWorkItemTitleAndId(body: string, title: string, itemId: string): string {
  let b = body;
  b = b.replace(new RegExp(`\\[\\s*${escapeRegExp(itemId.trim())}\\s*\\]`, 'gi'), '');
  const et = escapeRegExp(title.trim());
  b = b.replace(new RegExp(`(^|\\n)\\s*${et}\\s*`, 'm'), '$1');
  b = b.replace(new RegExp(`\\s*${et}\\s*`, 'g'), ' ');
  return b.replace(/\s{2,}/g, ' ').replace(/\n{2,}/g, '\n').trim();
}

function workItemHref(projectId?: string, boardId?: string, itemId?: string): string | undefined {
  if (projectId && boardId && itemId) {
    return `/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardId)}/items/${encodeURIComponent(itemId)}`;
  }
  return undefined;
}

const WIKI_ROUTE_DOMAINS = new Set(['infra', 'platform', 'ai-learning', 'research']);

function wikiPageHref(rec: Record<string, unknown>): string | undefined {
  const domain = firstPresent(rec, ['wiki_domain', 'domain', 'wikiDomain']);
  const path = firstPresent(rec, ['path', 'page_path', 'relative_path', 'slug', 'page_slug']);
  if (domain && path) {
    const d = domain.trim();
    const p = path.replace(/^\/+/, '');
    return `/wiki/${encodeURIComponent(d)}/${p}`;
  }
  if (path) {
    const trimmed = path.replace(/^\/+/, '');
    const seg = trimmed.split('/').filter(Boolean);
    if (seg.length >= 2 && WIKI_ROUTE_DOMAINS.has(seg[0])) {
      return `/wiki/${seg[0]}/${seg.slice(1).join('/')}`;
    }
  }
  if (domain && WIKI_ROUTE_DOMAINS.has(domain.trim())) {
    return `/wiki/${encodeURIComponent(domain.trim())}`;
  }
  return undefined;
}

function pushPlatformActionRefsFromData(data: Record<string, unknown>, message: ConversationMessage, out: ChatArtifactRef[]): void {
  if (data.success === false) return;
  let innerRaw = data.result;
  if (innerRaw && typeof innerRaw === 'object' && !Array.isArray(innerRaw)) {
    const wrap = innerRaw as Record<string, unknown>;
    if (
      wrap.result &&
      typeof wrap.result === 'object' &&
      !Array.isArray(wrap.result) &&
      !pickString(data.resource_type)
    ) {
      innerRaw = wrap.result;
    }
  }
  if (!innerRaw || typeof innerRaw !== 'object' || Array.isArray(innerRaw)) return;

  const rec = innerRaw as Record<string, unknown>;
  const rt = pickString(data.resource_type)?.toLowerCase();
  const metaProject = pickString(message.metadata?.project_id);

  const itemIdExplicit = firstPresent(rec, ['item_id', 'work_item_id']);
  const itemTypeField = pickString(rec.item_type);

  if (rt === 'work_item' || !!itemTypeField || !!itemIdExplicit) {
    const itemId = itemIdExplicit ?? (rt === 'work_item' ? pickString(rec.id) : undefined);
    if (!itemId) return;
    const boardId = firstPresent(rec, ['board_id']);
    const projectId = firstPresent(rec, ['project_id']) ?? metaProject;
    const title = firstPresent(rec, ['title', 'name']) ?? itemId;
    const href = workItemHref(projectId, boardId, itemId);
    const disabledReason =
      projectId && boardId
        ? undefined
        : 'Work item location needs a project and board context to open in the board drawer.';
    pushUnique(out, {
      key: `work_item:${itemId}:title`,
      kind: 'work_item',
      label: title,
      to: href,
      disabledReason,
      refRole: 'title',
    });
    if (href && title.trim() !== itemId.trim()) {
      pushUnique(out, {
        key: `work_item:${itemId}:id`,
        kind: 'work_item',
        label: itemId,
        to: href,
        disabledReason,
        refRole: 'id',
      });
    }
    return;
  }

  const projectIdForBoard = firstPresent(rec, ['project_id']) ?? metaProject;
  const boardIdField = firstPresent(rec, ['board_id']);
  if (
    rt === 'board' ||
    (!!boardIdField && !!projectIdForBoard && !itemTypeField && !itemIdExplicit)
  ) {
    const boardId = firstPresent(rec, ['board_id']) ?? (rt === 'board' ? pickString(rec.id) : undefined);
    const projectId = projectIdForBoard;
    const label = firstPresent(rec, ['name', 'title']) ?? boardId;
    if (boardId && projectId) {
      pushUnique(out, {
        key: `board:${boardId}`,
        kind: 'board',
        label: label ?? boardId,
        to: `/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardId)}`,
      });
    }
    return;
  }

  if (rt === 'project') {
    const projectId = firstPresent(rec, ['id', 'project_id']);
    const label = firstPresent(rec, ['name', 'title', 'slug']) ?? projectId;
    if (projectId) {
      pushUnique(out, {
        key: `project:${projectId}`,
        kind: 'project',
        label: label ?? projectId,
        to: `/projects/${encodeURIComponent(projectId)}`,
      });
    }
    return;
  }

  if (!boardIdField && !itemIdExplicit && !itemTypeField && !firstPresent(rec, ['org_id', 'organization_id'])) {
    const projectId = firstPresent(rec, ['id', 'project_id']);
    if (projectId && firstPresent(rec, ['name', 'title', 'slug'])) {
      const label = firstPresent(rec, ['name', 'title', 'slug']) ?? projectId;
      pushUnique(out, {
        key: `project:${projectId}:heuristic`,
        kind: 'project',
        label,
        to: `/projects/${encodeURIComponent(projectId)}`,
      });
      return;
    }
  }

  if (rt === 'org') {
    const orgId = firstPresent(rec, ['id', 'org_id']);
    const label = firstPresent(rec, ['name', 'title', 'slug']) ?? orgId ?? 'Organization';
    pushUnique(out, {
      key: `org:${orgId ?? 'unknown'}`,
      kind: 'org',
      label,
      to: '/orgs',
      disabledReason: orgId ? undefined : 'Open Organizations to locate this org.',
    });
    return;
  }

  const agentId = firstPresent(rec, ['agent_id']);
  if (agentId && (rt === 'agent' || rt === 'mcp_tool' || rec.slug != null || rec.agent_slug != null || rec.role != null)) {
    const label = firstPresent(rec, ['name', 'display_name', 'title']) ?? agentId;
    pushUnique(out, {
      key: `agent:${agentId}`,
      kind: 'agent',
      label,
      to: `/agents/${encodeURIComponent(agentId)}`,
    });
    return;
  }

  let runId = firstPresent(rec, ['run_id']);
  if (!runId && rt === 'run') runId = pickString(rec.id);
  if (runId) {
    const workItemId = firstPresent(rec, ['work_item_id', 'item_id']);
    const projectId = firstPresent(rec, ['project_id']) ?? metaProject;
    const boardId = firstPresent(rec, ['board_id']);
    const label = firstPresent(rec, ['summary', 'status', 'title', 'name']) ?? runId;
    const href = workItemId ? workItemHref(projectId, boardId, workItemId) : undefined;
    pushUnique(out, {
      key: `run:${runId}`,
      kind: 'run',
      label,
      to: href,
      disabledReason: href ? undefined : 'Open this run from its work item when project, board, and work item ids are available.',
    });
    return;
  }

  let behaviorId = firstPresent(rec, ['behavior_id']);
  if (!behaviorId && rt === 'behavior') behaviorId = pickString(rec.id);
  if (behaviorId && (rt === 'behavior' || pickString(rec.behavior_name))) {
    const label = firstPresent(rec, ['name', 'title', 'behavior_name']) ?? behaviorId;
    pushUnique(out, {
      key: `behavior:${behaviorId}`,
      kind: 'behavior',
      label,
      to: `/bci?behavior=${encodeURIComponent(behaviorId)}`,
    });
    return;
  }

  const hrefWiki = wikiPageHref(rec);
  const wikiKey = firstPresent(rec, ['page_id', 'wiki_page_id', 'path', 'slug']);
  if (hrefWiki || wikiKey) {
    const label =
      firstPresent(rec, ['title', 'name', 'page_title']) ?? firstPresent(rec, ['path', 'page_path', 'slug']) ?? 'Wiki page';
    pushUnique(out, {
      key: `wiki:${wikiKey ?? label}`,
      kind: 'wiki',
      label,
      to: hrefWiki,
      disabledReason: hrefWiki ? undefined : 'Wiki path was missing from the action result.',
    });
  }
}

function extractArtifactRefs(message: ConversationMessage): ChatArtifactRef[] {
  const out: ChatArtifactRef[] = [];
  const sp = (message.structured_payload ?? null) as Record<string, unknown> | null;
  const payloadType = pickString(sp?.type);

  if (payloadType === 'platform_action_result' && sp) {
    const data = (sp.data ?? {}) as Record<string, unknown>;
    pushPlatformActionRefsFromData(data, message, out);
  }

  const cardKind = pickString(sp?.card_kind);
  const rows = Array.isArray(sp?.rows) ? (sp.rows as Record<string, unknown>[]) : [];
  const qpPlan = (sp?.query_plan ?? null) as Record<string, unknown> | null;
  const isResourceAnalysisCount =
    cardKind === 'resource_analysis' && pickString(qpPlan?.intent) === 'count';

  if (cardKind === 'project_list') {
    rows.forEach((row, i) => {
      const id = firstPresent(row, ['id', 'project_id']);
      const label = firstPresent(row, ['label', 'name', 'title']) ?? id;
      if (id) {
        pushUnique(out, {
          key: `project:${id}:${i}`,
          kind: 'project',
          label: label ?? id,
          to: `/projects/${encodeURIComponent(id)}`,
        });
      }
    });
  }

  if (cardKind === 'board_list') {
    rows.forEach((row, i) => {
      const boardId = firstPresent(row, ['id', 'board_id']);
      const projectId = firstPresent(row, ['project_id']);
      const label = firstPresent(row, ['name', 'title']) ?? boardId;
      if (boardId && projectId) {
        pushUnique(out, {
          key: `board:${boardId}:${i}`,
          kind: 'board',
          label: label ?? boardId,
          to: `/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardId)}`,
        });
      }
    });
  }

  if (cardKind === 'work_item_list') {
    if (rows.length === 1) {
      const row = rows[0] as Record<string, unknown>;
      const itemId = firstPresent(row, ['id', 'item_id', 'work_item_id']);
      const projectId = firstPresent(row, ['project_id']);
      const boardId = firstPresent(row, ['board_id']);
      const label = firstPresent(row, ['title', 'name']) ?? itemId;
      const href = workItemHref(projectId, boardId, itemId);
      const disabledReason = href
        ? undefined
        : 'Open this work item from its board — board id was not included in the inventory row.';
      if (itemId && href && label && label.trim() !== itemId.trim()) {
        pushUnique(out, {
          key: `work_item:${itemId}:title`,
          kind: 'work_item',
          label: label ?? itemId,
          to: href,
          disabledReason,
          refRole: 'title',
        });
        pushUnique(out, {
          key: `work_item:${itemId}:id`,
          kind: 'work_item',
          label: itemId,
          to: href,
          disabledReason,
          refRole: 'id',
        });
      } else if (itemId) {
        pushUnique(out, {
          key: `work_item:${itemId}:0`,
          kind: 'work_item',
          label: label ?? itemId,
          to: href,
          disabledReason,
        });
      }
    } else {
      rows.forEach((row, i) => {
        const itemId = firstPresent(row, ['id', 'item_id', 'work_item_id']);
        const projectId = firstPresent(row, ['project_id']);
        const boardId = firstPresent(row, ['board_id']);
        const label = firstPresent(row, ['title', 'name']) ?? itemId;
        if (itemId) {
          const href = workItemHref(projectId, boardId, itemId);
          pushUnique(out, {
            key: `work_item:${itemId}:${i}`,
            kind: 'work_item',
            label: label ?? itemId,
            to: href,
            disabledReason: href ? undefined : 'Open this work item from its board — board id was not included in the inventory row.',
          });
        }
      });
    }
  }

  if (cardKind === 'agent_list' || cardKind === 'assignment') {
    rows.forEach((row, i) => {
      const agentId = firstPresent(row, ['id', 'agent_id']);
      const label = firstPresent(row, ['name', 'display_name', 'title']) ?? agentId;
      if (agentId) {
        pushUnique(out, {
          key: `agent:${agentId}:${i}`,
          kind: 'agent',
          label: label ?? agentId,
          to: `/agents/${encodeURIComponent(agentId)}`,
        });
      }
    });
  }

  if (cardKind === 'run_list') {
    rows.forEach((row, i) => {
      const runId = firstPresent(row, ['id', 'run_id']);
      const workItemId = firstPresent(row, ['work_item_id', 'item_id']);
      const projectId = firstPresent(row, ['project_id']);
      const boardId = firstPresent(row, ['board_id']);
      const label = firstPresent(row, ['summary', 'status', 'title']) ?? runId;
      if (runId) {
        const href = workItemId ? workItemHref(projectId, boardId, workItemId) : undefined;
        pushUnique(out, {
          key: `run:${runId}:${i}`,
          kind: 'run',
          label: label ?? runId,
          to: href,
          disabledReason: href
            ? undefined
            : 'Link this run from its work item when project, board, and work item ids are available.',
        });
      }
    });
  }

  if (cardKind === 'resource_analysis') {
    if (!isResourceAnalysisCount) {
      rows.forEach((row, i) => {
        pushResourceAnalysisRef(row, i, out);
      });
    }
    const wiRows = rows.filter((row) => {
      if (pickString(row.resource_type) !== 'work_item') return false;
      return !!(firstPresent(row, ['item_id', 'work_item_id']) ?? firstPresent(row, ['id']));
    });
    if (!isResourceAnalysisCount && wiRows.length === 1) {
      const row = wiRows[0] as Record<string, unknown>;
      const itemId =
        firstPresent(row, ['item_id', 'work_item_id']) ?? (pickString(row.resource_type) === 'work_item' ? firstPresent(row, ['id']) : undefined);
      const projectId = firstPresent(row, ['project_id']);
      const boardId = firstPresent(row, ['board_id']);
      const title =
        firstPresent(row, ['title', 'name', 'label', 'summary', 'path', 'email', 'id']) ??
        pickString(row.resource_type) ??
        'Resource';
      const href = workItemHref(projectId, boardId, itemId);
      if (itemId && href && title.trim() !== itemId.trim()) {
        const filtered = out.filter((r) => !r.key.startsWith(`resource_analysis:work_item:${itemId}:`));
        out.length = 0;
        out.push(...filtered);
        const disabledReason = projectId && boardId ? undefined : 'Open this work item from its board when project and board ids are available.';
        pushUnique(out, {
          key: `resource_analysis:work_item:${itemId}:title`,
          kind: 'work_item',
          label: title,
          to: href,
          disabledReason,
          refRole: 'title',
        });
        pushUnique(out, {
          key: `resource_analysis:work_item:${itemId}:id`,
          kind: 'work_item',
          label: itemId,
          to: href,
          disabledReason,
          refRole: 'id',
        });
      }
    }
  }

  if (cardKind === 'work_item') {
    const p = (sp ?? {}) as CardPayload;
    const itemId = firstPresent(p as Record<string, unknown>, ['work_item_id', 'item_id', 'id']);
    const projectId = firstPresent(p as Record<string, unknown>, ['project_id']);
    const boardId = firstPresent(p as Record<string, unknown>, ['board_id']);
    const label = firstPresent(p as Record<string, unknown>, ['title', 'name']) ?? itemId;
    if (itemId) {
      const href = workItemHref(projectId, boardId, itemId);
      const disabledReason = href ? undefined : 'Missing project or board id on this work item card payload.';
      if (href && label && label.trim() !== itemId.trim()) {
        pushUnique(out, {
          key: `work_item:${itemId}:card-title`,
          kind: 'work_item',
          label: label ?? itemId,
          to: href,
          disabledReason,
          refRole: 'title',
        });
        pushUnique(out, {
          key: `work_item:${itemId}:card-id`,
          kind: 'work_item',
          label: itemId,
          to: href,
          disabledReason,
          refRole: 'id',
        });
      } else {
        pushUnique(out, {
          key: `work_item:${itemId}:card`,
          kind: 'work_item',
          label: label ?? itemId,
          to: href,
          disabledReason,
        });
      }
    }
  }

  if (cardKind === 'run') {
    const p = (sp ?? {}) as CardPayload;
    const runId = firstPresent(p as Record<string, unknown>, ['run_id', 'id']);
    const workItemId = firstPresent(p as Record<string, unknown>, ['work_item_id', 'item_id']);
    const projectId = firstPresent(p as Record<string, unknown>, ['project_id']);
    const boardId = firstPresent(p as Record<string, unknown>, ['board_id']);
    const label = firstPresent(p as Record<string, unknown>, ['title', 'summary']) ?? runId;
    if (runId) {
      const href = workItemId ? workItemHref(projectId, boardId, workItemId) : undefined;
      pushUnique(out, {
        key: `run:${runId}:card`,
        kind: 'run',
        label: label ?? runId,
        to: href,
        disabledReason: href ? undefined : 'Open this run from its work item when ids are available.',
      });
    }
  }

  if (cardKind === 'direct_answer' && rows.length > 0) {
    rows.forEach((row, i) => {
      const projectId = firstPresent(row, ['project_id']);
      const boardId = firstPresent(row, ['board_id', 'id']);
      const agentId = firstPresent(row, ['agent_id', 'id']);
      const name = firstPresent(row, ['name', 'title', 'label']);
      if (agentId && (row.slug != null || row.agent_slug != null || row.role != null)) {
        pushUnique(out, {
          key: `agent:${agentId}:direct:${i}`,
          kind: 'agent',
          label: name ?? agentId,
          to: `/agents/${encodeURIComponent(agentId)}`,
        });
        return;
      }
      if (boardId && projectId && !row.agent_id) {
        pushUnique(out, {
          key: `board:${boardId}:direct:${i}`,
          kind: 'board',
          label: name ?? boardId,
          to: `/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardId)}`,
        });
        return;
      }
      const pid = firstPresent(row, ['id', 'project_id']);
      if (pid && (row.label != null || row.slug != null)) {
        pushUnique(out, {
          key: `project:${pid}:direct:${i}`,
          kind: 'project',
          label: name ?? pid,
          to: `/projects/${encodeURIComponent(pid)}`,
        });
      }
    });
  }

  const topWorkItem = pickString(message.work_item_id);
  if (topWorkItem && !isResourceAnalysisCount) {
    const hasWorkItemChipForId = out.some(
      (r) => r.kind === 'work_item' && r.key.startsWith(`work_item:${topWorkItem}:`),
    );
    if (!hasWorkItemChipForId) {
      const meta = (message.metadata ?? {}) as Record<string, unknown>;
      const projectId = firstPresent(meta, ['project_id']);
      const boardId = firstPresent(meta, ['board_id']);
      const href = workItemHref(projectId, boardId, topWorkItem);
      pushUnique(out, {
        key: `work_item:${topWorkItem}:top`,
        kind: 'work_item',
        label: topWorkItem,
        to: href,
        disabledReason: href ? undefined : 'Open from board context when project and board are known.',
      });
    }
  }

  const topBehavior = pickString(message.behavior_id);
  if (topBehavior) {
    pushUnique(out, {
      key: `behavior:${topBehavior}`,
      kind: 'behavior',
      label: topBehavior,
      to: `/bci?behavior=${encodeURIComponent(topBehavior)}`,
    });
  }

  return mergeArtifactRefsUnique(out, refsFromStructuredPayloadRows(sp));
}

function pushResourceAnalysisRef(row: Record<string, unknown>, i: number, out: ChatArtifactRef[]): void {
  const resourceType = pickString(row.resource_type);
  const label =
    firstPresent(row, ['title', 'name', 'label', 'summary', 'path', 'email', 'id']) ??
    resourceType ??
    'Resource';
  const projectId = firstPresent(row, ['project_id']);
  const boardId = firstPresent(row, ['board_id']);
  const itemId = firstPresent(row, ['item_id', 'work_item_id']) ?? (resourceType === 'work_item' ? firstPresent(row, ['id']) : undefined);
  if (itemId) {
    pushUnique(out, {
      key: `resource_analysis:work_item:${itemId}:${i}`,
      kind: 'work_item',
      label,
      to: workItemHref(projectId, boardId, itemId),
      disabledReason: projectId && boardId ? undefined : 'Open this work item from its board when project and board ids are available.',
    });
    return;
  }

  const projectResourceId = resourceType === 'project' ? firstPresent(row, ['project_id', 'id']) : undefined;
  if (projectResourceId) {
    pushUnique(out, {
      key: `resource_analysis:project:${projectResourceId}:${i}`,
      kind: 'project',
      label,
      to: `/projects/${encodeURIComponent(projectResourceId)}`,
    });
    return;
  }

  const boardResourceId = resourceType === 'board' ? firstPresent(row, ['board_id', 'id']) : undefined;
  if (boardResourceId && projectId) {
    pushUnique(out, {
      key: `resource_analysis:board:${boardResourceId}:${i}`,
      kind: 'board',
      label,
      to: `/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardResourceId)}`,
    });
    return;
  }

  const runResourceId = resourceType === 'run' ? firstPresent(row, ['run_id', 'id']) : undefined;
  if (runResourceId) {
    pushUnique(out, {
      key: `resource_analysis:run:${runResourceId}:${i}`,
      kind: 'run',
      label,
      disabledReason: 'Open this run from its related work item when that context is available.',
    });
    return;
  }

  const wikiHref = wikiPageHref(row);
  if (wikiHref) {
    pushUnique(out, {
      key: `resource_analysis:wiki:${wikiHref}:${i}`,
      kind: 'wiki',
      label,
      to: wikiHref,
    });
    return;
  }

  const id = firstPresent(row, ['id', 'agent_id', 'behavior_id', 'credential_id', 'conversation_id', 'message_id', 'path']);
  if (id) {
    pushUnique(out, {
      key: `resource_analysis:${resourceType ?? 'resource'}:${id}:${i}`,
      kind: resourceType === 'agent' ? 'agent' : resourceType === 'behavior' ? 'behavior' : 'resource',
      label,
      disabledReason: 'This resource is part of the analyst result but does not have a direct chat deep link yet.',
    });
  }
}

function findProjectIdForWorkItem(message: ConversationMessage, itemId: string): string | undefined {
  const sp = (message.structured_payload ?? null) as Record<string, unknown> | null;
  if (!sp) return undefined;
  const rows = Array.isArray(sp.rows) ? (sp.rows as Record<string, unknown>[]) : [];
  for (const row of rows) {
    const rid = firstPresent(row, ['item_id', 'work_item_id', 'id']);
    if (rid === itemId) return firstPresent(row, ['project_id']);
  }
  const payloadType = pickString(sp.type);
  if (payloadType === 'platform_action_result') {
    const data = (sp.data ?? {}) as Record<string, unknown>;
    let innerRaw: unknown = data.result;
    if (innerRaw && typeof innerRaw === 'object' && !Array.isArray(innerRaw)) {
      const wrap = innerRaw as Record<string, unknown>;
      if (
        wrap.result &&
        typeof wrap.result === 'object' &&
        !Array.isArray(wrap.result) &&
        !pickString(data.resource_type)
      ) {
        innerRaw = wrap.result;
      }
    }
    if (innerRaw && typeof innerRaw === 'object' && !Array.isArray(innerRaw)) {
      const rec = innerRaw as Record<string, unknown>;
      const iid = firstPresent(rec, ['item_id', 'work_item_id']) ?? pickString(rec.id);
      if (iid === itemId) return firstPresent(rec, ['project_id']);
    }
  }
  if (pickString(sp.card_kind) === 'work_item') {
    const rid = firstPresent(sp as Record<string, unknown>, ['work_item_id', 'item_id', 'id']);
    if (rid === itemId) return firstPresent(sp as Record<string, unknown>, ['project_id']);
  }
  return undefined;
}

function AnalysisRunCellsBlock({ message }: { message: ConversationMessage }) {
  const sp = (message.structured_payload ?? null) as Record<string, unknown> | null;
  const run = sp?.analysis_run as Record<string, unknown> | undefined;
  const cells = run?.cells;
  if (!Array.isArray(cells) || cells.length === 0) {
    return null;
  }
  return (
    <aside className="msg-analysis-run" aria-label="Analysis steps">
      <div className="msg-analysis-run__heading">Analysis steps</div>
      <ol className="msg-analysis-run__list">
        {cells.map((cell, idx) => {
          const rec = cell as Record<string, unknown>;
          const status = pickString(rec.status) ?? '—';
          const q = pickString(rec.input) ?? '—';
          return (
            <li key={pickString(rec.id) ?? `step-${idx}`} className="msg-analysis-run__item">
              <span className="msg-analysis-run__query">{q}</span>
              {' '}
              <span className="msg-analysis-run__status">({status})</span>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}

function ResourceAnalysisInsightsBlock({ message }: { message: ConversationMessage }) {
  const sp = (message.structured_payload ?? null) as Record<string, unknown> | null;
  if (pickString(sp?.card_kind) !== 'resource_analysis') {
    return null;
  }
  const insights = sp?.insights as Record<string, unknown> | undefined;
  const byType = insights?.by_item_type;
  if (!Array.isArray(byType) || byType.length === 0) {
    return null;
  }
  return (
    <aside className="msg-resource-insights" aria-label="Work item types in scope">
      <div className="msg-resource-insights__heading">Types in this scope</div>
      <ul className="msg-resource-insights__list">
        {byType.map((row, idx) => {
          const rec = row as Record<string, unknown>;
          const label = pickString(rec.item_type_label) ?? pickString(rec.item_type) ?? '—';
          const rawCount = rec.count;
          const count = typeof rawCount === 'number' ? rawCount : Number(rawCount);
          return (
            <li key={`${label}-${idx}`} className="msg-resource-insights__row">
              <span className="msg-resource-insights__type">{label}</span>
              <span className="msg-resource-insights__count" aria-label={`count ${count}`}>
                {Number.isFinite(count) ? count : '—'}
              </span>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

const InlineArtifactBody = memo(function InlineArtifactBody({
  message,
  displayBody,
  refs,
}: {
  message: ConversationMessage;
  displayBody: string;
  refs: ChatArtifactRef[];
}) {
  const dual = getDualWorkItemTitleIdRefs(refs);
  const trimmed = displayBody.trim();
  if (dual) {
    const [titleRef, idRef] = dual;
    const itemId = idRef.label;
    const title = titleRef.label;
    const projectId = findProjectIdForWorkItem(message, itemId);
    let prefix = '';
    let suffix = '';
    if (trimmed.length > 0) {
      const split = splitDualWorkItemBody(displayBody, title, itemId, projectId);
      prefix = split.prefix;
      suffix = split.suffix;
      const merged = `${prefix}${suffix}`.trim();
      if (merged.includes(title) || merged.toLowerCase().includes(itemId.toLowerCase())) {
        prefix = stripEchoedWorkItemTitleAndId(displayBody, title, itemId);
        suffix = projectId ? ` - done in project ${projectId}` : '';
      }
    }
    const restRefs = refs.filter((r) => r.key !== titleRef.key && r.key !== idRef.key);
    return (
      <div className="msg-artifact-inline msg-artifact-inline--interleaved" data-testid="artifact-inline-flow">
        {prefix.trim().length > 0 ? (
          <span className="msg-markdown msg-markdown--artifact-inline msg-markdown--interleaved">
            <ChatMarkdownWithArtifacts markdown={prefix.trim()} refs={refs} />
          </span>
        ) : null}
        {prefix.trim().length > 0 ? <span className="msg-artifact-inline-gap" aria-hidden /> : null}
        <span className="msg-artifact-inline-chips" role="group" aria-label="Referenced work item">
          <ArtifactChipLink artifact={titleRef} listItem={false} />
          <span className="msg-artifact-inline-gap" aria-hidden />
          <ArtifactChipLink artifact={idRef} listItem={false} />
        </span>
        {suffix.trim().length > 0 ? (
          <span className="msg-markdown msg-markdown--artifact-inline msg-markdown--interleaved">
            <ChatMarkdownWithArtifacts markdown={suffix.trim()} refs={refs} />
          </span>
        ) : null}
        {restRefs.length > 0 ? <ArtifactChipRow refs={restRefs} /> : null}
        <ResourceAnalysisInsightsBlock message={message} />
        <AnalysisRunCellsBlock message={message} />
      </div>
    );
  }
  return (
    <div className="msg-artifact-inline">
      {trimmed.length > 0 ? (
        <div className="msg-markdown msg-markdown--artifact-inline">
          <ChatMarkdownWithArtifacts markdown={displayBody} refs={refs} />
        </div>
      ) : null}
      <ArtifactChipRow refs={refs} />
      <ResourceAnalysisInsightsBlock message={message} />
      <AnalysisRunCellsBlock message={message} />
    </div>
  );
});

const ArtifactInlineMessage = memo(function ArtifactInlineMessage({ message }: { message: ConversationMessage }) {
  const refs = useMemo(() => extractArtifactRefs(message), [message]);
  const sp = (message.structured_payload ?? null) as Record<string, unknown> | null;
  const fallbackBody =
    pickString(sp?.summary) ||
    pickString(sp?.title) ||
    '';

  const body = (message.content && message.content.trim().length > 0 ? message.content : fallbackBody) ?? '';
  const displayBody = useMemo(() => artifactInlineDisplayBody(body, refs), [body, refs]);

  if (refs.length === 0 && !displayBody.trim()) {
    return (
      <div className="msg-body-empty" role="status">
        <span className="msg-body-empty-text">No message content was returned for this reply.</span>
      </div>
    );
  }

  return <InlineArtifactBody message={message} displayBody={displayBody} refs={refs} />;
});

const PlainMessageWithArtifacts = memo(function PlainMessageWithArtifacts({ message }: { message: ConversationMessage }) {
  const refs = useMemo(() => extractArtifactRefs(message), [message]);
  const body = message.content ?? '';
  const displayBody = useMemo(() => artifactInlineDisplayBody(body, refs), [body, refs]);
  if (refs.length === 0) {
    return (
      <div className="msg-markdown">
        <ChatMarkdownWithArtifacts markdown={body} refs={refs} />
      </div>
    );
  }
  return <InlineArtifactBody message={message} displayBody={displayBody} refs={refs} />;
});

const ARTIFACT_INLINE_CARD_KINDS = new Set([
  'direct_answer',
  'assignment',
  'project_list',
  'board_list',
  'agent_list',
  'run_list',
  'work_item_list',
  'work_item',
  'run',
  /** Read-only inventory / analyst results — same inline text + chip pattern as other artifacts */
  'resource_analysis',
]);

const PLATFORM_ARTIFACT_PAYLOAD_TYPES = new Set(['platform_action_result']);

// ── Message Content Router ───────────────────────────────────────────────────

function MessageContent({
  message,
  msgType,
}: {
  message: ConversationMessage;
  msgType: ConversationMessage['message_type'] | null | undefined;
}) {
  const sp = message.structured_payload as Record<string, unknown> | undefined;
  const cardKind = String(sp?.card_kind ?? '');
  const payloadType = typeof sp?.type === 'string' ? String(sp.type) : '';

  if (ARTIFACT_INLINE_CARD_KINDS.has(cardKind) || PLATFORM_ARTIFACT_PAYLOAD_TYPES.has(payloadType)) {
    return <ArtifactInlineMessage message={message} />;
  }

  if (cardKind === 'plan') {
    return <PlanArtifactCard payload={message.structured_payload} />;
  }
  if (cardKind === 'recovery') {
    return <RecoveryArtifactCard payload={message.structured_payload} />;
  }

  switch (msgType) {
    case MessageType.StatusCard:
      return <StatusCard payload={message.structured_payload} />;
    case MessageType.BlockerCard:
      return <BlockerCard payload={message.structured_payload} />;
    case MessageType.ProgressCard:
      return <ProgressCard payload={message.structured_payload} />;
    case MessageType.CodeBlock:
      return <CodeBlockCard content={message.content} payload={message.structured_payload} />;
    case MessageType.RunSummary:
      return <RunSummaryCard payload={message.structured_payload} />;
    default:
      return <PlainMessageWithArtifacts message={message} />;
  }
}

// ── Structured Cards ─────────────────────────────────────────────────────────

interface CardPayload {
  title?: string;
  summary?: string;
  status?: string;
  icon?: string;
  run_id?: string;
  percentage?: number;
  step_current?: number;
  step_total?: number;
  eta?: string;
  language?: string;
  code?: string;
  card_kind?: string;
  priority?: string;
  assignee?: string;
  agent?: string;
  branch?: string;
  phase?: string;
  queue_state?: string;
  recent_activity?: string;
  progress_pct?: number;
  completion_summary?: string;
  plan_artifact_id?: string;
  work_item_id?: string;
  cta_label?: string;
  secondary_cta_label?: string;
  rows?: Array<Record<string, unknown>>;
  trace_summary?: Record<string, unknown>;
  knowledge_retrieval?: Record<string, unknown>;
  [key: string]: unknown;
}

function ArtifactActions({
  primary,
  secondary,
}: {
  primary?: string;
  secondary?: string;
}) {
  if (!primary && !secondary) return null;
  return (
    <div className="msg-artifact-actions">
      {primary && <button type="button" className="msg-card-cta pressable">{primary}</button>}
      {secondary && <button type="button" className="msg-card-cta msg-card-cta--secondary pressable">{secondary}</button>}
    </div>
  );
}

function PlanArtifactCard({ payload }: { payload?: Record<string, unknown> | null }) {
  const p = (payload ?? {}) as CardPayload;
  return (
    <article className="msg-artifact-card msg-artifact-card--plan" aria-label={`Plan ${p.plan_artifact_id ?? p.title ?? ''}`}>
      <div className="msg-artifact-kicker">Plan</div>
      <div className="msg-artifact-title">{p.title ?? 'Plan artifact'}</div>
      {p.summary && <div className="msg-artifact-summary">{p.summary}</div>}
      <div className="msg-artifact-meta">
        {p.status && <span>Status: {p.status}</span>}
        {p.plan_artifact_id && <span>{p.plan_artifact_id}</span>}
      </div>
      <ArtifactActions primary={p.cta_label ?? 'Review plan'} secondary={p.secondary_cta_label ?? 'Revise'} />
    </article>
  );
}

function RecoveryArtifactCard({ payload }: { payload?: Record<string, unknown> | null }) {
  const p = (payload ?? {}) as CardPayload;
  return (
    <article className="msg-artifact-card msg-artifact-card--recovery" aria-label={`Recovery action ${p.title ?? ''}`}>
      <div className="msg-artifact-kicker">Needs attention</div>
      <div className="msg-artifact-title">{p.title ?? 'Action failed'}</div>
      {p.summary && <div className="msg-artifact-summary">{p.summary}</div>}
      <ArtifactActions primary={p.cta_label ?? 'Retry'} secondary={p.secondary_cta_label ?? 'Show details'} />
    </article>
  );
}

function StatusCard({ payload }: { payload?: Record<string, unknown> | null }) {
  const p = (payload ?? {}) as CardPayload;
  return (
    <div className="msg-card msg-card--status">
      <div className="msg-card-accent msg-card-accent--green" />
      <div className="msg-card-body">
        <div className="msg-card-title">{p.title ?? 'Status update'}</div>
        {p.summary && <div className="msg-card-summary">{p.summary}</div>}
        {p.run_id && (
          <span className="msg-card-link">View run →</span>
        )}
      </div>
    </div>
  );
}

function BlockerCard({ payload }: { payload?: Record<string, unknown> | null }) {
  const p = (payload ?? {}) as CardPayload;
  const isError = p.status === 'error' || p.status === 'blocked';
  return (
    <div className={`msg-card ${isError ? 'msg-card--error' : 'msg-card--warning'}`}>
      <div className={`msg-card-accent ${isError ? 'msg-card-accent--red' : 'msg-card-accent--amber'}`} />
      <div className="msg-card-body">
        <div className="msg-card-title">{p.title ?? 'Blocker'}</div>
        {p.summary && <div className="msg-card-summary">{p.summary}</div>}
        <button type="button" className="msg-card-cta pressable">Help resolve</button>
      </div>
    </div>
  );
}

function ProgressCard({ payload }: { payload?: Record<string, unknown> | null }) {
  const p = (payload ?? {}) as CardPayload;
  const pct = typeof p.percentage === 'number' ? Math.min(100, Math.max(0, p.percentage)) : 0;
  return (
    <div className="msg-card msg-card--progress">
      <div className="msg-card-body">
        <div className="msg-card-title">{p.title ?? 'Progress'}</div>
        <div className="msg-progress-bar-track">
          <div className="msg-progress-bar-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="msg-progress-meta">
          <span>{pct}%</span>
          {p.step_current != null && p.step_total != null && (
            <span>Step {p.step_current}/{p.step_total}</span>
          )}
          {p.eta && <span>ETA: {p.eta}</span>}
        </div>
      </div>
    </div>
  );
}

function CodeBlockCard({ content, payload }: { content?: string | null; payload?: Record<string, unknown> | null }) {
  const p = (payload ?? {}) as CardPayload;
  const code = p.code ?? content ?? '';
  const lang = p.language ?? '';
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [code]);

  return (
    <div className="msg-code-block">
      <div className="msg-code-header">
        {lang && <span className="msg-code-lang">{lang}</span>}
        <button type="button" className="msg-code-copy pressable" onClick={handleCopy}>
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre className="msg-code-pre"><code>{code}</code></pre>
    </div>
  );
}

function RunSummaryCard({ payload }: { payload?: Record<string, unknown> | null }) {
  const p = (payload ?? {}) as CardPayload;
  const ts = p.trace_summary;
  const trace =
    ts && typeof ts === 'object' && !Array.isArray(ts) ? (ts as Record<string, unknown>) : null;
  const krRaw = p.knowledge_retrieval ?? trace?.knowledge_retrieval;
  const knowledgeSlice =
    krRaw && typeof krRaw === 'object' && !Array.isArray(krRaw) ? (krRaw as Record<string, unknown>) : null;
  return (
    <div className="msg-card msg-card--status">
      <div className="msg-card-accent msg-card-accent--blue" />
      <div className="msg-card-body">
        <div className="msg-card-title">{p.title ?? 'Run Summary'}</div>
        {p.summary && <div className="msg-card-summary">{p.summary}</div>}
        <KnowledgeRetrievalSummary data={knowledgeSlice} className="msg-run-summary-knowledge" />
        {p.run_id && (
          <span className="msg-card-link">View full run →</span>
        )}
      </div>
    </div>
  );
}

// ── ReactionBar ──────────────────────────────────────────────────────────────

function ReactionBar({
  reactions,
  currentUserId,
  onToggle,
}: {
  reactions: ConversationReaction[];
  currentUserId?: string;
  onToggle: (emoji: string) => void;
}) {
  const groups = useMemo(() => {
    const map = new Map<string, { emoji: string; count: number; hasOwn: boolean }>();
    for (const r of reactions) {
      const existing = map.get(r.emoji);
      if (existing) {
        existing.count++;
        if (r.actor_id === currentUserId) existing.hasOwn = true;
      } else {
        map.set(r.emoji, { emoji: r.emoji, count: 1, hasOwn: r.actor_id === currentUserId });
      }
    }
    return Array.from(map.values());
  }, [reactions, currentUserId]);

  return (
    <div className="msg-reaction-bar">
      {groups.map((g) => (
        <button
          key={g.emoji}
          type="button"
          className={`msg-reaction-chip ${g.hasOwn ? 'msg-reaction-chip--active' : ''}`}
          onClick={() => onToggle(g.emoji)}
        >
          <span className="msg-reaction-emoji">{g.emoji}</span>
          <span className="msg-reaction-count">{g.count}</span>
        </button>
      ))}
    </div>
  );
}

// ── Inline SVG Icons ─────────────────────────────────────────────────────────

function ReplyIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true" className="msg-action-icon">
      <path d="M6 4L2 8l4 4" />
      <path d="M2 8h8a4 4 0 0 1 4 4v1" />
    </svg>
  );
}

function EmojiIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true" className="msg-action-icon">
      <circle cx="8" cy="8" r="6" />
      <path d="M5.5 6.5v.5M10.5 6.5v.5" />
      <path d="M5.5 9.5a3 3 0 0 0 5 0" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true" className="msg-action-icon">
      <path d="M11.5 2.5l2 2L5 13H3v-2l8.5-8.5z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true" className="msg-action-icon">
      <path d="M3 4h10M6 4V3h4v1M5 4v8a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1V4" />
    </svg>
  );
}
