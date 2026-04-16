/**
 * WikiPage — local wiki workspace with its own navigation, landing states, and search.
 */

import { memo, useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useWikiTree } from '../../api/wiki';
import { WikiArticle } from './WikiArticle';
import { WikiSearch } from './WikiSearch';
import { WikiSidebar } from './WikiSidebar';
import {
  WIKI_DOMAINS,
  getWikiDomainConfig,
  saveRecentWikiPage,
  type WikiDomain,
} from './wikiData';
import './Wiki.css';

const BookIcon = () => (
  <svg className="wiki-header-icon" viewBox="0 0 20 20" fill="none">
    <path d="M3 4.5A1.5 1.5 0 0 1 4.5 3h3A1.5 1.5 0 0 1 9 4.5v11A1.5 1.5 0 0 1 7.5 17h-3A1.5 1.5 0 0 1 3 15.5v-11Z" stroke="currentColor" strokeWidth="1.5" />
    <path d="M9 5.5A1.5 1.5 0 0 1 10.5 4h5A1.5 1.5 0 0 1 17 5.5v10a1.5 1.5 0 0 1-1.5 1.5h-5A1.5 1.5 0 0 1 9 15.5v-10Z" stroke="currentColor" strokeWidth="1.5" />
    <path d="M6 7h1.5M6 9.5h1.5M12 7.5h2.5M12 10h2.5M12 12.5h2.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

const SearchIconSmall = () => (
  <svg className="wiki-search-trigger-icon" viewBox="0 0 16 16" fill="none">
    <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
    <path d="M10.5 10.5L13.5 13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const MenuIcon = () => (
  <svg className="wiki-search-trigger-icon" viewBox="0 0 16 16" fill="none">
    <path d="M3 4.5h10M3 8h10M3 11.5h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

function isWikiDomain(value: string | undefined): value is WikiDomain {
  return value === 'infra' || value === 'platform' || value === 'ai-learning' || value === 'research';
}

interface DomainLandingProps {
  domain: WikiDomain;
}

const DomainLanding = memo(function DomainLanding({ domain }: DomainLandingProps) {
  const config = getWikiDomainConfig(domain);

  return (
    <div className="wiki-domain-landing">
      <div className="wiki-domain-hero-copy">
        <div className="wiki-domain-eyebrow">{config.label}</div>
        <h1 className="wiki-domain-title">{config.tagline}</h1>
        <p className="wiki-domain-description">{config.description}</p>

        <div className="wiki-domain-overview">
          <div className="wiki-domain-overview-column">
            <div className="wiki-domain-overview-title">What lives here</div>
            <ul className="wiki-domain-overview-list">
              {config.landingHighlights.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>

          <div className="wiki-domain-overview-column">
            <div className="wiki-domain-overview-title">How to use it</div>
            <ul className="wiki-domain-overview-list">
              {config.landingGuidance.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>

        <div className="wiki-domain-note">
          <span className="wiki-domain-note-label">Tip</span>
          Search works across domains, so it is the fastest path when you already know the topic.
          <kbd>⌘K</kbd>
        </div>
      </div>
    </div>
  );
});

export const WikiPage = memo(function WikiPage() {
  const { domain: rawDomain, '*': pagePath } = useParams<{ domain: string; '*': string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const domain: WikiDomain = isWikiDomain(rawDomain) ? rawDomain : 'infra';
  const activePath = pagePath || '';
  const searchParamOpen = searchParams.get('search') === '1';
  const routeKey = `${domain}:${activePath}`;

  const [manualSearchOpen, setManualSearchOpen] = useState(false);
  const [mobileSidebar, setMobileSidebar] = useState({ open: false, routeKey });

  const { data: treeData, isLoading: treeLoading } = useWikiTree(domain);

  const pages = treeData?.pages ?? [];

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setManualSearchOpen((open) => !open);
      }
      if (event.key === 'Escape') {
        setManualSearchOpen(false);
        setMobileSidebar((current) => ({ ...current, open: false }));
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);
  const searchOpen = searchParamOpen || manualSearchOpen;
  const sidebarOpen = mobileSidebar.open && mobileSidebar.routeKey === routeKey;

  const handleDomainChange = useCallback((nextDomain: WikiDomain) => {
    navigate(`/wiki/${nextDomain}`);
  }, [navigate]);

  const handlePageSelect = useCallback((path: string) => {
    navigate(`/wiki/${domain}/${path}`);
  }, [domain, navigate]);

  const handleArticleNavigate = useCallback((targetDomain: WikiDomain, targetPath: string) => {
    navigate(`/wiki/${targetDomain}/${targetPath}`);
  }, [navigate]);

  const handleSearchNavigate = useCallback((targetDomain: string, targetPath: string) => {
    setManualSearchOpen(false);
    setSearchParams((params) => {
      const next = new URLSearchParams(params);
      next.delete('search');
      return next;
    });
    navigate(`/wiki/${targetDomain}/${targetPath}`);
  }, [navigate, setSearchParams]);

  const handleSearchOpen = useCallback(() => {
    setManualSearchOpen(true);
    setSearchParams((params) => {
      const next = new URLSearchParams(params);
      next.set('search', '1');
      return next;
    });
  }, [setSearchParams]);

  const handleSearchClose = useCallback(() => {
    setManualSearchOpen(false);
    setSearchParams((params) => {
      const next = new URLSearchParams(params);
      next.delete('search');
      return next;
    });
  }, [setSearchParams]);

  const handlePageView = useCallback((page: { title: string; pageType: string }) => {
    saveRecentWikiPage({
      domain,
      path: activePath,
      title: page.title,
      pageType: page.pageType,
      visitedAt: new Date().toISOString(),
    });
  }, [activePath, domain]);

  const domainConfig = getWikiDomainConfig(domain);

  return (
    <div className="wiki-layout">
      <div className="wiki-header">
        <div className="wiki-header-title">
          <BookIcon />
          <div className="wiki-header-title-copy">
            <span>Wiki</span>
            <span className="wiki-header-subtitle">{domainConfig.label}</span>
          </div>
        </div>

        <div className="wiki-domain-tabs">
          {WIKI_DOMAINS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`wiki-domain-tab ${domain === item.id ? 'active' : ''}`}
              onClick={() => handleDomainChange(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="wiki-header-actions">
          <button
            type="button"
            className="wiki-search-trigger wiki-search-trigger--mobile"
            onClick={() => setMobileSidebar({ open: true, routeKey })}
          >
            <MenuIcon />
            Browse
          </button>
          <button
            type="button"
            className="wiki-search-trigger"
            onClick={handleSearchOpen}
            aria-label="Open wiki search"
          >
            <SearchIconSmall />
            Search
            <kbd>⌘K</kbd>
          </button>
        </div>
      </div>

      <div className="wiki-shell">
        {sidebarOpen && (
          <button
            type="button"
            className="wiki-sidebar-backdrop"
            aria-label="Close wiki navigation"
            onClick={() => setMobileSidebar((current) => ({ ...current, open: false }))}
          />
        )}

        <aside className={`wiki-local-nav ${sidebarOpen ? 'open' : ''}`}>
          <WikiSidebar
            pages={pages}
            activePath={activePath}
            isLoading={treeLoading}
            domain={domain}
            onSelect={handlePageSelect}
          />
        </aside>

        <div className="wiki-main-stage">
          {activePath ? (
            <WikiArticle
              domain={domain}
              path={activePath}
              pages={pages}
              onNavigate={handleArticleNavigate}
              onPageView={handlePageView}
            />
          ) : (
            <DomainLanding domain={domain} />
          )}
        </div>
      </div>

      {searchOpen && (
        <WikiSearch
          domain={domain}
          onClose={handleSearchClose}
          onNavigate={handleSearchNavigate}
        />
      )}
    </div>
  );
});
