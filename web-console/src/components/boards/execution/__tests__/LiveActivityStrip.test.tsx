import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LiveActivityStrip } from '../LiveActivityStrip';

describe('LiveActivityStrip', () => {
  it('shows phase, step, and elapsed', () => {
    render(
      <LiveActivityStrip phaseLabel="Executing" stepLabel="Build" elapsedMs={65000} isRunning={false} />
    );
    expect(screen.getByText(/Executing: Build/)).toBeInTheDocument();
    expect(screen.getByText(/1m 5s/)).toBeInTheDocument();
  });
});
