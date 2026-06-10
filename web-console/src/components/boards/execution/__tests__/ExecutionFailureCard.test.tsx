import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExecutionFailureCard } from '../ExecutionFailureCard';

describe('ExecutionFailureCard', () => {
  it('renders error details and fires retry', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <ExecutionFailureCard
        failingPhase="testing"
        errorClass="AssertionError"
        errorMessage="Expected 1 to be 2"
        runId="run-xyz-123456789"
        rawRunHref="/projects/p1/traces/run-xyz-123456789"
        onRetry={onRetry}
        retryPending={false}
      />
    );
    expect(screen.getByRole('alert', { name: /execution failed/i })).toBeInTheDocument();
    expect(screen.getByText('AssertionError')).toBeInTheDocument();
    expect(screen.getByText('Expected 1 to be 2')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /retry execution/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
