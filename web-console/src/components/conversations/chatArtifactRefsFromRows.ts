/**
 * Derive chat artifact refs from structured_payload.rows (inventory, analysis, etc.)
 * so markdown bodies can resolve inline `code` / **bold** tokens to the same chips.
 */

export type ChatArtifactKind =
  | 'work_item'
  | 'project'
  | 'board'
  | 'agent'
  | 'run'
  | 'behavior'
  | 'wiki'
  | 'org'
  | 'resource';

export interface ChatArtifactRef {
  key: string;
  kind: ChatArtifactKind;
  label: string;
  to?: string;
  disabledReason?: string;
  refRole?: 'title' | 'id';
}

function pickString(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value.trim();
  return undefined;
}

function firstPresent(record: Record<string, unknown> | null | undefined, keys: string[]): string | undefined {
  if (!record) return undefined;
  for (const key of keys) {
    const v = pickString(record[key]);
    if (v) return v;
  }
  return undefined;
}

function workItemHref(projectId?: string, boardId?: string, itemId?: string): string | undefined {
  if (projectId && boardId && itemId) {
    return `/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardId)}/items/${encodeURIComponent(itemId)}`;
  }
  return undefined;
}

function pushUnique(out: ChatArtifactRef[], ref: ChatArtifactRef): void {
  if (out.some((r) => r.key === ref.key)) return;
  out.push(ref);
}

function isLikelyInventoryWorkItemRow(row: Record<string, unknown>): boolean {
  if (firstPresent(row, ['item_id', 'work_item_id'])) return true;
  const title = firstPresent(row, ['title', 'name']);
  const id = pickString(row.id);
  const projectId = firstPresent(row, ['project_id']);
  if (!title || !id || !projectId) return false;
  if (firstPresent(row, ['agent_id'])) return false;
  if (firstPresent(row, ['board_id'])) return false;
  if (row.project_name != null || row.is_default !== undefined) return false;
  if (row.slug != null && row.label != null) return false;
  return row.status != null || row.item_type != null || row.assignee != null || row.assignee_id != null;
}

/**
 * Build artifact refs from generic `structured_payload.rows` (any card_kind).
 * Used to map inline markdown tokens (e.g. `` `4049e4ae` ``) to clickable chips.
 */
export function refsFromStructuredPayloadRows(sp: Record<string, unknown> | null | undefined): ChatArtifactRef[] {
  const out: ChatArtifactRef[] = [];
  if (!sp || !Array.isArray(sp.rows)) return out;
  const rowsRaw = sp.rows as Record<string, unknown>[];
  const qp = (sp.query_plan ?? null) as Record<string, unknown> | null;
  const isCount = pickString(qp?.intent) === 'count';
  const resourceType = pickString(qp?.resource_type);
  // Count-mode work-item answers can include many rows; chips stay off to avoid noise.
  const suppressCountWorkItemRowRefs = isCount && resourceType === 'work_items';
  const rows = suppressCountWorkItemRowRefs
    ? []
    : isCount && rowsRaw.length > 24
      ? rowsRaw.slice(0, 24)
      : rowsRaw;

  rows.forEach((row, i) => {
    const agentId = firstPresent(row, ['agent_id']);
    if (
      agentId &&
      (row.display_name != null ||
        row.agent_slug != null ||
        row.agent_name != null ||
        row.role != null ||
        row.slug != null)
    ) {
      const name = firstPresent(row, ['name', 'display_name', 'agent_name', 'title']);
      pushUnique(out, {
        key: `agent:${agentId}:rows:${i}`,
        kind: 'agent',
        label: name ?? agentId,
        to: `/agents/${encodeURIComponent(agentId)}`,
      });
      return;
    }

    const projectId = firstPresent(row, ['project_id']);
    const boardIdExplicit = firstPresent(row, ['board_id']);
    const title = firstPresent(row, ['title', 'name', 'label']);
    const itemId = firstPresent(row, ['item_id', 'work_item_id']);
    const idField = pickString(row.id);
    const boardIdForHref =
      boardIdExplicit ??
      (projectId && idField && (row.project_name != null || row.is_default !== undefined) ? idField : undefined);

    if (itemId || isLikelyInventoryWorkItemRow(row)) {
      const resolvedId = itemId ?? idField;
      if (!resolvedId) return;
      const href = workItemHref(projectId, boardIdExplicit, resolvedId);
      const label = title ?? resolvedId;
      const disabledReason = href
        ? undefined
        : 'Open this work item from its board when project and board ids are available.';
      if (href && title && title.trim() !== resolvedId.trim()) {
        pushUnique(out, {
          key: `work_item:${resolvedId}:rows:${i}:title`,
          kind: 'work_item',
          label: title,
          to: href,
          disabledReason,
          refRole: 'title',
        });
        pushUnique(out, {
          key: `work_item:${resolvedId}:rows:${i}:id`,
          kind: 'work_item',
          label: resolvedId,
          to: href,
          disabledReason,
          refRole: 'id',
        });
      } else {
        pushUnique(out, {
          key: `work_item:${resolvedId}:rows:${i}`,
          kind: 'work_item',
          label,
          to: href,
          disabledReason,
        });
      }
      return;
    }

    if (boardIdForHref && projectId && firstPresent(row, ['name', 'title']) && !itemId && !isLikelyInventoryWorkItemRow(row)) {
      const name = firstPresent(row, ['name', 'title']) ?? boardIdForHref;
      pushUnique(out, {
        key: `board:${boardIdForHref}:rows:${i}`,
        kind: 'board',
        label: name,
        to: `/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardIdForHref)}`,
      });
      return;
    }

    const pid = firstPresent(row, ['project_id', 'id']);
    if (pid && (title || row.slug != null) && !boardIdExplicit && !boardIdForHref) {
      const name = title ?? pid;
      pushUnique(out, {
        key: `project:${pid}:rows:${i}`,
        kind: 'project',
        label: name,
        to: `/projects/${encodeURIComponent(pid)}`,
      });
      return;
    }

    const runId = firstPresent(row, ['run_id', 'id']);
    if (runId && (row.status != null || row.summary != null || row.message != null)) {
      const workItemId = firstPresent(row, ['work_item_id', 'item_id']);
      const href = workItemId ? workItemHref(projectId, boardIdExplicit, workItemId) : undefined;
      pushUnique(out, {
        key: `run:${runId}:rows:${i}`,
        kind: 'run',
        label: firstPresent(row, ['summary', 'status', 'title']) ?? runId,
        to: href,
        disabledReason: href ? undefined : 'Open this run from its related work item when that context is available.',
      });
    }
  });

  return out;
}

function refSemanticKey(r: ChatArtifactRef): string {
  return `${r.kind}\0${r.to ?? ''}\0${r.label.trim().toLowerCase()}\0${r.refRole ?? ''}`;
}

/** Merges row-derived refs without duplicating the same chip (same kind, href, label, role). */
export function mergeArtifactRefsUnique(base: ChatArtifactRef[], extra: ChatArtifactRef[]): ChatArtifactRef[] {
  const out = [...base];
  const seen = new Set(out.map(refSemanticKey));
  for (const r of extra) {
    if (out.some((x) => x.key === r.key)) continue;
    const sem = refSemanticKey(r);
    if (seen.has(sem)) continue;
    seen.add(sem);
    out.push(r);
  }
  return out;
}

/** Map labels (and lowercase) to refs so markdown `code` / **bold** can resolve. */
export function buildArtifactMarkdownLookup(refs: ChatArtifactRef[]): Map<string, ChatArtifactRef> {
  const m = new Map<string, ChatArtifactRef>();
  for (const r of refs) {
    const label = r.label?.trim();
    if (!label) continue;
    m.set(label, r);
    m.set(label.toLowerCase(), r);
  }
  return m;
}

function normalizeResourceIdKey(s: string): string {
  return s.trim().toLowerCase().replace(/-/g, '');
}

/**
 * True when the token is hex / UUID-shaped (production agent text often uses 8-char id prefixes).
 * Rejects slugs and prose so we do not chip-match arbitrary words.
 */
export function looksLikeResourceIdToken(t: string): boolean {
  const s = t.trim();
  if (s.length < 4 || s.length > 36) return false;
  if (!/^[0-9a-f-]+$/i.test(s)) return false;
  const hex = normalizeResourceIdKey(s);
  return hex.length >= 4 && hex.length <= 32;
}

/**
 * Resolve inline markdown text to an artifact ref: exact label match first, then a unique
 * hex/UUID-prefix match among refs whose labels are id-shaped (avoids collisions).
 */
export function resolveChatArtifactMarkdownToken(
  lookup: Map<string, ChatArtifactRef>,
  allRefs: ChatArtifactRef[],
  token: string,
): ChatArtifactRef | undefined {
  const t = token.trim();
  if (!t) return undefined;
  const exact = lookup.get(t) ?? lookup.get(t.toLowerCase());
  if (exact) return exact;
  if (!looksLikeResourceIdToken(t)) return undefined;
  const needle = normalizeResourceIdKey(t);
  if (needle.length < 6) return undefined;
  const matches = allRefs.filter((r) => {
    const lab = r.label?.trim();
    if (!lab || !looksLikeResourceIdToken(lab)) return false;
    const h = normalizeResourceIdKey(lab);
    return h === needle || h.startsWith(needle);
  });
  if (matches.length !== 1) return undefined;
  return matches[0];
}

export function stringifyMdChildren(node: unknown): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(stringifyMdChildren).join('');
  if (typeof node === 'object' && node !== null && 'props' in (node as object)) {
    const p = (node as { props?: { children?: unknown } }).props;
    return stringifyMdChildren(p?.children);
  }
  return '';
}
