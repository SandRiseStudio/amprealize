"""WebSocket listener + hybrid lease handler (lease_ack + delegated tools)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from amprealize.local_execution_connector_hub import CONNECTOR_PROBE_RUN_ID

logger = logging.getLogger(__name__)

_MAX_READ_BYTES = int(os.environ.get("AMPREALIZE_CONNECTOR_MAX_READ_BYTES", str(512 * 1024)))
_MAX_WRITE_BYTES = int(os.environ.get("AMPREALIZE_CONNECTOR_MAX_WRITE_BYTES", str(512 * 1024)))
_MAX_SHELL_OUT = int(os.environ.get("AMPREALIZE_CONNECTOR_MAX_SHELL_BYTES", str(256 * 1024)))
_SHELL_TIMEOUT = float(os.environ.get("AMPREALIZE_CONNECTOR_SHELL_TIMEOUT_SEC", "30"))
_HEARTBEAT_INTERVAL_SEC = float(os.environ.get("AMPREALIZE_CONNECTOR_HEARTBEAT_SEC", "25"))
_TERMINAL_TIMEOUT = float(os.environ.get("AMPREALIZE_CONNECTOR_TERMINAL_TIMEOUT_SEC", "60"))


def workdir() -> Path:
    return Path(os.environ.get("AMPREALIZE_CONNECTOR_WORKDIR", os.getcwd())).resolve()


def _safe_child_path(rel: str) -> Optional[Path]:
    base = workdir()
    p = (base / rel).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        return None
    return p


def read_file_bounded(rel_path: str) -> Dict[str, Any]:
    path = _safe_child_path(rel_path)
    if path is None or not path.is_file():
        return {"ok": False, "error": "not_found_or_unsafe", "path": rel_path}
    data = path.read_bytes()[:_MAX_READ_BYTES]
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = repr(data[:1024])
    return {"ok": True, "path": rel_path, "content": text, "truncated": path.stat().st_size > len(data)}


def run_shell_bounded(argv: List[str]) -> Dict[str, Any]:
    if not argv:
        return {"ok": False, "error": "empty_argv"}
    try:
        proc = subprocess.run(
            argv,
            cwd=str(workdir()),
            capture_output=True,
            text=True,
            timeout=_SHELL_TIMEOUT,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if len(out) > _MAX_SHELL_OUT:
            out = out[:_MAX_SHELL_OUT] + "\n...[truncated]"
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": out,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "timeout_sec": _SHELL_TIMEOUT}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def execute_delegated_tool(tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    """Run one delegated tool under connector workdir (best-effort, bounded)."""
    args = tool_args or {}

    if tool_name == "read_file":
        path = str(args.get("path", ""))
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        rf = read_file_bounded(path)
        if not rf.get("ok"):
            return {"ok": False, "output": "", "error": rf.get("error") or "read_failed"}
        content = str(rf.get("content") or "")
        if start_line or end_line:
            lines = content.split("\n")
            start = (int(start_line) - 1) if start_line else 0
            end = int(end_line) if end_line else len(lines)
            content = "\n".join(lines[start:end])
        return {"ok": True, "output": content, "error": None}

    if tool_name == "list_dir":
        rel = str(args.get("path", ".") or ".")
        path = _safe_child_path(rel)
        if path is None or not path.is_dir():
            return {"ok": False, "output": "", "error": "not_found_or_unsafe"}
        try:
            entries = sorted(os.listdir(path))
            return {"ok": True, "output": json.dumps(entries), "error": None}
        except OSError as exc:
            return {"ok": False, "output": "", "error": str(exc)}

    if tool_name == "write_file":
        rel = str(args.get("path", ""))
        content = str(args.get("content", ""))
        if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
            return {"ok": False, "output": "", "error": "content_too_large"}
        path = _safe_child_path(rel)
        if path is None:
            return {"ok": False, "output": "", "error": "unsafe_path"}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {"ok": True, "output": f"Wrote {len(content)} bytes to {rel}", "error": None}
        except OSError as exc:
            return {"ok": False, "output": "", "error": str(exc)}

    if tool_name == "edit_file":
        rel = str(args.get("path", ""))
        old_s = str(args.get("old_string", ""))
        new_s = str(args.get("new_string", ""))
        path = _safe_child_path(rel)
        if path is None or not path.is_file():
            return {"ok": False, "output": "", "error": "not_found_or_unsafe"}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "output": "", "error": str(exc)}
        if old_s not in text:
            return {"ok": False, "output": "", "error": "old_string_not_found"}
        text = text.replace(old_s, new_s, 1)
        if len(text.encode("utf-8")) > _MAX_WRITE_BYTES:
            return {"ok": False, "output": "", "error": "result_too_large"}
        try:
            path.write_text(text, encoding="utf-8")
            return {"ok": True, "output": f"Applied edit to {rel}", "error": None}
        except OSError as exc:
            return {"ok": False, "output": "", "error": str(exc)}

    if tool_name == "run_in_terminal":
        command = str(args.get("command", ""))
        if not command.strip():
            return {"ok": False, "output": "", "error": "empty_command"}
        cwd_rel = args.get("cwd")
        cwd_p = workdir()
        if cwd_rel:
            sp = _safe_child_path(str(cwd_rel))
            if sp is None or not sp.is_dir():
                return {"ok": False, "output": "", "error": "unsafe_or_missing_cwd"}
            cwd_p = sp
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd_p),
                capture_output=True,
                text=True,
                timeout=_TERMINAL_TIMEOUT,
                check=False,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if len(out) > _MAX_SHELL_OUT:
                out = out[:_MAX_SHELL_OUT] + "\n...[truncated]"
            if proc.returncode != 0:
                out += f"\nError (exit {proc.returncode})"
            return {"ok": proc.returncode == 0, "output": out, "error": None if proc.returncode == 0 else f"exit_{proc.returncode}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": "", "error": "timeout"}
        except Exception as exc:
            return {"ok": False, "output": "", "error": str(exc)}

    return {"ok": False, "output": "", "error": f"unsupported_tool:{tool_name}"}


async def _send(ws: Any, payload: Dict[str, Any]) -> None:
    await ws.send(json.dumps(payload))


async def _connector_heartbeat_loop(ws: Any, active_run_id: Optional[str]) -> None:
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL_SEC)
        body: Dict[str, Any] = {"type": "connector.heartbeat"}
        if active_run_id:
            body["active_run_id"] = active_run_id
        await _send(ws, body)


async def handle_run_lease(
    lease: Dict[str, Any],
    ws: Any,
    *,
    tool_queue: asyncio.Queue,
    cancel_event: Optional[asyncio.Event] = None,
    active_run_queues: Dict[str, asyncio.Queue],
) -> None:
    """Hybrid path: lease_ack then process tool.invoke until release/cancel."""
    run_id = str(lease.get("run_id") or "")
    if not run_id:
        return
    active_run_queues[run_id] = tool_queue

    async def _cancelled() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    await _send(
        ws,
        {
            "type": "run.lease_ack",
            "run_id": run_id,
            "protocol_version": 1,
            "message": "Local connector ready for delegated tools",
        },
    )

    try:
        while True:
            if await _cancelled():
                return
            try:
                msg = await asyncio.wait_for(tool_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            mtype = msg.get("type")
            if mtype == "run.connector_release" and str(msg.get("run_id")) == run_id:
                return
            if mtype == "run.cancel_requested" and str(msg.get("run_id", "")) == run_id:
                return
            if mtype != "tool.invoke":
                continue
            if str(msg.get("run_id")) != run_id:
                continue
            invoke_id = msg.get("invoke_id")
            tool_name = str(msg.get("tool_name") or "")
            tool_args = msg.get("tool_args") if isinstance(msg.get("tool_args"), dict) else {}
            result = execute_delegated_tool(tool_name, tool_args)
            await _send(
                ws,
                {
                    "type": "tool.result",
                    "protocol_version": 1,
                    "invoke_id": invoke_id,
                    "run_id": run_id,
                    "ok": bool(result.get("ok")),
                    "output": result.get("output") or "",
                    "error": result.get("error"),
                },
            )
    finally:
        active_run_queues.pop(run_id, None)


async def listen_forever(
    ws_url: str,
    *,
    on_run_lease: Callable[..., Any] = handle_run_lease,
) -> None:
    import websockets

    extra: Dict[str, Any] = {}
    tok = os.environ.get("AMPREALIZE_TOKEN") or os.environ.get("AMPREALIZE_API_TOKEN")
    if tok:
        extra["additional_headers"] = {"Authorization": f"Bearer {tok}"}

    async with websockets.connect(ws_url, **extra) as ws:
        logger.info("Connected to %s", ws_url.split("?", 1)[0])
        incoming: asyncio.Queue = asyncio.Queue()
        active_run_queues: Dict[str, asyncio.Queue] = {}
        cancel_event = asyncio.Event()

        async def pump_in() -> None:
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    mtype = msg.get("type")
                    if mtype == "tool.invoke" and str(msg.get("run_id")) == CONNECTOR_PROBE_RUN_ID:
                        invoke_id = msg.get("invoke_id")
                        tool_name = str(msg.get("tool_name") or "")
                        tool_args = msg.get("tool_args") if isinstance(msg.get("tool_args"), dict) else {}
                        result = execute_delegated_tool(tool_name, tool_args)
                        await _send(
                            ws,
                            {
                                "type": "tool.result",
                                "protocol_version": 1,
                                "invoke_id": invoke_id,
                                "run_id": CONNECTOR_PROBE_RUN_ID,
                                "ok": bool(result.get("ok")),
                                "output": result.get("output") or "",
                                "error": result.get("error"),
                            },
                        )
                        continue
                    if mtype == "run.cancel_requested":
                        cancel_event.set()
                    rid = msg.get("run_id")
                    if isinstance(rid, str) and rid in active_run_queues:
                        if mtype in ("tool.invoke", "run.connector_release"):
                            await active_run_queues[rid].put(msg)
                            continue
                    await incoming.put(msg)
            except asyncio.CancelledError:
                raise

        pump_task = asyncio.create_task(pump_in())
        hb_task: Optional[asyncio.Task] = None
        try:
            while True:
                msg = await incoming.get()
                mtype = msg.get("type")
                if mtype == "run_lease":
                    rid = msg.get("run_id")
                    hb_task = asyncio.create_task(_connector_heartbeat_loop(ws, str(rid) if rid else None))
                    tq: asyncio.Queue = asyncio.Queue()
                    try:
                        await on_run_lease(
                            msg,
                            ws,
                            tool_queue=tq,
                            cancel_event=cancel_event,
                            active_run_queues=active_run_queues,
                        )
                    finally:
                        if hb_task:
                            hb_task.cancel()
                            try:
                                await hb_task
                            except asyncio.CancelledError:
                                pass
                            hb_task = None
                        cancel_event.clear()
                elif mtype == "connector.ready":
                    logger.info("connector.ready replayed_pending=%s", msg.get("replayed_pending"))
                elif mtype == "pong":
                    pass
                elif mtype == "connector.heartbeat_ack":
                    pass
                elif mtype == "error":
                    logger.error("server error: %s", msg)
        finally:
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass
            if hb_task:
                hb_task.cancel()
                try:
                    await hb_task
                except asyncio.CancelledError:
                    pass


def ws_url_with_token(device_token: str) -> str:
    from amprealize.connector_daemon.client import api_base_url

    base = api_base_url().replace("http://", "ws://").replace("https://", "wss://")
    return f"{base}/api/v1/execution-connector/ws?device_token={device_token}"
