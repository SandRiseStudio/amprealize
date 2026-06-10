import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PhaseStepper } from '../PhaseStepper';
import type { PhaseRowModel } from '../selectPhaseModel';
import { GEP_PHASE_ORDER } from '../selectPhaseModel';

function rowsForAllDone(): PhaseRowModel[] {
  return GEP_PHASE_ORDER.map((id) => ({
    id,
    label: id,
    status: 'done',
    durationMs: 100,
  }));
}

describe('PhaseStepper', () => {
  it('renders eight phases and marks aria-current on running step', () => {
    const phases = GEP_PHASE_ORDER.map((id, i) => ({
      id,
      label: id,
      status: i < 2 ? 'done' : i === 2 ? 'running' : 'idle',
      durationMs: null,
    })) as PhaseRowModel[];

    render(<PhaseStepper phases={phases} currentPhaseIndex={2} />);
    expect(screen.getByLabelText('Execution phases')).toBeInTheDocument();
    const current = screen.getByRole('listitem', { current: 'step' });
    expect(current).toHaveTextContent('architecting');
  });

  it('exposes alert role on failed phase', () => {
    const phases = rowsForAllDone().map((p) =>
      p.id === 'verifying' ? { ...p, status: 'failed' as const } : p
    );
    render(<PhaseStepper phases={phases} currentPhaseIndex={GEP_PHASE_ORDER.indexOf('verifying')} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});
