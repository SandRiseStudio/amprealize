/**
 * Conversations API hooks (web console)
 *
 * Real-time WebSocket integration + TanStack Query REST hooks.
 *
 * Following:
 * - CONVERSATION_SYSTEM_PLAN.md: conversation system architecture
 * - behavior_use_raze_for_logging (Student)
 * - behavior_design_api_contract (Student)
 */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import {
  ConnectionState,
  ConversationStreamClient,
  createConversationStreamClient,
  type Conversation,
  type ConversationListResponse,
  type ConversationMessage,
  type ConversationMessageEventPayload,
  type ConversationParticipant,
  type ConversationReactionEventPayload,
  type ConversationStreamConfig,
  type ConversationTypingPayload,
  type MessageListResponse,
  type SearchResultsResponse,
} from '../lib/collab-client';
import { apiClient, ApiError, API_ORIGIN } from './client';
import { razeLog } from '../telemetry/raze';

// ---------------------------------------------------------------------------
// Query key factory
// ---------------------------------------------------------------------------

export const conversationKeys = {
  all: ['conversations'] as const,
  lists: () => [...conversationKeys.all, 'list'] as const,
  list: (projectId: string, filters?: Record<string, unknown>) =>
    [...conversationKeys.lists(), projectId, filters] as const,
  details: () => [...conversationKeys.all, 'detail'] as const,
  detail: (conversationId: string) =>
    [...conversationKeys.details(), conversationId] as const,
  messagesPrefix: (conversationId: string) =>
    [...conversationKeys.all, 'messages', conversationId] as const,
  messages: (conversationId: string, filters?: Record<string, unknown>) =>
    [...conversationKeys.messagesPrefix(conversationId), filters] as const,
  participants: (conversationId: string) =>
    [...conversationKeys.all, 'participants', conversationId] as const,
  search: (conversationId: string, query: string) =>
    [...conversationKeys.all, 'search', conversationId, query] as const,
};

function isInfiniteMessageData(
  data: MessageListResponse | InfiniteData<MessageListResponse> | undefined,
): data is InfiniteData<MessageListResponse> {
  return !!data && typeof data === 'object' && 'pages' in data && Array.isArray(data.pages);
}

function updateMessageCollections(
  qc: ReturnType<typeof useQueryClient>,
  conversationId: string,
  updater: (messages: ConversationMessage[]) => ConversationMessage[],
): void {
  qc.setQueriesData(
    { queryKey: conversationKeys.messagesPrefix(conversationId) },
    (old: MessageListResponse | InfiniteData<MessageListResponse> | undefined) => {
      if (!old) return old;

      if (isInfiniteMessageData(old)) {
        return {
          ...old,
          pages: old.pages.map((page) => ({
            ...page,
            items: updater(page.items),
          })),
        };
      }

      const nextItems = updater(old.items);
      return {
        ...old,
        items: nextItems,
      };
    },
  );
}

function appendMessageToCollections(
  qc: ReturnType<typeof useQueryClient>,
  conversationId: string,
  message: ConversationMessage,
): void {
  qc.setQueriesData(
    { queryKey: conversationKeys.messagesPrefix(conversationId) },
    (old: MessageListResponse | InfiniteData<MessageListResponse> | undefined) => {
      if (!old) return old;

      if (isInfiniteMessageData(old)) {
        if (old.pages.some((page) => page.items.some((item) => item.id === message.id))) {
          return old;
        }

        const lastPageIndex = old.pages.length - 1;
        return {
          ...old,
          pages: old.pages.map((page, index) => {
            if (index !== lastPageIndex) {
              return page;
            }

            return {
              ...page,
              items: [...page.items, message],
              total: page.total + 1,
            };
          }),
        };
      }

      if (old.items.some((item) => item.id === message.id)) {
        return old;
      }

      return {
        ...old,
        items: [...old.items, message],
        total: old.total + 1,
      };
    },
  );
}

// ---------------------------------------------------------------------------
// Query hooks
// ---------------------------------------------------------------------------

interface UseConversationsOptions {
  projectId: string;
  scope?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function useConversations(opts: UseConversationsOptions) {
  const { projectId, scope, includeArchived, limit = 50, offset = 0, enabled = true } = opts;
  const filters = { scope, includeArchived, limit, offset };
  return useQuery<ConversationListResponse>({
    queryKey: conversationKeys.list(projectId, filters),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (scope) params.set('scope', scope);
      if (includeArchived) params.set('include_archived', 'true');
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      const qs = params.toString();
      return apiClient.get<ConversationListResponse>(
        `/v1/projects/${projectId}/conversations${qs ? `?${qs}` : ''}`,
      );
    },
    enabled: enabled && !!projectId,
    staleTime: 5_000,
  });
}

export function useConversation(conversationId: string | undefined) {
  return useQuery<Conversation>({
    queryKey: conversationKeys.detail(conversationId ?? ''),
    queryFn: () => apiClient.get<Conversation>(`/v1/conversations/${conversationId}`),
    enabled: !!conversationId,
    staleTime: 10_000,
  });
}

interface UseMessagesOptions {
  conversationId: string;
  parentId?: string;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function useMessages(opts: UseMessagesOptions) {
  const { conversationId, parentId, limit = 50, offset = 0, enabled = true } = opts;
  const filters = { parentId, limit, offset };
  return useQuery<MessageListResponse>({
    queryKey: conversationKeys.messages(conversationId, filters),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (parentId) params.set('parent_id', parentId);
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      const qs = params.toString();
      return apiClient.get<MessageListResponse>(
        `/v1/conversations/${conversationId}/messages${qs ? `?${qs}` : ''}`,
      );
    },
    enabled: enabled && !!conversationId,
    staleTime: 2_000,
  });
}

interface UseInfiniteMessagesOptions {
  conversationId: string;
  parentId?: string;
  limit?: number;
  enabled?: boolean;
}

export function useInfiniteMessages(opts: UseInfiniteMessagesOptions) {
  const { conversationId, parentId, limit = 50, enabled = true } = opts;
  return useInfiniteQuery<MessageListResponse>({
    queryKey: conversationKeys.messages(conversationId, { parentId, limit, infinite: true }),
    queryFn: async ({ pageParam = 0 }) => {
      const params = new URLSearchParams();
      if (parentId) params.set('parent_id', parentId);
      params.set('limit', String(limit));
      params.set('offset', String(pageParam));
      const qs = params.toString();
      return apiClient.get<MessageListResponse>(
        `/v1/conversations/${conversationId}/messages${qs ? `?${qs}` : ''}`,
      );
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      if (!lastPage.has_more) return undefined;
      return allPages.reduce((acc, p) => acc + p.items.length, 0);
    },
    enabled: enabled && !!conversationId,
    staleTime: 2_000,
  });
}

export function useConversationParticipants(conversationId: string | undefined) {
  return useQuery<{ items: ConversationParticipant[]; total: number }>({
    queryKey: conversationKeys.participants(conversationId ?? ''),
    queryFn: () =>
      apiClient.get<{ items: ConversationParticipant[]; total: number }>(
        `/v1/conversations/${conversationId}/participants`,
      ),
    enabled: !!conversationId,
    staleTime: 30_000,
  });
}

interface UseSearchMessagesOptions {
  conversationId: string;
  query: string;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function useSearchMessages(opts: UseSearchMessagesOptions) {
  const { conversationId, query, limit = 20, offset = 0, enabled = true } = opts;
  return useQuery<SearchResultsResponse>({
    queryKey: conversationKeys.search(conversationId, query),
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set('q', query);
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      return apiClient.get<SearchResultsResponse>(
        `/v1/conversations/${conversationId}/search?${params.toString()}`,
      );
    },
    enabled: enabled && !!conversationId && query.length > 0,
    staleTime: 10_000,
  });
}

// ---------------------------------------------------------------------------
// Mutation hooks
// ---------------------------------------------------------------------------

interface CreateConversationVars {
  projectId: string;
  scope: string;
  title?: string;
  participantIds?: string[];
}

export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation<Conversation, ApiError, CreateConversationVars>({
    mutationFn: async ({ projectId, scope, title, participantIds }) => {
      return apiClient.post<Conversation>(
        `/v1/projects/${projectId}/conversations`,
        {
          scope,
          title: title ?? null,
          participant_ids: participantIds ?? [],
        },
      );
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.lists() });
      razeLog('INFO', 'conversation.created', { project_id: vars.projectId });
    },
  });
}

// ---------------------------------------------------------------------------
// Direct conversation (get-or-create 1:1 DM)
// ---------------------------------------------------------------------------

interface DirectConversationVars {
  projectId: string;
  targetParticipantId: string;
  actorType?: 'user' | 'agent';
}

interface DirectConversationResult {
  conversation: Conversation;
  created: boolean;
}

export function useGetOrCreateDirectConversation() {
  const qc = useQueryClient();
  return useMutation<DirectConversationResult, ApiError, DirectConversationVars>({
    mutationFn: async ({ projectId, targetParticipantId, actorType }) => {
      return apiClient.post<DirectConversationResult>(
        `/v1/projects/${projectId}/conversations/direct`,
        {
          target_participant_id: targetParticipantId,
          actor_type: actorType ?? null,
        },
      );
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.lists() });
      razeLog('INFO', 'conversation.direct.resolved', {
        project_id: vars.projectId,
        created: _data.created,
      });
    },
  });
}

interface SendMessageVars {
  conversationId: string;
  content: string;
  messageType?: string;
  structuredPayload?: Record<string, unknown>;
  parentId?: string;
  runId?: string;
  behaviorId?: string;
  workItemId?: string;
  metadata?: Record<string, unknown>;
}

export function useSendMessage() {
  const qc = useQueryClient();
  return useMutation<ConversationMessage, ApiError, SendMessageVars>({
    mutationFn: async ({
      conversationId,
      content,
      messageType,
      structuredPayload,
      parentId,
      runId,
      behaviorId,
      workItemId,
      metadata,
    }) => {
      return apiClient.post<ConversationMessage>(
        `/v1/conversations/${conversationId}/messages`,
        {
          content,
          message_type: messageType ?? 'text',
          structured_payload: structuredPayload ?? null,
          parent_id: parentId ?? null,
          run_id: runId ?? null,
          behavior_id: behaviorId ?? null,
          work_item_id: workItemId ?? null,
          metadata: metadata ?? {},
        },
      );
    },
    onSuccess: (data, vars) => {
      appendMessageToCollections(qc, vars.conversationId, data);
      qc.invalidateQueries({ queryKey: conversationKeys.messagesPrefix(vars.conversationId) });
      razeLog('INFO', 'conversation.message.sent', { conversation_id: vars.conversationId });
    },
  });
}

interface EditMessageVars {
  messageId: string;
  content: string;
  conversationId: string; // for cache invalidation
}

export function useEditMessage() {
  const qc = useQueryClient();
  return useMutation<ConversationMessage, ApiError, EditMessageVars>({
    mutationFn: async ({ messageId, content }) => {
      return apiClient.patch<ConversationMessage>(`/v1/messages/${messageId}`, {
        content,
      });
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.messagesPrefix(vars.conversationId) });
    },
  });
}

interface DeleteMessageVars {
  messageId: string;
  conversationId: string;
}

export function useDeleteMessage() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, DeleteMessageVars>({
    mutationFn: async ({ messageId }) => {
      return apiClient.delete<void>(`/v1/messages/${messageId}`);
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.messagesPrefix(vars.conversationId) });
    },
  });
}

interface AddReactionVars {
  messageId: string;
  emoji: string;
  conversationId: string;
}

export function useAddReaction() {
  const qc = useQueryClient();
  return useMutation<unknown, ApiError, AddReactionVars>({
    mutationFn: async ({ messageId, emoji }) => {
      return apiClient.post(`/v1/messages/${messageId}/reactions?emoji=${encodeURIComponent(emoji)}`, {});
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.messagesPrefix(vars.conversationId) });
    },
  });
}

interface RemoveReactionVars {
  messageId: string;
  emoji: string;
  conversationId: string;
}

export function useRemoveReaction() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, RemoveReactionVars>({
    mutationFn: async ({ messageId, emoji }) => {
      return apiClient.delete<void>(
        `/v1/messages/${messageId}/reactions?emoji=${encodeURIComponent(emoji)}`,
      );
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.messagesPrefix(vars.conversationId) });
    },
  });
}

interface ArchiveConversationVars {
  conversationId: string;
}

export function useArchiveConversation() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, ArchiveConversationVars>({
    mutationFn: async ({ conversationId }) => {
      return apiClient.post<void>(`/v1/conversations/${conversationId}/archive`, {});
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: conversationKeys.all });
      razeLog('INFO', 'conversation.archived', {});
    },
  });
}

interface PinMessageVars {
  conversationId: string;
  messageId: string;
}

export function usePinMessage() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, PinMessageVars>({
    mutationFn: async ({ conversationId, messageId }) => {
      return apiClient.put<void>(`/v1/conversations/${conversationId}/pin`, {
        message_id: messageId,
      });
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.detail(vars.conversationId) });
    },
  });
}

interface UnpinMessageVars {
  conversationId: string;
}

export function useUnpinMessage() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, UnpinMessageVars>({
    mutationFn: async ({ conversationId }) => {
      return apiClient.delete<void>(`/v1/conversations/${conversationId}/pin`);
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.detail(vars.conversationId) });
    },
  });
}

interface UpdateMyParticipantVars {
  conversationId: string;
  lastReadMessageId?: string;
  isMuted?: boolean;
  notificationPreference?: string;
}

export function useUpdateMyParticipant() {
  const qc = useQueryClient();
  return useMutation<unknown, ApiError, UpdateMyParticipantVars>({
    mutationFn: async ({ conversationId, lastReadMessageId, isMuted, notificationPreference }) => {
      return apiClient.patch(
        `/v1/conversations/${conversationId}/participants/me`,
        {
          last_read_message_id: lastReadMessageId ?? null,
          is_muted: isMuted ?? null,
          notification_preference: notificationPreference ?? null,
        },
      );
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.participants(vars.conversationId) });
    },
  });
}

// ---------------------------------------------------------------------------
// WebSocket live-stream hook (ConversationStreamClient → TanStack cache)
// ---------------------------------------------------------------------------

export interface UseConversationSocketResult {
  connectionState: ConnectionState;
  typingUsers: Map<string, ConversationTypingPayload>;
}

export function useConversationSocket(
  conversationId: string | undefined,
  userId: string | undefined,
): UseConversationSocketResult {
  const qc = useQueryClient();
  const clientRef = useRef<ConversationStreamClient | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>(
    ConnectionState.Disconnected,
  );
  const [typingUsers, setTypingUsers] = useState<Map<string, ConversationTypingPayload>>(
    new Map(),
  );
  const normalizedConversationId =
    conversationId && conversationId !== 'null' && conversationId !== 'undefined'
      ? conversationId
      : undefined;

  useEffect(() => {
    if (!userId) {
      clientRef.current?.disconnect();
      clientRef.current = null;
      return;
    }

    const token = apiClient.getToken?.() ?? '';

    const config: ConversationStreamConfig = {
      baseUrl: API_ORIGIN,
      userId,
      authToken: token,
      getAuthToken: async () => apiClient.getToken?.() ?? null,
      reconnect: { enabled: true },
      debug: import.meta.env.DEV,
    };

    const client = createConversationStreamClient(config);
    clientRef.current = client;

    // -- Connection events --
    const offConnected = client.on('connected', (payload) => {
      setConnectionState(ConnectionState.Connected);
      razeLog('INFO', 'conversation.ws.connected', { conversation_id: payload.conversation_id });
    });
    const offDisconnected = client.on('disconnected', () => {
      setConnectionState(ConnectionState.Disconnected);
      setTypingUsers(new Map());
    });

    // -- Message events → merge into cache --
    const offMessageNew = client.on('message.new', (payload: ConversationMessageEventPayload) => {
      appendMessageToCollections(qc, payload.conversation_id, payload.message);
    });

    const offMessageUpdated = client.on('message.updated', (payload: ConversationMessageEventPayload) => {
      updateMessageCollections(qc, payload.conversation_id, (items) =>
        items.map((m) => (m.id === payload.message.id ? payload.message : m)),
      );
    });

    const offMessageDeleted = client.on('message.deleted', (payload: ConversationMessageEventPayload) => {
      updateMessageCollections(qc, payload.conversation_id, (items) =>
        items.map((m) =>
          m.id === payload.message.id
            ? { ...m, is_deleted: true, content: '' }
            : m,
        ),
      );
    });

    const offReactionAdded = client.on('reaction.added', (payload: ConversationReactionEventPayload) => {
      updateMessageCollections(qc, payload.conversation_id, (items) =>
        items.map((m) =>
          m.id === payload.message_id
            ? { ...m, reactions: [...(m.reactions ?? []), payload.reaction] }
            : m,
        ),
      );
    });

    const offReactionRemoved = client.on('reaction.removed', (payload: ConversationReactionEventPayload) => {
      updateMessageCollections(qc, payload.conversation_id, (items) =>
        items.map((m) =>
          m.id === payload.message_id
            ? {
                ...m,
                reactions: (m.reactions ?? []).filter(
                  (r) => r.id !== payload.reaction.id,
                ),
              }
            : m,
        ),
      );
    });

    const offTyping = client.on('typing.indicator', (payload: ConversationTypingPayload) => {
      setTypingUsers((prev) => {
        const next = new Map(prev);
        if (payload.is_typing) {
          next.set(payload.actor_id, payload);
        } else {
          next.delete(payload.actor_id);
        }
        return next;
      });
    });

    const offReadReceipt = client.on('read.receipt', (payload) => {
      qc.invalidateQueries({ queryKey: conversationKeys.participants(payload.conversation_id) });
    });
    const offParticipantJoined = client.on('participant.joined', (payload) => {
      qc.invalidateQueries({ queryKey: conversationKeys.participants(payload.conversation_id) });
    });
    const offParticipantLeft = client.on('participant.left', (payload) => {
      qc.invalidateQueries({ queryKey: conversationKeys.participants(payload.conversation_id) });
    });

    return () => {
      client.disconnect();
      offConnected();
      offDisconnected();
      offMessageNew();
      offMessageUpdated();
      offMessageDeleted();
      offReactionAdded();
      offReactionRemoved();
      offTyping();
      offReadReceipt();
      offParticipantJoined();
      offParticipantLeft();
      clientRef.current = null;
    };
  }, [userId, qc]);

  useEffect(() => {
    const client = clientRef.current;

    if (!client || !userId) {
      return;
    }

    if (!normalizedConversationId) {
      client.disconnect('missing_conversation');
      return;
    }

    client.connect(normalizedConversationId);
  }, [normalizedConversationId, userId]);

  return { connectionState, typingUsers };
}

// ---------------------------------------------------------------------------
// SSE hook for agent token streaming
// ---------------------------------------------------------------------------

export interface UseMessageStreamResult {
  tokens: string[];
  fullText: string;
  isStreaming: boolean;
  error: string | null;
}

export function useMessageStream(
  conversationId: string | undefined,
  messageId: string | undefined,
): UseMessageStreamResult {
  const [tokens, setTokens] = useState<string[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!conversationId || !messageId) return;

    const token = apiClient.getToken?.() ?? '';
    const url = `${API_ORIGIN}/api/v1/conversations/${conversationId}/stream/${messageId}?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);

    es.onopen = () => {
      setIsStreaming(true);
      setTokens([]);
      setError(null);
    };

    es.addEventListener('token', (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setTokens((prev) => [...prev, data.token]);
      } catch {
        // ignore malformed token events
      }
    });

    es.addEventListener('complete', () => {
      setIsStreaming(false);
      es.close();
    });

    es.addEventListener('error', () => {
      // EventSource fires a generic error on connection close
      if (es.readyState === EventSource.CLOSED) {
        setIsStreaming(false);
        return;
      }
      setError('Stream connection lost');
      setIsStreaming(false);
      es.close();
    });

    return () => {
      es.close();
      setIsStreaming(false);
    };
  }, [conversationId, messageId]);

  const fullText = tokens.join('');

  return { tokens, fullText, isStreaming, error };
}
