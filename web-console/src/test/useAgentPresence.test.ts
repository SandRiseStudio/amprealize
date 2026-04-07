/**
 * Tests for useAgentPresence hook
 *
 * Exercises presence derivation, summary calculation, and display utilities.
 */

import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import {
  useAgentPresence,
  formatPresenceSummary,
  PRESENCE_LABELS,
  PRESENCE_COLORS,
} from '../hooks/useAgentPresence';
import type { Agent } from '../api/dashboard';

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 'agent-001',
    name: 'Test Agent',
    agent_type: 'specialist',
    status: 'active',
    config: {},
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('useAgentPresence', () => {
  it('returns empty presences and zeroed summary for no agents', () => {
    const { result } = renderHook(() => useAgentPresence([], 'proj-1'));
    expect(result.current.presences).toHaveLength(0);
    expect(result.current.summary.total).toBe(0);
  });

  it('derives "available" from active status', () => {
    const agents = [makeAgent({ status: 'active' })];
    const { result } = renderHook(() => useAgentPresence(agents));
    expect(result.current.presences[0].presence).toBe('available');
    expect(result.current.summary.available).toBe(1);
  });

  it('derives "available" from idle status', () => {
    const agents = [makeAgent({ status: 'idle' })];
    const { result } = renderHook(() => useAgentPresence(agents));
    expect(result.current.presences[0].presence).toBe('available');
  });

  it('derives "working" from busy status', () => {
    const agents = [makeAgent({ status: 'busy' })];
    const { result } = renderHook(() => useAgentPresence(agents));
    expect(result.current.presences[0].presence).toBe('working');
    expect(result.current.summary.working).toBe(1);
    expect(result.current.presences[0].activeItemCount).toBe(1);
  });

  it('derives "paused" from paused status', () => {
    const agents = [makeAgent({ status: 'paused' })];
    const { result } = renderHook(() => useAgentPresence(agents));
    expect(result.current.presences[0].presence).toBe('paused');
    expect(result.current.summary.paused).toBe(1);
  });

  it('derives "offline" from disabled status', () => {
    const agents = [makeAgent({ status: 'disabled' })];
    const { result } = renderHook(() => useAgentPresence(agents));
    expect(result.current.presences[0].presence).toBe('offline');
    expect(result.current.summary.offline).toBe(1);
  });

  it('derives "offline" from archived status', () => {
    const agents = [makeAgent({ status: 'archived' })];
    const { result } = renderHook(() => useAgentPresence(agents));
    expect(result.current.presences[0].presence).toBe('offline');
  });

  it('extracts agent name and avatar initials', () => {
    const agents = [makeAgent({ name: 'Code Reviewer' })];
    const { result } = renderHook(() => useAgentPresence(agents));
    expect(result.current.presences[0].name).toBe('Code Reviewer');
    expect(result.current.presences[0].avatar).toBe('CR');
  });

  it('uses registry_agent_id from config when available', () => {
    const agents = [makeAgent({ id: 'local-1', config: { registry_agent_id: 'reg-abc' } })];
    const { result } = renderHook(() => useAgentPresence(agents));
    expect(result.current.presences[0].agentId).toBe('reg-abc');
  });

  it('filters by projectId when provided', () => {
    const agents = [
      makeAgent({ id: '1', project_id: 'proj-a' }),
      makeAgent({ id: '2', project_id: 'proj-b' }),
      makeAgent({ id: '3', project_id: 'proj-a' }),
    ];
    const { result } = renderHook(() => useAgentPresence(agents, 'proj-a'));
    expect(result.current.presences).toHaveLength(2);
    expect(result.current.summary.total).toBe(2);
  });

  it('computes summary across all presence states', () => {
    const agents = [
      makeAgent({ id: '1', status: 'active' }),
      makeAgent({ id: '2', status: 'busy' }),
      makeAgent({ id: '3', status: 'paused' }),
      makeAgent({ id: '4', status: 'disabled' }),
    ];
    const { result } = renderHook(() => useAgentPresence(agents));
    const s = result.current.summary;
    expect(s.total).toBe(4);
    expect(s.available).toBe(1);
    expect(s.working).toBe(1);
    expect(s.paused).toBe(1);
    expect(s.offline).toBe(1);
  });
});

describe('PRESENCE_LABELS', () => {
  it('has a label for every presence state', () => {
    const states = ['available', 'working', 'finished_recently', 'paused', 'offline', 'at_capacity'] as const;
    for (const state of states) {
      expect(PRESENCE_LABELS[state]).toBeTruthy();
    }
  });
});

describe('PRESENCE_COLORS', () => {
  it('has a CSS variable color for every presence state', () => {
    const states = ['available', 'working', 'finished_recently', 'paused', 'offline', 'at_capacity'] as const;
    for (const state of states) {
      expect(PRESENCE_COLORS[state]).toMatch(/var\(--/);
    }
  });
});

describe('formatPresenceSummary', () => {
  it('formats a summary with working and available counts', () => {
    const summary = {
      total: 4,
      working: 2,
      available: 1,
      paused: 1,
      offline: 0,
      atCapacity: 0,
      finishedRecently: 0,
    };
    const result = formatPresenceSummary(summary);
    expect(result).toContain('4 assigned');
    expect(result).toContain('2 working');
    expect(result).toContain('1 available');
  });

  it('omits zero counts', () => {
    const summary = {
      total: 3,
      working: 0,
      available: 3,
      paused: 0,
      offline: 0,
      atCapacity: 0,
      finishedRecently: 0,
    };
    const result = formatPresenceSummary(summary);
    expect(result).not.toContain('working');
    expect(result).toContain('3 available');
  });
});
