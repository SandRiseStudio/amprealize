/**
 * Heuristics for research work item UX (URL ingest vs pasted body).
 */

export type ResearchExecutionStatusLite = {
  state?: string | null;
  error?: string | null;
  lastError?: string | null;
};

/**
 * When the latest run failed in a way typical of URL fetch / rate limits,
 * prompt the user to paste article text into `research_body_markdown`.
 */
export function researchIngestFailureSuggestsBodyPaste(
  status: ResearchExecutionStatusLite | null | undefined,
): boolean {
  if (!status) return false;
  const st = String(status.state ?? '').toLowerCase();
  if (st !== 'failed' && st !== 'error') return false;
  const msg = `${status.lastError ?? ''} ${status.error ?? ''}`.toLowerCase();
  return (
    msg.includes('429') ||
    msg.includes('too many requests') ||
    msg.includes('rate-limit') ||
    msg.includes('rate limit') ||
    msg.includes('url fetch failed') ||
    msg.includes('paste the article body') ||
    msg.includes('datacenter')
  );
}
