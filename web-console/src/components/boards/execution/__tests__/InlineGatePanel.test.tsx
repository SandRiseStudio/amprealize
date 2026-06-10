import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InlineGatePanel } from '../InlineGatePanel';

describe('InlineGatePanel', () => {
  it('shows clarification UI when questions exist', () => {
    render(
      <InlineGatePanel
        state="paused"
        questions={[{ id: 'q1', question: 'What scope?' }]}
        onClarifySubmit={vi.fn()}
        clarifySubmitting={false}
        onApproveGate={vi.fn()}
        approveGatePending={false}
      />
    );
    expect(screen.getByText('What scope?')).toBeInTheDocument();
  });

  it('shows approve gate when paused with no clarifications', async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    render(
      <InlineGatePanel
        state="paused"
        questions={[]}
        onClarifySubmit={vi.fn()}
        clarifySubmitting={false}
        onApproveGate={onApprove}
        approveGatePending={false}
      />
    );
    await user.click(screen.getByRole('button', { name: /approve strict gate/i }));
    expect(onApprove).toHaveBeenCalled();
  });
});
