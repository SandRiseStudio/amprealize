import { describe, it, expect } from 'vitest';
import {
  buildArtifactMarkdownLookup,
  resolveChatArtifactMarkdownToken,
  looksLikeResourceIdToken,
  type ChatArtifactRef,
} from './chatArtifactRefsFromRows';

describe('resolveChatArtifactMarkdownToken', () => {
  it('returns undefined for ambiguous hex prefix when two id labels share it', () => {
    const refs: ChatArtifactRef[] = [
      {
        key: 'a',
        kind: 'project',
        label: 'aaaaaaaa-0000-4000-8000-000000000001',
        to: '/projects/aaaaaaaa-0000-4000-8000-000000000001',
      },
      {
        key: 'b',
        kind: 'project',
        label: 'aaaaaaaa-0000-4000-8000-000000000002',
        to: '/projects/aaaaaaaa-0000-4000-8000-000000000002',
      },
    ];
    const lookup = buildArtifactMarkdownLookup(refs);
    expect(resolveChatArtifactMarkdownToken(lookup, refs, 'aaaaaaaa')).toBeUndefined();
  });

  it('resolves unique 8-char prefix to the only matching id-shaped label', () => {
    const refs: ChatArtifactRef[] = [
      {
        key: 'p',
        kind: 'project',
        label: 'fedcba98-0000-4000-8000-000000000099',
        to: '/projects/fedcba98-0000-4000-8000-000000000099',
      },
    ];
    const lookup = buildArtifactMarkdownLookup(refs);
    const hit = resolveChatArtifactMarkdownToken(lookup, refs, 'fedcba98');
    expect(hit?.to).toBe('/projects/fedcba98-0000-4000-8000-000000000099');
  });
});

describe('looksLikeResourceIdToken', () => {
  it('accepts uuid and short hex fragments', () => {
    expect(looksLikeResourceIdToken('fedcba98')).toBe(true);
    expect(looksLikeResourceIdToken('fedcba98-0000-4000-8000-000000000099')).toBe(true);
  });

  it('rejects prose and slugs', () => {
    expect(looksLikeResourceIdToken('Alpha')).toBe(false);
    expect(looksLikeResourceIdToken('my-proj')).toBe(false);
  });
});
