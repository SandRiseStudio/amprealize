"""Canonical merge helpers for per-run knowledge retrieval receipts.

Stored under run metadata key ``knowledge_retrieval_receipt`` and surfaced via
execution ``trace_summary.knowledge_retrieval`` for web, chat, MCP, and CLI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from amprealize.execution_observability import sanitize_observability_payload

RECEIPT_METADATA_KEY = "knowledge_retrieval_receipt"
RECEIPT_VERSION = 1
MAX_SPANS = 200
_MAX_TEXT = 512


def _utc_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clip(value: Any, max_len: int = _MAX_TEXT) -> Any:
    if isinstance(value, str) and len(value) > max_len:
        return value[: max_len - 1] + "…"
    return value


def normalize_span(span: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy with bounded string fields."""
    out: Dict[str, Any] = {}
    for key, val in span.items():
        if val is None:
            continue
        out[key] = _clip(val) if isinstance(val, str) else val
    if "occurred_at" not in out:
        out["occurred_at"] = _utc_iso()
    if "span_id" not in out:
        out["span_id"] = str(uuid.uuid4())
    return sanitize_observability_payload(out)


def merge_receipt_spans(
    existing: Optional[Dict[str, Any]],
    new_spans: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge new spans into a receipt dict (caps total span count)."""
    base_spans: List[Dict[str, Any]] = []
    version = RECEIPT_VERSION
    rollup: Dict[str, Any] = {"by_channel": {}, "by_source": {}}
    if isinstance(existing, dict):
        base_spans = list(existing.get("spans") or [])
        version = int(existing.get("version") or RECEIPT_VERSION)
        rollup = dict(existing.get("rollup") or {"by_channel": {}, "by_source": {}})
        rollup.setdefault("by_channel", {})
        rollup.setdefault("by_source", {})

    for raw in new_spans:
        if not isinstance(raw, dict):
            continue
        span = normalize_span(dict(raw))
        base_spans.append(span)
        ch = str(span.get("channel") or "unknown")
        st = str(span.get("source_type") or "other")
        rollup["by_channel"][ch] = int(rollup["by_channel"].get(ch, 0)) + 1
        rollup["by_source"][st] = int(rollup["by_source"].get(st, 0)) + 1

    overflow = len(base_spans) - MAX_SPANS
    if overflow > 0:
        base_spans = base_spans[overflow:]

    return {
        "version": version,
        "spans": base_spans,
        "rollup": rollup,
        "updated_at": _utc_iso(),
    }


def trace_summary_knowledge_slice(receipt: Optional[Dict[str, Any]], *, max_spans: int = 50) -> Dict[str, Any]:
    """Bounded payload for API / SSE (avoid huge JSON)."""
    if not isinstance(receipt, dict):
        return {"version": RECEIPT_VERSION, "span_count": 0, "spans": [], "rollup": {}}
    spans = list(receipt.get("spans") or [])
    tail = spans[-max_spans:] if len(spans) > max_spans else spans
    return {
        "version": int(receipt.get("version") or RECEIPT_VERSION),
        "span_count": len(spans),
        "spans": tail,
        "rollup": dict(receipt.get("rollup") or {}),
        "updated_at": receipt.get("updated_at"),
    }


def span_from_bci_match(
    match: Any,
    *,
    channel: str,
    phase: Optional[str] = None,
    retrieval_strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a span dict from a :class:`amprealize.bci_contracts.BehaviorMatch`."""
    behavior_id = getattr(match, "behavior_id", None) or ""
    name = getattr(match, "name", "") or ""
    version = getattr(match, "version", "") or ""
    score = float(getattr(match, "score", 0.0) or 0.0)
    anchor = f"behavior:{behavior_id}:{version}" if behavior_id else f"behavior_name:{name}"
    span: Dict[str, Any] = {
        "source_type": "behavior",
        "title": name or behavior_id,
        "anchor": anchor,
        "channel": channel,
        "behavior_id": behavior_id or None,
        "score": score,
    }
    if phase:
        span["phase"] = phase
    if retrieval_strategy:
        span["retrieval_strategy"] = retrieval_strategy
    return span


def spans_from_phase_behavior_names(names: List[Any], *, phase: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in names:
        if isinstance(item, str) and item.strip():
            out.append(
                {
                    "source_type": "behavior",
                    "title": item.strip(),
                    "anchor": f"behavior_name:{item.strip()}",
                    "channel": "phase_bci",
                    "phase": phase,
                }
            )
        elif isinstance(item, dict):
            bid = item.get("behavior_id") or item.get("id")
            title = item.get("name") or item.get("title") or str(bid or "behavior")
            span: Dict[str, Any] = {
                "source_type": "behavior",
                "title": str(title)[:_MAX_TEXT],
                "channel": "phase_bci",
                "phase": phase,
            }
            if bid:
                span["behavior_id"] = str(bid)
                span["anchor"] = f"behavior:{bid}"
            else:
                span["anchor"] = f"behavior_name:{title}"
            out.append(span)
    return out


def spans_from_behavior_retrieval_refs(
    refs: List[Dict[str, Any]],
    *,
    channel: str = "mcp_behaviors_getForTask",
) -> List[Dict[str, Any]]:
    spans: List[Dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        bid = ref.get("behavior_id")
        name = ref.get("name") or bid or "behavior"
        version = ref.get("version") or ""
        score = ref.get("score")
        span: Dict[str, Any] = {
            "source_type": "behavior",
            "title": str(name),
            "channel": channel,
        }
        if bid:
            span["behavior_id"] = str(bid)
            span["anchor"] = f"behavior:{bid}:{version}" if version else f"behavior:{bid}"
        else:
            span["anchor"] = f"behavior_name:{name}"
        if score is not None:
            try:
                span["score"] = float(score)
            except (TypeError, ValueError):
                pass
        spans.append(span)
    return spans
