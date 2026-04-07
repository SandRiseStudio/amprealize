/**
 * Amprealize collaboration store
 *
 * Central state management for real-time collaboration.
 * Uses zustand-like pattern without external deps for maximum perf.
 */

import { useSyncExternalStore } from 'react';
import type {
  Document,
  DocumentId,
  Workspace,
  WorkspaceId,
  UserPresence,
  UserId,
} from '../lib/collab-client';

// ---------------------------------------------------------------------------
// Store Types
// ---------------------------------------------------------------------------

export interface CollabState {
  // Active entities
  activeWorkspaceId: WorkspaceId | null;
  activeDocumentId: DocumentId | null;

  // Cached data
  workspaces: Map<WorkspaceId, Workspace>;
  documents: Map<DocumentId, Document>;

  // Presence
  presence: Map<UserId, UserPresence>;

  // Connection
  connectionState: 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

  // UI state
  sidebarCollapsed: boolean;
  commandPaletteOpen: boolean;
}

type CollabActions = {
  setActiveWorkspace: (id: WorkspaceId | null) => void;
  setActiveDocument: (id: DocumentId | null) => void;
  addWorkspace: (workspace: Workspace) => void;
  updateWorkspace: (workspace: Workspace) => void;
  addDocument: (document: Document) => void;
  updateDocument: (document: Document) => void;
  setPresence: (userId: UserId, presence: UserPresence | null) => void;
  replacePresence: (presence: Iterable<UserPresence>) => void;
  clearPresence: () => void;
  setConnectionState: (state: CollabState['connectionState']) => void;
  toggleSidebar: () => void;
  toggleCommandPalette: () => void;
};

// ---------------------------------------------------------------------------
// Store Implementation
// ---------------------------------------------------------------------------

const initialState: CollabState = {
  activeWorkspaceId: null,
  activeDocumentId: null,
  workspaces: new Map(),
  documents: new Map(),
  presence: new Map(),
  connectionState: 'disconnected',
  sidebarCollapsed: false,
  commandPaletteOpen: false,
};

let state = { ...initialState };
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((l) => l());
}

function setState(partial: Partial<CollabState>) {
  state = { ...state, ...partial };
  notify();
}

export const collabStore: CollabActions = {
  setActiveWorkspace: (id) => setState({ activeWorkspaceId: id }),
  setActiveDocument: (id) => setState({ activeDocumentId: id }),

  addWorkspace: (workspace) => {
    const next = new Map(state.workspaces);
    next.set(workspace.id, workspace);
    setState({ workspaces: next });
  },

  updateWorkspace: (workspace) => {
    const next = new Map(state.workspaces);
    next.set(workspace.id, workspace);
    setState({ workspaces: next });
  },

  addDocument: (document) => {
    const next = new Map(state.documents);
    next.set(document.id, document);
    setState({ documents: next });
  },

  updateDocument: (document) => {
    const next = new Map(state.documents);
    next.set(document.id, document);
    setState({ documents: next });
  },

  setPresence: (userId, presence) => {
    const next = new Map(state.presence);
    if (presence) {
      next.set(userId, presence);
    } else {
      next.delete(userId);
    }
    setState({ presence: next });
  },

  replacePresence: (presence) => {
    const next = new Map<UserId, UserPresence>();
    for (const item of presence) {
      next.set(item.user_id, item);
    }
    setState({ presence: next });
  },

  clearPresence: () => setState({ presence: new Map() }),

  setConnectionState: (connectionState) => setState({ connectionState }),

  toggleSidebar: () => setState({ sidebarCollapsed: !state.sidebarCollapsed }),

  toggleCommandPalette: () =>
    setState({ commandPaletteOpen: !state.commandPaletteOpen }),
};

// ---------------------------------------------------------------------------
// React Hooks
// ---------------------------------------------------------------------------

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function getSnapshot() {
  return state;
}

export function useCollabStore(): CollabState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function useCollabSelector<T>(selector: (state: CollabState) => T): T {
  const state = useCollabStore();
  return selector(state);
}

// Convenience hooks
export function useActiveWorkspace(): Workspace | null {
  const { activeWorkspaceId, workspaces } = useCollabStore();
  return activeWorkspaceId ? workspaces.get(activeWorkspaceId) ?? null : null;
}

export function useActiveDocument(): Document | null {
  const { activeDocumentId, documents } = useCollabStore();
  return activeDocumentId ? documents.get(activeDocumentId) ?? null : null;
}

export function usePresenceList(): UserPresence[] {
  const { presence } = useCollabStore();
  return Array.from(presence.values());
}

export function useConnectionState(): CollabState['connectionState'] {
  return useCollabSelector((s) => s.connectionState);
}
