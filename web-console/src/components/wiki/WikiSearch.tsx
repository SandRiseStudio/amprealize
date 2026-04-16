/**
 * WikiSearch — command-palette-style search overlay with explicit scope.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useWikiSearch } from '../../api/wiki';
import { WIKI_DOMAINS, type WikiDomain, getWikiDomainConfig, pageTypeLabel } from './wikiData';

interface WikiSearchProps {
  domain: WikiDomain;
  onClose: () => void;
  onNavigate: (domain: string, pagePath: string) => void;
}

type SearchScope = 'all' | WikiDomain;

const SEARCH_SCOPES: { id: SearchScope; label: string }[] = [
  { id: 'all', label: 'All' },
  ...WIKI_DOMAINS.map((domain) => ({ id: domain.id, label: domain.label })),
];

const SearchIcon = () => (
  <svg className="wiki-search-input-icon" viewBox="0 0 16 16" fill="none">
    <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
    <path d="M10.5 10.5L13.5 13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

function highlightText(text: string, query: string): React.ReactNode {
  const normalizedQuery = query.trim();
  if (!normalizedQuery) return text;

  const pattern = new RegExp(`(${normalizedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'ig');
  const parts = text.split(pattern);
  return parts.map((part, index) => (
    index % 2 === 1
      ? <mark key={`${part}-${index}`}>{part}</mark>
      : <span key={`${part}-${index}`}>{part}</span>
  ));
}

export const WikiSearch = memo(function WikiSearch({
  onClose,
  onNavigate,
}: WikiSearchProps) {
  const [query, setQuery] = useState('');
  const [focusIndex, setFocusIndex] = useState(0);
  const [scope, setScope] = useState<SearchScope>('all');
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const scopedDomain = scope === 'all' ? undefined : scope;
  const { data: searchResults, isFetching } = useWikiSearch(query, scopedDomain);
  const results = useMemo(() => searchResults?.results ?? [], [searchResults?.results]);
  const clampedFocusIndex = results.length > 0 ? Math.min(focusIndex, results.length - 1) : 0;

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const element = listRef.current?.querySelector<HTMLElement>(
      `[data-search-index="${clampedFocusIndex}"]`,
    );
    element?.scrollIntoView({ block: 'nearest' });
  }, [clampedFocusIndex]);

  const placeholder = useMemo(() => {
    if (scope === 'all') return 'Search across all wiki knowledge...';
    return `Search ${getWikiDomainConfig(scope).label}...`;
  }, [scope]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        setFocusIndex((index) => Math.min(index + 1, results.length - 1));
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        setFocusIndex((index) => Math.max(index - 1, 0));
      } else if (event.key === 'Enter' && results[clampedFocusIndex]) {
        const result = results[clampedFocusIndex];
        onNavigate(result.domain, result.page_path);
      }
    },
    [clampedFocusIndex, onClose, onNavigate, results],
  );

  const handleBackdropClick = useCallback(
    (event: React.MouseEvent) => {
      if (event.target === event.currentTarget) onClose();
    },
    [onClose],
  );

  return (
    <div
      className="wiki-search-overlay"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-label="Search wiki"
    >
      <div className="wiki-search-panel" onKeyDown={handleKeyDown}>
        <div className="wiki-search-input-wrap">
          <SearchIcon />
          <input
            ref={inputRef}
            type="text"
            className="wiki-search-input"
            placeholder={placeholder}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search query"
          />
        </div>

        <div className="wiki-search-scopes" role="tablist" aria-label="Search scope">
          {SEARCH_SCOPES.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`wiki-search-scope-chip ${scope === option.id ? 'active' : ''}`}
              onClick={() => setScope(option.id)}
              role="tab"
              aria-selected={scope === option.id}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="wiki-search-results" ref={listRef}>
          {query.length < 2 ? (
            <div className="wiki-search-empty">
              Search all domains, then jump straight into an article, path, or reference.
            </div>
          ) : isFetching ? (
            <div className="wiki-search-empty">Searching the wiki…</div>
          ) : results.length === 0 ? (
            <div className="wiki-search-empty">
              No {scope === 'all' ? 'wiki' : getWikiDomainConfig(scope).label.toLowerCase()} results for "{query}".
            </div>
          ) : (
            results.map((result, index) => (
              <button
                key={`${result.domain}/${result.page_path}`}
                type="button"
                className={`wiki-search-result-item ${index === clampedFocusIndex ? 'focused' : ''}`}
                onClick={() => onNavigate(result.domain, result.page_path)}
                onMouseEnter={() => setFocusIndex(index)}
                data-search-index={index}
              >
                <div className="wiki-search-result-topline">
                  <span className="wiki-search-result-domain-badge">
                    {getWikiDomainConfig(result.domain as WikiDomain).label}
                  </span>
                  <span className="wiki-search-result-type-badge">
                    {pageTypeLabel(result.page_type)}
                  </span>
                </div>
                <span className="wiki-search-result-title">
                  {highlightText(result.title, query)}
                </span>
                <span className="wiki-search-result-snippet">
                  {highlightText(result.snippet, query)}
                </span>
                <span className="wiki-search-result-meta">
                  <span>{result.page_path}</span>
                  {result.score > 0 && (
                    <>
                      <span>•</span>
                      <span>{Math.round(result.score * 100)}% match</span>
                    </>
                  )}
                </span>
              </button>
            ))
          )}
        </div>

        <div className="wiki-search-footer">
          <span><kbd>↑</kbd> <kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
});
