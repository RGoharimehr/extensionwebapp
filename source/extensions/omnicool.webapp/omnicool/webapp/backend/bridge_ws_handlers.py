"""WebSocket message handler for the Flownex bridge protocol (port 8001).

The React webapp connects to ``ws://127.0.0.1:8001/ws`` using a *push-based*
protocol that is **different** from the USD-bridge protocol on port 8899.

Client → Server messages
------------------------
All messages carry ``{type, id, payload}``.  The ``id`` field is sent by the
client but responses are NOT matched by ``id``; the server pushes typed
messages independently.

=========== ================================================================
Type        Payload
=========== ================================================================
configure   ``{projectPath, ioDir, backend}`` — save paths and backend name
open_project ``{}`` — attach to the configured Flownex project
close_project ``{}`` — close the currently attached project
close_app   ``{}`` — exit Flownex
get_state   ``{}`` — request a full state push
set_input   ``{scope, key, value}`` — report a user-controlled input value
run         ``{mode}`` — run simulation (``mode="steady"`` supported)
connect     ``{projectPath}`` — shorthand: configure + open_project in one
custom_msg  ``{msgType, payload}`` — forwarded for extensibility
=========== ================================================================

Server → Client messages
------------------------
The server pushes ``{type, payload}`` messages independently of incoming
requests.  The React webapp dispatches on the ``type`` field.

============= ==================================================================
Type          Payload                        Used by
============= ==================================================================
schema        ``{inputs:[…], outputs:[…]}``  initial + after reload
state         ``{status, inputs, outputs}``  full state snapshot
status        ``{state, message, progress}`` transient status update
inputs_delta  ``{scope, key, value}``        echo a single input change
outputs_delta ``{key, value}``               push a single output reading
============= ==================================================================
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from omnicool.webapp.backend import flownex_bridge as _fb

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Push-message builders
# ---------------------------------------------------------------------------

def _status_json(state: str, message: str = "", progress: float = 0.0) -> str:
    """Serialise a ``status`` push message."""
    return json.dumps({
        "type": "status",
        "payload": {"state": state, "message": message, "progress": progress},
    })


def _schema_json() -> str:
    """Serialise a ``schema`` push message (all inputs + outputs)."""
    return json.dumps({
        "type": "schema",
        "payload": _fb.get_schema(),
    })


def _state_json() -> str:
    """Serialise a ``state`` push message (current project attachment + values)."""
    bridge_status = _fb.get_status()
    if not bridge_status.get("available"):
        status_payload = {
            "state": "error",
            "message": "Flownex not available on this machine.",
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
    # Include saved paths so the UI can restore them on reconnect.
    config = _fb.get_config()
    return json.dumps({
        "type": "state",
        "payload": {
            "status": status_payload,
            # Input and output *values* are populated incrementally via
            # inputs_delta / outputs_delta when a simulation produces results.
            "inputs": {},
            "outputs": {},
            # Saved configuration paths — used by the index.html localStorage patch
            # to pre-populate the Configuration tab inputs after reconnect.
            "savedProjectPath": config.get("flownexProject", ""),
            "savedIoDir": config.get("ioFileDirectory", ""),
        },
    })


# ---------------------------------------------------------------------------
# Native file / folder dialog (server-side)
# ---------------------------------------------------------------------------

async def _open_native_dialog(mode: str, filters: list) -> str:
    """Open a native OS file-selection dialog on the server and return the path.

    Parameters
    ----------
    mode:
        ``"file"`` — pick a single file (project path).
        ``"directory"`` — pick a directory (IO directory).
    filters:
        Optional list of ``{"label": …, "extension": …}`` dicts to restrict
        which file types appear.  Ignored for directory mode.

    Returns
    -------
    The absolute path chosen by the user, or ``""`` when the dialog was
    cancelled or is unavailable.

    Implementation strategy (first that succeeds wins):
    1.  ``omni.kit.window.file_importer`` — native Omniverse file browser.
    2.  Python ``tkinter.filedialog`` — works on all platforms when Tk is
        available (common in standalone Python; may not be present in Kit).
    3.  Falls back to ``""`` with a warning.
    """
    import asyncio as _asyncio

    # ── Attempt 1: Omniverse Kit file importer ────────────────────────────
    try:
        import omni.kit.window.file_importer as _fi  # type: ignore

        result_fut: "_asyncio.Future[str]" = _asyncio.get_event_loop().create_future()

        def _on_selected(filename: str, dirname: str, specs: Any) -> None:
            if not result_fut.done():
                result_fut.set_result(str(filename or dirname or ""))

        def _on_cancelled() -> None:
            if not result_fut.done():
                result_fut.set_result("")

        importer = _fi.get_file_importer()
        if mode == "directory":
            importer.show_window(
                title="Select IO Directory",
                import_button_label="Select",
                import_handler=_on_selected,
                show_only_collections=["my-computer"],
            )
        else:
            # Build extension filter tuples like [("Flownex project", "*.proj")]
            ext_types = [(f.get("label", "All files"), f.get("extension", "*.*"))
                         for f in (filters or [])] or [("All files", "*.*")]
            importer.show_window(
                title="Select Project File",
                import_button_label="Select",
                import_handler=_on_selected,
                file_extension_types=ext_types,
            )
        try:
            return await _asyncio.wait_for(
                _asyncio.shield(result_fut), timeout=120
            )
        except _asyncio.TimeoutError:
            return ""
    except Exception:  # noqa: BLE001
        pass  # Omniverse importer not available — try next approach

    # ── Attempt 2: tkinter file dialog ───────────────────────────────────
    try:
        import tkinter as _tk
        import tkinter.filedialog as _fd

        loop = _asyncio.get_event_loop()

        def _tk_dialog() -> str:
            root = _tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            if mode == "directory":
                path = _fd.askdirectory(title="Select IO Directory", parent=root)
            else:
                ftypes: list = [(f.get("label", "All files"), f.get("extension", "*.*"))
                                for f in (filters or [])]
                if not ftypes:
                    ftypes = [("All files", "*.*")]
                path = _fd.askopenfilename(title="Select Project File", filetypes=ftypes, parent=root)
            root.destroy()
            return str(path or "")

        return await loop.run_in_executor(None, _tk_dialog)
    except Exception as exc:  # noqa: BLE001
        log.warning("[bridge_ws] _open_native_dialog tkinter fallback failed: %s", exc)

    return ""


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

async def handle_bridge_connect(websocket: Any) -> None:
    """Send the initial schema and state snapshots to a newly connected client."""
    try:
        await websocket.send(_schema_json())
        await websocket.send(_state_json())
    except Exception as exc:  # noqa: BLE001
        log.warning("[bridge_ws] on_connect send error: %s", exc)


# ---------------------------------------------------------------------------
# Message dispatcher
# ---------------------------------------------------------------------------

async def handle_bridge_message(msg: str, websocket: Any) -> None:
    """Dispatch a single message received from the React webapp.

    Parameters
    ----------
    msg:
        Raw JSON string from the WebSocket.
    websocket:
        The open WebSocket connection used to push responses back.
    """
    try:
        data = json.loads(msg)
    except Exception:  # noqa: BLE001
        return  # Silently ignore malformed frames

    typ: str = data.get("type", "")
    payload: Dict[str, Any] = data.get("payload") or {}

    try:
        # ── configure ──────────────────────────────────────────────────────
        if typ == "configure":
            project_path = str(payload.get("projectPath", "") or "")
            io_dir = str(payload.get("ioDir", "") or "")
            backend = str(payload.get("backend", "flownex") or "flownex")

            patch: Dict[str, Any] = {}
            if project_path:
                patch["flownexProject"] = project_path
            if io_dir:
                patch["ioFileDirectory"] = io_dir

            if patch:
                _fb.set_config(patch)

            await websocket.send(_status_json(
                "idle",
                f"Configured — project: {project_path!r}  "
                f"ioDir: {io_dir!r}  backend: {backend!r}",
            ))
            # Reload CSV schema in case ioDir changed.
            await websocket.send(_schema_json())

        # ── open_project ───────────────────────────────────────────────────
        elif typ == "open_project":
            await websocket.send(_status_json("running", "Opening project…", 0.1))
            result = _fb.open_project()
            final_state = "idle" if result.get("ok") else "error"
            await websocket.send(_status_json(
                final_state,
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))
            await websocket.send(_schema_json())
            await websocket.send(_state_json())

        # ── close_project ──────────────────────────────────────────────────
        elif typ == "close_project":
            result = _fb.close_project()
            final_state = "idle" if result.get("ok") else "error"
            await websocket.send(_status_json(final_state, result.get("message", "")))
            await websocket.send(_state_json())

        # ── close_app ──────────────────────────────────────────────────────
        elif typ == "close_app":
            result = _fb.exit_app()
            final_state = "idle" if result.get("ok") else "error"
            await websocket.send(_status_json(final_state, result.get("message", "")))

        # ── get_state ──────────────────────────────────────────────────────
        elif typ == "get_state":
            await websocket.send(_state_json())
            await websocket.send(_schema_json())

        # ── set_input ──────────────────────────────────────────────────────
        elif typ == "set_input":
            scope = str(payload.get("scope", "") or "")
            key = str(payload.get("key", "") or "")
            value = payload.get("value")
            # Echo back as inputs_delta so the React state stays in sync.
            await websocket.send(json.dumps({
                "type": "inputs_delta",
                "payload": {"scope": scope, "key": key, "value": value},
            }))
            # TODO: propagate to FNXApi.SetPropertyValue when a project is attached.

        # ── run ────────────────────────────────────────────────────────────
        elif typ == "run":
            mode = str(payload.get("mode", "steady") or "steady")
            if mode == "steady":
                await websocket.send(_status_json("running", "Running steady-state simulation…", 0.1))
                result = _fb.run_steady()
                final_state = "idle" if result.get("ok") else "error"
                final_progress = 1.0 if result.get("ok") else 0.0
                await websocket.send(_status_json(
                    final_state,
                    result.get("message", ""),
                    final_progress,
                ))
            else:
                await websocket.send(_status_json(
                    "error",
                    f"Unsupported run mode: {mode!r}",
                ))

        # ── connect (shorthand: configure + open_project) ──────────────────
        elif typ == "connect":
            project_path = str(payload.get("projectPath", "") or "")
            if project_path:
                _fb.set_config({"flownexProject": project_path})
            await websocket.send(_status_json("running", "Connecting to project…", 0.1))
            result = _fb.open_project()
            final_state = "idle" if result.get("ok") else "error"
            await websocket.send(_status_json(
                final_state,
                result.get("message", ""),
                1.0 if result.get("ok") else 0.0,
            ))
            await websocket.send(_schema_json())
            await websocket.send(_state_json())

        # ── custom_msg ─────────────────────────────────────────────────────
        elif typ == "custom_msg":
            log.info(
                "[bridge_ws] custom_msg received — msgType=%r",
                payload.get("msgType"),
            )
            # No-op: extensibility hook for external scripts that use
            # window.__bridgeAPI.sendCustom(…).

        # ── config.browse_file ─────────────────────────────────────────────
        # Opens a native file-selection dialog on the server machine and
        # returns the chosen full path.  The UI cannot get a full path from
        # an <input type="file"> due to browser security restrictions, so we
        # delegate to the server where the file system is directly accessible.
        elif typ == "config.browse_file":
            mode = str(payload.get("mode", "file") or "file")
            filters = payload.get("filters") or []
            path = await _open_native_dialog(mode, filters)
            await websocket.send(json.dumps({
                "type": "browse_result",
                "payload": {
                    "mode": mode,
                    "path": path,
                    "requestId": payload.get("requestId", ""),
                },
            }))

        else:
            log.debug("[bridge_ws] unknown message type %r — ignoring", typ)

    except Exception as exc:  # noqa: BLE001
        log.warning("[bridge_ws] handler error for type=%r: %s", typ, exc)
        try:
            await websocket.send(_status_json("error", str(exc)))
        except Exception:  # noqa: BLE001
            pass
