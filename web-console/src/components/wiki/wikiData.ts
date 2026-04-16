import type { WikiPageNode } from '../../api/wiki';
import { STORAGE_KEYS } from '../../config/storageKeys';

export type WikiDomain = 'infra' | 'platform' | 'ai-learning' | 'research';

export interface WikiDomainConfig {
  id: WikiDomain;
  label: string;
  tagline: string;
  description: string;
  landingHighlights: string[];
  landingGuidance: string[];
  primaryCtaLabel: string;
  primaryFeaturedPath?: string;
  primaryFeaturedTitle: string;
  primaryFeaturedDescription: string;
}

export interface WikiRecentPage {
  domain: WikiDomain;
  path: string;
  title: string;
  pageType: string;
  visitedAt: string;
}

export interface WikiFolderGroup {
  folder: string;
  label: string;
  pages: WikiPageNode[];
}

export interface WikiRelatedPage extends WikiPageNode {
  reason: 'folder' | 'tag';
}

const MAX_RECENT_WIKI_PAGES = 8;

export const WIKI_DOMAINS: WikiDomainConfig[] = [
  {
    id: 'infra',
    label: 'Infrastructure',
    tagline: 'Runbooks, architecture, and operating knowledge',
    description: 'Move from “where is this?” to “I know exactly what to do next.”',
    landingHighlights: [
      'Runbooks for common operational tasks and incident workflows.',
      'Architecture notes that explain how systems fit together.',
      'Reference pages for configuration, tooling, and conventions.',
    ],
    landingGuidance: [
      'Browse from the sidebar when you want to move through a system area.',
      'Use search when you already know the service, tool, or file name.',
    ],
    primaryCtaLabel: 'Open testing guide',
    primaryFeaturedPath: 'howto/run-tests.md',
    primaryFeaturedTitle: 'Get local testing under control',
    primaryFeaturedDescription: 'Start with the run-tests guide and then branch into references and architecture.',
  },
  {
    id: 'platform',
    label: 'Platform',
    tagline: 'Runtime context, system surfaces, and product-wide operating model',
    description: 'Understand how Amprealize fits together so you can move from repo trivia to system-level clarity.',
    landingHighlights: [
      'Reference pages for contexts, surfaces, editions, and MCP tools.',
      'How-to guides for getting started, environment setup, tests, and knowledge packs.',
      'Architecture notes that connect the behavior system, services, and platform workflows.',
    ],
    landingGuidance: [
      'Start with reference pages when you need the exact contract or command shape.',
      'Jump into architecture pages when you need to connect multiple services or runtime concepts.',
    ],
    primaryCtaLabel: 'Open context system reference',
    primaryFeaturedPath: 'reference/context-system.md',
    primaryFeaturedTitle: 'Start with the context system',
    primaryFeaturedDescription: 'Use the platform wiki as the front door to runtime context, environment routing, and pack-aware workflows.',
  },
  {
    id: 'ai-learning',
    label: 'AI Learning',
    tagline: 'Concepts and practical intuition',
    description: 'A guided map for learning the ideas behind the system, not just memorizing terms.',
    landingHighlights: [
      'Concept pages that explain core ideas in plain language.',
      'Practical notes that connect theory back to implementation.',
    ],
    landingGuidance: [
      'Browse concepts when you want intuition first.',
      'Use search when you already know the topic you need.',
    ],
    primaryCtaLabel: 'Start with fundamentals',
    primaryFeaturedPath: 'concepts/llms.md',
    primaryFeaturedTitle: 'Start with the foundations',
    primaryFeaturedDescription: 'Begin with core concepts to build practical understanding.',
  },
  {
    id: 'research',
    label: 'Research',
    tagline: 'Evaluations, synthesis, and evidence-backed decisions',
    description: 'Trace product and architecture choices back to research findings and contradictions.',
    landingHighlights: [
      'Syntheses that summarize what we know so far.',
      'Evaluation notes and experiment readouts.',
      'Decision context that ties conclusions back to evidence.',
    ],
    landingGuidance: [
      'Browse from the sidebar to move through a topic area.',
      'Use search to jump directly to a paper, test, or finding.',
    ],
    primaryCtaLabel: 'Open research index',
    primaryFeaturedPath: 'index.md',
    primaryFeaturedTitle: 'Start from the research index',
    primaryFeaturedDescription: 'Use the index and synthesis pages as the front door to deeper evaluations.',
  },
];

const WIKI_DOMAIN_MAP = new Map<WikiDomain, WikiDomainConfig>(
  WIKI_DOMAINS.map((domain) => [domain.id, domain]),
);

export function getWikiDomainConfig(domain: WikiDomain): WikiDomainConfig {
  return WIKI_DOMAIN_MAP.get(domain) ?? WIKI_DOMAINS[0];
}

export function pageTypeLabel(pageType: string): string {
  return pageType.replace(/[-_]/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function folderLabel(folder: string): string {
  if (!folder) return 'Pages';
  return folder
    .split('/')
    .pop()!
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function groupWikiPages(pages: WikiPageNode[]): WikiFolderGroup[] {
  const map = new Map<string, WikiPageNode[]>();

  for (const page of pages) {
    const key = page.folder || '';
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(page);
  }

  const groups: WikiFolderGroup[] = [];
  for (const [folder, folderPages] of map) {
    groups.push({
      folder,
      label: folderLabel(folder),
      pages: folderPages.sort((a, b) => a.title.localeCompare(b.title)),
    });
  }

  return groups.sort((a, b) => {
    if (!a.folder) return -1;
    if (!b.folder) return 1;
    return a.folder.localeCompare(b.folder);
  });
}

export function loadRecentWikiPages(): WikiRecentPage[] {
  if (typeof window === 'undefined') return [];

  try {
    const raw = window.localStorage.getItem(STORAGE_KEYS.wikiRecentPages);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is WikiRecentPage =>
        typeof item?.domain === 'string'
        && typeof item?.path === 'string'
        && typeof item?.title === 'string'
        && typeof item?.pageType === 'string'
        && typeof item?.visitedAt === 'string',
    );
  } catch {
    return [];
  }
}

export function saveRecentWikiPage(entry: WikiRecentPage): WikiRecentPage[] {
  if (typeof window === 'undefined') return [entry];

  const existing = loadRecentWikiPages();
  const next = [
    entry,
    ...existing.filter((item) => !(item.domain === entry.domain && item.path === entry.path)),
  ].slice(0, MAX_RECENT_WIKI_PAGES);

  window.localStorage.setItem(STORAGE_KEYS.wikiRecentPages, JSON.stringify(next));
  return next;
}

export function findFeaturedWikiPage(
  pages: WikiPageNode[],
  domain: WikiDomain,
): WikiPageNode | undefined {
  const config = getWikiDomainConfig(domain);
  if (config.primaryFeaturedPath) {
    const featured = pages.find((page) => page.path === config.primaryFeaturedPath);
    if (featured) return featured;
  }
  return pages[0];
}

export function extractSummary(markdown: string, frontmatter?: Record<string, unknown>): string {
  const preferred = frontmatter?.summary ?? frontmatter?.description ?? frontmatter?.excerpt;
  if (typeof preferred === 'string' && preferred.trim()) return preferred.trim();

  const lines = markdown
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith('#'))
    .filter((line) => !line.startsWith('!['))
    .filter((line) => !line.startsWith('```'));

  const paragraph = lines.find((line) => !line.startsWith('- ') && !line.startsWith('* '));
  if (!paragraph) return '';
  return paragraph
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[`*_>#]/g, '')
    .trim();
}

export function normalizeWikiLink(link: string): string | null {
  const withoutAnchor = link.split('#')[0]?.trim();
  if (!withoutAnchor || !withoutAnchor.endsWith('.md')) return null;

  return withoutAnchor
    .replace(/^\.\//, '')
    .replace(/^\.\.\//, '')
    .replace(/^\.\.\/\.\.\//, '')
    .replace(/^\.\.\/\.\.\/\.\.\//, '')
    .replace(/^\/+/, '');
}

export function resolveWikiHref(
  currentDomain: WikiDomain,
  currentPath: string,
  href: string,
): { domain: WikiDomain; path: string } | null {
  const cleanHref = href.split('#')[0]?.trim();
  if (!cleanHref) return null;
  if (/^(https?:|mailto:|tel:)/.test(cleanHref)) return null;

  const currentDir = currentPath.split('/').slice(0, -1);
  const seed = cleanHref.startsWith('/') ? [] : currentDir;
  const rawParts = [...seed, ...cleanHref.replace(/^\/+/, '').split('/')];
  const parts: string[] = [];

  for (const part of rawParts) {
    if (!part || part === '.') continue;
    if (part === '..') {
      parts.pop();
      continue;
    }
    parts.push(part);
  }

  if (!parts.length) return null;
  if (parts[0] === 'wiki') parts.shift();

  let domain = currentDomain;
  if (parts[0] === 'infra' || parts[0] === 'platform' || parts[0] === 'ai-learning' || parts[0] === 'research') {
    domain = parts.shift() as WikiDomain;
  }

  const path = parts.join('/');
  if (!path.endsWith('.md')) return null;
  return { domain, path };
}

export function buildPageSequence(
  pages: WikiPageNode[],
  currentPath: string,
): { previous?: WikiPageNode; next?: WikiPageNode } {
  const grouped = groupWikiPages(pages);
  const ordered = grouped.flatMap((group) => group.pages);
  const index = ordered.findIndex((page) => page.path === currentPath);

  return {
    previous: index > 0 ? ordered[index - 1] : undefined,
    next: index >= 0 && index < ordered.length - 1 ? ordered[index + 1] : undefined,
  };
}

export function buildRelatedPages(
  pages: WikiPageNode[],
  currentPath: string,
  currentTags: string[],
): WikiRelatedPage[] {
  const current = pages.find((page) => page.path === currentPath);
  if (!current) return [];

  const currentFolder = current.folder || '';
  const currentTagSet = new Set(currentTags.map((tag) => tag.toLowerCase()));

  return pages
    .filter((page) => page.path !== currentPath)
    .map((page) => {
      const pageTags = Array.isArray((page as WikiPageNode & { tags?: string[] }).tags)
        ? ((page as WikiPageNode & { tags?: string[] }).tags ?? []).map((tag) => tag.toLowerCase())
        : [];

      if (page.folder === currentFolder && currentFolder) {
        return { ...page, reason: 'folder' as const };
      }

      if (pageTags.some((tag) => currentTagSet.has(tag))) {
        return { ...page, reason: 'tag' as const };
      }

      return null;
    })
    .filter((page): page is WikiRelatedPage => Boolean(page))
    .slice(0, 4);
}
