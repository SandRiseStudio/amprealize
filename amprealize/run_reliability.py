"""Run reliability helpers: GEP checkpoints, outbound policy resolution, snapshots.

See docs/contracts/RUN_RELIABILITY.md.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from amprealize.run_contracts import Run
from amprealize.task_cycle_contracts import CyclePhase
from amprealize.work_item_execution_contracts import OutboundReliabilityPolicy, ToolOutboundRule

logger = logging.getLogger(__name__)

GEP_PHASE_CHECKPOINT_KEY = "gep_phase_outputs_checkpoint"
GEP_CHECKPOINT_SEQ_KEY = "gep_checkpoint_seq"
GEP_CHECKPOINT_CYCLE_KEY = "gep_checkpoint_cycle_id"
GEP_CHECKPOINT_AT_KEY = "gep_checkpoint_updated_at"
RELIABILITY_CIRCUITS_KEY = "reliability_circuits"

_MAX_CHECKPOINT_JSON_BYTES = 450_000


def dependency_key_for_tool(tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> str:
    """Derive a stable dependency key for circuit accounting."""
    args = tool_args or {}
    for key in ("url", "endpoint", "api_url", "base_url"):
        raw = args.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                from urllib.parse import urlparse

                host = urlparse(raw).hostname
                if host:
                    return f"host:{host}"
            except Exception:
                break
    return f"tool:{tool_name}"


def _json_safe(obj: Any) -> Any:
    try:
        return json.loads(json.dumps(obj, default=str))
    except (TypeError, ValueError):
        return {"_serialization": "fallback", "repr": repr(obj)[:4096]}


def serialize_phase_outputs(phase_outputs: Dict[CyclePhase, Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for phase, payload in phase_outputs.items():
        key = phase.value if isinstance(phase, CyclePhase) else str(phase)
        out[key] = _json_safe(payload)
    return out


def deserialize_phase_outputs(data: Dict[str, Any]) -> Dict[CyclePhase, Dict[str, Any]]:
    result: Dict[CyclePhase, Dict[str, Any]] = {}
    for key, payload in data.items():
        try:
            ph = CyclePhase(key)
        except ValueError:
            logger.warning("Skipping unknown phase key in checkpoint: %s", key)
            continue
        if isinstance(payload, dict):
            result[ph] = payload
    return result


def load_phase_checkpoint_for_cycle(run: Run, cycle_id: str) -> Optional[Dict[CyclePhase, Dict[str, Any]]]:
    meta = run.metadata or {}
    if meta.get(GEP_CHECKPOINT_CYCLE_KEY) != cycle_id:
        return None
    raw = meta.get(GEP_PHASE_CHECKPOINT_KEY)
    if not isinstance(raw, dict):
        return None
    return deserialize_phase_outputs(raw)


def checkpoint_metadata_delta(
    run: Run,
    *,
    cycle_id: str,
    phase_outputs: Dict[CyclePhase, Dict[str, Any]],
) -> Tuple[Dict[str, Any], int, bool]:
    """Metadata keys to merge into the run for a checkpoint write.

    Returns (metadata_delta, new_seq, truncated).
    """
    meta = dict(run.metadata or {})
    prev_seq = int(meta.get(GEP_CHECKPOINT_SEQ_KEY) or 0)
    new_seq = prev_seq + 1
    checkpoint = serialize_phase_outputs(phase_outputs)
    raw = json.dumps(checkpoint, default=str)
    truncated = len(raw.encode("utf-8")) > _MAX_CHECKPOINT_JSON_BYTES
    if truncated:
        checkpoint = {
            k: {"_truncated": True, "keys": list(v.keys()) if isinstance(v, dict) else []}
            for k, v in checkpoint.items()
        }
    delta = {
        GEP_PHASE_CHECKPOINT_KEY: checkpoint,
        GEP_CHECKPOINT_SEQ_KEY: new_seq,
        GEP_CHECKPOINT_CYCLE_KEY: cycle_id,
        GEP_CHECKPOINT_AT_KEY: datetime.now(UTC).isoformat(),
    }
    return delta, new_seq, truncated


def build_reliability_snapshot(run: Run) -> Dict[str, Any]:
    """Public shape for REST/MCP/CLI (parity)."""
    meta = run.metadata or {}
    policy_raw = meta.get("execution_policy")
    outbound = None
    if isinstance(policy_raw, dict):
        ob = policy_raw.get("outbound_reliability")
        if isinstance(ob, dict):
            outbound = ob
    checkpoint_phases: List[str] = []
    chk = meta.get(GEP_PHASE_CHECKPOINT_KEY)
    if isinstance(chk, dict):
        checkpoint_phases = list(chk.keys())
    return {
        "run_id": run.run_id,
        "checkpoint": {
            "seq": meta.get(GEP_CHECKPOINT_SEQ_KEY),
            "cycle_id": meta.get(GEP_CHECKPOINT_CYCLE_KEY),
            "updated_at": meta.get(GEP_CHECKPOINT_AT_KEY),
            "phase_keys": checkpoint_phases,
        },
        "outbound_reliability": outbound,
        "circuits": meta.get(RELIABILITY_CIRCUITS_KEY) if isinstance(meta.get(RELIABILITY_CIRCUITS_KEY), dict) else {},
        "status": run.status,
    }


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def circuit_metadata_delta(
    run: Run,
    *,
    dependency_key: str,
    failures: int,
    open_until: Optional[str],
) -> Dict[str, Any]:
    """Single-key merge payload for ``reliability_circuits``."""
    meta = dict(run.metadata or {})
    circuits = dict(meta.get(RELIABILITY_CIRCUITS_KEY) or {})
    entry = dict(circuits.get(dependency_key) or {})
    entry["failures"] = failures
    entry["open_until"] = open_until
    circuits[dependency_key] = entry
    return {RELIABILITY_CIRCUITS_KEY: circuits}


def circuit_open_until(run: Run, dependency_key: str) -> Optional[str]:
    meta = run.metadata or {}
    circuits = meta.get(RELIABILITY_CIRCUITS_KEY) or {}
    if not isinstance(circuits, dict):
        return None
    entry = circuits.get(dependency_key) or {}
    if not isinstance(entry, dict):
        return None
    open_until = entry.get("open_until")
    if not open_until or not isinstance(open_until, str):
        return None
    try:
        until = datetime.fromisoformat(open_until.replace("Z", "+00:00"))
        if until > datetime.now(UTC):
            return open_until
    except Exception:
        return None
    return None


def compute_open_until(seconds: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=max(1.0, seconds))).isoformat()


def resolve_outbound_effective(
    policy: OutboundReliabilityPolicy,
    *,
    tool_name: str,
    dependency_key: str,
) -> Dict[str, Any]:
    """Merge per-dependency, per-tool, then defaults."""
    dep_rule: Optional[ToolOutboundRule] = policy.per_dependency_key.get(dependency_key)
    tool_rule: Optional[ToolOutboundRule] = policy.per_tool.get(tool_name)

    def _pick(attr: str, default: Any) -> Any:
        for r in (dep_rule, tool_rule):
            if r is None:
                continue
            val = getattr(r, attr)
            if val is not None:
                return val
        return default

    return {
        "max_retries": int(_pick("max_retries", policy.default_max_retries)),
        "timeout_seconds": float(_pick("timeout_seconds", policy.default_tool_timeout_seconds)),
        "circuit_failure_threshold": _pick("circuit_failure_threshold", None),
        "circuit_open_seconds": float(_pick("circuit_open_seconds", 60.0) or 60.0),
    }
