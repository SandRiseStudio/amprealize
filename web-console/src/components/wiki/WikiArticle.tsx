/**
 * WikiArticle — rich article view with progress, TOC state, and related navigation.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { WikiPageNode } from '../../api/wiki';
import { useWikiPage } from '../../api/wiki';
import {
  buildPageSequence,
  buildRelatedPages,
  pageTypeLabel,
  resolveWikiHref,
  type WikiDomain,
} from './wikiData';

interface WikiArticleProps {
  domain: WikiDomain;
  path: string;
  pages: WikiPageNode[];
  onNavigate: (domain: WikiDomain, path: string) => void;
  onPageView: (page: { title: string; pageType: string }) => void;
}

interface TocEntry {
  id: string;
  text: string;
  level: number;
}

function stripFrontmatter(body: string): string {
  if (body.startsWith('---')) {
    const end = body.indexOf('---', 3);
    if (end !== -1) return body.slice(end + 3).trim();
  }
  return body;
}

function normalizeHeading(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-');
}

function textFromChildren(children: ReactNode): string {
  if (typeof children === 'string') return children;
  if (typeof children === 'number') return String(children);
  if (Array.isArray(children)) return children.map((child) => textFromChildren(child)).join('');
  if (children && typeof children === 'object' && 'props' in children) {
    return textFromChildren((children as { props?: { children?: ReactNode } }).props?.children ?? '');
  }
  return '';
}

function extractToc(markdown: string): TocEntry[] {
  return markdown
    .split('\n')
    .map((line) => line.match(/^(#{2,3})\s+(.+)/))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .map((match) => ({
      id: normalizeHeading(match[2].replace(/[`*_~]/g, '')),
      text: match[2].replace(/[`*_~]/g, ''),
      level: match[1].length,
    }));
}

function stripLeadingTitle(markdown: string, title: string): string {
  const lines = markdown.split('\n');
  const firstContentIndex = lines.findIndex((line) => line.trim().length > 0);
  if (firstContentIndex === -1) return markdown;

  const firstLine = lines[firstContentIndex];
  const heading = firstLine.match(/^#\s+(.+)/);
  if (!heading) return markdown;
  if (heading[1].trim().toLowerCase() !== title.trim().toLowerCase()) return markdown;

  const nextLines = [...lines];
  nextLines.splice(firstContentIndex, 1);
  return nextLines.join('\n').trim();
}

function normalizeMarkdownParagraph(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[`*_>#]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/[.;:,!?]+$/g, '');
}

function stripLeadingSummary(markdown: string, summary: string): string {
  if (!summary.trim()) return markdown;

  const lines = markdown.split('\n');
  let start = 0;

  while (start < lines.length && !lines[start].trim()) start += 1;
  if (start >= lines.length) return markdown;

  const firstLine = lines[start].trim();
  if (/^(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|```|~~~|\|)/.test(firstLine)) return markdown;

  let end = start;
  while (end < lines.length && lines[end].trim()) end += 1;

  const leadParagraph = normalizeMarkdownParagraph(lines.slice(start, end).join(' '));
  const normalizedSummary = normalizeMarkdownParagraph(summary);
  if (!leadParagraph || leadParagraph !== normalizedSummary) return markdown;

  const remaining = [...lines.slice(0, start), ...lines.slice(end)];
  while (remaining[0]?.trim() === '') remaining.shift();
  return remaining.join('\n').trim();
}

function difficultyClass(difficulty?: string): string {
  if (!difficulty) return '';
  const lower = difficulty.toLowerCase();
  if (lower === 'beginner') return 'wiki-article-badge--difficulty-beginner';
  if (lower === 'intermediate') return 'wiki-article-badge--difficulty-intermediate';
  if (lower === 'advanced') return 'wiki-article-badge--difficulty-advanced';
  return '';
}

function reasonLabel(reason: 'folder' | 'tag'): string {
  if (reason === 'folder') return 'Same collection';
  return 'Shared theme';
}

export const WikiArticle = memo(function WikiArticle({
  domain,
  path,
  pages,
  onNavigate,
  onPageView,
}: WikiArticleProps) {
  const { data: page, isLoading, isError } = useWikiPage(domain, path);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [activeHeadingId, setActiveHeadingId] = useState<string>('');
  const [progress, setProgress] = useState(0);
  const [tocOpen, setTocOpen] = useState(false);

  const pageFrontmatter = useMemo(() => (page?.frontmatter ?? {}) as Record<string, unknown>, [page?.frontmatter]);

  const rawContent = useMemo(() => {
    if (!page) return '';
    return stripLeadingTitle(stripFrontmatter(page.body), page.title);
  }, [page]);

  const heroSummary = useMemo(() => {
    const preferred = pageFrontmatter.summary ?? pageFrontmatter.description ?? pageFrontmatter.excerpt;
    return typeof preferred === 'string' ? preferred.trim() : '';
  }, [pageFrontmatter]);

  const content = useMemo(() => stripLeadingSummary(rawContent, heroSummary), [rawContent, heroSummary]);

  const toc = useMemo(() => extractToc(content), [content]);

  useEffect(() => {
    if (!page) return;
    onPageView({ title: page.title, pageType: page.page_type });
  }, [onPageView, page]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return undefined;

    const handleScroll = () => {
      const total = element.scrollHeight - element.clientHeight;
      const next = total <= 0 ? 0 : Math.min(100, Math.max(0, (element.scrollTop / total) * 100));
      setProgress(next);
    };

    handleScroll();
    element.addEventListener('scroll', handleScroll, { passive: true });
    return () => element.removeEventListener('scroll', handleScroll);
  }, [content]);

  useEffect(() => {
    const root = scrollRef.current;
    const container = bodyRef.current;
    if (!root || !container) return undefined;

    const headings = Array.from(container.querySelectorAll<HTMLElement>('h2[id], h3[id]'));
    if (!headings.length) return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]?.target instanceof HTMLElement) {
          setActiveHeadingId(visible[0].target.id);
        }
      },
      {
        root,
        rootMargin: '-12% 0px -70% 0px',
        threshold: [0, 1],
      },
    );

    headings.forEach((heading) => observer.observe(heading));

    return () => observer.disconnect();
  }, [content]);

  const handleTocSelect = useCallback((id: string) => {
    const root = scrollRef.current;
    const container = bodyRef.current;
    if (!root || !container) return;

    const target = container.querySelector<HTMLElement>(`#${id}`);
    if (!target) return;

    const rootRect = root.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const top = root.scrollTop + (targetRect.top - rootRect.top) - 24;

    root.scrollTo({
      top: Math.max(0, top),
      behavior: 'smooth',
    });

    setActiveHeadingId(id);
    setTocOpen(false);
  }, []);

  if (isLoading) {
    return (
      <div className="wiki-article-pane">
        <div className="wiki-article-shell">
          <div className="wiki-article-inner">
            <div className="wiki-skeleton wiki-skeleton-title" />
            <div className="wiki-skeleton wiki-skeleton-line wide" />
            <div className="wiki-skeleton wiki-skeleton-line wide" />
            <div className="wiki-skeleton wiki-skeleton-line medium" />
            <div className="wiki-skeleton wiki-skeleton-line wide" />
            <div className="wiki-skeleton wiki-skeleton-line narrow" />
          </div>
        </div>
      </div>
    );
  }

  if (isError || !page) {
    return (
      <div className="wiki-welcome">
        <div className="wiki-welcome-title">Page not found</div>
        <div className="wiki-welcome-desc">
          The page <code>{path}</code> does not exist in the {domain} wiki.
        </div>
      </div>
    );
  }

  const tags = Array.isArray(pageFrontmatter.tags) ? pageFrontmatter.tags as string[] : [];
  const difficulty = typeof pageFrontmatter.difficulty === 'string' ? pageFrontmatter.difficulty : undefined;
  const pageType = typeof pageFrontmatter.type === 'string' ? pageFrontmatter.type : page.page_type;
  const pageSequence = buildPageSequence(pages, path);
  const previousPage = pageSequence.previous;
  const nextPage = pageSequence.next;
  const relatedPages = buildRelatedPages(pages, path, tags);

  return (
    <div className="wiki-article-pane" ref={scrollRef} key={`${domain}/${path}`}>
      <div className="wiki-article-shell">
        <div className="wiki-article-with-toc">
          <div className="wiki-article-inner">
            <div className="wiki-article-hero">
              <div className="wiki-article-progress-track" aria-hidden="true">
                <span className="wiki-article-progress-fill" style={{ width: `${progress}%` }} />
              </div>
              <div className="wiki-article-meta">
                {pageType && (
                  <span className="wiki-article-badge wiki-article-badge--type">{pageTypeLabel(pageType)}</span>
                )}
                {difficulty && (
                  <span className={`wiki-article-badge ${difficultyClass(difficulty)}`}>
                    {difficulty}
                  </span>
                )}
                {tags.map((tag) => (
                  <span key={tag} className="wiki-article-badge">{tag}</span>
                ))}
              </div>
              <h1 className="wiki-article-title">{page.title}</h1>
              {heroSummary && <p className="wiki-article-summary">{heroSummary}</p>}
              {toc.length > 0 && (
                <button
                  type="button"
                  className="wiki-article-mobile-toc-toggle"
                  onClick={() => setTocOpen((open) => !open)}
                >
                  On this page
                </button>
              )}
            </div>

            {toc.length > 0 && tocOpen && (
              <nav className="wiki-toc wiki-toc--mobile" aria-label="Table of contents">
                <div className="wiki-toc-title">On this page</div>
                <ul className="wiki-toc-list">
                  {toc.map((entry) => (
                    <li
                      key={entry.id}
                      className={`wiki-toc-item ${entry.level === 3 ? 'wiki-toc-item--h3' : ''}`}
                    >
                      <button
                        type="button"
                        className={`wiki-toc-link ${activeHeadingId === entry.id ? 'active' : ''}`}
                        onClick={() => handleTocSelect(entry.id)}
                      >
                        {entry.text}
                      </button>
                    </li>
                  ))}
                </ul>
              </nav>
            )}

            <div className="wiki-article-content">
              <div className="wiki-article-body" ref={bodyRef}>
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    a: ({ href, children, ...props }) => {
                      if (!href) return <a {...props}>{children}</a>;
                      const target = resolveWikiHref(domain, path, href);
                      if (!target) {
                        return (
                          <a href={href} {...props}>
                            {children}
                          </a>
                        );
                      }
                      return (
                        <a
                          href={`/wiki/${target.domain}/${target.path}`}
                          onClick={(event) => {
                            event.preventDefault();
                            onNavigate(target.domain, target.path);
                          }}
                          {...props}
                        >
                          {children}
                        </a>
                      );
                    },
                    h2: ({ children, ...props }) => {
                      const id = normalizeHeading(textFromChildren(children));
                      return <h2 id={id} {...props}>{children}</h2>;
                    },
                    h3: ({ children, ...props }) => {
                      const id = normalizeHeading(textFromChildren(children));
                      return <h3 id={id} {...props}>{children}</h3>;
                    },
                  }}
                >
                  {content}
                </ReactMarkdown>
              </div>

              {(previousPage || nextPage) && (
                <div className="wiki-article-nav">
                  {previousPage ? (
                    <button
                      type="button"
                      className="wiki-article-nav-card"
                      onClick={() => onNavigate(domain, previousPage.path)}
                    >
                      <span className="wiki-article-nav-eyebrow">Previous</span>
                      <span className="wiki-article-nav-title">{previousPage.title}</span>
                    </button>
                  ) : <div />}
                  {nextPage && (
                    <button
                      type="button"
                      className="wiki-article-nav-card wiki-article-nav-card--next"
                      onClick={() => onNavigate(domain, nextPage.path)}
                    >
                      <span className="wiki-article-nav-eyebrow">Next</span>
                      <span className="wiki-article-nav-title">{nextPage.title}</span>
                    </button>
                  )}
                </div>
              )}

              {relatedPages.length > 0 && (
                <div className="wiki-related">
                  <div className="wiki-related-header">
                    <div className="wiki-related-title">Related pages</div>
                    <div className="wiki-related-copy">Keep the thread of the topic without hunting.</div>
                  </div>
                  <div className="wiki-related-grid">
                    {relatedPages.map((related) => (
                      <button
                        key={related.path}
                        type="button"
                        className="wiki-related-card"
                        onClick={() => onNavigate(domain, related.path)}
                      >
                        <span className="wiki-related-card-reason">{reasonLabel(related.reason)}</span>
                        <span className="wiki-related-card-title">{related.title}</span>
                        <span className="wiki-related-card-meta">{pageTypeLabel(related.page_type)}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {toc.length > 1 && (
            <nav className="wiki-toc" aria-label="Table of contents">
              <div className="wiki-toc-title">On this page</div>
              <ul className="wiki-toc-list">
                {toc.map((entry) => (
                  <li
                    key={entry.id}
                    className={`wiki-toc-item ${entry.level === 3 ? 'wiki-toc-item--h3' : ''}`}
                  >
                    <button
                      type="button"
                      className={`wiki-toc-link ${activeHeadingId === entry.id ? 'active' : ''}`}
                      onClick={() => handleTocSelect(entry.id)}
                    >
                      {entry.text}
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          )}
        </div>
      </div>
    </div>
  );
});
