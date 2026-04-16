/**
 * Tests for BoardAgentPresenceRail component
 *
 * Verifies rendering, overflow behavior, empty state, and callback wiring.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BoardAgentPresenceRail } from '../components/boards/BoardAgentPresenceRail';
import { toActorViewModel } from '../utils/actorViewModel';
import type { BoardParticipant, BoardParticipantSummary } from '../components/boards/boardParticipants';

function makeAgent(id: string, presence: BoardParticipant['actor']['presenceState'] = 'available'): BoardParticipant {
  return {
    id: `agent:${id}`,
    kind: 'agent',
    actor: toActorViewModel(
      { id, name: `Agent ${id}`, agent_type: 'specialist', status: 'active', config: {}, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      { presenceState: presence },
    ),
    subtitle: 'specialist agent',
    roleLabel: 'specialist agent',
    statusLine: presence,
  };
}

function makeHuman(id: string, label = `Person ${id}`, isCurrentUser = false): BoardParticipant {
  return {
    id: `user:${id}`,
    kind: 'human',
    actor: toActorViewModel(
      { user_id: id, display_name: label, status: 'idle' },
      { presenceState: 'available', subtitle: 'owner', isCurrentUser },
    ),
    subtitle: 'owner',
    roleLabel: isCurrentUser ? 'owner • you' : 'owner',
    statusLine: isCurrentUser ? 'owner • you' : 'owner',
    isCurrentUser,
  };
}

function makeSummary(total: number, overrides: Partial<BoardParticipantSummary> = {}): BoardParticipantSummary {
  return {
    total,
    humans: 0,
    agents: total,
    ...overrides,
  };
}

describe('BoardAgentPresenceRail', () => {
  it('renders nothing when no agents are assigned', () => {
    const { container } = render(
      <BoardAgentPresenceRail
        participants={[]}
        summary={makeSummary(0)}
        onViewAll={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders the Project members label and summary', () => {
    const participants = [makeHuman('1', 'Nick Sanders', true), makeAgent('1')];
    render(
      <BoardAgentPresenceRail
        participants={participants}
        summary={makeSummary(2, { humans: 1, agents: 1 })}
        onViewAll={vi.fn()}
      />,
    );
    expect(screen.getByText('Project members')).toBeInTheDocument();
    expect(screen.getByText(/2 members/)).toBeInTheDocument();
    expect(screen.getByText(/1 people/)).toBeInTheDocument();
  });

  it('renders up to 6 participant avatars inline', () => {
    const participants = Array.from({ length: 6 }, (_, i) => makeAgent(String(i + 1)));
    render(
      <BoardAgentPresenceRail
        participants={participants}
        summary={makeSummary(6)}
        onViewAll={vi.fn()}
      />,
    );
    const avatars = screen.getAllByRole('button', { name: /Agent \d/ });
    expect(avatars).toHaveLength(6);
    expect(screen.getByRole('button', { name: 'View all' })).toBeInTheDocument();
  });

  it('shows overflow chip for members beyond 6', () => {
    const participants = Array.from({ length: 8 }, (_, i) => makeAgent(String(i + 1)));
    render(
      <BoardAgentPresenceRail
        participants={participants}
        summary={makeSummary(8)}
        onViewAll={vi.fn()}
      />,
    );
    expect(screen.getByText('+2')).toBeInTheDocument();
  });

  it('calls onViewAll when "View all" is clicked', async () => {
    const user = userEvent.setup();
    const onViewAll = vi.fn();
    render(
      <BoardAgentPresenceRail
        participants={[makeAgent('1')]}
        summary={makeSummary(1)}
        onViewAll={onViewAll}
      />,
    );
    await user.click(screen.getByText('View all'));
    expect(onViewAll).toHaveBeenCalledOnce();
  });

  it('ranks people before agents, then working agents before available', () => {
    const participants = [
      makeAgent('avail', 'available'),
      makeAgent('busy', 'working'),
      makeHuman('nick', 'Nick Sanders', true),
    ];
    render(
      <BoardAgentPresenceRail
        participants={participants}
        summary={makeSummary(3, { humans: 1, agents: 2 })}
        onViewAll={vi.fn()}
      />,
    );
    const buttons = screen.getAllByRole('button');
    expect(buttons[0]).toHaveAttribute('aria-label', expect.stringContaining('Nick Sanders'));
    expect(buttons[1]).toHaveAttribute('aria-label', expect.stringContaining('Agent busy'));
  });
});
