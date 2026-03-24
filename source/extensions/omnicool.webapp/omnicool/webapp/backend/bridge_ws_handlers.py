from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Set

from omnicool.webapp.backend import config_store as _cs
from omnicool.webapp.backend import flownex_bridge as _fb

log = logging.getLogger(__name__)

_clients: Set[Any] = set()
_poll_task: asyncio.Task | None = None


def _status_json(state: str, message: str = "", progress: float = 0.0) -> str:
    return json.dumps({
        "type": "status",
        "payload": {
            "state": state,
            "message": message,
            "progress": progress,
        },
    })


def _schema_json() -> str:
    return json.dumps({
        "type": "schema",
        "payload": _fb.get_schema(),
    })


def _state_json() -> str:
    bridge_status = _fb.get_status()
    snap = _fb.get_state_snapshot()

    if not bridge_status.get("available"):
        status_payload = {
            "state": "error",
            "message": "Flownex not available on this machine.",
            "progress": 0.0,
        }
    elif bridge_status.get("transientRunning"):
        status_payload = {
            "state": "running",
            "message": "Transient simulation running.",
            "progress": 0.0,
        }
    elif not bridge_status.get("projectAttached"):
        status_payload = {
            "state": "idle",
            "message": "No project attached.",
            "progress": 0.0,
        }
    else:
        status_payload = {
            "state": "idle",
            "message": f"Project attached: {bridge_status.get('projectPath', '')}",
            "progress": 1.0,
        }

    return json.dumps({
        "type": "state",
        "payload": {
            "status": status_payload,
            "connected_project": snap.get("connected_project", ""),
            "io_directory": snap.get("io_directory", ""),
            # Aliases used by the index.html IIFE for localStorage path persistence
            "savedProjectPath": snap.get("connected_project", ""),
            "savedIoDir": snap.get("io_directory", ""),
            "inputs": snap.get("inputs", {}),
            "outputs": snap.get("outputs", {}),
            "history": snap.get("history", []),
            "transientRunning": snap.get("transientRunning", False),
        },
    })


def _outputs_delta_messages(values: Dict[str, Any]) -> list[str]:
    msgs: list[str] = []
    for key, value in values.items():
        msgs.append(json.dumps({
            "type": "outputs_delta",
            "payload": {
                "key": key,
                "value": value,
            },
        }))
    return msgs


async def _broadcast(raw: str) -> None:
    stale: list[Any] = []
    for ws in list(_clients):
        try:
            await ws.send(raw)
        except Exception:
            stale.append(ws)

    for ws in stale:
        _clients.discard(ws)


async def _broadcast_outputs(values: Dict[str, Any]) -> None:
    for raw in _outputs_delta_messages(values):
        await _broadcast(raw)
    await _broadcast(_state_json())


async def _poll_outputs_loop() -> None:
    global _poll_task
    try:
        while _fb.is_transient_running():
            await asyncio.sleep(_fb.get_poll_interval())

            result = _fb.read_outputs()
            if result.get("ok"):
                await _broadcast_outputs(result.get("outputs", {}))

                usd_sync = result.get("usdSync") or {}
                if usd_sync.get("updatedPrims"):
                    await _broadcast(_status_json(
                        "running",
                        f"Transient poll: updated {usd_sync.get('updatedPrims', 0)} USD prim(s).",
                        0.0,
                    ))
            else:
                await _broadcast(_status_json(
                    "error",
                    result.get("message", "Failed to poll outputs."),
                    0.0,
                ))
                break
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("[bridge_ws] polling loop error: %s", exc)
        await _broadcast(_status_json("error", str(exc), 0.0))
    finally:
        _poll_task = None


async def _ensure_poll_task() -> None:
    global _poll_task
    if _poll_task is None or _poll_task.done():
        _poll_task = asyncio.create_task(_poll_outputs_loop())


async def _stop_poll_task() -> None:
    global _poll_task
    if _poll_task is not None:
        _poll_task.cancel()
        try:
            await _poll_task
        except BaseException:
            pass
        _poll_task = None


async def handle_bridge_connect(websocket: Any) -> None:
    _clients.add(websocket)
    try:
        await websocket.send(_schema_json())
        await websocket.send(_state_json())
    except Exception as exc:  # noqa: BLE001
        log.warning("[bridge_ws] on_connect send error: %s", exc)
        _clients.discard(websocket)


def apply_saved_config() -> None:
    """Restore persisted config from config_store into flownex_bridge.

    Called once at extension startup after ``config_store.set_path()``.
    Maps config_store field names to flownex_bridge patch keys.
    """
    try:
        cfg = _cs.load_config()
        if not cfg:
            log.info("[bridge_ws] apply_saved_config: no saved config found")
            return

        patch: Dict[str, Any] = {}
        if cfg.get("projectFile"):
            patch["flownexProject"] = cfg["projectFile"]
        if cfg.get("ioDirectory"):
            patch["ioFileDirectory"] = cfg["ioDirectory"]
        if "solveOnChange" in cfg:
            patch["solveOnChange"] = cfg["solveOnChange"]
        if "resultPollingInterval" in cfg:
            patch["resultPollingInterval"] = cfg["resultPollingInterval"]

        if patch:
            result = _fb.set_config(patch)
            if "error" not in result:
                log.info(
                    "[bridge_ws] apply_saved_config: restored keys=%s",
                    list(patch.keys()),
                )
            else:
                log.warning(
                    "[bridge_ws] apply_saved_config: set_config returned error: %s",
                    result["error"],
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("[bridge_ws] apply_saved_config error: %s", exc)

async def handle_bridge_message(msg: str, websocket: Any) -> None:
    try:
        data = json.loads(msg)
    except Exception:  # noqa: BLE001
        return

    _clients.add(websocket)

    typ: str = data.get("type", "")
    payload: Dict[str, Any] = data.get("payload") or {}

    print(f"[bridge] msg_type = {typ!r}")
    log.debug("[bridge_ws] received type=%r payload=%r", typ, payload)

    try:
        if typ == "configure":
            project_path = str(payload.get("projectPath", "") or "")
            io_dir = str(payload.get("ioDir", "") or "")
            backend = str(payload.get("backend", "flownex") or "flownex")

            patch: Dict[str, Any] = {}
            if project_path:
                patch["flownexProject"] = project_path
            if io_dir:
                patch["ioFileDirectory"] = io_dir
            if "solveOnChange" in payload:
                patch["solveOnChange"] = bool(payload.get("solveOnChange"))
            if "resultPollingInterval" in payload:
                patch["resultPollingInterval"] = payload.get("resultPollingInterval")

            if patch:
                result = _fb.set_config(patch)
                if "error" in result:
                    await websocket.send(_status_json("error", result["error"], 0.0))
                    return

            # Persist to disk so paths survive extension restarts
            _cs.save_config({
                "projectFile": project_path,
                "ioDirectory": io_dir,
                "solveOnChange": bool(payload.get("solveOnChange", False)),
                "resultPollingInterval": payload.get("resultPollingInterval", 1.0),
            })

            await websocket.send(_status_json(
                "idle",
                f"Configured — project: {project_path!r}  ioDir: {io_dir!r}  backend: {backend!r}",
                0.0,
            ))
            await websocket.send(_schema_json())
            await websocket.send(_state_json())

        elif typ == "open_flownex":
            await websocket.send(_status_json("running", "Opening Flownex…", 0.1))
            result = _fb.open_flownex()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))
            await websocket.send(_state_json())

        elif typ == "open_project":
            await websocket.send(_status_json("running", "Opening project…", 0.1))
            result = _fb.open_project()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))
            await websocket.send(_schema_json())
            await websocket.send(_state_json())

        elif typ == "close_project":
            await _stop_poll_task()
            result = _fb.close_project()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))
            await websocket.send(_state_json())

        elif typ == "close_app":
            await _stop_poll_task()
            result = _fb.exit_app()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))
            await websocket.send(_state_json())

        elif typ == "get_state":
            await websocket.send(_state_json())
            await websocket.send(_schema_json())

        elif typ == "set_input":
            scope = str(payload.get("scope", "") or "")
            key = str(payload.get("key", "") or "")
            value = payload.get("value")

            result = _fb.set_input_value(scope, key, value)

            await websocket.send(json.dumps({
                "type": "inputs_delta",
                "payload": {
                    "scope": scope,
                    "key": key,
                    "value": value,
                },
            }))

            if not result.get("ok"):
                await websocket.send(_status_json(
                    "error",
                    result.get("message", "Failed to set input."),
                    0.0,
                ))
            else:
                await websocket.send(_status_json(
                    "idle",
                    result.get("message", ""),
                    0.0,
                ))

                cfg = _fb.get_config()
                if bool(cfg.get("solveOnChange", False)) and scope in ("dynamic", "static"):
                    await websocket.send(_status_json(
                        "running",
                        "Running steady-state simulation…",
                        0.1,
                    ))
                    solve_result = _fb.run_steady()
                    await websocket.send(_status_json(
                        "idle" if solve_result.get("ok") else "error",
                        solve_result.get("message", ""),
                        1.0 if solve_result.get("ok") else 0.0,
                    ))
                    if solve_result.get("ok"):
                        await _broadcast_outputs(solve_result.get("outputs", {}))

        elif typ == "run":
            mode = str(payload.get("mode", "steady") or "steady")
            if mode == "steady":
                await websocket.send(_status_json(
                    "running",
                    "Running steady-state simulation…",
                    0.1,
                ))
                result = _fb.run_steady()
                await websocket.send(_status_json(
                    "idle" if result.get("ok") else "error",
                    result.get("message", ""),
                    1.0 if result.get("ok") else 0.0,
                ))
                if result.get("ok"):
                    await _broadcast_outputs(result.get("outputs", {}))
            else:
                await websocket.send(_status_json(
                    "error",
                    f"Unsupported run mode: {mode!r}",
                    0.0,
                ))

        elif typ == "load_defaults_and_run_steady":
            await websocket.send(_status_json(
                "running",
                "Loading defaults and solving steady state…",
                0.1,
            ))
            result = _fb.load_defaults_and_run_steady()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))

            if result.get("ok"):
                for scope, values in _fb.get_input_values().items():
                    for key, value in values.items():
                        await websocket.send(json.dumps({
                            "type": "inputs_delta",
                            "payload": {
                                "scope": scope,
                                "key": key,
                                "value": value,
                            },
                        }))
                await _broadcast_outputs(result.get("outputs", {}))

        elif typ == "start_transient":
            await websocket.send(_status_json(
                "running",
                "Starting transient simulation…",
                0.1,
            ))
            result = _fb.start_transient()
            await websocket.send(_status_json(
                "running" if result.get("ok") else "error",
                result.get("message", ""),
                0.0,
            ))
            if result.get("ok"):
                await _ensure_poll_task()
                await websocket.send(_state_json())

        elif typ == "stop_transient":
            result = _fb.stop_transient()
            await _stop_poll_task()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))

            outputs_result = _fb.read_outputs()
            outputs = outputs_result.get("outputs", {})
            if outputs:
                await _broadcast_outputs(outputs)
            else:
                await websocket.send(_state_json())

        elif typ == "connect":
            project_path = str(payload.get("projectPath", "") or "")
            io_dir = str(payload.get("ioDir", "") or "")

            patch = {}
            if project_path:
                patch["flownexProject"] = project_path
            if io_dir:
                patch["ioFileDirectory"] = io_dir

            if patch:
                result = _fb.set_config(patch)
                if "error" in result:
                    await websocket.send(_status_json("error", result["error"], 0.0))
                    return

            # Persist to disk
            _cs.save_config({
                "projectFile": project_path,
                "ioDirectory": io_dir,
            })

            await websocket.send(_status_json("running", "Connecting to project…", 0.1))
            result = _fb.open_project()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))
            await websocket.send(_schema_json())
            await websocket.send(_state_json())

        elif typ == "get_schema":
            await websocket.send(_schema_json())
            await websocket.send(_state_json())

        elif typ == "read_outputs":
            result = _fb.read_outputs()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))
            if result.get("ok"):
                await _broadcast_outputs(result.get("outputs", {}))
            else:
                await websocket.send(_state_json())

        elif typ == "config.browse_file":
            # tkinter is not available in this environment; return an empty
            # path so the frontend falls back gracefully to manual paste.
            req_id = data.get("id", "") or payload.get("requestId", "")
            request_id = payload.get("requestId", req_id)
            log.info("[bridge_ws] config.browse_file: tkinter unavailable, returning empty path")
            await websocket.send(json.dumps({
                "type": "browse_result",
                "payload": {
                    "requestId": request_id,
                    "path": "",
                },
            }))

    except Exception as exc:  # noqa: BLE001
        log.warning("[bridge_ws] handler error for type=%r: %s", typ, exc)
        try:
            await websocket.send(_status_json("error", str(exc), 0.0))
        except Exception:
            pass
