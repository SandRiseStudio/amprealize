/**
 * Format a work item's display ID for user-facing presentation.
 *
 * Priority order:
 * 1. Sequential display number + project slug  → "MYPROJ-42"
 * 2. Legacy prefixed short IDs                 → "#a1b2c3d4e5f6"
 * 3. UUID fallback (first 8 chars)             → "#a1b2c3d4"
 */
export function formatWorkItemDisplayId(
  itemOrId: string | { item_id: string; display_number?: number | null },
  projectSlug?: string | null,
): string {
  if (typeof itemOrId === 'string') {
    // Legacy string-only call — no display_number available
    if (itemOrId.startsWith('task-')) return itemOrId.replace('task-', '#');
    if (itemOrId.startsWith('feature-')) return itemOrId.replace('feature-', '#');
    if (itemOrId.startsWith('goal-')) return itemOrId.replace('goal-', '#');
    // Legacy prefixes (backward compat)
    if (itemOrId.startsWith('story-')) return itemOrId.replace('story-', '#');
    if (itemOrId.startsWith('epic-')) return itemOrId.replace('epic-', '#');
    return `#${itemOrId.slice(0, 8)}`;
  }

  const { item_id, display_number } = itemOrId;

  if (display_number != null) {
    const prefix = projectSlug ? projectSlug.toUpperCase() : 'WI';
    return `${prefix}-${display_number}`;
  }

  // Fallback for legacy prefixed IDs
  if (item_id.startsWith('task-')) return item_id.replace('task-', '#');
  if (item_id.startsWith('feature-')) return item_id.replace('feature-', '#');
  if (item_id.startsWith('goal-')) return item_id.replace('goal-', '#');
  // Legacy prefixes (backward compat)
  if (item_id.startsWith('story-')) return item_id.replace('story-', '#');
  if (item_id.startsWith('epic-')) return item_id.replace('epic-', '#');

  // Fallback for UUID-only items (existing data without display_number)
  return `#${item_id.slice(0, 8)}`;
}

/**
 * Format a board's display ID for user-facing presentation.
 */
export function formatBoardDisplayId(
  board: { board_id: string; display_number?: number | null },
  projectSlug?: string | null,
): string {
  if (board.display_number != null) {
    const prefix = projectSlug ? projectSlug.toUpperCase() : 'BRD';
    return `${prefix}-B${board.display_number}`;
  }
  return `#${board.board_id.slice(0, 8)}`;
}

export async function copyTextToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to legacy path.
    }
  }

  if (typeof document === 'undefined') return false;

  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    textarea.style.pointerEvents = 'none';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(textarea);
    return copied;
  } catch {
    return false;
  }
}
