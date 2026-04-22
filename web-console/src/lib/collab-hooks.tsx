import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ConnectionState,
  createCollabClient,
  createCollabApi,
  CollabApi,
} from '../vendor/collab-client-dist/core.js';
import type {
  CollabClientConfig,
  Document,
  DocumentId,
  EditOperation,
  EditOperationType,
  UserId,
  UserPresence,
} from '../vendor/collab-client-dist/index.js';

export interface UseCollaborationOptions {
  config: CollabClientConfig;
  documentId: DocumentId;
  onContentChange?: (content: string, document: Document) => void;
  onConflict?: (serverDocument: Document) => string | null;
}

export interface UseCollaborationReturn {
  document: Document | null;
  connectionState: ConnectionState;
  isConnected: boolean;
  sendEdit: (type: EditOperationType, position: number, content: string, length?: number) => string;
  insert: (position: number, content: string) => string;
  delete: (position: number, length: number) => string;
  replace: (position: number, length: number, content: string) => string;
  updateCursor: (position: number, selectionEnd?: number) => void;
  cursors: Map<UserId, { position: number; selectionEnd?: number }>;
  presence: Map<UserId, UserPresence>;
  operations: EditOperation[];
  error: { code: string; message: string } | null;
  reconnect: () => void;
  disconnect: () => void;
}

export function useCollaboration(options: UseCollaborationOptions): UseCollaborationReturn {
  const { config, documentId, onContentChange, onConflict } = options;
  const onContentChangeRef = useRef(onContentChange);
  const onConflictRef = useRef(onConflict);

  useEffect(() => {
    onContentChangeRef.current = onContentChange;
  }, [onContentChange]);

  useEffect(() => {
    onConflictRef.current = onConflict;
  }, [onConflict]);

  const {
    baseUrl,
    userId,
    sessionId,
    authToken,
    reconnect: reconnectOptions,
    heartbeatIntervalMs,
    debug,
    getAuthToken: getAuthTokenProp,
  } = config;

  const getAuthTokenRef = useRef(getAuthTokenProp);
  useEffect(() => {
    getAuthTokenRef.current = getAuthTokenProp;
  }, [getAuthTokenProp]);

  const reconnectEnabled = reconnectOptions?.enabled;
  const reconnectMaxAttempts = reconnectOptions?.maxAttempts;
  const reconnectBaseDelayMs = reconnectOptions?.baseDelayMs;
  const reconnectMaxDelayMs = reconnectOptions?.maxDelayMs;
  const hasExplicitReconnectFields =
    reconnectEnabled !== undefined ||
    reconnectMaxAttempts !== undefined ||
    reconnectBaseDelayMs !== undefined ||
    reconnectMaxDelayMs !== undefined;

  const clientRef = useRef<ReturnType<typeof createCollabClient> | null>(null);
  const [clientVersion, setClientVersion] = useState(0);
  const [document, setDocument] = useState<Document | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>(ConnectionState.Disconnected);
  const [cursors, setCursors] = useState<Map<UserId, { position: number; selectionEnd?: number }>>(new Map());
  const [presence, setPresence] = useState<Map<UserId, UserPresence>>(new Map());
  const [operations, setOperations] = useState<EditOperation[]>([]);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  useEffect(() => {
    const client = createCollabClient({
      baseUrl,
      userId,
      sessionId,
      authToken,
      getAuthToken: () => getAuthTokenRef.current?.() ?? Promise.resolve(null),
      reconnect: hasExplicitReconnectFields
        ? {
            enabled: reconnectEnabled,
            maxAttempts: reconnectMaxAttempts,
            baseDelayMs: reconnectBaseDelayMs,
            maxDelayMs: reconnectMaxDelayMs,
          }
        : reconnectOptions,
      heartbeatIntervalMs,
      debug,
    });
    clientRef.current = client;
    queueMicrotask(() => setClientVersion((v) => v + 1));

    const offConnected = client.on('connected', (doc: Document) => {
      setDocument(doc);
      setConnectionState(ConnectionState.Connected);
      setError(null);
      onContentChangeRef.current?.(doc.content, doc);
    });

    const offDisconnected = client.on('disconnected', (reason: string) => {
      setConnectionState(ConnectionState.Disconnected);
      setPresence(new Map());
      setCursors(new Map());
      setError({ code: 'DISCONNECTED', message: reason });
    });

    const offOperation = client.on('operation', (op: EditOperation, doc: Document | null) => {
      if (doc) {
        setDocument(doc);
        onContentChangeRef.current?.(doc.content, doc);
      }
      setOperations((prev) => [...prev.slice(-99), op]);
    });

    const offConflict = client.on('conflict', (_expected: number, _got: number, serverDoc: Document | null) => {
      if (!serverDoc) return;
      const rebased = onConflictRef.current?.(serverDoc);
      if (rebased != null) {
        client.sendEdit({
          operation_type: 'replace' as EditOperationType,
          position: 0,
          content: rebased,
          length: serverDoc.content.length,
        });
      } else {
        setDocument(serverDoc);
        onContentChangeRef.current?.(serverDoc.content, serverDoc);
      }
    });

    const offCursor = client.on('cursor', (userId: UserId, position: number, selectionEnd?: number) => {
      setCursors((prev) => new Map(prev).set(userId, { position, selectionEnd }));
    });

    const offPresence = client.on('presence', (userId: UserId, status: UserPresence['status']) => {
      setPresence((prev) => {
        const next = new Map(prev);
        if (status === 'disconnected') {
          next.delete(userId);
        } else {
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
        }
        return next;
      });
    });

    const offError = client.on('error', (code: string, message: string) => {
      setError({ code, message });
    });

    return () => {
      offConnected();
      offDisconnected();
      offOperation();
      offConflict();
      offCursor();
      offPresence();
      offError();
      client.disconnect();
      client.removeAllListeners();
      clientRef.current = null;
    };
  }, [
    baseUrl,
    userId,
    sessionId,
    authToken,
    reconnectEnabled,
    reconnectMaxAttempts,
    reconnectBaseDelayMs,
    reconnectMaxDelayMs,
    heartbeatIntervalMs,
    debug,
    reconnectOptions,
    hasExplicitReconnectFields,
  ]);

  useEffect(() => {
    if (clientRef.current && documentId) {
      queueMicrotask(() => setConnectionState(ConnectionState.Connecting));
      clientRef.current.connect(documentId);
    }
  }, [documentId, clientVersion]);

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
    [],
  );

  const insert = useCallback((position: number, content: string) => sendEdit('insert' as EditOperationType, position, content), [sendEdit]);
  const deleteOp = useCallback((position: number, length: number) => sendEdit('delete' as EditOperationType, position, '', length), [sendEdit]);
  const replace = useCallback((position: number, length: number, content: string) => sendEdit('replace' as EditOperationType, position, content, length), [sendEdit]);
  const updateCursor = useCallback((position: number, selectionEnd?: number) => clientRef.current?.sendCursor(position, selectionEnd), []);
  const reconnect = useCallback(() => {
    if (clientRef.current && documentId) clientRef.current.connect(documentId);
  }, [documentId]);
  const disconnect = useCallback(() => clientRef.current?.disconnect(), []);

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

export const useCollabDocument = useCollaboration;

export function useCollabApi(config: ConstructorParameters<typeof CollabApi>[0]): CollabApi {
  return useMemo(() => createCollabApi(config), [config]);
}
