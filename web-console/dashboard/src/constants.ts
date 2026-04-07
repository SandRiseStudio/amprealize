/** Amprealize embedded dashboard — storage keys (rebrand from amprealize). */

/** Default public OSS repo; override at build time with VITE_DASHBOARD_SOURCE_REPO_URL. */
export const DASHBOARD_SOURCE_REPO_URL =
  (import.meta.env.VITE_DASHBOARD_SOURCE_REPO_URL?.trim() ||
    'https://github.com/SandRiseStudio/amprealize') as string;

export const THEME_STORAGE_KEY = 'amprealize-theme';
export const THEME_STORAGE_KEY_LEGACY = 'amprealize-theme';

export function readStoredTheme(): string | null {
  if (typeof window === 'undefined') return null;
  return (
    window.localStorage.getItem(THEME_STORAGE_KEY) ??
    window.localStorage.getItem(THEME_STORAGE_KEY_LEGACY)
  );
}

export function writeStoredTheme(value: string): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(THEME_STORAGE_KEY, value);
  window.localStorage.removeItem(THEME_STORAGE_KEY_LEGACY);
}
