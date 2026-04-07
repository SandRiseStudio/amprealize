import React, { memo, useCallback, useEffect, useRef, useState } from 'react';
import {
  ActorType as _ActorType,
  ConnectionState,
  createCollabClient,
  createCollabApi,
  CollabApi,
  CollabApiError,
  ConversationScope,
  ConversationStreamClient,
  createConversationStreamClient,
  ExecutionStreamClient,
  MessageType as _MessageType,
} from '../vendor/collab-client-dist/core.js';

// Re-export enums with local binding to avoid Vite ESM analysis issues
export const ActorType = _ActorType;
export const MessageType = _MessageType;

export {
  ConnectionState,
  ConversationScope,
  ConversationStreamClient,
  createCollabApi,
  createConversationStreamClient,
  CollabApi,
  CollabApiError,
  ExecutionStreamClient,
};

export type {
  CollabClientConfig,
  Conversation,
  ConversationListResponse,
  ConversationMessage,
  ConversationMessageEventPayload,
  ConversationParticipant,
  ConversationParticipantEventPayload,
  ConversationReaction,
  ConversationReactionEventPayload,
  ConversationReadReceiptPayload,
  ConversationStreamConfig,
  ConversationTypingPayload,
  Document,
  DocumentId,
  EditOperation,
  EditOperationType,
  ExecutionListItem,
  ExecutionListResponse,
  ExecutionSnapshotEventPayload,
  ExecutionState,
  ExecutionStatus,
  ExecutionStatusEventPayload,
  ExecutionStatusSnapshotPayload,
  ExecutionStep,
  ExecutionStepEventPayload,
  ExecutionStepSnapshotPayload,
  ExecutionStepsResponse,
  MessageListResponse,
  SearchResult,
  SearchResultsResponse,
  UserId,
  UserPresence,
  Workspace,
  WorkspaceId,
} from '../vendor/collab-client-dist/index.js';

import type {
  CollabClientConfig,
  Document,
  DocumentId,
  EditOperation,
  EditOperationType,
  ExecutionState,
  ExecutionStatus,
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
  onContentChangeRef.current = onContentChange;
  onConflictRef.current = onConflict;

  const clientRef = useRef<ReturnType<typeof createCollabClient> | null>(null);
  const [clientVersion, setClientVersion] = useState(0);
  const [document, setDocument] = useState<Document | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>(ConnectionState.Disconnected);
  const [cursors, setCursors] = useState<Map<UserId, { position: number; selectionEnd?: number }>>(new Map());
  const [presence, setPresence] = useState<Map<UserId, UserPresence>>(new Map());
  const [operations, setOperations] = useState<EditOperation[]>([]);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  useEffect(() => {
    const client = createCollabClient(config);
    clientRef.current = client;
    setClientVersion((v) => v + 1);

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
  }, [config.baseUrl, config.userId, config.sessionId]);

  useEffect(() => {
    if (clientRef.current && documentId) {
      setConnectionState(ConnectionState.Connecting);
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
  const apiRef = useRef<CollabApi | null>(null);
  if (!apiRef.current) {
    apiRef.current = createCollabApi(config);
  }
  return apiRef.current;
}

export interface ExecutionStatusBadgeProps {
  state?: ExecutionState | string | null;
  phase?: string | null;
  statusLabel?: string;
  phaseLabel?: string;
  progressPct?: number | null;
  showPhase?: boolean;
  showProgress?: boolean;
  className?: string;
}

function toTitleLabel(value?: string | null): string {
  if (!value) return 'Unknown';
  return value.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function ExecutionStatusBadge({
  state,
  phase,
  statusLabel,
  phaseLabel,
  progressPct,
  showPhase = true,
  showProgress = false,
  className,
}: ExecutionStatusBadgeProps): React.JSX.Element {
  return (
    <span className={className ?? 'execution-status-badge'} title={phase ? `${toTitleLabel(state)} • ${toTitleLabel(phase)}` : toTitleLabel(state)}>
      <span>{statusLabel ?? toTitleLabel(state)}</span>
      {showPhase && phase ? <span>{` • ${phaseLabel ?? toTitleLabel(phase)}`}</span> : null}
      {showProgress && progressPct != null ? <span>{` • ${Math.round(progressPct)}%`}</span> : null}
    </span>
  );
}

export interface ExecutionStatusCardProps {
  status?: ExecutionStatus | null;
  isLoading?: boolean;
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
  emptyLabel?: string;
  className?: string;
}

export const ExecutionStatusCard = memo(function ExecutionStatusCard({
  status,
  isLoading = false,
  title = 'Execution',
  subtitle,
  actions,
  emptyLabel = 'No execution yet',
  className,
}: ExecutionStatusCardProps): React.JSX.Element {
  const statusText = status?.state ? toTitleLabel(status.state) : emptyLabel;
  return (
    <div className={className ?? 'execution-status-card'}>
      <div>
        <strong>{title}</strong>
        <div>{statusText}</div>
        {subtitle ? <div>{subtitle}</div> : null}
        {status?.phase ? <div>{toTitleLabel(status.phase)}</div> : null}
      </div>
      {isLoading ? <div>Loading…</div> : null}
      {actions ? <div>{actions}</div> : null}
    </div>
  );
});

export interface ClarificationQuestion {
  id: string;
  question: string;
  context?: string | null;
  required?: boolean;
}

export interface ClarificationPanelProps {
  questions: ClarificationQuestion[];
  onSubmit: (questionId: string, response: string) => void;
  isSubmitting?: boolean;
  className?: string;
  title?: string;
  emptyMessage?: string;
  expanded?: boolean;
}

export const ClarificationPanel = memo(function ClarificationPanel({
  questions,
  onSubmit,
  isSubmitting = false,
  className,
  title = 'Clarifications',
  emptyMessage = 'No clarification needed',
}: ClarificationPanelProps): React.JSX.Element {
  const [responses, setResponses] = useState<Record<string, string>>({});

  if (!questions.length) {
    return <div className={className}>{emptyMessage}</div>;
  }

  return (
    <div className={className}>
      <div><strong>{title}</strong></div>
      {questions.map((question) => (
        <div key={question.id}>
          <div>{question.question}</div>
          {question.context ? <div>{question.context}</div> : null}
          <textarea
            value={responses[question.id] ?? ''}
            onChange={(event) => setResponses((prev) => ({ ...prev, [question.id]: event.target.value }))}
            placeholder="Type your answer"
          />
          <button
            type="button"
            onClick={() => onSubmit(question.id, responses[question.id] ?? '')}
            disabled={isSubmitting || !(responses[question.id] ?? '').trim()}
          >
            {isSubmitting ? 'Submitting…' : 'Submit'}
          </button>
        </div>
      ))}
    </div>
  );
});
