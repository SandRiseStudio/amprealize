import { describe, expect, it } from 'vitest';
import type { ExecutionStatus, ExecutionStep } from '../../../../lib/collab-client';
import { GEP_PHASE_ORDER, selectPhaseModel } from '../selectPhaseModel';

function baseStatus(overrides: Partial<ExecutionStatus> = {}): ExecutionStatus {
  return {
    hasExecution: true,
    runId: 'run-1',
    workItemId: 'w1',
    agentId: 'a1',
    projectId: 'p1',
    orgId: 'o1',
    state: 'running',
    phase: 'executing',
    startedAt: '2026-01-01T00:00:00.000Z',
    completedAt: null,
    progressPct: 40,
    currentStep: 'Indexing repo',
    totalTokens: 100,
    totalCostUsd: 0.01,
    toolCount: 1,
    stepCount: 1,
    error: null,
    lastError: null,
    modelId: null,
    surface: null,
    sourceType: null,
    conversationId: null,
    messageId: null,
    requestId: null,
    executionMode: null,
    queueJobId: null,
    queueMetadata: null,
    phaseTimings: {
      planning: { duration_ms: 500 },
      clarifying: { duration_ms: 300 },
    },
    traceSummary: null,
    pendingClarifications: [],
    ...overrides,
  };
}

describe('selectPhaseModel', () => {
  it('returns eight GEP phases in order', () => {
    const m = selectPhaseModel(baseStatus(), [], { pipeline: 'gep' });
    expect(m.phases.map((p) => p.id)).toEqual([...GEP_PHASE_ORDER]);
  });

  it('returns research pipeline phases when pipeline is research', () => {
    const m = selectPhaseModel(
      baseStatus({ phase: 'research_evaluate', state: 'running' }),
      [],
      { pipeline: 'research' },
    );
    expect(m.phases.map((p) => p.id).every((id) => id.startsWith('research_'))).toBe(true);
    const ev = m.phases.find((p) => p.id === 'research_evaluate');
    expect(ev?.status).toBe('running');
  });

  it('marks phases before current as done when running', () => {
    const m = selectPhaseModel(
      baseStatus({
        phase: 'testing',
        phaseTimings: {
          planning: { duration_ms: 100 },
          clarifying: { duration_ms: 100 },
          architecting: { duration_ms: 100 },
          executing: { duration_ms: 100 },
        },
      }),
      [],
      { pipeline: 'gep' },
    );
    const testingIdx = GEP_PHASE_ORDER.indexOf('testing');
    expect(m.phases[0]?.status).toBe('done');
    expect(m.phases[testingIdx]?.status).toBe('running');
    expect(m.phases[testingIdx + 1]?.status).toBe('idle');
  });

  it('marks failed phase from status.phase', () => {
    const m = selectPhaseModel(
      baseStatus({
        state: 'failed',
        phase: 'verifying',
        lastError: 'Gate rejected',
      }),
      [],
      { pipeline: 'gep' },
    );
    const idx = GEP_PHASE_ORDER.indexOf('verifying');
    expect(m.phases[idx]?.status).toBe('failed');
    expect(m.errorMessage).toBe('Gate rejected');
  });

  it('reads errorClass from last ERROR step metadata', () => {
    const steps: ExecutionStep[] = [
      {
        stepId: 's1',
        phase: 'executing',
        stepType: 'llm',
        startedAt: '2026-01-01T00:00:01.000Z',
        completedAt: '2026-01-01T00:00:02.000Z',
        name: 'Call',
        status: 'ERROR',
        progressPct: null,
        durationMs: 1000,
        inputTokens: 0,
        outputTokens: 0,
        costUsd: null,
        toolCalls: 0,
        contentPreview: null,
        contentFull: null,
        toolNames: null,
        modelId: null,
        error: 'boom',
        metadata: { error_class: 'ToolExecutionError' },
      },
    ];
    const m = selectPhaseModel(baseStatus({ state: 'failed', lastError: null }), steps, { pipeline: 'gep' });
    expect(m.errorClass).toBe('ToolExecutionError');
    expect(m.errorMessage).toBe('boom');
  });
});
