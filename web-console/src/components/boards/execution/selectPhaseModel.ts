/**
 * Phase-aware view model for execution UI (Student).
 * Maps REST/WS execution status + steps into declarative phase rows for the drawer.
 *
 * - **GEP** (default): planning → … → completing (agent execution loop).
 * - **Research**: ingest → comprehend → … → finalize (AI research evaluation pipeline).
 */

import type { ExecutionState, ExecutionStatus, ExecutionStep } from '../../../lib/collab-client';

export const GEP_PHASE_ORDER = [
  'planning',
  'clarifying',
  'architecting',
  'executing',
  'testing',
  'fixing',
  'verifying',
  'completing',
] as const;

export type GepPhaseId = (typeof GEP_PHASE_ORDER)[number];

/** Canonical research pipeline phases (mirrors ResearchService.evaluate progress). */
export const RESEARCH_PHASE_ORDER = [
  'research_ingest',
  'research_comprehend',
  'research_codebase',
  'research_evaluate',
  'research_recommend',
  'research_finalize',
] as const;

export type ResearchPhaseId = (typeof RESEARCH_PHASE_ORDER)[number];

export type PhaseRowStatus = 'idle' | 'running' | 'done' | 'failed' | 'skipped';

export interface PhaseRowModel {
  id: string;
  label: string;
  status: PhaseRowStatus;
  durationMs?: number | null;
}

export interface PhaseExecutionModel {
  phases: PhaseRowModel[];
  /** Resolved phase index for the current run, or -1 if unknown / pre-start */
  currentPhaseIndex: number;
  /** Current phase id from the active pipeline (GEP or research slug). */
  currentGepPhase: string | null;
  currentStepLabel: string;
  elapsedMs: number;
  /** Raw phase string from API when failed (may be outside known list) */
  failingPhase: string | null;
  errorMessage: string | null;
  errorClass: string | null;
  isActiveExecution: boolean;
}

const PHASE_ALIASES: Record<string, GepPhaseId> = {
  implementation: 'executing',
  coding: 'executing',
  queue_dispatch: 'executing',
};

/** Short labels for research pipeline phases (timeline, stepper). */
export const RESEARCH_LABELS: Record<string, string> = {
  research_ingest: 'Ingest',
  research_comprehend: 'Comprehend',
  research_codebase: 'Codebase',
  research_evaluate: 'Evaluate',
  research_recommend: 'Recommend',
  research_finalize: 'Finalize',
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function numberValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function titleCasePhase(id: string): string {
  return id
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
}

function resolveGepPhase(raw: string | null | undefined): GepPhaseId | null {
  if (!raw) return null;
  const key = raw.toLowerCase().trim();
  if ((GEP_PHASE_ORDER as readonly string[]).includes(key)) {
    return key as GepPhaseId;
  }
  return PHASE_ALIASES[key] ?? null;
}

function mergePhaseTimings(status: ExecutionStatus | null): Record<string, unknown> {
  if (!status) return {};
  const trace = status.traceSummary && typeof status.traceSummary === 'object' ? asRecord(status.traceSummary) : {};
  const fromTrace = trace.phase_timings;
  const a = typeof fromTrace === 'object' && fromTrace && !Array.isArray(fromTrace) ? (fromTrace as Record<string, unknown>) : {};
  const b = status.phaseTimings && typeof status.phaseTimings === 'object' && !Array.isArray(status.phaseTimings)
    ? (status.phaseTimings as Record<string, unknown>)
    : {};
  return { ...a, ...b };
}

function timingDurationMs(timings: Record<string, unknown>, phaseId: string): number | null {
  const raw = timings[phaseId];
  const entry = asRecord(raw);
  return numberValue(entry.duration_ms);
}

function lastErrorStep(steps: readonly ExecutionStep[]): ExecutionStep | null {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const s = steps[i];
    const st = (s.status ?? '').toUpperCase();
    if (st === 'ERROR' || st === 'FAILED' || s.error) {
      return s;
    }
  }
  return null;
}

function isActiveState(state: ExecutionState | null | undefined): boolean {
  if (!state) return false;
  const s = String(state).toLowerCase();
  return s === 'running' || s === 'paused' || s === 'pending';
}

function researchPhaseIndex(raw: string | null | undefined): number {
  if (!raw) return -1;
  const key = raw.toLowerCase().trim();
  if (key === 'completed') {
    return RESEARCH_PHASE_ORDER.length;
  }
  const order = RESEARCH_PHASE_ORDER as readonly string[];
  const idx = order.indexOf(key as ResearchPhaseId);
  if (idx >= 0) return idx;
  if (key === 'research' || key === 'planning') {
    return 0;
  }
  return -1;
}

function selectResearchPhaseModel(status: ExecutionStatus | null, steps: readonly ExecutionStep[]): PhaseExecutionModel {
  const timings = mergePhaseTimings(status);
  const rawPhase = status?.phase ?? null;
  let currentPhaseIndex = researchPhaseIndex(rawPhase);
  const order = RESEARCH_PHASE_ORDER as readonly string[];

  const lastStep = steps.length > 0 ? steps[steps.length - 1] : null;
  const currentStepLabel =
    status?.currentStep?.trim() ||
    lastStep?.name?.trim() ||
    lastStep?.contentPreview?.trim() ||
    (rawPhase ? titleCasePhase(String(rawPhase).replace(/^research_/, '')) : 'Idle');

  const state = status?.state ?? null;
  if (
    (state === 'running' || state === 'pending' || state === 'paused') &&
    currentPhaseIndex >= order.length
  ) {
    currentPhaseIndex = order.length - 1;
  }

  const startedAt = status?.startedAt ? Date.parse(status.startedAt) : NaN;
  const completedAt = status?.completedAt ? Date.parse(status.completedAt) : NaN;
  const now = Date.now();
  let elapsedMs = 0;
  if (Number.isFinite(startedAt)) {
    if (Number.isFinite(completedAt)) {
      elapsedMs = Math.max(0, completedAt - startedAt);
    } else if (isActiveState(state) || state === 'completed' || state === 'failed' || state === 'cancelled') {
      elapsedMs = Math.max(0, now - startedAt);
    }
  }

  const errStep = lastErrorStep(steps);
  const errorMessage =
    status?.lastError?.trim() ||
    status?.error?.trim() ||
    errStep?.error?.trim() ||
    null;
  const meta = errStep?.metadata ? asRecord(errStep.metadata) : {};
  const errorClass =
    stringValue(meta.error_class) ||
    stringValue(meta.errorClass) ||
    stringValue(meta.class) ||
    null;

  const failingPhaseRaw =
    state === 'failed'
      ? rawPhase?.trim() || errStep?.phase?.trim() || (currentPhaseIndex >= 0 ? order[currentPhaseIndex] : null)
      : null;

  if (state === 'failed' && currentPhaseIndex < 0 && failingPhaseRaw) {
    currentPhaseIndex = researchPhaseIndex(failingPhaseRaw);
  }

  const isActiveExecution = Boolean(status?.hasExecution && isActiveState(state));

  let inferredFailIndex = -1;
  if (state === 'failed' && currentPhaseIndex < 0) {
    let lastTimed = -1;
    order.forEach((p, i) => {
      const d = timingDurationMs(timings, p);
      if (d != null && d > 0) lastTimed = i;
    });
    inferredFailIndex = lastTimed >= 0 ? Math.min(lastTimed + 1, order.length - 1) : 0;
  }

  const phases: PhaseRowModel[] = order.map((id) => {
    const durationMs = timingDurationMs(timings, id);
    let rowStatus: PhaseRowStatus = 'idle';

    if (state === 'completed') {
      rowStatus = 'done';
    } else if (state === 'failed') {
      const idx = order.indexOf(id);
      const failIdx = currentPhaseIndex >= 0 ? currentPhaseIndex : inferredFailIndex;
      if (failIdx >= 0) {
        if (idx < failIdx) rowStatus = 'done';
        else if (idx === failIdx) rowStatus = 'failed';
        else rowStatus = 'skipped';
      } else {
        rowStatus = 'skipped';
      }
    } else if (state === 'cancelled') {
      const idx = order.indexOf(id);
      if (currentPhaseIndex >= 0) {
        if (idx < currentPhaseIndex) rowStatus = 'done';
        else if (idx === currentPhaseIndex) rowStatus = 'skipped';
        else rowStatus = 'skipped';
      } else if (durationMs != null && durationMs > 0) {
        rowStatus = 'done';
      } else {
        rowStatus = 'skipped';
      }
    } else if (!status?.hasExecution || !state) {
      rowStatus = 'idle';
    } else {
      const idx = order.indexOf(id);
      if (currentPhaseIndex < 0) {
        rowStatus = durationMs != null && durationMs > 0 ? 'done' : 'idle';
      } else if (idx < currentPhaseIndex) {
        rowStatus = 'done';
      } else if (idx === currentPhaseIndex) {
        rowStatus = 'running';
      } else {
        rowStatus = 'idle';
      }
    }

    return {
      id,
      label: RESEARCH_LABELS[id] ?? titleCasePhase(id.replace(/^research_/, '')),
      status: rowStatus,
      durationMs,
    };
  });

  const resolvedCurrent =
    rawPhase && typeof rawPhase === 'string'
      ? rawPhase.toLowerCase().trim()
      : null;

  return {
    phases,
    currentPhaseIndex,
    currentGepPhase: resolvedCurrent,
    currentStepLabel,
    elapsedMs,
    failingPhase: failingPhaseRaw,
    errorMessage,
    errorClass,
    isActiveExecution,
  };
}

function selectGepPhaseModel(status: ExecutionStatus | null, steps: readonly ExecutionStep[]): PhaseExecutionModel {
  const timings = mergePhaseTimings(status);
  const rawPhase = status?.phase ?? null;
  const resolvedCurrent = resolveGepPhase(rawPhase);
  let currentPhaseIndex = resolvedCurrent ? (GEP_PHASE_ORDER as readonly string[]).indexOf(resolvedCurrent) : -1;

  const lastStep = steps.length > 0 ? steps[steps.length - 1] : null;
  const currentStepLabel =
    status?.currentStep?.trim() ||
    lastStep?.name?.trim() ||
    lastStep?.contentPreview?.trim() ||
    (resolvedCurrent ? titleCasePhase(resolvedCurrent) : 'Idle');

  const state = status?.state ?? null;
  const startedAt = status?.startedAt ? Date.parse(status.startedAt) : NaN;
  const completedAt = status?.completedAt ? Date.parse(status.completedAt) : NaN;
  const now = Date.now();
  let elapsedMs = 0;
  if (Number.isFinite(startedAt)) {
    if (Number.isFinite(completedAt)) {
      elapsedMs = Math.max(0, completedAt - startedAt);
    } else if (isActiveState(state) || state === 'completed' || state === 'failed' || state === 'cancelled') {
      elapsedMs = Math.max(0, now - startedAt);
    }
  }

  const errStep = lastErrorStep(steps);
  const errorMessage =
    status?.lastError?.trim() ||
    status?.error?.trim() ||
    errStep?.error?.trim() ||
    null;
  const meta = errStep?.metadata ? asRecord(errStep.metadata) : {};
  const errorClass =
    stringValue(meta.error_class) ||
    stringValue(meta.errorClass) ||
    stringValue(meta.class) ||
    null;

  const failingPhaseRaw =
    state === 'failed'
      ? rawPhase?.trim() || errStep?.phase?.trim() || resolvedCurrent || null
      : null;

  if (state === 'failed' && currentPhaseIndex < 0 && failingPhaseRaw) {
    const g = resolveGepPhase(failingPhaseRaw);
    if (g) currentPhaseIndex = (GEP_PHASE_ORDER as readonly string[]).indexOf(g);
  }

  const isActiveExecution = Boolean(status?.hasExecution && isActiveState(state));

  let inferredFailIndex = -1;
  if (state === 'failed' && currentPhaseIndex < 0) {
    let lastTimed = -1;
    GEP_PHASE_ORDER.forEach((p, i) => {
      const d = timingDurationMs(timings, p);
      if (d != null && d > 0) lastTimed = i;
    });
    inferredFailIndex = lastTimed >= 0 ? Math.min(lastTimed + 1, GEP_PHASE_ORDER.length - 1) : 0;
  }

  const phases: PhaseRowModel[] = GEP_PHASE_ORDER.map((id) => {
    const durationMs = timingDurationMs(timings, id);
    let rowStatus: PhaseRowStatus = 'idle';

    if (state === 'completed') {
      rowStatus = 'done';
    } else if (state === 'failed') {
      const idx = (GEP_PHASE_ORDER as readonly string[]).indexOf(id);
      const failIdx = currentPhaseIndex >= 0 ? currentPhaseIndex : inferredFailIndex;
      if (failIdx >= 0) {
        if (idx < failIdx) rowStatus = 'done';
        else if (idx === failIdx) rowStatus = 'failed';
        else rowStatus = 'skipped';
      } else {
        rowStatus = 'skipped';
      }
    } else if (state === 'cancelled') {
      const idx = (GEP_PHASE_ORDER as readonly string[]).indexOf(id);
      if (currentPhaseIndex >= 0) {
        if (idx < currentPhaseIndex) rowStatus = 'done';
        else if (idx === currentPhaseIndex) rowStatus = 'skipped';
        else rowStatus = 'skipped';
      } else if (durationMs != null && durationMs > 0) {
        rowStatus = 'done';
      } else {
        rowStatus = 'skipped';
      }
    } else if (!status?.hasExecution || !state) {
      rowStatus = 'idle';
    } else {
      const idx = (GEP_PHASE_ORDER as readonly string[]).indexOf(id);
      if (currentPhaseIndex < 0) {
        rowStatus = durationMs != null && durationMs > 0 ? 'done' : 'idle';
      } else if (idx < currentPhaseIndex) {
        rowStatus = 'done';
      } else if (idx === currentPhaseIndex) {
        rowStatus = 'running';
      } else {
        rowStatus = 'idle';
      }
    }

    return {
      id,
      label: titleCasePhase(id),
      status: rowStatus,
      durationMs,
    };
  });

  return {
    phases,
    currentPhaseIndex,
    currentGepPhase: resolvedCurrent,
    currentStepLabel,
    elapsedMs,
    failingPhase: failingPhaseRaw,
    errorMessage,
    errorClass,
    isActiveExecution,
  };
}

/**
 * Build phase rows, timing, and error metadata for ExecutionProgress / PhaseStepper.
 *
 * @param options.pipeline — `research` for research work items; default `gep`.
 */
export function selectPhaseModel(
  status: ExecutionStatus | null,
  steps: readonly ExecutionStep[],
  options: { pipeline?: 'gep' | 'research' } = {},
): PhaseExecutionModel {
  const pipeline = options.pipeline ?? 'gep';
  if (pipeline === 'research') {
    return selectResearchPhaseModel(status, steps);
  }
  return selectGepPhaseModel(status, steps);
}
