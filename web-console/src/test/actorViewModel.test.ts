import { describe, expect, it } from 'vitest';
import { toActorViewModel } from '../utils/actorViewModel';

describe('toActorViewModel', () => {
  it('normalizes agents into actor view models', () => {
    const actor = toActorViewModel({
      id: 'agent-local',
      name: 'Code Bot',
      agent_type: 'specialist',
      status: 'busy',
      config: { registry_agent_id: 'agent-registry' },
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });

    expect(actor.id).toBe('agent-registry');
    expect(actor.kind).toBe('agent');
    expect(actor.displayName).toBe('Code Bot');
    expect(actor.presenceState).toBe('working');
  });

  it('normalizes org members with role subtitles', () => {
    const actor = toActorViewModel({
      id: 'membership-1',
      org_id: 'org-1',
      user_id: 'user-1',
      role: 'PROJECT_OWNER',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });

    expect(actor.kind).toBe('human');
    expect(actor.subtitle).toBe('project owner');
    expect(actor.displayName).toContain('Member');
  });

  it('normalizes actor identities and keeps current-user metadata', () => {
    const actor = toActorViewModel(
      {
        id: 'me-1',
        type: 'human',
        role: 'STUDENT',
        surface: 'WEB',
        displayName: 'Nick',
        email: 'nick@example.com',
      },
      { isCurrentUser: true, presenceState: 'available' },
    );

    expect(actor.displayName).toBe('Nick');
    expect(actor.isCurrentUser).toBe(true);
    expect(actor.presenceLabel).toBe('Available');
  });
});
