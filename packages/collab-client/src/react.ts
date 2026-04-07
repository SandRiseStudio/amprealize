/**
 * React hooks for Amprealize Collaboration
 *
 * Provides useCollaboration hook for easy integration with React components.
 * Works in both SaaS (web-console) and VS Code webviews.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { CollabClient, ConnectionState, createCollabClient, type CollabClientConfig } from './client.js';
import type { Document, DocumentId, EditOperation, EditOperationType, UserId, UserPresence } from './types.js';

// ---------------------------------------------------------------------------
// Hook Types
// ---------------------------------------------------------------------------

export interface UseCollaborationOptions {
  /** Client configuration */
  config: CollabClientConfig;
  /** Document to connect to */
  documentId: DocumentId;
  /** Called when document content changes (local or remote) */
  onContentChange?: (content: string, document: Document) => void;
  /** Called on version conflict - return rebased content or null to use server content */
  onConflict?: (serverDocument: Document) => string | null;
}

export interface UseCollaborationReturn {
  /** Current document state */
  document: Document | null;
  /** Connection state */
  connectionState: ConnectionState;
  /** Whether connected and ready */
  isConnected: boolean;
  /** Send an edit operation */
  sendEdit: (type: EditOperationType, position: number, content: string, length?: number) => string;
  /** Send insert at position */
  insert: (position: number, content: string) => string;
  /** Send delete at position */
  delete: (position: number, length: number) => string;
  /** Send replace at position */
  replace: (position: number, length: number, content: string) => string;
  /** Update cursor position */
  updateCursor: (position: number, selectionEnd?: number) => void;
  /** Remote user cursors */
  cursors: Map<UserId, { position: number; selectionEnd?: number }>;
  /** Remote user presence */
  presence: Map<UserId, UserPresence>;
  /** Recent operations (for undo/redo, debugging) */
  operations: EditOperation[];
  /** Last error */
  error: { code: string; message: string } | null;
  /** Reconnect manually */
  reconnect: () => void;
  /** Disconnect */
  disconnect: () => void;
}

// ---------------------------------------------------------------------------
// useCollaboration Hook
// ---------------------------------------------------------------------------

export function useCollaboration(options: UseCollaborationOptions): UseCollaborationReturn {
  const { config, documentId, onContentChange, onConflict } = options;

  // Refs for stable callbacks
  const onContentChangeRef = useRef(onContentChange);
  const onConflictRef = useRef(onConflict);
  onContentChangeRef.current = onContentChange;
  onConflictRef.current = onConflict;

  // Client instance (stable across renders)
  const clientRef = useRef<CollabClient | null>(null);
  const [clientVersion, setClientVersion] = useState(0);

  // State
  const [document, setDocument] = useState<Document | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>(ConnectionState.Disconnected);
  const [cursors, setCursors] = useState<Map<UserId, { position: number; selectionEnd?: number }>>(new Map());
  const [presence, setPresence] = useState<Map<UserId, UserPresence>>(new Map());
  const [operations, setOperations] = useState<EditOperation[]>([]);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  // Create client on mount
  useEffect(() => {
    const client = createCollabClient(config);
    clientRef.current = client;
    setClientVersion((v) => v + 1);

    // Event handlers
    const handleConnected = (doc: Document) => {
      setDocument(doc);
      setConnectionState(ConnectionState.Connected);
      setError(null);
      onContentChangeRef.current?.(doc.content, doc);
    };

    const handleDisconnected = (reason: string) => {
      setConnectionState(ConnectionState.Disconnected);
      setPresence(new Map());
      setCursors(new Map());
      setError({ code: 'DISCONNECTED', message: reason });
    };

    const handleOperation = (op: EditOperation, doc: Document | null) => {
      if (doc) {
        setDocument(doc);
        onContentChangeRef.current?.(doc.content, doc);
      }
      setOperations((prev) => [...prev.slice(-99), op]); // Keep last 100
    };

    const handleConflict = (_expected: number, _got: number, serverDoc: Document | null) => {
      if (serverDoc) {
        const rebased = onConflictRef.current?.(serverDoc);
        if (rebased !== null && rebased !== undefined) {
          // User provided rebased content - send as replace
          client.sendEdit({
            operation_type: 'replace' as EditOperationType,
            position: 0,
            content: rebased,
            length: serverDoc.content.length,
          });
        } else {
          // Use server content as-is
          setDocument(serverDoc);
          onContentChangeRef.current?.(serverDoc.content, serverDoc);
        }
      }
    };

    const handleCursor = (userId: UserId, position: number, selectionEnd?: number) => {
      setCursors((prev) => {
        const next = new Map(prev);
        next.set(userId, { position, selectionEnd });
        return next;
      });

      setPresence((prev) => {
        const next = new Map(prev);
        const existing = next.get(userId);
        next.set(userId, {
          user_id: userId,
          session_id: existing?.session_id,
          display_name: existing?.display_name,
          color: existing?.color,
          status: existing?.status ?? 'active',
          cursor_position: position,
          selection_end: selectionEnd,
          last_active: new Date().toISOString(),
        });
        return next;
      });
    };

    const handlePresence = (userId: UserId, status: UserPresence['status']) => {
      setPresence((prev) => {
        const next = new Map(prev);
        if (status === 'disconnected') {
          next.delete(userId);
          return next;
        }

        const existing = next.get(userId);
        next.set(userId, {
          user_id: userId,
          session_id: existing?.session_id,
          display_name: existing?.display_name,
          color: existing?.color,
          status,
          cursor_position: existing?.cursor_position,
          selection_end: existing?.selection_end,
          last_active: new Date().toISOString(),
        });
        return next;
      });

      if (status === 'disconnected') {
        setCursors((prev) => {
          const next = new Map(prev);
          next.delete(userId);
          return next;
        });
      }
    };

    const handleError = (code: string, message: string) => {
      setError({ code, message });
    };

    client.on('connected', handleConnected);
    client.on('disconnected', handleDisconnected);
    client.on('operation', handleOperation);
    client.on('conflict', handleConflict);
    client.on('cursor', handleCursor);
    client.on('presence', handlePresence);
    client.on('error', handleError);

    return () => {
      client.disconnect();
      client.removeAllListeners();
      clientRef.current = null;
    };
  }, [config.baseUrl, config.userId, config.sessionId]); // Re-create if config changes

  // Connect to document when documentId changes
  useEffect(() => {
    if (clientRef.current && documentId) {
      setConnectionState(ConnectionState.Connecting);
      clientRef.current.connect(documentId);
    }
  }, [documentId, clientVersion]);

  // Action callbacks
  const sendEdit = useCallback(
    (type: EditOperationType, position: number, content: string, length?: number): string => {
      if (!clientRef.current) return '';
      return clientRef.current.sendEdit({
        operation_type: type,
        position,
        content,
        length,
      });
    },
    []
  );

  const insert = useCallback(
    (position: number, content: string): string => {
      return sendEdit('insert' as EditOperationType, position, content);
    },
    [sendEdit]
  );

  const deleteOp = useCallback(
    (position: number, length: number): string => {
      return sendEdit('delete' as EditOperationType, position, '', length);
    },
    [sendEdit]
  );

  const replace = useCallback(
    (position: number, length: number, content: string): string => {
      return sendEdit('replace' as EditOperationType, position, content, length);
    },
    [sendEdit]
  );

  const updateCursor = useCallback((position: number, selectionEnd?: number) => {
    clientRef.current?.sendCursor(position, selectionEnd);
  }, []);

  const reconnect = useCallback(() => {
    if (clientRef.current && documentId) {
      clientRef.current.connect(documentId);
    }
  }, [documentId]);

  const disconnect = useCallback(() => {
    clientRef.current?.disconnect();
  }, []);

  return {
    document,
    connectionState,
    isConnected: connectionState === ConnectionState.Connected,
    sendEdit,
    insert,
    delete: deleteOp,
    replace,
    updateCursor,
    cursors,
    presence,
    operations,
    error,
    reconnect,
    disconnect,
  };
}

// ---------------------------------------------------------------------------
// useCollabApi Hook (for REST operations)
// ---------------------------------------------------------------------------

import { CollabApi, createCollabApi, type CollabApiConfig } from './api.js';
import type {
  GitHubBranchListResponse,
  GitHubRepoValidationRequest,
  GitHubRepoValidationResponse,
  ProjectSettings,
  UpdateProjectSettingsRequest,
} from './types.js';

export function useCollabApi(config: CollabApiConfig): CollabApi {
  const apiRef = useRef<CollabApi | null>(null);

  if (!apiRef.current) {
    apiRef.current = createCollabApi(config);
  }

  return apiRef.current;
}

// ---------------------------------------------------------------------------
// Project Settings Hooks
// ---------------------------------------------------------------------------

export interface UseProjectSettingsOptions {
  api: CollabApi;
  projectId: string;
  /** Auto-fetch on mount (default: true) */
  autoFetch?: boolean;
}

export interface UseProjectSettingsReturn {
  settings: ProjectSettings | null;
  isLoading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}

/**
 * Hook to fetch project settings.
 */
export function useProjectSettings(options: UseProjectSettingsOptions): UseProjectSettingsReturn {
  const { api, projectId, autoFetch = true } = options;
  const [settings, setSettings] = useState<ProjectSettings | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await api.getProjectSettings(projectId);
      setSettings(result);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setIsLoading(false);
    }
  }, [api, projectId]);

  useEffect(() => {
    if (autoFetch && projectId) {
      refetch();
    }
  }, [autoFetch, projectId, refetch]);

  return { settings, isLoading, error, refetch };
}

export interface UseUpdateProjectSettingsOptions {
  api: CollabApi;
  projectId: string;
  /** Callback on successful update */
  onSuccess?: (settings: ProjectSettings) => void;
  /** Callback on error */
  onError?: (error: Error) => void;
}

export interface UseUpdateProjectSettingsReturn {
  update: (updates: UpdateProjectSettingsRequest) => Promise<ProjectSettings | null>;
  isUpdating: boolean;
  error: Error | null;
}

/**
 * Hook to update project settings.
 */
export function useUpdateProjectSettings(
  options: UseUpdateProjectSettingsOptions
): UseUpdateProjectSettingsReturn {
  const { api, projectId, onSuccess, onError } = options;
  const [isUpdating, setIsUpdating] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const update = useCallback(
    async (updates: UpdateProjectSettingsRequest): Promise<ProjectSettings | null> => {
      setIsUpdating(true);
      setError(null);
      try {
        const result = await api.updateProjectSettings(projectId, updates);
        onSuccess?.(result);
        return result;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        onError?.(error);
        return null;
      } finally {
        setIsUpdating(false);
      }
    },
    [api, projectId, onSuccess, onError]
  );

  return { update, isUpdating, error };
}

export interface UseValidateGitHubRepoOptions {
  api: CollabApi;
  projectId: string;
}

export interface UseValidateGitHubRepoReturn {
  validate: (request: GitHubRepoValidationRequest) => Promise<GitHubRepoValidationResponse | null>;
  isValidating: boolean;
  result: GitHubRepoValidationResponse | null;
  error: Error | null;
}

/**
 * Hook to validate a GitHub repository.
 */
export function useValidateGitHubRepo(
  options: UseValidateGitHubRepoOptions
): UseValidateGitHubRepoReturn {
  const { api, projectId } = options;
  const [isValidating, setIsValidating] = useState(false);
  const [result, setResult] = useState<GitHubRepoValidationResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const validate = useCallback(
    async (request: GitHubRepoValidationRequest): Promise<GitHubRepoValidationResponse | null> => {
      setIsValidating(true);
      setError(null);
      try {
        const response = await api.validateGitHubRepository(projectId, request);
        setResult(response);
        return response;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        return null;
      } finally {
        setIsValidating(false);
      }
    },
    [api, projectId]
  );

  return { validate, isValidating, result, error };
}

export interface UseGitHubBranchesOptions {
  api: CollabApi;
  projectId: string;
  /** Auto-fetch on mount (default: false) */
  autoFetch?: boolean;
}

export interface UseGitHubBranchesReturn {
  branches: GitHubBranchListResponse | null;
  isLoading: boolean;
  error: Error | null;
  refetch: (page?: number, perPage?: number) => Promise<void>;
}

/**
 * Hook to list GitHub branches for a project's repository.
 */
export function useGitHubBranches(options: UseGitHubBranchesOptions): UseGitHubBranchesReturn {
  const { api, projectId, autoFetch = false } = options;
  const [branches, setBranches] = useState<GitHubBranchListResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(
    async (page = 1, perPage = 30) => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await api.listGitHubBranches(projectId, page, perPage);
        setBranches(result);
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        setIsLoading(false);
      }
    },
    [api, projectId]
  );

  useEffect(() => {
    if (autoFetch && projectId) {
      refetch();
    }
  }, [autoFetch, projectId, refetch]);

  return { branches, isLoading, error, refetch };
}
