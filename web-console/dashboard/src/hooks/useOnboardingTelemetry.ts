import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { OnboardingMetric, OnboardingSnapshot } from '../data';
import {
  emitTelemetry,
  ensureTelemetrySession,
  getTelemetryStore,
  registerTelemetrySink,
  TelemetryEvent,
} from '../telemetry';

interface Counters {
  runs: number;
  totalTime: number;
  checklistCompleted: number;
  behaviorSearchEvents: number;
  behaviorInsertions: number;
  behaviorReuseHits: number;
  tokenSavingsTotal: number;
  taskCompleted: number;
  complianceLogged: number;
}

const cloneMetric = (metric: OnboardingMetric): OnboardingMetric => ({ ...metric });

const toCountersFromMetric = (metric: OnboardingMetric): Counters => {
  const sample = Math.max(metric.sampleSize, 0);
  return {
    runs: sample,
    totalTime: metric.averageTimeToFirstBehaviorMinutes * sample,
    checklistCompleted: Math.round((metric.checklistCompletionRate / 100) * sample),
    behaviorSearchEvents: sample,
    behaviorInsertions: Math.round((metric.behaviorSearchToInsertRate / 100) * sample),
    behaviorReuseHits: Math.round((metric.behaviorReuseRate / 100) * sample),
    tokenSavingsTotal: metric.tokenSavingsAverage * sample,
    taskCompleted: Math.round((metric.taskCompletionRate / 100) * sample),
    complianceLogged: Math.round((metric.complianceCoverage / 100) * sample),
  };
};

const countersToMetric = (surface: string, counters: Counters): OnboardingMetric => {
  const runs = Math.max(counters.runs, 0);
  const sampleSize = runs;
  const averageTime = runs === 0 ? 0 : counters.totalTime / runs;
  const checklist = runs === 0 ? 0 : (counters.checklistCompleted / runs) * 100;
  const searchEvents = Math.max(counters.behaviorSearchEvents, runs === 0 ? 1 : 0);
  const searchInsert = searchEvents === 0 ? 0 : (counters.behaviorInsertions / searchEvents) * 100;
  const behaviorReuse = runs === 0 ? 0 : (counters.behaviorReuseHits / runs) * 100;
  const tokenSavings = runs === 0 ? 0 : counters.tokenSavingsTotal / runs;
  const taskCompletion = runs === 0 ? 0 : (counters.taskCompleted / runs) * 100;
  const compliance = runs === 0 ? 0 : (counters.complianceLogged / runs) * 100;

  return {
    surface,
    sampleSize,
    averageTimeToFirstBehaviorMinutes: averageTime,
    checklistCompletionRate: checklist,
    behaviorSearchToInsertRate: searchInsert,
    behaviorReuseRate: behaviorReuse,
    tokenSavingsAverage: tokenSavings,
    taskCompletionRate: taskCompletion,
    complianceCoverage: compliance,
  };
};

const buildSnapshotPayload = (snapshot: OnboardingSnapshot): Record<string, unknown> => ({
  updated_at: snapshot.updated,
  metrics: snapshot.metrics.map((metric) => ({
    surface: metric.surface,
    sample_size: metric.sampleSize,
    avg_time_to_first_behavior_minutes: metric.averageTimeToFirstBehaviorMinutes,
    checklist_completion_pct: metric.checklistCompletionRate,
    behavior_search_to_insert_pct: metric.behaviorSearchToInsertRate,
    behavior_reuse_pct: metric.behaviorReuseRate,
    token_savings_pct: metric.tokenSavingsAverage,
    task_completion_pct: metric.taskCompletionRate,
    compliance_coverage_pct: metric.complianceCoverage,
  })),
});

const parseSnapshotCounters = (snapshot: OnboardingSnapshot): Map<string, Counters> => {
  const map = new Map<string, Counters>();
  snapshot.metrics.forEach((metric) => {
    map.set(metric.surface, toCountersFromMetric(metric));
  });
  return map;
};

const updateMetricsFromCounters = (
  countersMap: Map<string, Counters>,
  setMetrics: (metrics: OnboardingMetric[]) => void
): void => {
  const metrics = Array.from(countersMap.entries())
    .map(([surface, counters]) => countersToMetric(surface, counters))
    .sort((a, b) => a.surface.localeCompare(b.surface));
  setMetrics(metrics);
};

const applySnapshotEvent = (
  payload: Record<string, unknown>,
  countersMap: Map<string, Counters>,
  setMetrics: (metrics: OnboardingMetric[]) => void,
  setUpdatedAt: (value: string) => void
): void => {
  countersMap.clear();
  const rows = (payload.metrics as Record<string, unknown>[]) ?? [];
  rows.forEach((row) => {
    const surface = String(row.surface ?? 'unknown');
    const sampleSize = Number(row.sample_size ?? row.sampleSize ?? 0);
    const counters = toCountersFromMetric({
      surface,
      sampleSize,
      averageTimeToFirstBehaviorMinutes: Number(
        row.avg_time_to_first_behavior_minutes ?? row.averageTimeToFirstBehaviorMinutes ?? 0
      ),
      checklistCompletionRate: Number(row.checklist_completion_pct ?? row.checklistCompletionRate ?? 0),
      behaviorSearchToInsertRate: Number(row.behavior_search_to_insert_pct ?? row.behaviorSearchToInsertRate ?? 0),
      behaviorReuseRate: Number(row.behavior_reuse_pct ?? row.behaviorReuseRate ?? 0),
      tokenSavingsAverage: Number(row.token_savings_pct ?? row.tokenSavingsAverage ?? 0),
      taskCompletionRate: Number(row.task_completion_pct ?? row.taskCompletionRate ?? 0),
      complianceCoverage: Number(row.compliance_coverage_pct ?? row.complianceCoverage ?? 0),
    });
    countersMap.set(surface, counters);
  });
  updateMetricsFromCounters(countersMap, setMetrics);
  const updated = String(payload.updated_at ?? payload.updatedAt ?? new Date().toISOString());
  setUpdatedAt(updated);
};

const applyRunEvent = (
  event: TelemetryEvent,
  countersMap: Map<string, Counters>,
  setMetrics: (metrics: OnboardingMetric[]) => void,
  setUpdatedAt: (value: string) => void
): void => {
  const surface = String(event.payload.surface ?? 'unknown');
  const counters = countersMap.get(surface) ?? {
    runs: 0,
    totalTime: 0,
    checklistCompleted: 0,
    behaviorSearchEvents: 0,
    behaviorInsertions: 0,
    behaviorReuseHits: 0,
    tokenSavingsTotal: 0,
    taskCompleted: 0,
    complianceLogged: 0,
  };

  const timeToFirstBehavior = Number(
    event.payload.time_to_first_behavior_minutes ?? event.payload.timeToFirstBehaviorMinutes ?? 0
  );
  const checklistCompleted = Boolean(event.payload.checklist_completed ?? event.payload.checklistCompleted ?? false);
  const behaviorSearchEvents = Number(event.payload.behavior_search_events ?? event.payload.behaviorSearchEvents ?? 1);
  const behaviorInsertions = Number(event.payload.behavior_insertions ?? event.payload.behaviorInsertions ?? 0);
  const behaviorReusePayload = event.payload.behavior_reuse ?? event.payload.behaviorReuse ?? event.payload.behavior_reuse_pct;
  const tokenSavings = Number(event.payload.token_savings_pct ?? event.payload.tokenSavingsPct ?? 0);
  const taskCompleted = Boolean(event.payload.task_completed ?? event.payload.taskCompleted ?? false);
  const complianceLogged = Boolean(event.payload.compliance_logged ?? event.payload.complianceLogged ?? false);

  counters.runs += 1;
  if (!Number.isNaN(timeToFirstBehavior) && timeToFirstBehavior > 0) {
    counters.totalTime += timeToFirstBehavior;
  }
  if (checklistCompleted) {
    counters.checklistCompleted += 1;
  }
  if (!Number.isNaN(behaviorSearchEvents) && behaviorSearchEvents > 0) {
    counters.behaviorSearchEvents += behaviorSearchEvents;
    counters.behaviorInsertions += Math.max(0, Math.min(behaviorSearchEvents, behaviorInsertions));
  }
  if (typeof behaviorReusePayload === 'number' && !Number.isNaN(behaviorReusePayload)) {
    const normalized = behaviorReusePayload > 1 ? behaviorReusePayload / 100 : behaviorReusePayload;
    counters.behaviorReuseHits += Math.max(0, Math.min(1, normalized));
  } else if (typeof behaviorReusePayload === 'boolean') {
    counters.behaviorReuseHits += behaviorReusePayload ? 1 : 0;
  }
  if (!Number.isNaN(tokenSavings)) {
    counters.tokenSavingsTotal += tokenSavings;
  }
  if (taskCompleted) {
    counters.taskCompleted += 1;
  }
  if (complianceLogged) {
    counters.complianceLogged += 1;
  }

  countersMap.set(surface, counters);
  updateMetricsFromCounters(countersMap, setMetrics);
  setUpdatedAt(event.timestamp);
};

export interface OnboardingTelemetryState {
  metrics: OnboardingMetric[];
  updatedAt: string;
}

export const useOnboardingTelemetry = (initialSnapshot: OnboardingSnapshot): OnboardingTelemetryState => {
  const [metrics, setMetrics] = useState<OnboardingMetric[]>(initialSnapshot.metrics.map(cloneMetric));
  const [updatedAt, setUpdatedAt] = useState<string>(initialSnapshot.updated);
  const countersRef = useRef<Map<string, Counters>>(parseSnapshotCounters(initialSnapshot));

  useEffect(() => {
    countersRef.current = parseSnapshotCounters(initialSnapshot);
    setMetrics(initialSnapshot.metrics.map(cloneMetric));
    setUpdatedAt(initialSnapshot.updated);
  }, [initialSnapshot]);

  useEffect(() => {
    ensureTelemetrySession();

    const existing = getTelemetryStore();
    existing
      .filter((event) => event.event_type === 'analytics.onboarding.snapshot')
      .forEach((event) => {
        applySnapshotEvent(event.payload as Record<string, unknown>, countersRef.current, setMetrics, setUpdatedAt);
      });

    if (!existing.some((event) => event.event_type === 'analytics.onboarding.snapshot')) {
      emitTelemetry('analytics.onboarding.snapshot', buildSnapshotPayload(initialSnapshot));
    }

    const unsubscribe = registerTelemetrySink((event) => {
      if (event.event_type === 'analytics.onboarding.snapshot') {
        applySnapshotEvent(event.payload as Record<string, unknown>, countersRef.current, setMetrics, setUpdatedAt);
      }
      if (event.event_type === 'analytics.onboarding') {
        applyRunEvent(event, countersRef.current, setMetrics, setUpdatedAt);
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
