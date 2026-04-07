/**
 * MessageSearch — slide-down search overlay for conversation messages (AMPREALIZE-596).
 *
 * Triggered by a search button in the thread header. Uses Cmd+F / Ctrl+F as shortcut.
 * Displays highlighted snippet results from the full-text search endpoint.
 * Follows glassmorphism design language and ConversationPanel CSS variable system.
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { useSearchMessages } from '../../api/conversations';
import type { ConversationMessage } from '../../lib/collab-client';
import './MessageSearch.css';

// ── Types ────────────────────────────────────────────────────────────────────

export interface MessageSearchProps {
  conversationId: string;
  onClose: () => void;
  /** Called when user clicks a search result — scroll to the message */
  onJumpToMessage?: (messageId: string) => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export const MessageSearch = memo(function MessageSearch({
  conversationId,
  onClose,
  onJumpToMessage,
}: MessageSearchProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');

  // Debounce the search query (300ms)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const { data, isLoading, isError } = useSearchMessages({
    conversationId,
    query: debouncedQuery,
    limit: 20,
    enabled: debouncedQuery.length > 0,
  });

  // Auto-focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Escape key closes
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener('keydown', handleKey, true);
    return () => document.removeEventListener('keydown', handleKey, true);
  }, [onClose]);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value);
  }, []);

  const handleClear = useCallback(() => {
    setQuery('');
    setDebouncedQuery('');
    inputRef.current?.focus();
  }, []);

  const handleResultClick = useCallback(
    (messageId: string) => {
      onJumpToMessage?.(messageId);
    },
    [onJumpToMessage],
  );

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="msg-search" role="search" aria-label="Search messages">
      {/* Search input bar */}
      <div className="msg-search-bar">
        <SearchIcon />
        <input
          ref={inputRef}
          className="msg-search-input"
          type="search"
          placeholder="Search messages…"
          value={query}
          onChange={handleInputChange}
          autoComplete="off"
          spellCheck={false}
          aria-label="Search messages"
        />
        {query.length > 0 && (
          <button
            type="button"
            className="msg-search-clear pressable"
            onClick={handleClear}
            aria-label="Clear search"
          >
            <ClearIcon />
          </button>
        )}
        <button
          type="button"
          className="msg-search-close pressable"
          onClick={onClose}
          aria-label="Close search"
        >
          <CloseIcon />
        </button>
      </div>

      {/* Results */}
      {debouncedQuery.length > 0 && (
        <div className="msg-search-results" role="listbox" aria-label="Search results">
          {isLoading && (
            <div className="msg-search-status">Searching…</div>
          )}
          {isError && (
            <div className="msg-search-status msg-search-error">
              Search failed. Try again.
            </div>
          )}
          {!isLoading && !isError && items.length === 0 && (
            <div className="msg-search-status">
              No messages match "<strong>{debouncedQuery}</strong>"
            </div>
          )}
          {!isLoading && items.length > 0 && (
            <>
              <div className="msg-search-count">
                {total} result{total !== 1 ? 's' : ''}
              </div>
              <ul className="msg-search-list">
                {items.map((item) => (
                  <SearchResultItem
                    key={item.message.id}
                    message={item.message}
                    headline={item.headline ?? undefined}
                    rank={item.rank}
                    onClick={handleResultClick}
                  />
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
});

// ── Search result item ───────────────────────────────────────────────────────

interface SearchResultItemProps {
  message: ConversationMessage;
  headline?: string;
  rank: number;
  onClick: (messageId: string) => void;
}

const SearchResultItem = memo(function SearchResultItem({
  message,
  headline,
  onClick,
}: SearchResultItemProps) {
  const handleClick = useCallback(() => onClick(message.id), [onClick, message.id]);

  return (
    <li className="msg-search-item pressable" role="option" onClick={handleClick}>
      <div className="msg-search-item-meta">
        <span className="msg-search-item-sender">{message.sender_id}</span>
        <span className="msg-search-item-time">
          {message.created_at ? formatRelativeTime(message.created_at) : ''}
        </span>
      </div>
      {headline ? (
        <div
          className="msg-search-item-snippet"
          dangerouslySetInnerHTML={{ __html: sanitizeHeadline(headline) }}
        />
      ) : (
        <div className="msg-search-item-snippet">
          {message.content?.slice(0, 100) ?? '(no text)'}
        </div>
      )}
    </li>
  );
});

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Sanitize pg ts_headline output — only allow <b> tags for highlighting */
function sanitizeHeadline(html: string): string {
  return html.replace(/<(?!\/?b\b)[^>]*>/gi, '');
}

function formatRelativeTime(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  if (diffMins < 1) return 'now';
  if (diffMins < 60) return `${diffMins}m`;
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs}h`;
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays < 7) return `${diffDays}d`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// ── Inline SVG icons ─────────────────────────────────────────────────────────

function SearchIcon() {
  return (
    <svg className="msg-search-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5L14 14" />
    </svg>
  );
}

function ClearIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true" width="14" height="14">
      <circle cx="8" cy="8" r="6" />
      <path d="M6 6l4 4M10 6l-4 4" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true" width="14" height="14">
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}
