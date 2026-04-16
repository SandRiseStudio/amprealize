import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { WikiPage } from '../components/wiki/WikiPage';
import {
  useWikiPage,
  useWikiSearch,
  useWikiStatus,
  useWikiTree,
} from '../api/wiki';

vi.mock('../api/wiki', () => ({
  useWikiTree: vi.fn(),
  useWikiStatus: vi.fn(),
  useWikiPage: vi.fn(),
  useWikiSearch: vi.fn(),
}));

const pagesByDomain = {
  infra: [
    { path: 'index.md', title: 'Infrastructure Index', page_type: 'reference', folder: '' },
    { path: 'howto/run-tests.md', title: 'Run Tests Locally', page_type: 'howto', folder: 'howto' },
    { path: 'reference/pytest-ini.md', title: 'pytest.ini Reference', page_type: 'reference', folder: 'reference' },
  ],
  platform: [
    { path: 'reference/context-system.md', title: 'Context System', page_type: 'reference', folder: 'reference' },
    { path: 'architecture/service-map.md', title: 'Service Map', page_type: 'architecture', folder: 'architecture' },
  ],
  'ai-learning': [
    { path: 'concepts/attention.md', title: 'Attention', page_type: 'concept', folder: 'concepts' },
    { path: 'concepts/transformers.md', title: 'Transformers', page_type: 'concept', folder: 'concepts' },
  ],
  research: [
    { path: 'index.md', title: 'Research Index', page_type: 'reference', folder: '' },
  ],
} as const;

const pageBodies: Record<string, { title: string; page_type: string; body: string; frontmatter: Record<string, unknown> }> = {
  'infra/howto/run-tests.md': {
    title: 'Run Tests Locally',
    page_type: 'howto',
    body: '# Run Tests Locally\n\nGet the local stack ready.\n\n## Prepare\n\nInstall dependencies.\n\n## Execute\n\nRun the suite.\n',
    frontmatter: { type: 'howto', difficulty: 'beginner', tags: ['testing'] },
  },
  'infra/reference/pytest-ini.md': {
    title: 'pytest.ini Reference',
    page_type: 'reference',
    body: '# pytest.ini Reference\n\nThe settings that shape test execution.\n\n## Defaults\n\nThis file controls pytest defaults.\n',
    frontmatter: { type: 'reference', tags: ['testing'] },
  },
  'platform/reference/context-system.md': {
    title: 'Context System',
    page_type: 'reference',
    body: '# Context System\n\nThe context system manages named database configurations.\n\n## Core Concepts\n\nSwitch between local Postgres, Neon, SQLite, and memory.\n',
    frontmatter: {
      type: 'reference',
      summary: 'The context system manages named database configurations.',
      tags: ['context-system', 'configuration'],
    },
  },
  'ai-learning/concepts/attention.md': {
    title: 'Attention',
    page_type: 'concept',
    body: '# Attention\n\nAttention lets a model weigh relevant context.\n\n## Why it matters\n\nIt makes transformers useful.\n',
    frontmatter: { type: 'concept', difficulty: 'intermediate', tags: ['transformers'] },
  },
};

const searchResults = [
  {
    domain: 'ai-learning',
    page_path: 'concepts/attention.md',
    title: 'Attention',
    page_type: 'concept',
    score: 0.98,
    snippet: 'Attention lets a model weigh relevant context.',
  },
  {
    domain: 'infra',
    page_path: 'howto/run-tests.md',
    title: 'Run Tests Locally',
    page_type: 'howto',
    score: 0.34,
    snippet: 'Run the local stack before executing tests.',
  },
];

beforeAll(() => {
  Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  });

  class MockIntersectionObserver {
    observe = vi.fn();
    disconnect = vi.fn();
    unobserve = vi.fn();
  }

  vi.stubGlobal('IntersectionObserver', MockIntersectionObserver);
});

function renderWiki(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/wiki" element={<WikiPage />} />
        <Route path="/wiki/:domain" element={<WikiPage />} />
        <Route path="/wiki/:domain/*" element={<WikiPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('WikiPage', () => {
  beforeEach(() => {
    localStorage.clear();

    vi.mocked(useWikiTree).mockImplementation((domain: string) => ({
      data: {
        domain,
        pages: pagesByDomain[domain as keyof typeof pagesByDomain] ?? [],
        total: (pagesByDomain[domain as keyof typeof pagesByDomain] ?? []).length,
      },
      isLoading: false,
    } as never));

    vi.mocked(useWikiStatus).mockImplementation((domain: string) => ({
      data: {
        domain,
        total_pages: (pagesByDomain[domain as keyof typeof pagesByDomain] ?? []).length,
        pages_by_type: Object.fromEntries(
          Object.entries(
            (pagesByDomain[domain as keyof typeof pagesByDomain] ?? []).reduce<Record<string, number>>((acc, page) => {
              acc[page.page_type] = (acc[page.page_type] ?? 0) + 1;
              return acc;
            }, {}),
          ),
        ),
      },
    } as never));

    vi.mocked(useWikiPage).mockImplementation((domain: string, path: string) => ({
      data: pageBodies[`${domain}/${path}`],
      isLoading: false,
      isError: !pageBodies[`${domain}/${path}`],
    } as never));

    vi.mocked(useWikiSearch).mockImplementation((query: string, domain?: string) => ({
      data: {
        query,
        results: searchResults.filter((result) => {
          if (!query || query.length < 2) return false;
          if (domain && result.domain !== domain) return false;
          return result.title.toLowerCase().includes(query.toLowerCase())
            || result.snippet.toLowerCase().includes(query.toLowerCase());
        }),
        total: 0,
      },
      isFetching: false,
    } as never));
  });

  it('renders a polished domain landing and opens an article from the sidebar', async () => {
    const user = userEvent.setup();
    renderWiki('/wiki/infra');

    expect(screen.getByRole('heading', { name: /runbooks, architecture, and operating knowledge/i })).toBeInTheDocument();
    expect(screen.getByText(/What lives here/i)).toBeInTheDocument();
    expect(screen.getByText(/How to use it/i)).toBeInTheDocument();
    expect(screen.getByText(/Runbooks for common operational tasks and incident workflows/i)).toBeInTheDocument();
    expect(screen.getByText(/Search works across domains/i)).toBeInTheDocument();
    expect(screen.queryByText(/Browse by collection/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Start here/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /run tests locally/i }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /run tests locally/i })).toBeInTheDocument();
    });

    expect(screen.getAllByText(/Get the local stack ready/i)).toHaveLength(1);
    expect(screen.getByText(/^Previous$/i)).toBeInTheDocument();
    expect(screen.getByText(/^Next$/i)).toBeInTheDocument();
  });

  it('shows explicit search scopes and filters results by the selected domain', async () => {
    const user = userEvent.setup();
    renderWiki('/wiki/infra');

    await user.click(screen.getByRole('button', { name: /open wiki search/i }));
    await user.type(screen.getByLabelText(/search query/i), 'attention');

    expect(screen.getByRole('tab', { name: 'All' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByText(/Attention/).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('tab', { name: /Infrastructure/i }));

    expect(screen.queryByText(/^Attention$/)).not.toBeInTheDocument();
    expect(screen.getByText(/No infrastructure results for "attention"/i)).toBeInTheDocument();
  });

  it('recognizes the platform wiki domain and renders its landing state', () => {
    renderWiki('/wiki/platform');

    expect(screen.getByRole('heading', { name: /runtime context, system surfaces, and product-wide operating model/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /platform/i })).toHaveClass('active');
    expect(screen.getByText(/Reference pages for contexts, surfaces, editions, and MCP tools/i)).toBeInTheDocument();
  });

  it('keeps explicit summaries in the header without duplicating them in the article body', async () => {
    const user = userEvent.setup();
    renderWiki('/wiki/platform');

    await user.click(screen.getByRole('button', { name: /context system/i }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^context system$/i })).toBeInTheDocument();
    });

    expect(screen.getAllByText(/The context system manages named database configurations/i)).toHaveLength(1);
    expect(screen.getByText(/Switch between local Postgres, Neon, SQLite, and memory/i)).toBeInTheDocument();
  });
});
