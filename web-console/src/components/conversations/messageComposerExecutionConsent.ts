import type { ConversationMessage } from '../../lib/collab-client';

/** API returns newest messages first within each page. */
export function isAgentMessage(msg: ConversationMessage): boolean {
  const t = String(msg.sender_type ?? '').toLowerCase();
  return t === 'agent';
}

/** Primary route category from persisted assistant `metadata.chat_route` (see `ChatActionRouteResult`). */
export function primaryRouteCategoryFromMessage(msg: ConversationMessage | undefined): string | null {
  if (!msg?.metadata) return null;
  const route = msg.metadata.chat_route;
  if (!route || typeof route !== 'object') return null;
  const candidates = (route as { candidates?: unknown }).candidates;
  if (!Array.isArray(candidates) || candidates.length === 0) return null;
  const first = candidates[0];
  if (!first || typeof first !== 'object') return null;
  const cat = (first as { category?: unknown }).category;
  return typeof cat === 'string' ? cat : null;
}

/**
 * Whether the composer should show execution consent controls.
 * @param messages Conversation rows in newest-first order (same as infinite message pages).
 */
export function showExecutionConsentFromNewestFirstMessages(
  messages: readonly ConversationMessage[],
): boolean {
  const latestAgent = messages.find(isAgentMessage);
  const cat = primaryRouteCategoryFromMessage(latestAgent ?? undefined);
  return cat === 'execution_start' || cat === 'execution_cancel';
}
