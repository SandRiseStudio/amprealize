/**
 * Amprealize Execution Stream Client
 *
 * Real-time WebSocket client for execution status + steps.
 */

import type {
  ExecutionReadyEventPayload,
  ExecutionSnapshotEventPayload,
  ExecutionStatusEventPayload,
  ExecutionStepEventPayload,
  ExecutionStreamEvents,
} from './types.js';
import { ConnectionState } from './client.js';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface ExecutionStreamConfig {
  /** WebSocket base URL origin (e.g., http://localhost:8080) */
  baseUrl: string;
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

export interface ExecutionStreamTarget {
  runId?: string | null;
  orgId?: string | null;
  projectId?: string | null;
}

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
        console.error(`[ExecutionStreamClient] Error in ${String(event)} handler:`, err);
      }
    });
  }

  removeAllListeners(): void {
    this.handlers.clear();
  }
}

// ---------------------------------------------------------------------------
// Execution Stream Client
// ---------------------------------------------------------------------------

export class ExecutionStreamClient extends TypedEventEmitter<ExecutionStreamEvents> {
  private config: ExecutionStreamConfig & { reconnect: RequiredReconnect; heartbeatIntervalMs: number; debug: boolean };
  private ws: WebSocket | null = null;
  private target: ExecutionStreamTarget | null = null;
  private connectionState: ConnectionState = ConnectionState.Disconnected;
  private reconnectAttempts = 0;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private authToken: string | null = null;
  private shouldReconnect = true;

  constructor(config: ExecutionStreamConfig) {
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

  connect(target: ExecutionStreamTarget): void {
    if (!target.runId && !(target.orgId && target.projectId)) {
      throw new Error('ExecutionStreamClient.connect requires runId or orgId + projectId');
    }

    const normalizedTarget: ExecutionStreamTarget = {
      runId: target.runId ?? null,
      orgId: target.orgId ?? null,
      projectId: target.projectId ?? null,
    };

    if (this.isSameTarget(normalizedTarget) && this.connectionState === ConnectionState.Connected) {
      this.log('Already connected to execution target', normalizedTarget);
      return;
    }

    this.disconnect();
    this.target = normalizedTarget;
    this.shouldReconnect = true;
    this.connectionState = ConnectionState.Connecting;
    this.reconnectAttempts = 0;
    void this.openConnection();
  }

  disconnect(reason = 'manual_disconnect'): void {
    this.shouldReconnect = false;
    this.clearTimers();
    if (this.ws) {
      this.ws.close();
    }
    this.ws = null;
    this.target = null;
    this.connectionState = ConnectionState.Disconnected;
    this.emit('disconnected', reason);
  }

  // ---------------------------------------------------------------------------
  // Connection Flow
  // ---------------------------------------------------------------------------

  private async openConnection(): Promise<void> {
    if (!this.target) return;

    const token = await this.resolveAuthToken();
    const url = this.buildWebSocketUrl(this.target, token ?? undefined);
    this.log('Connecting to', url);

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.log('WebSocket connected');
      this.connectionState = ConnectionState.Connected;
      this.reconnectAttempts = 0;
      this.startHeartbeat();
    };

    this.ws.onmessage = (event) => {
      this.handleMessage(event.data);
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
      case 'execution.status':
        this.emit('status', message.payload as ExecutionStatusEventPayload);
        break;
      case 'execution.step':
        this.emit('step', message.payload as ExecutionStepEventPayload);
        break;
      case 'execution.snapshot': {
        const payload = message.payload as ExecutionSnapshotEventPayload;
        this.emit('snapshot', payload);
        this.emit('connected', this.snapshotContext(payload));
        break;
      }
      case 'execution.ready': {
        const payload = message.payload as ExecutionReadyEventPayload;
        this.emit('ready', payload);
        this.emit('connected', payload);
        break;
      }
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

  private snapshotContext(payload: ExecutionSnapshotEventPayload): ExecutionReadyEventPayload {
    return {
      run_id: payload.run_id ?? this.target?.runId ?? null,
      org_id: this.target?.orgId ?? null,
      project_id: this.target?.projectId ?? null,
    };
  }

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

  private buildWebSocketUrl(target: ExecutionStreamTarget, token?: string): string {
    const url = new URL('/api/v1/executions/ws', this.config.baseUrl);
    if (target.runId) url.searchParams.set('run_id', target.runId);
    if (target.orgId) url.searchParams.set('org_id', target.orgId);
    if (target.projectId) url.searchParams.set('project_id', target.projectId);
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
      if (!this.target) return;
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

  private send(message: { type: string }): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      this.log('Sent:', message.type);
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

  private isSameTarget(target: ExecutionStreamTarget): boolean {
    return (
      this.target?.runId === (target.runId ?? null) &&
      this.target?.orgId === (target.orgId ?? null) &&
      this.target?.projectId === (target.projectId ?? null)
    );
  }

  private log(...args: unknown[]): void {
    if (this.config.debug) {
      console.log('[ExecutionStreamClient]', ...args);
    }
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createExecutionStreamClient(config: ExecutionStreamConfig): ExecutionStreamClient {
  return new ExecutionStreamClient(config);
}
