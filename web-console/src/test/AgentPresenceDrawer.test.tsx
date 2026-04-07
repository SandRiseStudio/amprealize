/**
 * Tests for AgentPresenceDrawer component
 *
 * Verifies grouping, section rendering, close behavior, and manage button.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentPresenceDrawer } from '../components/boards/AgentPresenceDrawer';
import { toActorViewModel } from '../utils/actorViewModel';
import type { BoardParticipant } from '../components/boards/boardParticipants';

function makeAgent(id: string, presence: BoardParticipant['actor']['presenceState'], name?: string): BoardParticipant {
  return {
    id: `agent:${id}`,
    kind: 'agent',
    actor: toActorViewModel(
      { id, name: name ?? `Agent ${id}`, agent_type: 'specialist', status: 'active', config: {}, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      { presenceState: presence },
    ),
    subtitle: 'specialist agent',
    roleLabel: 'specialist agent',
    statusLine: presence,
  };
}

function makeHuman(id: string, name = `Person ${id}`, isCurrentUser = false): BoardParticipant {
  return {
    id: `user:${id}`,
    kind: 'human',
    actor: toActorViewModel(
      { user_id: id, display_name: name, status: 'idle' },
      { presenceState: 'available', subtitle: 'owner', isCurrentUser },
    ),
    subtitle: 'owner',
    roleLabel: isCurrentUser ? 'owner • you' : 'owner',
    statusLine: isCurrentUser ? 'owner • you' : 'owner',
    isCurrentUser,
  };
}

describe('AgentPresenceDrawer', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <AgentPresenceDrawer participants={[]} open={false} onClose={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders dialog with title when open', () => {
    render(
      <AgentPresenceDrawer
        participants={[makeAgent('1', 'available')]}
        open={true}
        onClose={vi.fn()}
      />,
    );
    // The dialog is inside an aria-hidden scrim, so query with hidden: true
    expect(screen.getByRole('dialog', { hidden: true })).toBeInTheDocument();
    expect(screen.getByText('Project members')).toBeInTheDocument();
  });

  it('groups participants into People and Agents', () => {
    const participants = [
      makeHuman('nick', 'Nick Sanders', true),
      makeAgent('w', 'working', 'Worker'),
      makeAgent('a', 'available', 'Avail'),
      makeAgent('p', 'paused', 'Pauser'),
    ];
    render(
      <AgentPresenceDrawer participants={participants} open={true} onClose={vi.fn()} />,
    );
    expect(screen.getByText('People')).toBeInTheDocument();
    expect(screen.getByText('Agents')).toBeInTheDocument();
    expect(screen.getAllByText('Nick Sanders').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Worker').length).toBeGreaterThanOrEqual(1);
  });

  it('hides empty sections', () => {
    const participants = [makeAgent('a', 'available')];
    render(
      <AgentPresenceDrawer participants={participants} open={true} onClose={vi.fn()} />,
    );
    expect(screen.queryByText('People')).not.toBeInTheDocument();
    expect(screen.getByText('Agents')).toBeInTheDocument();
  });

  it('closes on Escape key', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <AgentPresenceDrawer
        participants={[makeAgent('1', 'available')]}
        open={true}
        onClose={onClose}
      />,
    );
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('shows Manage agents button when onManage is provided', () => {
    render(
      <AgentPresenceDrawer
        participants={[makeAgent('1', 'available')]}
        open={true}
        onClose={vi.fn()}
        onManage={vi.fn()}
      />,
    );
    expect(screen.getByText('Manage agents')).toBeInTheDocument();
  });

  it('hides Manage agents button when onManage is not provided', () => {
    render(
      <AgentPresenceDrawer
        participants={[makeAgent('1', 'available')]}
        open={true}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByText('Manage agents')).not.toBeInTheDocument();
  });

  it('renders Project room when onProjectRoom is provided', () => {
    const onProjectRoom = vi.fn();
    render(
      <AgentPresenceDrawer
        participants={[makeAgent('1', 'available')]}
        open={true}
        onClose={vi.fn()}
        onProjectRoom={onProjectRoom}
      />,
    );
    expect(screen.getByText('Project room')).toBeInTheDocument();
  });

  it('calls onManage when Manage agents is clicked', async () => {
    const user = userEvent.setup();
    const onManage = vi.fn();
    render(
      <AgentPresenceDrawer
        participants={[makeAgent('1', 'available')]}
        open={true}
        onClose={vi.fn()}
        onManage={onManage}
      />,
    );
    await user.click(screen.getByText('Manage agents'));
    expect(onManage).toHaveBeenCalledOnce();
  });

  it('calls onClose when close button is clicked', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <AgentPresenceDrawer
        participants={[makeAgent('1', 'available')]}
        open={true}
        onClose={onClose}
      />,
    );
    await user.click(screen.getByLabelText('Close members sheet'));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
