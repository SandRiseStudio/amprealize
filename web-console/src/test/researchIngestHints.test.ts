import { describe, expect, it } from 'vitest';
import { researchIngestFailureSuggestsBodyPaste } from '../components/boards/researchIngestHints';

describe('researchIngestFailureSuggestsBodyPaste', () => {
  it('returns false when no execution', () => {
    expect(researchIngestFailureSuggestsBodyPaste(null)).toBe(false);
    expect(researchIngestFailureSuggestsBodyPaste(undefined)).toBe(false);
  });

  it('returns false when run succeeded', () => {
    expect(
      researchIngestFailureSuggestsBodyPaste({
        state: 'completed',
        lastError: 'URL fetch failed with HTTP 429',
      }),
    ).toBe(false);
  });

  it('returns true on failed + 429 in lastError', () => {
    expect(
      researchIngestFailureSuggestsBodyPaste({
        state: 'failed',
        lastError: 'URL fetch failed with HTTP 429 after 5 attempts',
      }),
    ).toBe(true);
  });

  it('returns true on error state + paste hint text', () => {
    expect(
      researchIngestFailureSuggestsBodyPaste({
        state: 'error',
        error: 'paste the article body into the research work item',
      }),
    ).toBe(true);
  });

  it('matches error field when lastError empty', () => {
    expect(
      researchIngestFailureSuggestsBodyPaste({
        state: 'failed',
        lastError: null,
        error: 'URL fetch failed with HTTP 503',
      }),
    ).toBe(true);
  });
});
