"""Flownex backend bridge.

Wraps ``FNXApi`` (Windows COM API) and ``FlownexIO`` (CSV-based IO config)
into simple, JSON-safe functions that can be called from ``ws_handlers.py``.

Both dependencies are imported lazily so this module loads safely on any
platform or environment where Flownex is not installed — calls simply return
graceful empty/fallback responses.

Module-level singletons
-----------------------
``_api``  : ``FNXApi | None``  — created once on first call that needs it.
``_io``   : ``FlownexIO | None`` — created once on first call that needs it.

These can be replaced in tests via :func:`reset_singletons`.

Expected companion files (placed alongside this module in ``backend/``):
  ``fnx_api.py``            — ``FNXApi`` class (Windows-only, uses pythonnet)
  ``fnx_io_definition.py``  — ``FlownexIO`` / ``InputDefinition`` /
                               ``OutputDefinition`` (pure-Python, cross-platform)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons — lazily initialised
# ---------------------------------------------------------------------------

_api: Any = None   # FNXApi | None
_io: Any = None    # FlownexIO | None


def _get_api() -> Any:
    """Return (or create on first call) the FNXApi singleton."""
    global _api
    if _api is None:
        try:
            from omnicool.webapp.backend.fnx_api import FNXApi  # noqa: PLC0415
            _api = FNXApi()
        except Exception as exc:  # noqa: BLE001
            log.info("[flownex_bridge] FNXApi not available: %s", exc)
    return _api


def _get_io() -> Any:
    """Return (or create on first call) the FlownexIO singleton."""
    global _io
    if _io is None:
        try:
            from omnicool.webapp.backend.fnx_io_definition import FlownexIO  # noqa: PLC0415
            _io = FlownexIO()
        except Exception as exc:  # noqa: BLE001
            log.info("[flownex_bridge] FlownexIO not available: %s", exc)
    return _io


def reset_singletons(api: Any = None, io: Any = None) -> None:
    """Replace the module-level singletons.  Intended for testing only."""
    global _api, _io
    _api = api
    _io = io


# ---------------------------------------------------------------------------
# Internal serialisation helpers
# ---------------------------------------------------------------------------

def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _input_def_to_dict(inp: Any) -> Dict[str, Any]:
    """Serialise an ``InputDefinition`` instance to a JSON-safe dict."""
    return {
        "key": str(getattr(inp, "Key", "") or ""),
        "description": str(getattr(inp, "Description", "") or ""),
        "componentIdentifier": str(getattr(inp, "ComponentIdentifier", "") or ""),
        "propertyIdentifier": str(getattr(inp, "PropertyIdentifier", "") or ""),
        "editType": str(getattr(inp, "EditType", "") or ""),
        "min": _safe_float(getattr(inp, "Min", None)),
        "max": _safe_float(getattr(inp, "Max", None)),
        "step": _safe_float(getattr(inp, "Step", None)),
        "unit": str(getattr(inp, "Unit", "") or ""),
        # DefaultValue may be bool (checkbox) or float (slider) — preserve as-is
        "defaultValue": getattr(inp, "DefaultValue", None),
    }


def _output_def_to_dict(out: Any) -> Dict[str, Any]:
    """Serialise an ``OutputDefinition`` instance to a JSON-safe dict."""
    return {
        "key": str(getattr(out, "Key", "") or ""),
        "description": str(getattr(out, "Description", "") or ""),
        "componentIdentifier": str(getattr(out, "ComponentIdentifier", "") or ""),
        "propertyIdentifier": str(getattr(out, "PropertyIdentifier", "") or ""),
        "unit": str(getattr(out, "Unit", "") or ""),
        "category": str(getattr(out, "Category", "") or ""),
    }


# ---------------------------------------------------------------------------
# Public API — one function per WS command
# ---------------------------------------------------------------------------

def get_status() -> Dict[str, Any]:
    """Return Flownex availability and project-attachment status.

    Returns
    -------
    dict with keys:
        ``available``      – bool: Flownex installation detected by FNXApi.
        ``projectAttached``– bool: a project is currently open/attached.
        ``projectPath``    – str:  path of the attached project, or "".
    """
    api = _get_api()
    if api is None:
        return {"available": False, "projectAttached": False, "projectPath": ""}
    try:
        available = bool(api.IsFnxAvailable())
        attached = getattr(api, "AttachedProject", None) is not None
        project_path = str(getattr(api, "ProjectFile", "") or "")
        return {
            "available": available,
            "projectAttached": attached,
            "projectPath": project_path,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] get_status error: %s", exc)
        return {
            "available": False,
            "projectAttached": False,
            "projectPath": "",
            "error": str(exc),
        }


def get_config() -> Dict[str, Any]:
    """Return the current ``FlownexIO`` configuration.

    Reads from the ``FlownexUser.json`` settings file next to
    ``fnx_io_definition.py``.

    Returns
    -------
    dict with keys:
        ``flownexProject``       – str
        ``ioFileDirectory``      – str
        ``solveOnChange``        – bool
        ``resultPollingInterval``– float (seconds)
    """
    io = _get_io()
    if io is None:
        return {
            "flownexProject": "",
            "ioFileDirectory": "",
            "solveOnChange": False,
            "resultPollingInterval": 1.0,
        }
    try:
        setup = io.Setup
        return {
            "flownexProject": str(getattr(setup, "FlownexProject", "") or ""),
            "ioFileDirectory": str(getattr(setup, "IOFileDirectory", "") or ""),
            "solveOnChange": bool(getattr(setup, "SolveOnChange", False)),
            # ResultPollingInterval is stored as a string in UserSetupStore
            "resultPollingInterval": float(
                getattr(setup, "ResultPollingInterval", 1.0) or 1.0
            ),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] get_config error: %s", exc)
        return {"error": str(exc)}


def set_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Apply *patch* fields to the ``FlownexIO`` configuration and save.

    Only the keys present in *patch* are updated; other fields are left
    unchanged.  Accepted keys match those returned by :func:`get_config`:
    ``flownexProject``, ``ioFileDirectory``, ``solveOnChange``,
    ``resultPollingInterval``.

    Returns
    -------
    Updated config dict (same shape as :func:`get_config`) on success, or
    ``{"error": "<message>"}`` on failure.
    """
    io = _get_io()
    if io is None:
        return {"error": "FlownexIO not available"}
    try:
        setup = io.Setup
        if "flownexProject" in patch:
            setup.FlownexProject = str(patch["flownexProject"])
        if "ioFileDirectory" in patch:
            setup.IOFileDirectory = str(patch["ioFileDirectory"])
        if "solveOnChange" in patch:
            setup.SolveOnChange = bool(patch["solveOnChange"])
        if "resultPollingInterval" in patch:
            # Stored as string for legacy compat with UserSetupStore
            setup.ResultPollingInterval = str(float(patch["resultPollingInterval"]))
        io.Save()
        return get_config()
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] set_config error: %s", exc)
        return {"error": str(exc)}


def load_inputs() -> List[Dict[str, Any]]:
    """Load dynamic input definitions from ``Inputs.csv``.

    Returns
    -------
    List of serialised ``InputDefinition`` dicts, or ``[]`` when
    ``FlownexIO`` is unavailable or the file is missing/empty.
    """
    io = _get_io()
    if io is None:
        return []
    try:
        items = io.LoadDynamicInputs() or []
        return [_input_def_to_dict(i) for i in items]
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] load_inputs error: %s", exc)
        raise


def load_static_inputs() -> List[Dict[str, Any]]:
    """Load static input definitions from ``StaticInputs.csv``.

    Returns
    -------
    List of serialised ``InputDefinition`` dicts, or ``[]`` when
    ``FlownexIO`` is unavailable or the file is missing/empty.
    """
    io = _get_io()
    if io is None:
        return []
    try:
        items = io.LoadStaticInputs() or []
        return [_input_def_to_dict(i) for i in items]
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] load_static_inputs error: %s", exc)
        raise


def load_outputs() -> List[Dict[str, Any]]:
    """Load output definitions from ``Outputs.csv``.

    Returns
    -------
    List of serialised ``OutputDefinition`` dicts, or ``[]`` when
    ``FlownexIO`` is unavailable or the file is missing/empty.
    """
    io = _get_io()
    if io is None:
        return []
    try:
        items = io.LoadOutputs() or []
        return [_output_def_to_dict(o) for o in items]
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] load_outputs error: %s", exc)
        raise


def get_schema() -> Dict[str, Any]:
    """Return the combined inputs/outputs schema for the React webapp.

    Merges dynamic inputs, static inputs, and outputs into a single dict
    that the React app renders as its operating-conditions and results panels.

    Returns
    -------
    dict with keys:
        ``inputs``  – list of serialised ``InputDefinition`` dicts (dynamic + static).
        ``outputs`` – list of serialised ``OutputDefinition`` dicts.
    """
    try:
        inputs = (load_inputs() or []) + (load_static_inputs() or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] get_schema inputs error: %s", exc)
        inputs = []
    try:
        outputs = load_outputs() or []
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] get_schema outputs error: %s", exc)
        outputs = []
    return {"inputs": inputs, "outputs": outputs}


def open_project() -> Dict[str, Any]:
    """Open / attach to the Flownex project configured in ``FlownexIO``.

    Reads ``FlownexIO.Setup.FlownexProject`` to get the project path, then
    calls :py:meth:`FNXApi.AttachToProject`.

    Returns
    -------
    dict with keys:
        ``ok``      – bool: True on success.
        ``message`` – str: human-readable result.
    """
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}

    # Resolve project path from FlownexIO config
    project_path = ""
    io = _get_io()
    if io is not None:
        try:
            project_path = str(getattr(io.Setup, "FlownexProject", "") or "")
        except Exception as exc:  # noqa: BLE001
            log.warning("[flownex_bridge] open_project: cannot read FlownexProject: %s", exc)

    if not project_path:
        return {
            "ok": False,
            "message": "No project path configured. Send a 'configure' message first.",
        }

    try:
        api.AttachToProject(project_path)
        attached = getattr(api, "AttachedProject", None) is not None
        if attached:
            return {"ok": True, "message": f"Attached to project: {project_path}"}
        return {"ok": False, "message": f"Failed to attach to project: {project_path}"}
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] open_project error: %s", exc)
        return {"ok": False, "message": str(exc)}


def close_project() -> Dict[str, Any]:
    """Close the currently attached Flownex project.

    Returns
    -------
    dict with keys:
        ``ok``      – bool: True on success.
        ``message`` – str: human-readable result.
    """
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}
    try:
        api.CloseProject()
        return {"ok": True, "message": "Project closed."}
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] close_project error: %s", exc)
        return {"ok": False, "message": str(exc)}


def exit_app() -> Dict[str, Any]:
    """Exit the Flownex application.

    Returns
    -------
    dict with keys:
        ``ok``      – bool: True on success.
        ``message`` – str: human-readable result.
    """
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}
    try:
        api.ExitApplication()
        return {"ok": True, "message": "Flownex exited."}
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] exit_app error: %s", exc)
        return {"ok": False, "message": str(exc)}


def run_steady() -> Dict[str, Any]:
    """Run a blocking steady-state Flownex simulation.

    Returns
    -------
    dict with keys:
        ``ok``      – bool: True when the solver converged.
        ``message`` – str: human-readable result.
    """
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}
    try:
        success = bool(api.RunSteadyStateSimulationBlocking())
        if success:
            return {"ok": True, "message": "Steady-state simulation completed."}
        return {
            "ok": False,
            "message": "Simulation did not converge or timed out.",
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] run_steady error: %s", exc)
        return {"ok": False, "message": str(exc)}
