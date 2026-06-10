import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { PhaseTimeline } from '../PhaseTimeline';
import type { ExecutionStep } from '../../../../lib/collab-client';

function step(overrides: Partial<ExecutionStep>): ExecutionStep {
  return {
    stepId: 's1',
    name: 'n',
    status: 'completed',
    phase: 'executing',
    stepType: 't',
    startedAt: '2020-01-01T00:00:00.000Z',
    completedAt: null,
    progressPct: null,
    durationMs: 10,
    inputTokens: 0,
    outputTokens: 0,
    costUsd: null,
    toolCalls: 0,
    contentPreview: null,
    contentFull: null,
    toolNames: null,
    modelId: null,
    error: null,
    metadata: {},
    ...overrides,
  };
}

describe('PhaseTimeline', () => {
  it('groups GEP steps under GEP phase buckets', () => {
    const steps = [
      step({ stepId: 'a', phase: 'planning', name: 'Plan' }),
      step({ stepId: 'b', phase: 'executing', name: 'Do' }),
    ];
    render(<PhaseTimeline steps={steps} pipeline="gep" />);
    const planning = screen.getByText('Planning').closest('details');
    expect(planning).toBeTruthy();
    expect(within(planning!).getByText('Plan')).toBeInTheDocument();
    const executing = screen.getByText('Executing').closest('details');
    expect(executing).toBeTruthy();
    expect(within(executing!).getByText('Do')).toBeInTheDocument();
  });

  it('groups research steps under research phase labels', () => {
    const steps = [
      step({ stepId: 'r1', phase: 'research_evaluate', name: 'Evaluate: done', contentPreview: 'ok' }),
      step({ stepId: 'r2', phase: 'research_finalize', name: 'Finalize: report' }),
    ];
    render(<PhaseTimeline steps={steps} pipeline="research" />);
    expect(screen.queryByText('Executing')).not.toBeInTheDocument();
    const evalGroup = screen.getByText('Evaluate').closest('details');
    expect(evalGroup).toBeTruthy();
    expect(within(evalGroup!).getByText('Evaluate: done')).toBeInTheDocument();
    const fin = screen.getByText('Finalize').closest('details');
    expect(fin).toBeTruthy();
    expect(within(fin!).getByText('Finalize: report')).toBeInTheDocument();
  });

  it('shows research-specific empty copy', () => {
    render(<PhaseTimeline steps={[]} pipeline="research" />);
    expect(screen.getByRole('status')).toHaveTextContent('research step log');
  });
});
