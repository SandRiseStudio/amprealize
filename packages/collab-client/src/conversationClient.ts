/**
 * Amprealize Conversation Stream Client
 *
 * Real-time WebSocket client for conversation messages, reactions, typing
 * indicators, and read receipts. Mirrors ExecutionStreamClient pattern.
 */

import type {
  ConversationMessageEventPayload,
  ConversationParticipantEventPayload,
  ConversationReactionEventPayload,
  ConversationReadReceiptPayload,
  ConversationReadyPayload,
  ConversationStreamEvents,
  ConversationTypingPayload,
  MessageType,
} from './types.js';
import { ConnectionState } from './client.js';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface ConversationStreamConfig {
  /** WebSocket base URL origin (e.g., http://localhost:8080) */
  baseUrl: string;
  /** User ID for the current user */
  userId: string;
  /** Optional auth token passed as a query param */
  authToken?: string;
  /** Callback to fetch a fresh auth token before connecting/reconnecting */
  getAuthToken?: () => Promise<string | null>;
  /** Reconnection settings */
  reconnect?: {
    enabled?: boolean;
    maxAttempts?: number;
    baseDelayMs?: number;
    maxDelayMs?: number;
  };
  /** Heartbeat interval in ms (default: 25000) */
  heartbeatIntervalMs?: number;
  /** Debug logging */
  debug?: boolean;
}

type RequiredReconnect = {
  enabled: boolean;
  maxAttempts: number;
  baseDelayMs: number;
  maxDelayMs: number;
};

const DEFAULT_RECONNECT: RequiredReconnect = {
  enabled: true,
  maxAttempts: 10,
  baseDelayMs: 1000,
  maxDelayMs: 30000,
};

const DEFAULT_CONFIG: { reconnect: RequiredReconnect; heartbeatIntervalMs: number; debug: boolean } = {
  reconnect: DEFAULT_RECONNECT,
  heartbeatIntervalMs: 25000,
  debug: false,
};

// ---------------------------------------------------------------------------
// Client → Server Command Payloads
// ---------------------------------------------------------------------------

interface SendMessageCommand {
  type: 'message.send';
  content?: string | null;
  message_type?: MessageType | string;
  structured_payload?: Record<string, unknown> | null;
  parent_id?: string | null;
}

interface EditMessageCommand {
  type: 'message.edit';
  message_id: string;
  content: string;
}

interface DeleteMessageCommand {
  type: 'message.delete';
  message_id: string;
}

interface ReactionCommand {
  type: 'reaction.add' | 'reaction.remove';
  message_id: string;
  emoji: string;
}

interface ReadUpdateCommand {
  type: 'read.update';
  last_read_message_id: string;
}

type ClientCommand =
  | { type: 'ping' }
  | { type: 'typing.start' }
  | { type: 'typing.stop' }
  | SendMessageCommand
  | EditMessageCommand
  | DeleteMessageCommand
  | ReactionCommand
  | ReadUpdateCommand;

// ---------------------------------------------------------------------------
// Event Emitter (minimal, no dependencies)
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyFunction = (...args: any[]) => void;

class TypedEventEmitter<Events> {
  private handlers = new Map<keyof Events, Set<AnyFunction>>();

  on<K extends keyof Events>(event: K, handler: Events[K]): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler as AnyFunction);
    return () => this.off(event, handler);
  }

  off<K extends keyof Events>(event: K, handler: Events[K]): void {
    this.handlers.get(event)?.delete(handler as AnyFunction);
  }

  protected emit<K extends keyof Events>(
    event: K,
    ...args: Events[K] extends (...a: infer P) => void ? P : never
  ): void {
    this.handlers.get(event)?.forEach((handler) => {
      try {
        handler(...args);
      } catch (err) {
        console.error(`[ConversationStreamClient] Error in ${String(event)} handler:`, err);
      }
    });
  }

  removeAllListeners(): void {
    this.handlers.clear();
  }
}

// ---------------------------------------------------------------------------
// Conversation Stream Client
// ---------------------------------------------------------------------------

export class ConversationStreamClient extends TypedEventEmitter<ConversationStreamEvents> {
  private config: ConversationStreamConfig & { reconnect: RequiredReconnect; heartbeatIntervalMs: number; debug: boolean };
  private ws: WebSocket | null = null;
  private conversationId: string | null = null;
  private connectionState: ConnectionState = ConnectionState.Disconnected;
  private reconnectAttempts = 0;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private authToken: string | null = null;
  private shouldReconnect = true;

  constructor(config: ConversationStreamConfig) {
    super();
    this.config = {
      ...config,
      reconnect: { ...DEFAULT_RECONNECT, ...config.reconnect },
      heartbeatIntervalMs: config.heartbeatIntervalMs ?? DEFAULT_CONFIG.heartbeatIntervalMs,
      debug: config.debug ?? DEFAULT_CONFIG.debug,
    };
    this.authToken = config.authToken ?? null;
  }

  // ---------------------------------------------------------------------------
  // Auth Token Management
  // ---------------------------------------------------------------------------

  setAuthToken(token: string | null): void {
    this.authToken = token;
    this.log('Auth token updated');
  }

  getAuthToken(): string | null {
    return this.authToken;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  get state(): ConnectionState {
    return this.connectionState;
  }

  get activeConversationId(): string | null {
    return this.conversationId;
  }

  connect(conversationId: string): void {
    if (!conversationId) {
      this.log('Skipping connect without conversationId');
      return;
    }

    if (this.conversationId === conversationId && this.connectionState === ConnectionState.Connected) {
      this.log('Already connected to conversation', conversationId);
      return;
    }

    this.disconnect();
    this.conversationId = conversationId;
    this.shouldReconnect = true;
    this.connectionState = ConnectionState.Connecting;
    this.reconnectAttempts = 0;
    void this.openConnection(conversationId);
  }

  disconnect(reason = 'manual_disconnect'): void {
    this.shouldReconnect = false;
    this.clearTimers();
    if (this.ws) {
      this.ws.close();
    }
    this.ws = null;
    this.conversationId = null;
    this.connectionState = ConnectionState.Disconnected;
    this.emit('disconnected', reason);
  }

  // ---------------------------------------------------------------------------
  // Client → Server Commands
  // ---------------------------------------------------------------------------

  sendMessage(options: {
    content?: string | null;
    message_type?: MessageType | string;
    structured_payload?: Record<string, unknown> | null;
    parent_id?: string | null;
  }): void {
    this.send({
      type: 'message.send',
      content: options.content,
      message_type: options.message_type,
      structured_payload: options.structured_payload,
      parent_id: options.parent_id,
    });
  }

  editMessage(messageId: string, content: string): void {
    this.send({ type: 'message.edit', message_id: messageId, content });
  }

  deleteMessage(messageId: string): void {
    this.send({ type: 'message.delete', message_id: messageId });
  }

  addReaction(messageId: string, emoji: string): void {
    this.send({ type: 'reaction.add', message_id: messageId, emoji });
  }

  removeReaction(messageId: string, emoji: string): void {
    this.send({ type: 'reaction.remove', message_id: messageId, emoji });
  }

  startTyping(): void {
    this.send({ type: 'typing.start' });
  }

  stopTyping(): void {
    this.send({ type: 'typing.stop' });
  }

  updateReadPosition(lastReadMessageId: string): void {
    this.send({ type: 'read.update', last_read_message_id: lastReadMessageId });
  }

  // ---------------------------------------------------------------------------
  // Connection Flow
  // ---------------------------------------------------------------------------

  private async openConnection(requestedConversationId?: string): Promise<void> {
    const targetConversationId = requestedConversationId ?? this.conversationId;
    if (!targetConversationId) {
      this.log('Skipping openConnection without conversationId');
      return;
    }

    const token = await this.resolveAuthToken();
    if (this.conversationId !== targetConversationId || !this.shouldReconnect) {
      this.log('Aborting stale openConnection', targetConversationId, this.conversationId);
      return;
    }

    const url = this.buildWebSocketUrl(targetConversationId, token ?? undefined);
    this.log('Connecting to', url);

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.log('WebSocket connected');
      this.connectionState = ConnectionState.Connected;
      this.reconnectAttempts = 0;
      this.startHeartbeat();
    };

    this.ws.onmessage = (event) => {
      this.handleMessage(event.data as string);
    };

    this.ws.onerror = () => {
      this.log('WebSocket error');
    };

    this.ws.onclose = (event) => {
      this.log('WebSocket closed', event.code, event.reason);
      this.clearTimers();
      this.ws = null;

      const reason = event.reason || 'connection_closed';
      if (this.shouldReconnect && this.config.reconnect.enabled) {
        this.scheduleReconnect(reason);
      } else {
        this.connectionState = ConnectionState.Disconnected;
        this.emit('disconnected', reason);
      }
    };
  }

  private handleMessage(rawMessage: string): void {
    let message: { type?: string; payload?: unknown; code?: string; message?: string };
    try {
      message = JSON.parse(rawMessage) as { type?: string; payload?: unknown; code?: string; message?: string };
    } catch {
      this.log('Invalid JSON message', rawMessage);
      return;
    }

    switch (message.type) {
      case 'conversation.ready':
        this.emit('connected', message.payload as ConversationReadyPayload);
        break;
      case 'message.new':
        this.emit('message.new', message.payload as ConversationMessageEventPayload);
        break;
      case 'message.updated':
        this.emit('message.updated', message.payload as ConversationMessageEventPayload);
        break;
      case 'message.deleted':
        this.emit('message.deleted', message.payload as ConversationMessageEventPayload);
        break;
      case 'reaction.added':
        this.emit('reaction.added', message.payload as ConversationReactionEventPayload);
        break;
      case 'reaction.removed':
        this.emit('reaction.removed', message.payload as ConversationReactionEventPayload);
        break;
      case 'typing':
        this.emit('typing.indicator', message.payload as ConversationTypingPayload);
        break;
      case 'read.receipt':
        this.emit('read.receipt', message.payload as ConversationReadReceiptPayload);
        break;
      case 'participant.joined':
        this.emit('participant.joined', message.payload as ConversationParticipantEventPayload);
        break;
      case 'participant.left':
        this.emit('participant.left', message.payload as ConversationParticipantEventPayload);
        break;
      case 'pong':
        break;
      case 'error':
        this.emit('error', message.code ?? 'UNKNOWN', message.message ?? 'Unknown error');
        break;
      default:
        this.log('Unhandled message', message);
    }
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  private async resolveAuthToken(): Promise<string | null> {
    if (this.config.getAuthToken) {
      try {
        const fresh = await this.config.getAuthToken();
        if (fresh) {
          this.authToken = fresh;
        }
      } catch {
        // Best-effort token refresh; continue with existing token.
      }
    }
    return this.authToken;
  }

  private buildWebSocketUrl(conversationId: string, token?: string): string {
    const url = new URL(`/api/v1/conversations/${encodeURIComponent(conversationId)}/ws`, this.config.baseUrl);
    url.searchParams.set('user_id', this.config.userId);
    if (token) url.searchParams.set('token', token);

    if (url.protocol === 'https:' || url.protocol === 'wss:') {
      url.protocol = 'wss:';
    } else {
      url.protocol = 'ws:';
    }

    return url.toString();
  }

  private scheduleReconnect(reason: string): void {
    this.connectionState = ConnectionState.Reconnecting;
    this.emit('disconnected', reason);

    const maxAttempts = this.config.reconnect.maxAttempts ?? DEFAULT_CONFIG.reconnect.maxAttempts;
    if (this.reconnectAttempts >= maxAttempts) {
      this.log('Max reconnect attempts reached');
      this.connectionState = ConnectionState.Disconnected;
      return;
    }

    const attempt = this.reconnectAttempts + 1;
    const baseDelayMs = this.config.reconnect.baseDelayMs ?? DEFAULT_CONFIG.reconnect.baseDelayMs;
    const maxDelayMs = this.config.reconnect.maxDelayMs ?? DEFAULT_CONFIG.reconnect.maxDelayMs;
    const delay = Math.min(baseDelayMs * 2 ** (attempt - 1), maxDelayMs);
    this.reconnectAttempts = attempt;

    this.reconnectTimeout = setTimeout(() => {
      if (!this.conversationId) return;
      this.log(`Reconnect attempt ${attempt}`);
      void this.openConnection();
    }, delay);
  }

  private startHeartbeat(): void {
    const heartbeatIntervalMs = this.config.heartbeatIntervalMs ?? DEFAULT_CONFIG.heartbeatIntervalMs;
    if (heartbeatIntervalMs <= 0) return;
    this.heartbeatInterval = setInterval(() => {
      this.send({ type: 'ping' });
    }, heartbeatIntervalMs);
  }

  private send(command: ClientCommand): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(command));
      this.log('Sent:', command.type);
    }
  }

  private clearTimers(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  private log(...args: unknown[]): void {
    if (this.config.debug) {
      console.log('[ConversationStreamClient]', ...args);
    }
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createConversationStreamClient(config: ConversationStreamConfig): ConversationStreamClient {
  return new ConversationStreamClient(config);
}
