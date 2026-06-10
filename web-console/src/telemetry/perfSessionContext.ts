/**
 * Short-lived ID for correlating web perf marks and API requests in the same
 * dashboard session (guideai-1140 / browser↔server timing).
 */

let currentId: string | null = null;

export function setWebPerfSessionId(next: string | null): void {
  currentId = next;
}

export function getWebPerfSessionId(): string | null {
  return currentId;
}
