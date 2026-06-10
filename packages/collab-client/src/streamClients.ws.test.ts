import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConnectionState } from './client.js';
import { ConversationStreamClient } from './conversationClient.js';
import { ExecutionStreamClient } from './executionClient.js';

/** Minimal WebSocket mock; records instances for stale-close simulation */
function installMockWebSocket(): MockWebSocket[] {
  const sockets: MockWebSocket[] = [];

  class MockWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    url: string;
    readyState: number;
    onopen: ((ev: Event) => void) | null = null;
    onclose: ((ev: CloseEvent) => void) | null = null;
    onmessage: ((ev: MessageEvent) => void) | null = null;
    onerror: ((ev: Event) => void) | null = null;

    constructor(url: string | URL, _protocols?: string | string[]) {
      this.url = typeof url === 'string' ? url : url.toString();
      this.readyState = MockWebSocket.CONNECTING;
      sockets.push(this);
    }

    simulateOpen(): void {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.(new Event('open'));
    }

    send(_data: string): void {}

    close(): void {
      this.readyState = MockWebSocket.CLOSED;
    }

    simulateClose(code = 1005, reason = ''): void {
      const ev = { target: this, code, reason, type: 'close' } as CloseEvent;
      this.onclose?.(ev);
    }
  }

  vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);
  return sockets;
}

describe('WebSocket stale onclose guard', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('ConversationStreamClient ignores stale socket onclose after switching conversation', async () => {
    const sockets = installMockWebSocket();
    const client = new ConversationStreamClient({
      baseUrl: 'http://localhost:8080',
      userId: 'user-1',
      authToken: 'tok',
      reconnect: { enabled: true, baseDelayMs: 10, maxDelayMs: 50, maxAttempts: 5 },
      heartbeatIntervalMs: 0,
      debug: false,
    });

    client.connect('conv-a');
    await vi.runOnlyPendingTimersAsync();
    expect(sockets.length).toBe(1);
    sockets[0]!.simulateOpen();
    expect(client.state).toBe(ConnectionState.Connected);

    client.connect('conv-b');
    await vi.runOnlyPendingTimersAsync();
    expect(sockets.length).toBe(2);
    sockets[1]!.simulateOpen();
    expect(client.state).toBe(ConnectionState.Connected);

    sockets[0]!.simulateClose(1005, '');
    expect(client.state).toBe(ConnectionState.Connected);

    await vi.advanceTimersByTimeAsync(60_000);
    expect(client.state).toBe(ConnectionState.Connected);
  });

  it('ExecutionStreamClient ignores stale socket onclose after switching run target', async () => {
    const sockets = installMockWebSocket();
    const client = new ExecutionStreamClient({
      baseUrl: 'http://localhost:8080',
      authToken: 'tok',
      reconnect: { enabled: true, baseDelayMs: 10, maxDelayMs: 50, maxAttempts: 5 },
      heartbeatIntervalMs: 0,
      debug: false,
    });

    client.connect({ runId: 'run-a' });
    await vi.runOnlyPendingTimersAsync();
    expect(sockets.length).toBe(1);
    sockets[0]!.simulateOpen();
    expect(client.state).toBe(ConnectionState.Connected);

    client.connect({ runId: 'run-b' });
    await vi.runOnlyPendingTimersAsync();
    expect(sockets.length).toBe(2);
    sockets[1]!.simulateOpen();
    expect(client.state).toBe(ConnectionState.Connected);

    sockets[0]!.simulateClose(1005, '');
    expect(client.state).toBe(ConnectionState.Connected);

    await vi.advanceTimersByTimeAsync(60_000);
    expect(client.state).toBe(ConnectionState.Connected);
  });
});
