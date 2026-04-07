/**
 * MessageList — virtualized reverse-scroll message list.
 *
 * Uses @tanstack/react-virtual for efficient rendering of large message lists.
 * Groups consecutive same-sender messages within 5 minutes.
 * Includes DateSeparator, UnreadDivider, and scroll-to-bottom FAB.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useInfiniteMessages } from '../../api/conversations';
import type { ConversationMessage } from '../../lib/collab-client';
import { MessageBubble } from './MessageBubble';
import { StreamingMessage } from './StreamingMessage';

// ── Types ────────────────────────────────────────────────────────────────────

export interface MessageListProps {
  conversationId: string;
  currentUserId?: string;
  streamingMessageId?: string | null;
  lastReadMessageId?: string | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const GROUPING_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes

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
  lastReadMessageId,
}: MessageListProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const wasAtBottomRef = useRef(true);

  const {
    data: infiniteData,
    isLoading,
    fetchNextPage,
    hasNextPage: hasNextPageRaw,
    isFetchingNextPage,
  } = useInfiniteMessages({ conversationId });

  const hasNextPage = hasNextPageRaw ?? false;
  const allMessages = useMemo(
    () => infiniteData?.pages.flatMap((p) => p.items) ?? [],
    [infiniteData],
  );

  const rows = useMemo(
    () => buildRows(allMessages, lastReadMessageId),
    [allMessages, lastReadMessageId],
  );

  // Add streaming placeholder at end
  const rowsWithStreaming = useMemo(() => {
    if (!streamingMessageId) return rows;
    return [...rows, { kind: 'streaming' as const, messageId: streamingMessageId }];
  }, [rows, streamingMessageId]);

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

  // Scroll to bottom on new messages (if already at bottom)
  useEffect(() => {
    if (wasAtBottomRef.current && rowsWithStreaming.length > 0) {
      virtualizer.scrollToIndex(rowsWithStreaming.length - 1, { align: 'end', behavior: 'smooth' });
    }
  }, [rowsWithStreaming.length, virtualizer]);

  // Track scroll position
  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const atBottom = distanceFromBottom < 40;
    setIsAtBottom(atBottom);
    wasAtBottomRef.current = atBottom;

    // Load more on scroll to top
    if (el.scrollTop < 60 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const scrollToBottom = useCallback(() => {
    virtualizer.scrollToIndex(rowsWithStreaming.length - 1, { align: 'end', behavior: 'smooth' });
  }, [virtualizer, rowsWithStreaming.length]);

  if (isLoading) {
    return (
      <div className="msg-list-loading">
        <div className="msg-list-spinner" />
      </div>
    );
  }

  if (allMessages.length === 0) {
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
