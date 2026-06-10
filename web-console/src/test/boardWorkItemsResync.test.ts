import { describe, expect, it } from 'vitest';
import { shouldResyncAllWorkItemPages } from '../api/boards';

describe('shouldResyncAllWorkItemPages', () => {
  it('returns false for bootstrap-seeded partial cache (warm first page)', () => {
    expect(
      shouldResyncAllWorkItemPages(100, {
        total: 1000,
        loadedCount: 100,
        isPartial: true,
        seededFromBootstrap: true,
      }),
    ).toBe(false);
  });

  it('returns true for warm partial cache after bootstrap flag cleared (invalidate path)', () => {
    expect(
      shouldResyncAllWorkItemPages(100, {
        total: 1000,
        loadedCount: 100,
        isPartial: true,
      }),
    ).toBe(true);
  });

  it('returns false when no warm items', () => {
    expect(
      shouldResyncAllWorkItemPages(0, {
        total: 1000,
        loadedCount: 0,
        isPartial: true,
      }),
    ).toBe(false);
  });

  it('returns false on fresh manual reset meta', () => {
    expect(
      shouldResyncAllWorkItemPages(50, {
        total: 0,
        loadedCount: 0,
        isPartial: false,
      }),
    ).toBe(false);
  });
});
