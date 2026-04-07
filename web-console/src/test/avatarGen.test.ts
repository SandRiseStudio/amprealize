import { describe, expect, it } from 'vitest';
import { generateAvatarVariant } from '../utils/avatarGen';

describe('generateAvatarVariant', () => {
  it('is deterministic for the same seed and style version', () => {
    expect(generateAvatarVariant('agent:1:Code Bot', 'agent', 1)).toEqual(
      generateAvatarVariant('agent:1:Code Bot', 'agent', 1),
    );
  });

  it('changes when the seed changes', () => {
    expect(generateAvatarVariant('agent:1:Code Bot', 'agent', 1)).not.toEqual(
      generateAvatarVariant('agent:2:Code Bot', 'agent', 1),
    );
  });

  it('pins service actors to the antenna accessory', () => {
    expect(generateAvatarVariant('svc:1', 'service', 1).accessory).toBe('antenna');
  });

  it('keeps human actors on human personas with varied hairstyles', () => {
    const variants = Array.from({ length: 12 }, (_, index) =>
      generateAvatarVariant(`human:${index}:Person ${index}`, 'human', 1),
    );

    expect(new Set(variants.map((variant) => variant.persona))).toEqual(new Set(['human']));
    expect(new Set(variants.map((variant) => variant.hairStyle)).size).toBeGreaterThan(3);
  });

  it('creates multiple agent personas instead of a single repeated template', () => {
    const variants = Array.from({ length: 24 }, (_, index) =>
      generateAvatarVariant(`agent:${index}:Agent ${index}`, 'agent', 1),
    );

    expect(new Set(variants.map((variant) => variant.persona)).size).toBeGreaterThanOrEqual(4);
    expect(new Set(variants.map((variant) => variant.paletteId)).size).toBeGreaterThanOrEqual(6);
  });
});
