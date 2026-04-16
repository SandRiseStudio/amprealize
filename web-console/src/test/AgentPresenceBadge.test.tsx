/**
 * Tests for AgentPresenceBadge component
 *
 * Verifies rendering, accessibility labels, click handling, and compact mode.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentPresenceBadge } from '../components/boards/AgentPresenceBadge';
import type { AgentPresence } from '../hooks/useAgentPresence';
import { toActorViewModel } from '../utils/actorViewModel';

function makePresence(overrides: Partial<AgentPresence> = {}): AgentPresence {
  const name = overrides.name ?? 'Code Bot';
  const presence = overrides.presence ?? 'available';
  const statusLine = overrides.statusLine ?? (presence === 'working' ? 'Working' : 'Available');

  return {
    agentId: 'agent-001',
    name,
    agentType: 'specialist',
    avatar: 'CB',
    actor: toActorViewModel(
      { id: 'agent-001', name, agent_type: 'specialist', status: 'active', config: {}, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      { presenceState: presence, presenceLabel: statusLine },
    ),
    presence,
    statusLine,
    activeItemCount: 0,
    rawStatus: 'active',
    ...overrides,
  };
}

describe('AgentPresenceBadge', () => {
  it('renders agent name and status label', () => {
    render(<AgentPresenceBadge agent={makePresence()} />);
    expect(screen.getByText('Code Bot')).toBeInTheDocument();
    expect(screen.getByText('Available')).toBeInTheDocument();
  });

  it('renders avatar initials', () => {
    render(<AgentPresenceBadge agent={makePresence({ avatar: 'CB' })} />);
    expect(screen.getByLabelText('Code Bot — Available')).toBeInTheDocument();
  });

  it('sets correct aria-label', () => {
    render(
      <AgentPresenceBadge
        agent={makePresence({ name: 'Code Bot', presence: 'working' })}
        onClick={vi.fn()}
      />,
    );
    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('aria-label', 'Code Bot – Working');
  });

  it('calls onClick with the agent when clicked', async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();
    const agent = makePresence();
    render(<AgentPresenceBadge agent={agent} onClick={handleClick} />);

    await user.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledOnce();
    expect(handleClick).toHaveBeenCalledWith(agent);
  });

  it('hides label in compact mode', () => {
    render(<AgentPresenceBadge agent={makePresence()} compact />);
    expect(screen.queryByText('Code Bot')).not.toBeInTheDocument();
  });

  it('hides label when showLabel is false', () => {
    render(<AgentPresenceBadge agent={makePresence()} showLabel={false} />);
    expect(screen.queryByText('Code Bot')).not.toBeInTheDocument();
  });

  it('applies compact CSS class', () => {
    const { container } = render(<AgentPresenceBadge agent={makePresence()} compact />);
    expect(container.firstChild).toHaveClass('actor-presence-badge--compact');
  });
});
