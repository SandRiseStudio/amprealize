/**
 * MessageList — virtualized reverse-scroll message list.
 *
 * Uses @tanstack/react-virtual for efficient rendering of large message lists.
 * Groups consecutive same-sender messages within 5 minutes.
 * Includes DateSeparator, UnreadDivider, and scroll-to-bottom FAB.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { chatLoadBenchThreadFirstPaint, isChatLoadBenchEnabled, useInfiniteMessages } from '../../api/conversations';
import type { ConversationMessage } from '../../lib/collab-client';
import { MessageBubble } from './MessageBubble';
import { StreamingMessage } from './StreamingMessage';

// ── Types ────────────────────────────────────────────────────────────────────

export interface MessageListProps {
  conversationId: string;
  currentUserId?: string;
  streamingMessageId?: string | null;
  onStreamingComplete?: () => void;
  lastReadMessageId?: string | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const GROUPING_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes

/** REST returns newest-first pages; chat UI is oldest → newest (newest at bottom). */
function sortMessagesChronological(messages: ConversationMessage[]): ConversationMessage[] {
  return [...messages].sort((a, b) => {
    const ta = new Date(a.created_at ?? 0).getTime();
    const tb = new Date(b.created_at ?? 0).getTime();
    if (ta !== tb) return ta - tb;
    return a.id.localeCompare(b.id);
  });
}

export function isPersistedAssistantStreamMessage(
  message: ConversationMessage,
  streamingMessageId: string | null | undefined,
): boolean {
  if (!streamingMessageId || message.sender_type === 'user') return false;
  const persistedStreamId = message.metadata?.stream_message_id;
  return message.id === streamingMessageId || persistedStreamId === streamingMessageId;
}

interface MessageRow {
  kind: 'message';
  message: ConversationMessage;
  isFirstInGroup: boolean;
  isLastInGroup: boolean;
}

interface DateRow {
  kind: 'date';
  label: string;
  dateKey: string;
}

interface UnreadRow {
  kind: 'unread';
}

type VirtualRow = MessageRow | DateRow | UnreadRow;

function formatDateSeparator(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();

  if (isToday) return 'Today';
  if (isYesterday) return 'Yesterday';
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

function buildRows(
  messages: ConversationMessage[],
  lastReadMessageId: string | null | undefined,
): VirtualRow[] {
  const rows: VirtualRow[] = [];
  let lastDateKey = '';
  let unreadInserted = false;

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    const dateKey = (msg.created_at ?? '').slice(0, 10);

    // Date separator
    if (dateKey && dateKey !== lastDateKey) {
      rows.push({ kind: 'date', label: formatDateSeparator(msg.created_at ?? ''), dateKey });
      lastDateKey = dateKey;
    }

    // Unread divider (insert before first message after last read)
    if (!unreadInserted && lastReadMessageId && i > 0) {
      const prev = messages[i - 1];
      if (prev.id === lastReadMessageId) {
        rows.push({ kind: 'unread' });
        unreadInserted = true;
      }
    }

    // Message grouping
    const prev = i > 0 ? messages[i - 1] : null;
    const next = i < messages.length - 1 ? messages[i + 1] : null;
    const isSameSenderAsPrev =
      prev &&
      prev.sender_id === msg.sender_id &&
      msg.created_at &&
      prev.created_at &&
      new Date(msg.created_at).getTime() - new Date(prev.created_at).getTime() < GROUPING_THRESHOLD_MS;
    const isSameSenderAsNext =
      next &&
      next.sender_id === msg.sender_id &&
      next.created_at &&
      msg.created_at &&
      new Date(next.created_at).getTime() - new Date(msg.created_at).getTime() < GROUPING_THRESHOLD_MS;

    rows.push({
      kind: 'message',
      message: msg,
      isFirstInGroup: !isSameSenderAsPrev,
      isLastInGroup: !isSameSenderAsNext,
    });
  }

  return rows;
}

// ── Component ────────────────────────────────────────────────────────────────

export const MessageList = memo(function MessageList({
  conversationId,
  currentUserId,
  streamingMessageId,
  onStreamingComplete,
  lastReadMessageId,
}: MessageListProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const wasAtBottomRef = useRef(true);
  const threadBenchStartRef = useRef(0);
  const threadFirstPaintLoggedRef = useRef<string | null>(null);
  /** Blocks history prefetch while scrollTop is still at "top" before initial scroll-to-bottom. */
  const suppressOlderPrefetchRef = useRef(true);

  const {
    data: infiniteData,
    isLoading,
    fetchNextPage,
    hasNextPage: hasNextPageRaw,
    isFetchingNextPage,
  } = useInfiniteMessages({ conversationId });

  useEffect(() => {
    threadBenchStartRef.current = performance.now();
    threadFirstPaintLoggedRef.current = null;
    suppressOlderPrefetchRef.current = true;
  }, [conversationId]);

  useEffect(() => {
    if (!isChatLoadBenchEnabled()) return;
    if (isLoading) return;
    if (threadFirstPaintLoggedRef.current === conversationId) return;
    threadFirstPaintLoggedRef.current = conversationId;
    const messageCount = (infiniteData?.pages ?? []).flatMap((p) => p.items).length;
    chatLoadBenchThreadFirstPaint(conversationId, {
      conversation_id: conversationId,
      duration_ms: Number((performance.now() - threadBenchStartRef.current).toFixed(2)),
      message_count: messageCount,
      empty_thread: messageCount === 0,
    });
  }, [isLoading, conversationId, infiniteData]);

  const hasNextPage = hasNextPageRaw ?? false;
  const allMessages = useMemo(
    () => sortMessagesChronological(infiniteData?.pages.flatMap((p) => p.items) ?? []),
    [infiniteData],
  );
  const hasPersistedStreamingMessage = useMemo(() => {
    if (!streamingMessageId) return false;
    return allMessages.some((message) => isPersistedAssistantStreamMessage(message, streamingMessageId));
  }, [allMessages, streamingMessageId]);

  /** Fire `onStreamingComplete` once per `streamingMessageId` when the assistant row lands (avoids effect churn from unstable parent callbacks and transient cache flicker). */
  const streamCompleteCursorRef = useRef<{ streamId: string | null | undefined; fired: boolean }>({
    streamId: undefined,
    fired: false,
  });

  useEffect(() => {
    const sid = streamingMessageId;
    if (sid !== streamCompleteCursorRef.current.streamId) {
      streamCompleteCursorRef.current = { streamId: sid, fired: false };
    }
    if (!sid || !hasPersistedStreamingMessage || streamCompleteCursorRef.current.fired) {
      return;
    }
    streamCompleteCursorRef.current.fired = true;
    onStreamingComplete?.();
  }, [hasPersistedStreamingMessage, streamingMessageId, onStreamingComplete]);

  const visibleStreamingMessageId = hasPersistedStreamingMessage ? null : streamingMessageId;

  const rows = useMemo(
    () => buildRows(allMessages, lastReadMessageId),
    [allMessages, lastReadMessageId],
  );

  // Add streaming placeholder at end
  const rowsWithStreaming = useMemo(() => {
    if (!visibleStreamingMessageId) return rows;
    return [...rows, { kind: 'streaming' as const, messageId: visibleStreamingMessageId }];
  }, [rows, visibleStreamingMessageId]);

  type RowItem = VirtualRow | { kind: 'streaming'; messageId: string };

  // eslint-disable-next-line -- useVirtualizer returns non-memoizable functions; React Compiler will skip this component
  const virtualizer = useVirtualizer({
    count: rowsWithStreaming.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const row = rowsWithStreaming[index] as RowItem;
      if (row.kind === 'date') return 32;
      if (row.kind === 'unread') return 28;
      if (row.kind === 'streaming') return 60;
      return row.isFirstInGroup ? 52 : 32;
    },
    overscan: 8,
  });

  // Scroll to bottom on new messages (if already at bottom); then allow "load older" scroll handling.
  useEffect(() => {
    if (rowsWithStreaming.length === 0) {
      suppressOlderPrefetchRef.current = false;
      return;
    }
    if (wasAtBottomRef.current) {
      virtualizer.scrollToIndex(rowsWithStreaming.length - 1, { align: 'end', behavior: 'smooth' });
    }
    let innerFrame = 0;
    const outerFrame = requestAnimationFrame(() => {
      innerFrame = requestAnimationFrame(() => {
        suppressOlderPrefetchRef.current = false;
      });
    });
    return () => {
      cancelAnimationFrame(outerFrame);
      cancelAnimationFrame(innerFrame);
    };
  }, [rowsWithStreaming.length, virtualizer]);

  // Track scroll position
  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const atBottom = distanceFromBottom < 40;
    setIsAtBottom(atBottom);
    wasAtBottomRef.current = atBottom;

    // Load more on scroll to top (skip until initial scroll-to-bottom has settled)
    if (suppressOlderPrefetchRef.current) return;
    if (el.scrollTop < 60 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const scrollToBottom = useCallback(() => {
    virtualizer.scrollToIndex(rowsWithStreaming.length - 1, { align: 'end', behavior: 'smooth' });
  }, [virtualizer, rowsWithStreaming.length]);

  if (isLoading) {
    return (
      <div
        className="msg-list-loading"
        role="status"
        aria-busy="true"
        aria-label="Loading messages"
      >
        <div className="msg-list-spinner" aria-hidden />
      </div>
    );
  }

  if (allMessages.length === 0 && !visibleStreamingMessageId) {
    return (
      <div className="msg-list-empty">
        <span className="msg-list-empty-label">No messages yet</span>
        <span className="msg-list-empty-hint">Send a message to start the conversation</span>
      </div>
    );
  }

  return (
    <div className="msg-list-wrapper">
      <div
        ref={parentRef}
        className="msg-list-scroll-area"
        onScroll={handleScroll}
      >
        <div
          style={{
            height: virtualizer.getTotalSize(),
            width: '100%',
            position: 'relative',
          }}
        >
          {virtualizer.getVirtualItems().map((virtualItem) => {
            const row = rowsWithStreaming[virtualItem.index] as RowItem;

            return (
              <div
                key={virtualItem.key}
                data-index={virtualItem.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                {row.kind === 'date' && (
                  <DateSeparator label={row.label} />
                )}
                {row.kind === 'unread' && (
                  <UnreadDivider />
                )}
                {row.kind === 'message' && (
                  <MessageBubble
                    message={row.message}
                    isFirstInGroup={row.isFirstInGroup}
                    isOwn={row.message.sender_id === currentUserId}
                    conversationId={conversationId}
                  />
                )}
                {row.kind === 'streaming' && (
                  <StreamingMessage
                    conversationId={conversationId}
                    messageId={row.messageId}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Scroll-to-bottom FAB */}
      {!isAtBottom && (
        <button
          type="button"
          className="msg-list-scroll-fab pressable"
          onClick={scrollToBottom}
          aria-label="Scroll to bottom"
          data-haptic="light"
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
            <path d="M8 3v10M4 9l4 4 4-4" />
          </svg>
        </button>
      )}
    </div>
  );
});

// ── Sub-components ───────────────────────────────────────────────────────────

function DateSeparator({ label }: { label: string }) {
  return (
    <div className="message-date-separator" role="separator" aria-label={label}>
      <span className="message-date-separator-line" />
      <span className="message-date-separator-label">{label}</span>
      <span className="message-date-separator-line" />
    </div>
  );
}

function UnreadDivider() {
  return (
    <div className="message-unread-divider" role="separator" aria-label="New messages">
      <span className="message-unread-divider-line" />
      <span className="message-unread-divider-label">New messages</span>
      <span className="message-unread-divider-line" />
    </div>
  );
}
