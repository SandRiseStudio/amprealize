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
  ConversationScope,
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
import { perfMark, razeLog } from '../telemetry/raze';

// ---------------------------------------------------------------------------
// Chat load timing (mirror boardLoadBench logging shape).
// Production: localStorage.setItem('amprealize.chatLoadBench', '1') then reload.
// Development: on by default; disable with setItem('amprealize.chatLoadBench', '0').
// Emits console [chatLoadBench] lines + performance.mark('perf:chat:…').
// ---------------------------------------------------------------------------

const CHAT_LOAD_BENCH_LS_KEY = 'amprealize.chatLoadBench';

/**
 * Per-conversation counter for `[chatLoadBench]` `messages_page_fetch` so the first REST
 * page for a thread is always `fetch_seq: 1` (session-global counting was misleading when
 * switching conversations).
 */
const chatBenchMessagesFetchSeqByConversation = new Map<string, number>();
/** Optional cross-thread counter for correlating all message fetches in one tab session. */
let chatBenchMessagesFetchSeqSession = 0;

function isViteDev(): boolean {
  try {
    return typeof import.meta !== 'undefined' && import.meta.env?.DEV === true;
  } catch {
    return false;
  }
}

/** True when client-side chat load benchmarking is enabled. */
export function isChatLoadBenchEnabled(): boolean {
  try {
    if (typeof localStorage === 'undefined') return false;
    const raw = localStorage.getItem(CHAT_LOAD_BENCH_LS_KEY);
    if (raw === '0' || raw === 'off') return false;
    if (raw === '1') return true;
    return isViteDev();
  } catch {
    return false;
  }
}

function chatLoadBench(phase: string, detail: Record<string, unknown>): void {
  if (!isChatLoadBenchEnabled()) return;
  console.log('[chatLoadBench]', { phase, ...detail });
  razeLog('INFO', `chat.perf.${phase}`, {
    ...detail,
    phase,
    actor_surface: 'web',
  }).catch(() => {});
}

function chatLoadBenchMark(name: string, detail: Record<string, unknown> = {}): void {
  if (!isChatLoadBenchEnabled()) return;
  try {
    perfMark(`chat:${name}`, detail);
  } catch {
    /* perf API missing in test env */
  }
}

/** UI-layer milestones (e.g. spinner cleared) — console + perf mark when bench is on. */
export function chatLoadBenchPhase(phase: string, detail: Record<string, unknown>): void {
  chatLoadBench(phase, detail);
  chatLoadBenchMark(phase, detail);
}

/** Dedupes React Strict Mode remount double-fire for the same thread (~120ms). */
let threadFirstPaintBenchMs = 0;
let threadFirstPaintBenchConversationId: string | null = null;

export function chatLoadBenchThreadFirstPaint(conversationId: string, detail: Record<string, unknown>): void {
  if (!isChatLoadBenchEnabled()) return;
  const now = performance.now();
  if (
    threadFirstPaintBenchConversationId === conversationId &&
    now - threadFirstPaintBenchMs < 120
  ) {
    return;
  }
  threadFirstPaintBenchConversationId = conversationId;
  threadFirstPaintBenchMs = now;
  chatLoadBenchPhase('thread_first_paint', detail);
}

// ---------------------------------------------------------------------------
// Query key factory
// ---------------------------------------------------------------------------

export const conversationKeys = {
  all: ['conversations'] as const,
  lists: () => [...conversationKeys.all, 'list'] as const,
  list: (projectId: string | null, filters?: Record<string, unknown>) =>
    [...conversationKeys.lists(), projectId ?? 'global', filters] as const,
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

/** API lists messages newest-first; cache merges must keep that order (prepend to page 0). */
function dedupeMessagesById(items: ConversationMessage[]): ConversationMessage[] {
  const seen = new Set<string>();
  const out: ConversationMessage[] = [];
  for (const m of items) {
    if (seen.has(m.id)) continue;
    seen.add(m.id);
    out.push(m);
  }
  return out;
}

function stripOptimisticDuplicate(
  items: ConversationMessage[],
  incoming: ConversationMessage,
): ConversationMessage[] {
  return items.filter((item) => {
    if (!item.id.startsWith('optimistic-')) return true;
    const meta = item.metadata as Record<string, unknown> | undefined;
    if (meta?.optimistic !== true) return true;
    return !(
      item.sender_id === incoming.sender_id &&
      item.content === incoming.content
    );
  });
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
        const pagesStripped = old.pages.map((page) => ({
          ...page,
          items: stripOptimisticDuplicate(page.items, message),
        }));

        if (pagesStripped.some((page) => page.items.some((item) => item.id === message.id))) {
          return {
            ...old,
            pages: pagesStripped.map((page) => ({
              ...page,
              items: dedupeMessagesById(page.items),
            })),
          };
        }

        const first = pagesStripped[0];
        return {
          ...old,
          pages: [
            {
              ...first,
              items: dedupeMessagesById([message, ...first.items]),
            },
            ...pagesStripped.slice(1).map((page) => ({
              ...page,
              items: dedupeMessagesById(page.items),
            })),
          ],
        };
      }

      const stripped = stripOptimisticDuplicate(old.items, message);
      if (stripped.some((item) => item.id === message.id)) {
        return { ...old, items: dedupeMessagesById(stripped) };
      }

      return {
        ...old,
        items: dedupeMessagesById([message, ...stripped]),
      };
    },
  );
}

function removeMessageFromCollections(
  qc: ReturnType<typeof useQueryClient>,
  conversationId: string,
  messageId: string,
): void {
  qc.setQueriesData(
    { queryKey: conversationKeys.messagesPrefix(conversationId) },
    (old: MessageListResponse | InfiniteData<MessageListResponse> | undefined) => {
      if (!old) return old;

      if (isInfiniteMessageData(old)) {
        return {
          ...old,
          pages: old.pages.map((page) => {
            const nextItems = page.items.filter((item) => item.id !== messageId);
            const removed = page.items.length - nextItems.length;
            const nextTotal = page.total >= 0 ? page.total - removed : page.total;
            return {
              ...page,
              items: nextItems,
              total: nextTotal,
            };
          }),
        };
      }

      const nextItems = old.items.filter((item) => item.id !== messageId);
      const removed = old.items.length - nextItems.length;
      const nextTotal = old.total >= 0 ? old.total - removed : old.total;
      return {
        ...old,
        items: nextItems,
        total: nextTotal,
      };
    },
  );
}

function replaceMessageInCollections(
  qc: ReturnType<typeof useQueryClient>,
  conversationId: string,
  messageId: string,
  replacement: ConversationMessage,
): boolean {
  let replaced = false;
  qc.setQueriesData(
    { queryKey: conversationKeys.messagesPrefix(conversationId) },
    (old: MessageListResponse | InfiniteData<MessageListResponse> | undefined) => {
      if (!old) return old;

      if (isInfiniteMessageData(old)) {
        return {
          ...old,
          pages: old.pages.map((page) => ({
            ...page,
            items: dedupeMessagesById(
              page.items.map((item) => {
                if (item.id !== messageId) return item;
                replaced = true;
                return replacement;
              }),
            ),
          })),
        };
      }

      return {
        ...old,
        items: dedupeMessagesById(
          old.items.map((item) => {
            if (item.id !== messageId) return item;
            replaced = true;
            return replacement;
          }),
        ),
      };
    },
  );
  return replaced;
}

// ---------------------------------------------------------------------------
// Query hooks
// ---------------------------------------------------------------------------

interface UseConversationsOptions {
  projectId?: string | null;
  /** Single scope (ignored when `scopes` is set). */
  scope?: string;
  /** Union of several scopes in one request (sidebar global buckets). */
  scopes?: string[];
  includeArchived?: boolean;
  /** When false, server skips COUNT; `total` is -1. */
  includeTotal?: boolean;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function useConversations(opts: UseConversationsOptions) {
  const {
    projectId,
    scope,
    scopes,
    includeArchived,
    includeTotal = true,
    limit = 50,
    offset = 0,
    enabled = true,
  } = opts;
  const filters = { scope, scopes, includeArchived, includeTotal, limit, offset };
  return useQuery<ConversationListResponse>({
    queryKey: conversationKeys.list(projectId ?? null, filters),
    queryFn: async () => {
      const t0 = performance.now();
      const params = new URLSearchParams();
      if (scopes?.length) {
        for (const s of scopes) params.append('scopes', s);
      } else if (scope) {
        params.set('scope', scope);
      }
      if (includeArchived) params.set('include_archived', 'true');
      if (!includeTotal) params.set('include_total', 'false');
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      const qs = params.toString();
      const basePath = projectId ? `/v1/projects/${projectId}/conversations` : '/v1/conversations';
      const data = await apiClient.get<ConversationListResponse>(
        `${basePath}${qs ? `?${qs}` : ''}`,
      );
      if (isChatLoadBenchEnabled()) {
        const duration_ms = Math.round(performance.now() - t0);
        const detail = {
          duration_ms,
          project_id: projectId ?? 'global',
          item_count: data.items.length,
          total: data.total,
          limit,
          offset,
        };
        chatLoadBench('conversation_list_fetch', detail);
        chatLoadBenchMark('conversation_list_fetch', detail);
      }
      return data;
    },
    enabled,
    staleTime: 5_000,
    refetchOnWindowFocus: false,
  });
}

export function useConversation(conversationId: string | undefined) {
  return useQuery<Conversation>({
    queryKey: conversationKeys.detail(conversationId ?? ''),
    queryFn: async () => {
      const t0 = performance.now();
      const data = await apiClient.get<Conversation>(`/v1/conversations/${conversationId}`);
      if (isChatLoadBenchEnabled()) {
        const duration_ms = Math.round(performance.now() - t0);
        const detail = { conversation_id: conversationId, duration_ms };
        chatLoadBench('conversation_detail_fetch', detail);
        chatLoadBenchMark('conversation_detail_fetch', detail);
      }
      return data;
    },
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
  /**
   * When true (default), request full transcript including replies (assistant messages use parent_id).
   * Set false only for a roots-only feed.
   */
  includeThreadReplies?: boolean;
  /** When false, server skips COUNT; `total` is -1 (pagination uses has_more). */
  includeTotal?: boolean;
}

export function useInfiniteMessages(opts: UseInfiniteMessagesOptions) {
  const {
    conversationId,
    parentId,
    limit = 50,
    enabled = true,
    includeThreadReplies = true,
    includeTotal = false,
  } = opts;
  return useInfiniteQuery<MessageListResponse>({
    queryKey: conversationKeys.messages(conversationId, {
      parentId,
      limit,
      infinite: true,
      includeThreadReplies,
      includeTotal,
    }),
    queryFn: async ({ pageParam = 0, direction }) => {
      const t0 = performance.now();
      const params = new URLSearchParams();
      if (parentId) params.set('parent_id', parentId);
      if (includeThreadReplies && !parentId) {
        params.set('include_thread_replies', 'true');
      }
      if (!includeTotal) params.set('include_total', 'false');
      params.set('limit', String(limit));
      params.set('offset', String(pageParam));
      const qs = params.toString();
      const data = await apiClient.get<MessageListResponse>(
        `/v1/conversations/${conversationId}/messages${qs ? `?${qs}` : ''}`,
      );
      if (isChatLoadBenchEnabled()) {
        const duration_ms = Math.round(performance.now() - t0);
        const offset = Number(pageParam);
        const page_index = limit > 0 ? Math.floor(offset / limit) : 0;
        chatBenchMessagesFetchSeqSession += 1;
        const convSeq = (chatBenchMessagesFetchSeqByConversation.get(conversationId) ?? 0) + 1;
        chatBenchMessagesFetchSeqByConversation.set(conversationId, convSeq);
        const detail: Record<string, unknown> = {
          fetch_seq: convSeq,
          fetch_seq_session: chatBenchMessagesFetchSeqSession,
          conversation_id: conversationId,
          duration_ms,
          offset,
          limit,
          page_item_count: data.items.length,
          total: data.total,
          has_more: data.has_more,
          page_index,
          direction,
          include_thread_replies: Boolean(includeThreadReplies && !parentId),
        };
        chatLoadBench('messages_page_fetch', detail);
        chatLoadBenchMark('messages_page_fetch', detail);
        if (offset === 0) {
          chatLoadBenchMark('messages_first_page', detail);
        }
      }
      return data;
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      if (!lastPage.has_more) return undefined;
      return allPages.reduce((acc, p) => acc + p.items.length, 0);
    },
    enabled: enabled && !!conversationId,
    // WebSocket + optimistic sends keep the thread fresh; longer stale window avoids
    // noisy duplicate REST pages during dev (Strict Mode, catch-up refetches).
    staleTime: 30_000,
    refetchOnWindowFocus: false,
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

export interface AvailableLLMModel {
  model_id: string;
  api_name?: string;
  provider: string;
  display_name: string;
  context_limit: number;
  max_output_tokens: number;
  supports_tool_calls: boolean;
  supports_structured_output?: boolean;
  supports_reasoning_delta?: boolean;
  supports_streaming?: boolean;
  is_open_model?: boolean;
  is_default?: boolean;
  free_endpoint?: boolean;
  credential_source: string;
  is_byok: boolean;
}

export interface ModelAvailabilityResponse {
  project_id: string;
  org_id?: string | null;
  user_id?: string | null;
  models: AvailableLLMModel[];
  total_count: number;
  has_byok: boolean;
}

export function useProjectModels(
  projectId: string | undefined,
  opts: { orgId?: string | null; userId?: string | null; preferUser?: boolean } = {},
) {
  const preferUser = opts.preferUser ?? !!opts.userId;
  return useQuery<ModelAvailabilityResponse>({
    queryKey: ['llm-models', 'project', projectId, opts.orgId, opts.userId, preferUser],
    queryFn: async () => {
      if (!projectId) {
        return { project_id: '', models: [], total_count: 0, has_byok: false };
      }
      const params = new URLSearchParams();
      if (opts.orgId) params.set('org_id', opts.orgId);
      if (opts.userId) params.set('user_id', opts.userId);
      if (preferUser) params.set('prefer_user', 'true');
      const qs = params.toString();
      return apiClient.get<ModelAvailabilityResponse>(
        `/v1/projects/${projectId}/models${qs ? `?${qs}` : ''}`,
      );
    },
    enabled: !!projectId,
    staleTime: 30_000,
  });
}

export function useUserModels(userId: string | undefined) {
  return useQuery<ModelAvailabilityResponse>({
    queryKey: ['llm-models', 'user', userId],
    queryFn: async () => {
      if (!userId) {
        return { project_id: '', user_id: null, models: [], total_count: 0, has_byok: false };
      }
      const params = new URLSearchParams({
        provider_filter: 'nvidia',
        free_open_only: 'true',
      });
      return apiClient.get<ModelAvailabilityResponse>(`/v1/users/${userId}/models?${params.toString()}`);
    },
    enabled: !!userId,
    staleTime: 30_000,
  });
}

/** Unified readiness (BYOK + platform) — mirrors ``GET /api/v1/model-readiness``. */
export interface ModelReadinessResponse {
  state: string;
  can_send: boolean;
  detail?: string | null;
  suggested_model_id?: string | null;
  selected_model_id?: string | null;
  models: AvailableLLMModel[];
  total_count: number;
  has_byok: boolean;
  encryption: Record<string, unknown>;
  project_id?: string | null;
  org_id?: string | null;
  user_id?: string | null;
  prefer_user?: boolean;
}

export interface UseModelReadinessOptions {
  conversationId?: string;
  projectId?: string;
  orgId?: string | null;
  userId?: string;
  preferUser?: boolean;
  selectedModelId?: string;
  enabled?: boolean;
}

export function useModelReadiness(opts: UseModelReadinessOptions) {
  const {
    conversationId,
    projectId,
    orgId,
    userId,
    preferUser = false,
    selectedModelId,
    enabled = true,
  } = opts;

  return useQuery<ModelReadinessResponse>({
    queryKey: [
      'model-readiness',
      conversationId,
      projectId,
      orgId,
      userId,
      preferUser,
      selectedModelId,
    ],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (conversationId) params.set('conversation_id', conversationId);
      if (projectId) params.set('project_id', projectId);
      if (orgId) params.set('org_id', orgId);
      if (userId) params.set('user_id', userId);
      if (preferUser) params.set('prefer_user', 'true');
      if (selectedModelId) params.set('selected_model_id', selectedModelId);
      const qs = params.toString();
      return apiClient.get<ModelReadinessResponse>(`/v1/model-readiness${qs ? `?${qs}` : ''}`);
    },
    enabled: enabled && !!userId,
    staleTime: 15_000,
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
  projectId?: string | null;
  /** When omitted, defaults to project room (with projectId) or global personal thread (global create). */
  scope?: string;
  title?: string;
  participantIds?: string[];
}

export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation<Conversation, ApiError, CreateConversationVars>({
    mutationFn: async ({ projectId, scope, title, participantIds }) => {
      const basePath = projectId ? `/v1/projects/${projectId}/conversations` : '/v1/conversations';
      const resolvedScope = projectId
        ? scope ?? ConversationScope.ProjectRoom
        : scope ?? ConversationScope.GlobalPersonalThread;
      return apiClient.post<Conversation>(basePath, {
        scope: resolvedScope,
        title: title ?? null,
        participant_ids: participantIds ?? [],
      });
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: conversationKeys.lists() });
      const resolvedScope = vars.projectId
        ? vars.scope ?? ConversationScope.ProjectRoom
        : vars.scope ?? ConversationScope.GlobalPersonalThread;
      razeLog('INFO', 'conversation.created', {
        project_id: vars.projectId ?? null,
        scope: resolvedScope,
      });
    },
  });
}

interface PatchConversationVars {
  conversationId: string;
  title: string | null;
}

export function usePatchConversation() {
  const qc = useQueryClient();
  return useMutation<Conversation, ApiError, PatchConversationVars>({
    mutationFn: async ({ conversationId, title }) =>
      apiClient.patch<Conversation>(`/v1/conversations/${conversationId}`, { title }),
    onSuccess: (data, vars) => {
      qc.setQueryData(conversationKeys.detail(vars.conversationId), data);
      qc.invalidateQueries({ queryKey: conversationKeys.lists() });
      razeLog('INFO', 'conversation.patched', { conversation_id: vars.conversationId });
    },
  });
}

export function useArchiveConversation() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: async (conversationId) =>
      apiClient.post<void>(`/v1/conversations/${conversationId}/archive`, {}),
    onSuccess: (_data, conversationId) => {
      qc.removeQueries({ queryKey: conversationKeys.detail(conversationId) });
      qc.removeQueries({ queryKey: conversationKeys.messagesPrefix(conversationId) });
      qc.invalidateQueries({ queryKey: conversationKeys.lists() });
      razeLog('INFO', 'conversation.archived', { conversation_id: conversationId });
    },
  });
}

/** Response from ``GET /v1/conversations/global-chat-bootstrap``. */
export interface GlobalChatBootstrapResponse {
  conversation: Conversation;
  messages: MessageListResponse;
}

/** Align with ``useInfiniteMessages`` default page size and bootstrap ``limit``. */
export const GLOBAL_CHAT_BOOTSTRAP_MESSAGE_LIMIT = 50;

export function useEnsureGlobalHomeConversation() {
  const qc = useQueryClient();
  return useMutation<GlobalChatBootstrapResponse, ApiError>({
    mutationFn: async () => {
      const params = new URLSearchParams();
      params.set('limit', String(GLOBAL_CHAT_BOOTSTRAP_MESSAGE_LIMIT));
      params.set('offset', '0');
      params.set('include_thread_replies', 'true');
      return apiClient.get<GlobalChatBootstrapResponse>(
        `/v1/conversations/global-chat-bootstrap?${params.toString()}`,
      );
    },
    onSuccess: (data) => {
      const cid = data.conversation.id;
      qc.setQueryData(conversationKeys.detail(cid), data.conversation);
      qc.setQueryData(
        conversationKeys.messages(cid, {
          parentId: undefined,
          limit: GLOBAL_CHAT_BOOTSTRAP_MESSAGE_LIMIT,
          infinite: true,
          includeThreadReplies: true,
        }),
        {
          pages: [data.messages],
          pageParams: [0],
        } satisfies InfiniteData<MessageListResponse>,
      );
      qc.invalidateQueries({ queryKey: conversationKeys.lists() });
      razeLog('INFO', 'conversation.global_chat_bootstrapped', { conversation_id: cid });
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
  senderId?: string;
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
  return useMutation<ConversationMessage, ApiError, SendMessageVars, { optimisticId?: string }>({
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
    onMutate: async (vars) => {
      if (!vars.senderId) {
        return {};
      }

      const optimisticId = `optimistic-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      appendMessageToCollections(qc, vars.conversationId, {
        id: optimisticId,
        conversation_id: vars.conversationId,
        sender_id: vars.senderId,
        sender_type: 'user',
        content: vars.content,
        message_type: vars.messageType ?? 'text',
        structured_payload: vars.structuredPayload ?? null,
        parent_id: vars.parentId ?? null,
        run_id: vars.runId ?? null,
        behavior_id: vars.behaviorId ?? null,
        work_item_id: vars.workItemId ?? null,
        is_edited: false,
        edited_at: null,
        is_deleted: false,
        deleted_at: null,
        metadata: {
          ...(vars.metadata ?? {}),
          optimistic: true,
        },
        created_at: new Date().toISOString(),
        reactions: [],
        reply_count: 0,
      });

      return { optimisticId };
    },
    onSuccess: (data, vars, context) => {
      if (!context?.optimisticId || !replaceMessageInCollections(qc, vars.conversationId, context.optimisticId, data)) {
        appendMessageToCollections(qc, vars.conversationId, data);
      }
      razeLog('INFO', 'conversation.message.sent', { conversation_id: vars.conversationId });
    },
    onError: (_error, vars, context) => {
      if (context?.optimisticId) {
        removeMessageFromCollections(qc, vars.conversationId, context.optimisticId);
      }
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
  const qcRef = useRef(qc);
  qcRef.current = qc;
  const clientRef = useRef<ConversationStreamClient | null>(null);
  /** User id the stream client was constructed for (recreate client on user switch). */
  const clientUserIdRef = useRef<string | null>(null);
  /** Bumps each time the socket effect commits; used to skip teardown on React Strict Mode remount. */
  const socketEffectGenerationRef = useRef(0);
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
      clientUserIdRef.current = null;
      return;
    }

    socketEffectGenerationRef.current += 1;
    const generationAtMount = socketEffectGenerationRef.current;

    let wsConnectBenchStart = 0;
    let wsBenchLogged = false;

    const token = apiClient.getToken?.() ?? '';
    let client = clientRef.current;

    if (!client || clientUserIdRef.current !== userId) {
      client?.disconnect();
      const config: ConversationStreamConfig = {
        baseUrl: API_ORIGIN,
        userId,
        authToken: token,
        getAuthToken: async () => apiClient.getToken?.() ?? null,
        reconnect: { enabled: true },
        debug: import.meta.env.DEV,
      };
      client = createConversationStreamClient(config);
      clientRef.current = client;
      clientUserIdRef.current = userId;
    } else {
      client.setAuthToken(token);
    }

    // -- Connection events --
    const offConnected = client.on('connected', (payload) => {
      setConnectionState(ConnectionState.Connected);
      razeLog('INFO', 'conversation.ws.connected', { conversation_id: payload.conversation_id });
      if (isChatLoadBenchEnabled() && !wsBenchLogged && wsConnectBenchStart > 0) {
        wsBenchLogged = true;
        const duration_ms = Math.round(performance.now() - wsConnectBenchStart);
        const detail = { conversation_id: payload.conversation_id, duration_ms };
        chatLoadBench('ws_connected', detail);
        chatLoadBenchMark('ws_connected', detail);
      }
    });
    const offDisconnected = client.on('disconnected', () => {
      setConnectionState(ConnectionState.Disconnected);
      setTypingUsers(new Map());
    });

    // -- Message events → merge into cache (qc via ref avoids effect churn on queryClient identity) --
    const offMessageNew = client.on('message.new', (payload: ConversationMessageEventPayload) => {
      appendMessageToCollections(qcRef.current, payload.conversation_id, payload.message);
    });

    const offMessageUpdated = client.on('message.updated', (payload: ConversationMessageEventPayload) => {
      updateMessageCollections(qcRef.current, payload.conversation_id, (items) =>
        items.map((m) => (m.id === payload.message.id ? payload.message : m)),
      );
    });

    const offMessageDeleted = client.on('message.deleted', (payload: ConversationMessageEventPayload) => {
      updateMessageCollections(qcRef.current, payload.conversation_id, (items) =>
        items.map((m) =>
          m.id === payload.message.id
            ? { ...m, is_deleted: true, content: '' }
            : m,
        ),
      );
    });

    const offReactionAdded = client.on('reaction.added', (payload: ConversationReactionEventPayload) => {
      updateMessageCollections(qcRef.current, payload.conversation_id, (items) =>
        items.map((m) =>
          m.id === payload.message_id
            ? { ...m, reactions: [...(m.reactions ?? []), payload.reaction] }
            : m,
        ),
      );
    });

    const offReactionRemoved = client.on('reaction.removed', (payload: ConversationReactionEventPayload) => {
      updateMessageCollections(qcRef.current, payload.conversation_id, (items) =>
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
      qcRef.current.invalidateQueries({ queryKey: conversationKeys.participants(payload.conversation_id) });
    });
    const offParticipantJoined = client.on('participant.joined', (payload) => {
      qcRef.current.invalidateQueries({ queryKey: conversationKeys.participants(payload.conversation_id) });
    });
    const offParticipantLeft = client.on('participant.left', (payload) => {
      qcRef.current.invalidateQueries({ queryKey: conversationKeys.participants(payload.conversation_id) });
    });

    if (!normalizedConversationId) {
      client.disconnect('missing_conversation');
    } else {
      if (isChatLoadBenchEnabled()) {
        wsConnectBenchStart = performance.now();
        wsBenchLogged = false;
      }
      client.connect(normalizedConversationId);
    }

    return () => {
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

      const clientToMaybeClose = client;
      queueMicrotask(() => {
        if (socketEffectGenerationRef.current !== generationAtMount) {
          return;
        }
        clientToMaybeClose.disconnect();
        if (clientRef.current === clientToMaybeClose) {
          clientRef.current = null;
          clientUserIdRef.current = null;
        }
      });
    };
  }, [userId, normalizedConversationId]);

  return { connectionState, typingUsers };
}

// ---------------------------------------------------------------------------
// SSE hook for agent token streaming
// ---------------------------------------------------------------------------

export interface UseMessageStreamResult {
  tokens: string[];
  fullText: string;
  isStreaming: boolean;
  phase: string | null;
  statusLabel: string;
  sourceCounts: Record<string, number> | null;
  traceSteps: Array<Record<string, unknown>>;
  sourceRows: Array<Record<string, unknown>>;
  badge: string | null;
  error: string | null;
}

export function useMessageStream(
  conversationId: string | undefined,
  messageId: string | undefined,
): UseMessageStreamResult {
  const [tokens, setTokens] = useState<string[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);
  const [statusLabel, setStatusLabel] = useState('Thinking...');
  const [sourceCounts, setSourceCounts] = useState<Record<string, number> | null>(null);
  const [traceSteps, setTraceSteps] = useState<Array<Record<string, unknown>>>([]);
  const [sourceRows, setSourceRows] = useState<Array<Record<string, unknown>>>([]);
  const [badge, setBadge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sawReplyTokenRef = useRef(false);
  const processedEventIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!conversationId || !messageId) return;

    setIsStreaming(true);
    setTokens([]);
    setPhase('connecting');
    setStatusLabel('Thinking...');
    setSourceCounts(null);
    setTraceSteps([]);
    setSourceRows([]);
    setBadge(null);
    setError(null);
    sawReplyTokenRef.current = false;
    processedEventIdsRef.current = new Set();

    const token = apiClient.getToken?.() ?? '';
    const url = `${API_ORIGIN}/api/v1/conversations/${conversationId}/stream/${messageId}?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);

    es.onopen = () => {
      setIsStreaming(true);
      setError(null);
    };

    const shouldProcessEvent = (data: Record<string, unknown>) => {
      const eventId = typeof data._event_id === 'string' ? data._event_id : null;
      if (!eventId) return true;
      if (processedEventIdsRef.current.has(eventId)) return false;
      processedEventIdsRef.current.add(eventId);
      return true;
    };

    const applyTraceData = (data: Record<string, unknown>) => {
      if (data.source_counts && typeof data.source_counts === 'object') {
        setSourceCounts(data.source_counts as Record<string, number>);
      }
      if (Array.isArray(data.trace_steps)) {
        setTraceSteps((prev) => [...prev, ...(data.trace_steps as Array<Record<string, unknown>>)]);
      }
      if (Array.isArray(data.source_rows)) {
        setSourceRows(data.source_rows as Array<Record<string, unknown>>);
      }
      if (typeof data.badge === 'string') {
        setBadge(data.badge);
      }
    };

    const handleTokenEvent = (ev: MessageEvent<string>, eventName: 'token' | 'reply.token') => {
      try {
        const data = JSON.parse(ev.data);
        if (!shouldProcessEvent(data)) return;
        if (eventName === 'reply.token') {
          sawReplyTokenRef.current = true;
        } else if (sawReplyTokenRef.current) {
          return;
        }
        if (typeof data.label === 'string') setStatusLabel(data.label);
        if (typeof data.phase === 'string') setPhase(data.phase);
        applyTraceData(data);
        if (typeof data.token === 'string') {
          setTokens((prev) => [...prev, data.token]);
        }
      } catch {
        // ignore malformed token events
      }
    };

    const handleStepEvent = (ev: MessageEvent<string>) => {
      try {
        const data = JSON.parse(ev.data);
        if (!shouldProcessEvent(data)) return;
        if (typeof data.label === 'string') setStatusLabel(data.label);
        if (typeof data.phase === 'string') setPhase(data.phase);
        applyTraceData(data);
      } catch {
        // ignore malformed lifecycle events
      }
    };

    const handleCompleteEvent = (ev: MessageEvent<string>) => {
      try {
        const data = JSON.parse(ev.data);
        if (!shouldProcessEvent(data)) return;
        if (typeof data.content === 'string' && data.content.length > 0) {
          setTokens([data.content]);
        }
        if (typeof data.label === 'string') setStatusLabel(data.label);
        if (typeof data.phase === 'string') setPhase(data.phase);
        applyTraceData(data);
      } catch {
        // Legacy complete events can omit parseable metadata.
      }
      setIsStreaming(false);
      es.close();
    };

    const handleReplyErrorEvent = (ev: MessageEvent<string>) => {
      try {
        const data = JSON.parse(ev.data);
        if (!shouldProcessEvent(data)) return;
        setError(typeof data.error === 'string' ? data.error : 'Stream connection lost');
        if (typeof data.label === 'string') setStatusLabel(data.label);
        if (typeof data.phase === 'string') setPhase(data.phase);
      } catch {
        setError('Stream connection lost');
      }
      setIsStreaming(false);
      es.close();
    };

    es.addEventListener('token', (ev) => handleTokenEvent(ev as MessageEvent<string>, 'token'));
    es.addEventListener('reply.token', (ev) => handleTokenEvent(ev as MessageEvent<string>, 'reply.token'));
    es.addEventListener('reply.started', handleStepEvent);
    es.addEventListener('reply.step', handleStepEvent);

    es.addEventListener('complete', handleCompleteEvent);
    es.addEventListener('reply.complete', handleCompleteEvent);
    es.addEventListener('reply.error', handleReplyErrorEvent);

    es.addEventListener('error', (ev) => {
      if ('data' in ev && typeof ev.data === 'string') {
        handleReplyErrorEvent(ev as MessageEvent<string>);
        return;
      }
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

  return { tokens, fullText, isStreaming, phase, statusLabel, sourceCounts, traceSteps, sourceRows, badge, error };
}
