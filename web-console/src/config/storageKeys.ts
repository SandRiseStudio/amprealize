/**
 * localStorage keys for the Amprealize web console.
 * Legacy `amprealize*` keys are migrated once at startup (see migrateWebConsoleLocalStorage).
 */

export const STORAGE_KEYS = {
  authState: 'amprealize_auth',
  accessToken: 'amprealize_token',
  refreshToken: 'amprealize_refresh_token',
  orgContext: 'amprealize.org-context',
  projectSort: 'amprealize.projects.sort',
  sidebarSections: 'amprealize.sidebar.sections',
  sidebarRecentProjects: 'amprealize.sidebar.recentProjects',
  sidebarPinnedProjects: 'amprealize.sidebar.pinnedProjects',
  wikiRecentPages: 'amprealize.wiki.recentPages',
} as const;

const LEGACY_KEYS: Record<keyof typeof STORAGE_KEYS, string> = {
  authState: 'amprealize_auth',
  accessToken: 'amprealize_token',
  refreshToken: 'amprealize_refresh_token',
  orgContext: 'amprealize.org-context',
  projectSort: 'amprealize.projects.sort',
  sidebarSections: 'amprealize.sidebar.sections',
  sidebarRecentProjects: 'amprealize.sidebar.recentProjects',
  sidebarPinnedProjects: 'amprealize.sidebar.pinnedProjects',
  wikiRecentPages: 'amprealize.wiki.recentPages',
};

/** Board column collapsed state (per column id) */
export function boardCollapsedStorageKey(boardColumnId: string): string {
  return `amprealize:collapsed:${boardColumnId}`;
}

export function legacyBoardCollapsedStorageKey(boardColumnId: string): string {
  return `amprealize:collapsed:${boardColumnId}`;
}

/**
 * Copy legacy values into new keys when the new key is unset.
 * Safe to call multiple times.
 */
export function migrateWebConsoleLocalStorage(): void {
  if (typeof window === 'undefined') return;

  (Object.keys(STORAGE_KEYS) as (keyof typeof STORAGE_KEYS)[]).forEach((k) => {
    const oldKey = LEGACY_KEYS[k];
    const newKey = STORAGE_KEYS[k];
    const v = localStorage.getItem(oldKey);
    if (v != null && localStorage.getItem(newKey) == null) {
      localStorage.setItem(newKey, v);
    }
  });
}

/** Remove legacy keys after successful migration (optional cleanup) */
export function clearLegacyWebConsoleLocalStorage(): void {
  if (typeof window === 'undefined') return;

  (Object.keys(STORAGE_KEYS) as (keyof typeof STORAGE_KEYS)[]).forEach((k) => {
    localStorage.removeItem(LEGACY_KEYS[k]);
  });
}

// Run migration as soon as this module loads (before other stores read localStorage).
if (typeof window !== 'undefined') {
  migrateWebConsoleLocalStorage();
}
