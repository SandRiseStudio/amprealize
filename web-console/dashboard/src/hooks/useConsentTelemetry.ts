import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { ConsentMetric, ConsentSnapshot } from '../data';
import {
  emitTelemetry,
  ensureTelemetrySession,
  getTelemetryStore,
  registerTelemetrySink,
  TelemetryEvent,
} from '../telemetry';

const cloneMetric = (metric: ConsentMetric): ConsentMetric => ({ ...metric });

const toMetric = (entry: Record<string, unknown>): ConsentMetric => ({
  surface: String(entry.surface ?? 'unknown'),
  prompts: Number(entry.prompts ?? 0),
  approvals: Number(entry.approvals ?? 0),
  denials: Number(entry.denials ?? 0),
  snoozes: Number(entry.snoozes ?? 0),
  mfaRequired: Number(entry.mfa_required ?? entry.mfaRequired ?? 0),
  mfaCompleted: Number(entry.mfa_completed ?? entry.mfaCompleted ?? 0),
  averageLatencySeconds: Number(entry.avg_latency_seconds ?? entry.averageLatencySeconds ?? 0),
  p95LatencySeconds: Number(entry.p95_latency_seconds ?? entry.p95LatencySeconds ?? 0),
});

const buildSnapshotPayload = (snapshot: ConsentSnapshot): Record<string, unknown> => ({
  updated_at: snapshot.updated,
  metrics: snapshot.metrics.map((metric) => ({
    surface: metric.surface,
    prompts: metric.prompts,
    approvals: metric.approvals,
    denials: metric.denials,
    snoozes: metric.snoozes,
    mfa_required: metric.mfaRequired,
    mfa_completed: metric.mfaCompleted,
    avg_latency_seconds: metric.averageLatencySeconds,
    p95_latency_seconds: metric.p95LatencySeconds,
  })),
});

const percentile = (values: number[], percentileValue: number): number => {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.floor(percentileValue * (sorted.length - 1)));
  return sorted[index];
};

const initialiseLatencySamples = (
  snapshot: ConsentSnapshot,
  store: Map<string, number[]>
): void => {
  store.clear();
  snapshot.metrics.forEach((metric) => {
    const samples: number[] = [];
    if (metric.prompts > 0) {
      const steadySamples = Math.max(metric.prompts - 1, 0);
      for (let i = 0; i < steadySamples; i += 1) {
        samples.push(metric.averageLatencySeconds);
      }
      samples.push(metric.p95LatencySeconds);
    }
    store.set(metric.surface, samples);
  });
};

const applySnapshotEvent = (
  payload: Record<string, unknown>,
  setMetrics: (metrics: ConsentMetric[]) => void,
  setUpdatedAt: (updated: string) => void,
  latencyStore: Map<string, number[]>
): void => {
  const rawMetrics = (payload.metrics as Record<string, unknown>[]) ?? [];
  const metrics = rawMetrics.map(toMetric);
  setMetrics(metrics);
  const updatedAt = String(payload.updated_at ?? payload.updatedAt ?? new Date().toISOString());
  setUpdatedAt(updatedAt);
  latencyStore.clear();
  metrics.forEach((metric) => {
    const samples: number[] = [];
    if (metric.prompts > 0) {
      const steadySamples = Math.max(metric.prompts - 1, 0);
      for (let i = 0; i < steadySamples; i += 1) {
        samples.push(metric.averageLatencySeconds);
      }
      samples.push(metric.p95LatencySeconds);
    }
    latencyStore.set(metric.surface, samples);
  });
};

const applyPromptEvent = (
  event: TelemetryEvent,
  setMetrics: (updater: (prev: ConsentMetric[]) => ConsentMetric[]) => void,
  setUpdatedAt: (updated: string) => void,
  latencyStore: Map<string, number[]>
): void => {
  const surface = String(event.payload.surface ?? 'unknown');
  const decision = String(event.payload.decision ?? 'approved');
  const latencySeconds = Number(event.payload.latency_seconds ?? event.payload.latencySeconds ?? 0);
  const requiresMfa = Boolean(event.payload.mfa_required ?? event.payload.mfaRequired ?? false);
  const completedMfa = Boolean(event.payload.mfa_completed ?? event.payload.mfaCompleted ?? false);

  setMetrics((previous) => {
    const next = previous.map(cloneMetric);
    let index = next.findIndex((metric) => metric.surface === surface);
    if (index === -1) {
      next.push({
        surface,
        prompts: 0,
        approvals: 0,
        denials: 0,
        snoozes: 0,
        mfaRequired: 0,
        mfaCompleted: 0,
        averageLatencySeconds: 0,
        p95LatencySeconds: 0,
      });
      index = next.length - 1;
    }

    const metric = next[index];
    metric.prompts += 1;

    if (decision === 'approved') {
      metric.approvals += 1;
    } else if (decision === 'denied') {
      metric.denials += 1;
    } else if (decision === 'snoozed') {
      metric.snoozes += 1;
    }

    if (requiresMfa) {
      metric.mfaRequired += 1;
      if (completedMfa) {
        metric.mfaCompleted += 1;
      }
    }

    if (!Number.isNaN(latencySeconds) && latencySeconds > 0) {
      const samples = latencyStore.get(surface) ?? [];
      samples.push(latencySeconds);
      latencyStore.set(surface, samples);
      const total = samples.reduce((sum, value) => sum + value, 0);
      metric.averageLatencySeconds = total / samples.length;
      metric.p95LatencySeconds = percentile(samples, 0.95);
    }

    next[index] = { ...metric };
    return next;
  });

  setUpdatedAt(event.timestamp);
};

export interface ConsentTelemetryState {
  metrics: ConsentMetric[];
  updatedAt: string;
}

export const useConsentTelemetry = (initialSnapshot: ConsentSnapshot): ConsentTelemetryState => {
  const [metrics, setMetrics] = useState<ConsentMetric[]>(initialSnapshot.metrics.map(cloneMetric));
  const [updatedAt, setUpdatedAt] = useState<string>(initialSnapshot.updated);
  const latencyStoreRef = useRef<Map<string, number[]>>(new Map());

  useEffect(() => {
    initialiseLatencySamples(initialSnapshot, latencyStoreRef.current);
  }, [initialSnapshot]);

  useEffect(() => {
    ensureTelemetrySession();

    const existingEvents = getTelemetryStore();
    existingEvents
      .filter((event) => event.event_type === 'consent.snapshot')
      .forEach((event) => {
        applySnapshotEvent(event.payload as Record<string, unknown>, setMetrics, setUpdatedAt, latencyStoreRef.current);
      });

    if (!existingEvents.some((event) => event.event_type === 'consent.snapshot')) {
      emitTelemetry('consent.snapshot', buildSnapshotPayload(initialSnapshot));
    }

    const unsubscribe = registerTelemetrySink((event) => {
      if (event.event_type === 'consent.snapshot') {
        applySnapshotEvent(event.payload as Record<string, unknown>, setMetrics, setUpdatedAt, latencyStoreRef.current);
      }
      if (event.event_type === 'consent.prompt_finished') {
        applyPromptEvent(event, setMetrics, setUpdatedAt, latencyStoreRef.current);
      }
    });

    return () => {
      unsubscribe();
    };
  }, [initialSnapshot]);

  return useMemo(
    () => ({
      metrics,
      updatedAt,
    }),
    [metrics, updatedAt]
  );
};
