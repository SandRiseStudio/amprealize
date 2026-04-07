/**
 * Amprealize Collaboration Client
 *
 * High-performance, cross-surface WebSocket client for real-time collaboration.
 * Features:
 * - Automatic reconnection with exponential backoff
 * - Optimistic updates with conflict resolution
 * - Event-driven API for easy UI binding
 * - Works in both browser (SaaS) and VS Code webviews
 */

import type {
  ClientMessage,
  ClientEditOperation,
  CollabClientEvents,
  Document,
  DocumentId,
  EditOperation,
  EditOperationType,
  ErrorCode,
  ServerMessage,
  SessionId,
  UserId,
} from './types.js';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface CollabClientConfig {
  /** WebSocket endpoint base URL (e.g., ws://localhost:8080) */
  baseUrl: string;
  /** User identifier */
  userId: UserId;
  /** Optional session identifier for multi-tab/window support */
  sessionId?: SessionId;
  /**
   * Authentication token (Bearer token).
   * Required for authenticated WebSocket connections.
   * Can be updated via setAuthToken() for token refresh scenarios.
   */
  authToken?: string;
  /**
   * Callback to get a fresh auth token before reconnecting.
   * Useful for handling token refresh during long-lived connections.
   */
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

const DEFAULT_CONFIG: Required<Pick<CollabClientConfig, 'reconnect' | 'heartbeatIntervalMs' | 'debug'>> = {
  reconnect: {
    enabled: true,
    maxAttempts: 10,
    baseDelayMs: 1000,
    maxDelayMs: 30000,
  },
  heartbeatIntervalMs: 25000,
  debug: false,
};

// ---------------------------------------------------------------------------
// Event Emitter (minimal, no dependencies)
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyFunction = (...args: any[]) => void;

// Simple event emitter that works with any event map
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
        console.error(`[CollabClient] Error in ${String(event)} handler:`, err);
      }
    });
  }

  removeAllListeners(): void {
    this.handlers.clear();
  }
}

// ---------------------------------------------------------------------------
// Connection State
// ---------------------------------------------------------------------------

export enum ConnectionState {
  Disconnected = 'disconnected',
  Connecting = 'connecting',
  Connected = 'connected',
  Reconnecting = 'reconnecting',
}

// ---------------------------------------------------------------------------
// Collaboration Client
// ---------------------------------------------------------------------------

export class CollabClient extends TypedEventEmitter<CollabClientEvents> {
  private config: CollabClientConfig & typeof DEFAULT_CONFIG;
  private ws: WebSocket | null = null;
  private documentId: DocumentId | null = null;
  private document: Document | null = null;
  private connectionState: ConnectionState = ConnectionState.Disconnected;
  private reconnectAttempts = 0;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  /** Current auth token (can be updated via setAuthToken) */
  private authToken: string | null = null;

  // Pending operations awaiting server ACK (for optimistic updates)
  private pendingOps: Map<string, ClientEditOperation> = new Map();
  private opCounter = 0;

  constructor(config: CollabClientConfig) {
    super();
    this.config = {
      ...config,
      reconnect: { ...DEFAULT_CONFIG.reconnect, ...config.reconnect },
      heartbeatIntervalMs: config.heartbeatIntervalMs ?? DEFAULT_CONFIG.heartbeatIntervalMs,
      debug: config.debug ?? DEFAULT_CONFIG.debug,
    };
    this.authToken = config.authToken ?? null;
  }

  // ---------------------------------------------------------------------------
  // Auth Token Management
  // ---------------------------------------------------------------------------

  /**
   * Update the auth token. Use this when tokens are refreshed.
   * If currently connected, the new token will be used on next reconnect.
   */
  setAuthToken(token: string | null): void {
    this.authToken = token;
    this.log('Auth token updated');
  }

  /**
   * Get the current auth token.
   */
  getAuthToken(): string | null {
    return this.authToken;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  get state(): ConnectionState {
    return this.connectionState;
  }

  get currentDocument(): Document | null {
    return this.document;
  }

  get currentVersion(): number {
    return this.document?.version ?? 0;
  }

  /**
   * Connect to a document for real-time collaboration.
   */
  connect(documentId: DocumentId): void {
    if (this.ws && this.documentId === documentId && this.connectionState === ConnectionState.Connected) {
      this.log('Already connected to document', documentId);
      return;
    }

    this.disconnect();
    this.documentId = documentId;
    this.connectionState = ConnectionState.Connecting;
    // Fire and forget - errors handled in createWebSocket
    void this.createWebSocket();
  }

  /**
   * Disconnect from the current document.
   */
  disconnect(): void {
    this.clearTimers();
    if (this.ws) {
      this.ws.onclose = null; // Prevent reconnection
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.connectionState = ConnectionState.Disconnected;
    this.document = null;
    this.pendingOps.clear();
    this.reconnectAttempts = 0;
  }

  /**
   * Send an edit operation. Returns a local operation ID for tracking.
   */
  sendEdit(operation: Omit<ClientEditOperation, 'version' | 'user_id' | 'session_id'>): string {
    const localOpId = `op_${++this.opCounter}_${Date.now()}`;

    const fullOp: ClientEditOperation = {
      ...operation,
      version: this.currentVersion,
      user_id: this.config.userId,
      session_id: this.config.sessionId,
    };

    // Track for optimistic updates
    this.pendingOps.set(localOpId, fullOp);

    // Send if connected
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ type: 'edit', operation: fullOp });
    }

    return localOpId;
  }

  /**
   * Send cursor position update.
   */
  sendCursor(position: number, selectionEnd?: number): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ type: 'cursor', position, selection_end: selectionEnd });
    }
  }

  /**
   * Send presence status update.
   */
  sendPresence(status: 'active' | 'idle' | 'away'): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ type: 'presence', status });
    }
  }

  // ---------------------------------------------------------------------------
  // WebSocket Management
  // ---------------------------------------------------------------------------

  private async createWebSocket(): Promise<void> {
    if (!this.documentId) return;

    // Get fresh token if callback provided (for refresh scenarios)
    if (this.config.getAuthToken) {
      const freshToken = await this.config.getAuthToken();
      if (freshToken) {
        this.authToken = freshToken;
      }
    }

    const url = new URL(`/v1/collaboration/ws/${this.documentId}`, this.config.baseUrl);
    url.searchParams.set('user_id', this.config.userId);
    if (this.config.sessionId) {
      url.searchParams.set('session_id', this.config.sessionId);
    }
    // Include auth token as query param (WebSocket doesn't support custom headers)
    // The server should validate this token on connection
    if (this.authToken) {
      url.searchParams.set('token', this.authToken);
    }

    // Convert http(s) to ws(s)
    url.protocol = url.protocol.replace('http', 'ws');

    this.log('Connecting to', url.toString().replace(/token=[^&]+/, 'token=***'));
    this.ws = new WebSocket(url.toString());

    this.ws.onopen = this.handleOpen.bind(this);
    this.ws.onmessage = this.handleMessage.bind(this);
    this.ws.onclose = this.handleClose.bind(this);
    this.ws.onerror = this.handleError.bind(this);
  }

  private handleOpen(): void {
    this.log('WebSocket connected');
    this.reconnectAttempts = 0;
    this.startHeartbeat();
  }

  private handleMessage(event: MessageEvent): void {
    let message: ServerMessage;
    try {
      message = JSON.parse(event.data as string);
    } catch {
      this.log('Invalid message received:', event.data);
      return;
    }

    this.log('Received:', message.type, message);

    switch (message.type) {
      case 'pong':
        // Heartbeat acknowledged
        break;

      case 'snapshot':
        this.document = message.document;
        this.connectionState = ConnectionState.Connected;
        this.emit('connected', message.document);
        break;

      case 'operation':
        // Server confirmed operation
        this.document = message.document ?? this.document;
        if (message.document) {
          this.emit('operation', message.operation, message.document);
        }
        // Clear pending ops that have been confirmed (based on version)
        this.clearConfirmedOps(message.operation.version);
        break;

      case 'cursor':
        this.emit('cursor', message.user_id, message.position, message.selection_end);
        break;

      case 'presence':
        this.emit('presence', message.user_id, message.status);
        break;

      case 'error':
        this.handleServerError(message);
        break;
    }
  }

  private handleServerError(message: Extract<ServerMessage, { type: 'error' }>): void {
    this.log('Server error:', message.code, message.message);

    if (message.code === 'VERSION_CONFLICT') {
      // Update local document to server state
      if (message.document) {
        this.document = message.document;
      }
      this.emit(
        'conflict',
        message.expected_version ?? 0,
        message.got_version ?? 0,
        message.document ?? null
      );
      // Clear pending ops - client needs to rebase
      this.pendingOps.clear();
    } else if (message.code === 'NOT_FOUND') {
      this.emit('error', message.code, message.message);
      this.disconnect();
    } else {
      this.emit('error', message.code, message.message);
    }
  }

  private handleClose(event: CloseEvent): void {
    this.log('WebSocket closed:', event.code, event.reason);
    this.clearTimers();
    this.ws = null;

    const wasConnected = this.connectionState === ConnectionState.Connected;

    if (this.config.reconnect.enabled && this.reconnectAttempts < this.config.reconnect.maxAttempts!) {
      this.connectionState = ConnectionState.Reconnecting;
      this.scheduleReconnect();
    } else {
      this.connectionState = ConnectionState.Disconnected;
      if (wasConnected) {
        this.emit('disconnected', event.reason || 'Connection closed');
      }
    }
  }

  private handleError(event: Event): void {
    this.log('WebSocket error:', event);
  }

  // ---------------------------------------------------------------------------
  // Reconnection
  // ---------------------------------------------------------------------------

  private scheduleReconnect(): void {
    const delay = Math.min(
      this.config.reconnect.baseDelayMs! * Math.pow(2, this.reconnectAttempts),
      this.config.reconnect.maxDelayMs!
    );

    this.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectAttempts++;
      // Fire and forget - errors handled in createWebSocket
      void this.createWebSocket();
    }, delay);
  }

  // ---------------------------------------------------------------------------
  // Heartbeat
  // ---------------------------------------------------------------------------

  private startHeartbeat(): void {
    this.heartbeatInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.send({ type: 'ping' });
      }
    }, this.config.heartbeatIntervalMs);
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  private send(message: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      this.log('Sent:', message.type, message);
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

  private clearConfirmedOps(confirmedVersion: number): void {
    // Remove ops that have been incorporated into confirmed version
    for (const [opId, op] of this.pendingOps) {
      if (op.version < confirmedVersion) {
        this.pendingOps.delete(opId);
      }
    }
  }

  private log(...args: unknown[]): void {
    if (this.config.debug) {
      console.log('[CollabClient]', ...args);
    }
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createCollabClient(config: CollabClientConfig): CollabClient {
  return new CollabClient(config);
}
