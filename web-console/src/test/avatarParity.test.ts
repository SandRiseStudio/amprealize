import { describe, expect, it } from 'vitest';
import { createActorViewModel as createExtensionActor } from '../../../extension/src/utils/actorAvatar';
import { toActorViewModel } from '../utils/actorViewModel';

describe('avatar parity', () => {
  it('keeps the same variant choices across web and extension', () => {
    const webActor = toActorViewModel(
      {
        id: 'agent-42',
        name: 'Parity Bot',
        agent_type: 'reviewer',
        status: 'active',
        config: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      { presenceState: 'available' },
    );

    const extensionActor = createExtensionActor({
      id: 'agent-42',
      kind: 'agent',
      displayName: 'Parity Bot',
      subtitle: 'reviewer',
      presenceState: 'available',
    });

    expect(extensionActor.avatarVariant).toEqual({
      palette: webActor.avatarVariant.palette,
      accessory: webActor.avatarVariant.accessory,
      persona: webActor.avatarVariant.persona,
      hairStyle: webActor.avatarVariant.hairStyle,
      eyeShape: webActor.avatarVariant.eyeShape,
      mouthShape: webActor.avatarVariant.mouthShape,
      shellShape: webActor.avatarVariant.shellShape,
    });
  });
});
