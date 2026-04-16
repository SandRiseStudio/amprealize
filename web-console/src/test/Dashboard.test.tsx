import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../components/workspace/useShell', () => ({
  useShellTitle: vi.fn(),
}));

vi.mock('../telemetry/raze', () => ({
  razeLog: vi.fn(() => Promise.resolve()),
}));

vi.mock('../api/boards', () => ({
  useBoardsMultiProject: vi.fn(),
}));

vi.mock('../api/dashboard', () => ({
  useDashboardStats: vi.fn(),
  useOrganizations: vi.fn(),
  useProjects: vi.fn(),
  useRecentRuns: vi.fn(),
}));

vi.mock('../api/agentRegistry', () => ({
  useAllProjectAgents: vi.fn(),
  useVisibleProjectAgentPresence: vi.fn(),
}));

vi.mock('../hooks/useAgentPresence', () => ({
  useAgentPresence: vi.fn(),
}));

vi.mock('../store/orgContextStore', () => ({
  orgContextStore: { setCurrentOrgId: vi.fn() },
  useOrgContext: vi.fn(),
}));

vi.mock('../components/actors/ActorAvatar', () => ({
  ActorAvatar: ({ actor }: { actor?: { displayName?: string } }) => <span data-testid="actor-avatar">{actor?.displayName ?? 'avatar'}</span>,
}));

vi.mock('../components/actors/ActorPresenceScene', () => ({
  ActorPresenceScene: () => <div data-testid="actor-presence-scene" />,
}));

import { Dashboard } from '../components/Dashboard';
import { useBoardsMultiProject } from '../api/boards';
import { useAllProjectAgents, useVisibleProjectAgentPresence } from '../api/agentRegistry';
import { useDashboardStats, useOrganizations, useProjects, useRecentRuns } from '../api/dashboard';
import { useAgentPresence } from '../hooks/useAgentPresence';
import { useOrgContext } from '../store/orgContextStore';

const stats = {
  total_projects: 1,
  total_agents: 7,
  active_agents: 3,
  busy_agents: 1,
  completed_runs_today: 4,
  running_runs: 1,
  total_behaviors: 9,
};

const project = {
  id: 'proj-1',
  name: 'Fast Board Project',
  slug: 'fast-board-project',
  description: 'Ship the fast board experience',
  visibility: 'private',
  agent_count: 1,
  updated_at: '2026-04-15T00:00:00Z',
};

const agent = {
  id: 'agent-local-1',
  name: 'Planner Agent',
  agent_type: 'planner',
  status: 'active',
  config: { registry_agent_id: 'agent-1' },
  project_id: 'proj-1',
  created_at: '2026-04-15T00:00:00Z',
  updated_at: '2026-04-15T00:00:00Z',
};

const visiblePresence = new Map([
  ['proj-1', {
    agents: [
      {
        agentId: 'agent-1',
        presence: 'available',
        actor: { id: 'agent-1', displayName: 'Planner Agent' },
      },
    ],
    total: 1,
    summaryLine: '1 assigned',
  }],
]);

describe('Dashboard', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();

    vi.mocked(useDashboardStats).mockReturnValue({ data: stats, isLoading: false } as never);
    vi.mocked(useOrganizations).mockReturnValue({ data: [] } as never);
    vi.mocked(useProjects).mockReturnValue({
      data: [project],
      isLoading: false,
      isFetching: false,
      isError: false,
      refetch: vi.fn(),
    } as never);
    vi.mocked(useRecentRuns).mockReturnValue({
      data: [],
      isLoading: false,
      isFetching: false,
      isError: false,
    } as never);
    vi.mocked(useBoardsMultiProject).mockReturnValue({
      data: new Map([['proj-1', []]]),
      isLoading: false,
    } as never);
    vi.mocked(useAllProjectAgents).mockReturnValue({
      data: [agent],
      isLoading: false,
      isFetching: false,
      isError: false,
    } as never);
    vi.mocked(useVisibleProjectAgentPresence).mockReturnValue({
      data: visiblePresence,
      isLoading: false,
      isFetching: false,
    } as never);
    vi.mocked(useAgentPresence).mockReturnValue({
      presences: [],
      summary: { total: 0, available: 0, working: 0, paused: 0, offline: 0, atCapacity: 0, finishedRecently: 0 },
    } as never);
    vi.mocked(useOrgContext).mockReturnValue({ currentOrgId: null } as never);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders without an org, defers the full agent panel, and uses visible-project presence for project cards', async () => {
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    expect(useProjects).toHaveBeenCalledWith(undefined);
    expect(useAllProjectAgents).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText('1 assigned')).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(300);
      await Promise.resolve();
    });

    expect(useAllProjectAgents).toHaveBeenLastCalledWith({ enabled: true });
  });
});
