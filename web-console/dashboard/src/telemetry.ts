export type TelemetryPayload = Record<string, unknown>;

export interface TelemetryEvent {
  event_id: string;
  timestamp: string;
  actor: {
    id: string;
    role: string;
    surface: 'web' | 'cli' | 'api' | 'vscode' | 'mcp';
  };
  run_id?: string;
  action_id?: string;
  session_id?: string;
  event_type: string;
  payload: TelemetryPayload;
}

export type TelemetrySink = (event: TelemetryEvent) => void;

declare global {
  interface Window {
    __AMPREALIZE_TELEMETRY__?: TelemetryEvent[];
  }
}

const sinks: TelemetrySink[] = [];
let sessionInitialized = false;

const ensureStore = (): void => {
  if (typeof window === 'undefined') return;
  if (!window.__AMPREALIZE_TELEMETRY__) {
    window.__AMPREALIZE_TELEMETRY__ = [];
  }
};

const randomId = (): string => {
  if (typeof window !== 'undefined' && window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

export const ensureTelemetrySession = (): void => {
  if (typeof window === 'undefined' || sessionInitialized) return;
  sessionInitialized = true;
  ensureStore();
  if (!window.sessionStorage.getItem('amprealize-session-id')) {
    const legacy = window.sessionStorage.getItem('amprealize-session-id');
    window.sessionStorage.setItem('amprealize-session-id', legacy ?? randomId());
  }
};

export const registerTelemetrySink = (sink: TelemetrySink): (() => void) => {
  sinks.push(sink);
  return () => {
    const index = sinks.indexOf(sink);
    if (index !== -1) {
      sinks.splice(index, 1);
    }
  };
};

export const getTelemetryStore = (): TelemetryEvent[] => {
  if (typeof window === 'undefined') return [];
  ensureStore();
  return window.__AMPREALIZE_TELEMETRY__ ?? [];
};

export const emitTelemetry = (eventType: string, payload: TelemetryPayload = {}): void => {
  if (typeof window === 'undefined') return;
  ensureTelemetrySession();

  const event: TelemetryEvent = {
    event_id: randomId(),
    timestamp: new Date().toISOString(),
    actor: {
      id:
        window.localStorage.getItem('amprealize-actor-id') ??
        window.localStorage.getItem('amprealize-actor-id') ??
        'anonymous-web',
      role: 'STUDENT',
      surface: 'web',
    },
    session_id:
      window.sessionStorage.getItem('amprealize-session-id') ??
      window.sessionStorage.getItem('amprealize-session-id') ??
      undefined,
    event_type: eventType,
    payload: { ...payload },
  };

  ensureStore();
  window.__AMPREALIZE_TELEMETRY__?.push(event);
  sinks.forEach((sink) => sink(event));
  window.dispatchEvent(new CustomEvent('amprealize-telemetry', { detail: event }));
};
