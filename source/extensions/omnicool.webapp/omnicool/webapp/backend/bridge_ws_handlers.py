from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Dict, Optional, Set

from omnicool.webapp.backend import flownex_bridge as _fb

log = logging.getLogger(__name__)

_clients: Set[Any] = set()
_poll_task: asyncio.Task | None = None

# Optional async callback registered by the host extension to open a native
# file/directory picker.  Signature:
#   async def _cb(mode: str, filters: list) -> str
# where mode is "file" or "directory", filters is a list of
# {"label": str, "extension": str} dicts, and the return value is the
# selected path (empty string if cancelled).
_browse_callback: Optional[Callable[..., Coroutine[Any, Any, str]]] = None


def set_browse_callback(cb: Optional[Callable[..., Coroutine[Any, Any, str]]]) -> None:
    """Register (or clear) the async browse-file callback.

    The callback will be awaited when the frontend sends a
    ``config.browse_file`` message.  Pass *None* to remove it.
    """
    global _browse_callback
    _browse_callback = cb


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

    connected_project = snap.get("connected_project", "")
    io_directory = snap.get("io_directory", "")

    return json.dumps({
        "type": "state",
        "payload": {
            "status": status_payload,
            "connected_project": connected_project,
            "io_directory": io_directory,
            # Aliases expected by the frontend path-persistence IIFE so that
            # paths are saved to localStorage whenever a state message arrives.
            "savedProjectPath": connected_project,
            "savedIoDir": io_directory,
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
    _consecutive_errors: int = 0
    _MAX_CONSECUTIVE_ERRORS: int = 5
    try:
        while _fb.is_transient_running():
            await asyncio.sleep(_fb.get_poll_interval())

            result = _fb.read_outputs()
            if result.get("ok"):
                _consecutive_errors = 0
                await _broadcast_outputs(result.get("outputs", {}))

                usd_sync = result.get("usdSync") or {}
                if usd_sync.get("updatedPrims"):
                    await _broadcast(_status_json(
                        "running",
                        f"Transient poll: updated {usd_sync.get('updatedPrims', 0)} USD prim(s).",
                        0.0,
                    ))
            else:
                _consecutive_errors += 1
                log.warning(
                    "[bridge_ws] poll cycle error (%d/%d): %s",
                    _consecutive_errors,
                    _MAX_CONSECUTIVE_ERRORS,
                    result.get("message", "Unknown error"),
                )
                await _broadcast(_status_json(
                    "running",
                    f"Poll error ({_consecutive_errors}/{_MAX_CONSECUTIVE_ERRORS}): "
                    + result.get("message", "Failed to poll outputs."),
                    0.0,
                ))
                if _consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    log.warning(
                        "[bridge_ws] stopping transient poll after %d consecutive errors.",
                        _consecutive_errors,
                    )
                    await _broadcast(_status_json(
                        "error",
                        f"Transient polling stopped after {_consecutive_errors} consecutive errors: "
                        + result.get("message", ""),
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


async def handle_bridge_message(msg: str, websocket: Any) -> None:
    try:
        data = json.loads(msg)
    except Exception:  # noqa: BLE001
        return

    _clients.add(websocket)

    typ: str = data.get("type", "")
    payload: Dict[str, Any] = data.get("payload") or {}

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

        elif typ == "load_defaults":
            # Load default input values from vendor IO definitions without
            # running a simulation.  Broadcasts inputs_delta for each key so
            # the frontend sliders snap to their defaults.
            result = _fb.load_defaults()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", "Loaded default inputs."),
                1.0 if result.get("ok") else 0.0,
            ))
            if result.get("ok"):
                for scope, values in (result.get("inputs") or {}).items():
                    for key, value in (values or {}).items():
                        await websocket.send(json.dumps({
                            "type": "inputs_delta",
                            "payload": {
                                "scope": scope,
                                "key": key,
                                "value": value,
                            },
                        }))
            await websocket.send(_state_json())

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

            await websocket.send(_status_json("running", "Connecting to project…", 0.1))
            result = _fb.open_project()
            await websocket.send(_status_json(
                "idle" if result.get("ok") else "error",
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))
            await websocket.send(_schema_json())
            await websocket.send(_state_json())

        elif typ == "config.browse_file":
            # The frontend sends this when the user clicks a "..." path-browse
            # button.  We delegate to the registered async callback (if any) to
            # open a native OS file / directory picker, then respond with a
            # browse_result message so the frontend can populate the input.
            req_id = str(data.get("id", "") or payload.get("requestId", ""))
            mode = str(payload.get("mode", "file") or "file")
            filters = payload.get("filters") or []

            path = ""
            if _browse_callback is not None:
                try:
                    path = await _browse_callback(mode, filters) or ""
                except Exception as browse_exc:  # noqa: BLE001
                    log.warning("[bridge_ws] browse_file callback error: %s", browse_exc)

            await websocket.send(json.dumps({
                "type": "browse_result",
                "payload": {
                    "requestId": req_id,
                    "path": path,
                },
            }))

    except Exception as exc:  # noqa: BLE001
        log.warning("[bridge_ws] handler error for type=%r: %s", typ, exc)
        try:
            await websocket.send(_status_json("error", str(exc), 0.0))
        except Exception:
            pass
