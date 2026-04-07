import type { Project } from '../api/dashboard';
import { STORAGE_KEYS } from '../config/storageKeys';

export type ProjectSortMode = 'activity' | 'updated' | 'name';

export const PROJECT_SORT_STORAGE_KEY = STORAGE_KEYS.projectSort;
export const DEFAULT_PROJECT_SORT: ProjectSortMode = 'activity';

export function loadProjectSortPreference(): ProjectSortMode {
  if (typeof window === 'undefined') return DEFAULT_PROJECT_SORT;

  try {
    const raw = window.localStorage.getItem(PROJECT_SORT_STORAGE_KEY);
    return raw === 'updated' || raw === 'name' || raw === 'activity'
      ? raw
      : DEFAULT_PROJECT_SORT;
  } catch {
    return DEFAULT_PROJECT_SORT;
  }
}

export function saveProjectSortPreference(mode: ProjectSortMode): void {
  if (typeof window === 'undefined') return;

  try {
    window.localStorage.setItem(PROJECT_SORT_STORAGE_KEY, mode);
  } catch {
    // Ignore persistence failures and keep the in-memory choice.
  }
}

function getProjectActivityScore(project: Project): number {
  const updatedAt = project.updated_at ? new Date(project.updated_at).getTime() : 0;
  return updatedAt + ((project.agent_count ?? 0) * 250_000) + ((project.run_count ?? 0) * 100_000);
}

export function sortProjects(projects: Project[], mode: ProjectSortMode): Project[] {
  const next = [...projects];

  if (mode === 'name') {
    return next.sort((a, b) => a.name.localeCompare(b.name));
  }

  if (mode === 'updated') {
    return next.sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''));
  }

  return next.sort((a, b) => getProjectActivityScore(b) - getProjectActivityScore(a));
}
