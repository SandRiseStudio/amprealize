/**
 * Global org context store
 *
 * Keeps the active org selection consistent across pages.
 */

import { useSyncExternalStore } from 'react';
import { STORAGE_KEYS } from '../config/storageKeys';

const STORAGE_KEY = STORAGE_KEYS.orgContext;

export interface OrgContextState {
  currentOrgId: string | null;
}

type OrgContextActions = {
  setCurrentOrgId: (orgId: string | null) => void;
};

const defaultState: OrgContextState = {
  currentOrgId: null,
};

let state: OrgContextState = loadState();
const listeners = new Set<() => void>();

function loadState(): OrgContextState {
  if (typeof window === 'undefined') return { ...defaultState };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...defaultState };
    const parsed = JSON.parse(raw) as Partial<OrgContextState>;
    if (typeof parsed.currentOrgId === 'string' || parsed.currentOrgId === null) {
      return { currentOrgId: parsed.currentOrgId };
    }
  } catch {
    // Ignore malformed storage.
  }
  return { ...defaultState };
}

function persist(nextState: OrgContextState) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextState));
  } catch {
    // Ignore storage failures.
  }
}

function notify() {
  listeners.forEach((listener) => listener());
}

function setState(partial: Partial<OrgContextState>) {
  state = { ...state, ...partial };
  persist(state);
  notify();
}

export const orgContextStore: OrgContextActions = {
  setCurrentOrgId: (orgId) => setState({ currentOrgId: orgId }),
};

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function getSnapshot() {
  return state;
}

export function useOrgContext(): OrgContextState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
