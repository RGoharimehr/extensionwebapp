from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_api: Any = None
_io: Any = None

# ---------------------------------------------------------------------------
# In-memory runtime state
# ---------------------------------------------------------------------------

_dynamic_input_defs: Dict[str, Dict[str, Any]] = {}
_static_input_defs: Dict[str, Dict[str, Any]] = {}
_output_defs: Dict[str, Dict[str, Any]] = {}

_input_values: Dict[str, Dict[str, Any]] = {
    "dynamic": {},
    "static": {},
}
_output_values: Dict[str, Any] = {}
_simulation_data_history: List[Dict[str, Any]] = []

_transient_running: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_output_value(v: Any) -> Optional[float]:
    """Convert a vendor output value to a safe JSON-serializable float or None.

    The vendor ``GetPropertyValueUnit`` / ``GetPropertyValue`` methods may
    return:
    - ``None``                     → kept as ``None``
    - a numeric type or numeric str → converted to ``float``
    - an error message string       → treated as ``None`` (logged once upstream)
    - any other non-numeric type   → treated as ``None``

    This function never raises.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
            return f if f == f else None  # reject NaN
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(v, str):
        # Empty string or obvious error-message prefix → not a number
        stripped = v.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except (TypeError, ValueError):
            return None
    return None


def _is_potentially_truncated_prop_id(prop_id: str) -> bool:
    """Return True if ``prop_id`` looks like it was truncated by a CSV-quoting problem.

    Flownex PropertyIdentifier values often use the form::

        {Flow Element Results,Upstream}Total pressure

    The comma inside the curly braces means the field MUST be double-quoted in
    the CSV file.  If the field was NOT quoted, ``csv.DictReader`` splits at the
    comma and the PropertyIdentifier is silently truncated to something like::

        {Flow Element Results

    We detect this by checking for an opening ``{`` that is never closed.
    """
    if not prop_id:
        return False
    return "{" in prop_id and "}" not in prop_id


def _enumish_to_str(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "value"):
        return str(v.value)
    return str(v)


def _normalize(s: Any) -> str:
    return "".join(str(s or "").split()).lower()


# ---------------------------------------------------------------------------
# Lazy imports / singletons
# ---------------------------------------------------------------------------

def _get_api() -> Any:
    global _api
    if _api is None:
        try:
            from omnicool.webapp.backend.fnx_api import FNXApi  # noqa: PLC0415
            _api = FNXApi()
        except Exception as exc:  # noqa: BLE001
            log.info("[flownex_bridge] FNXApi not available: %s", exc)
    return _api


def _get_io() -> Any:
    global _io
    if _io is None:
        try:
            from omnicool.webapp.backend.fnx_io_definition import FlownexIO  # noqa: PLC0415
            _io = FlownexIO()
        except Exception as exc:  # noqa: BLE001
            log.info("[flownex_bridge] FlownexIO not available: %s", exc)
    return _io


def reset_singletons(api: Any = None, io: Any = None) -> None:
    global _api, _io
    _api = api
    _io = io


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _input_def_to_dict(inp: Any) -> Dict[str, Any]:
    return {
        "key": str(getattr(inp, "Key", "") or ""),
        "description": str(getattr(inp, "Description", "") or ""),
        "componentIdentifier": str(getattr(inp, "ComponentIdentifier", "") or ""),
        "propertyIdentifier": str(getattr(inp, "PropertyIdentifier", "") or ""),
        "editType": _enumish_to_str(getattr(inp, "EditType", "")),
        "min": _safe_float(getattr(inp, "Min", None)),
        "max": _safe_float(getattr(inp, "Max", None)),
        "step": _safe_float(getattr(inp, "Step", None)),
        "unit": str(getattr(inp, "Unit", "") or ""),
        "defaultValue": getattr(inp, "DefaultValue", None),
    }


def _output_def_to_dict(out: Any) -> Dict[str, Any]:
    return {
        "key": str(getattr(out, "Key", "") or ""),
        "description": str(getattr(out, "Description", "") or ""),
        "componentIdentifier": str(getattr(out, "ComponentIdentifier", "") or ""),
        "propertyIdentifier": str(getattr(out, "PropertyIdentifier", "") or ""),
        "unit": str(getattr(out, "Unit", "") or ""),
        "category": str(getattr(out, "Category", "") or ""),
    }


# ---------------------------------------------------------------------------
# Current config helpers
# ---------------------------------------------------------------------------

def _current_project_path() -> str:
    io = _get_io()
    if io is None:
        return ""
    try:
        return str(getattr(io.Setup, "FlownexProject", "") or "")
    except Exception:
        return ""


def _current_io_dir() -> str:
    io = _get_io()
    if io is None:
        return ""
    try:
        return str(getattr(io.Setup, "IOFileDirectory", "") or "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Definition caches
# ---------------------------------------------------------------------------

def _cache_input_defs(scope: str, items: List[Dict[str, Any]]) -> None:
    target = _dynamic_input_defs if scope == "dynamic" else _static_input_defs
    target.clear()

    for item in items:
        key = str(item.get("key", "") or "")
        if not key:
            continue
        target[key] = item
        if key not in _input_values[scope]:
            _input_values[scope][key] = item.get("defaultValue")


def _cache_output_defs(items: List[Dict[str, Any]]) -> None:
    _output_defs.clear()
    for item in items:
        key = str(item.get("key", "") or "")
        if not key:
            continue
        _output_defs[key] = item
        _output_values.setdefault(key, None)


def _get_input_def(scope: str, key: str) -> Optional[Dict[str, Any]]:
    if scope == "dynamic" and key not in _dynamic_input_defs:
        load_inputs()
    if scope == "static" and key not in _static_input_defs:
        load_static_inputs()

    defs = _dynamic_input_defs if scope == "dynamic" else _static_input_defs
    return defs.get(key)


def _get_output_defs() -> Dict[str, Dict[str, Any]]:
    if not _output_defs:
        load_outputs()
    return _output_defs


# ---------------------------------------------------------------------------
# Flownex property set / get helpers
# ---------------------------------------------------------------------------

def _set_property_from_definition(defn: Dict[str, Any], value: Any) -> None:
    """
    Uses the real FNXApi methods only.
    Unit handling remains separated in fnx_api.py / fnx_units.py.
    """
    api = _get_api()
    if api is None or getattr(api, "AttachedProject", None) is None:
        return

    component = str(defn.get("componentIdentifier", "") or "")
    prop = str(defn.get("propertyIdentifier", "") or "")
    unit = str(defn.get("unit", "") or "")
    edit_type = str(defn.get("editType", "") or "").lower()

    if not component or not prop:
        return

    if edit_type == "checkbox":
        api.SetPropertyValue(component, prop, "1" if bool(value) else "0")
        return

    if unit:
        api.SetPropertyValueUnit(component, prop, float(value), unit)
    else:
        api.SetPropertyValue(component, prop, str(value))


def _read_output_from_definition(defn: Dict[str, Any]) -> Optional[float]:
    """Read a single output value from the vendor API and return a safe float.

    The vendor ``GetPropertyValueUnit`` method is known to return error-message
    strings (e.g. ``"Error parsing property value: unknown unit group ..."``
    instead of ``None``) when unit conversion fails.  We must normalize those
    values here, in our adapter layer, without modifying the vendor file.

    Returns:
        A finite ``float``, or ``None`` if the value is unavailable, invalid,
        or an error string.  Never raises.
    """
    api = _get_api()
    if api is None or getattr(api, "AttachedProject", None) is None:
        return None

    component = str(defn.get("componentIdentifier", "") or "")
    prop = str(defn.get("propertyIdentifier", "") or "")
    unit = str(defn.get("unit", "") or "")

    if not component or not prop:
        return None

    try:
        if unit:
            raw = api.GetPropertyValueUnit(component, prop, unit)
        else:
            raw = api.GetPropertyValue(component, prop)

        normalized = _normalize_output_value(raw)
        if normalized is None and raw is not None:
            # Vendor returned something non-numeric (e.g. an error string).
            log.warning(
                "[flownex_bridge] non-numeric vendor value for %s.%s: %r — treating as None",
                component, prop, raw,
            )
        return normalized
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] failed reading %s.%s: %s", component, prop, exc)
        return None


# ---------------------------------------------------------------------------
# Output → standard result name mapping
# ---------------------------------------------------------------------------

def _map_output_to_standard_result(defn: Dict[str, Any]) -> Optional[str]:
    try:
        from omnicool.webapp.backend.flownex_results import RESULT_ATTRS  # noqa: PLC0415
    except Exception:
        return None

    key_norm = _normalize(defn.get("key"))
    prop_norm = _normalize(defn.get("propertyIdentifier"))
    desc_norm = _normalize(defn.get("description"))

    for plain_name, info in RESULT_ATTRS.items():
        if key_norm == _normalize(plain_name):
            return plain_name
        if prop_norm == _normalize(info.get("fnx_prop")):
            return plain_name
        if prop_norm == _normalize(plain_name):
            return plain_name
        if desc_norm == _normalize(info.get("fnx_prop")):
            return plain_name
    return None


def _sync_outputs_to_usd(outputs: Dict[str, Any]) -> Dict[str, Any]:
    summary = {
        "updatedPrims": 0,
        "matchedComponents": 0,
        "skippedOutputs": 0,
    }

    if not outputs:
        return summary

    try:
        import omni.usd  # noqa: PLC0415
        from omnicool.webapp.backend.flownex_results import ensure_result_attrs, update_result_attrs  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        log.debug("[flownex_bridge] USD sync unavailable: %s", exc)
        return summary

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return summary

    component_to_values: Dict[str, Dict[str, Any]] = {}

    for key, value in outputs.items():
        defn = _output_defs.get(key)
        if not defn:
            summary["skippedOutputs"] += 1
            continue

        result_name = _map_output_to_standard_result(defn)
        if result_name is None or value is None:
            summary["skippedOutputs"] += 1
            continue

        component = str(defn.get("componentIdentifier", "") or "")
        if not component:
            summary["skippedOutputs"] += 1
            continue

        component_to_values.setdefault(component, {})[result_name] = value

    if not component_to_values:
        return summary

    summary["matchedComponents"] = len(component_to_values)

    for prim in stage.Traverse():
        try:
            if not prim.IsValid():
                continue
            attr = prim.GetAttribute("flownex:componentName")
            if not attr or not attr.IsValid():
                continue
            component_name = str(attr.Get() or "")
            if not component_name or component_name not in component_to_values:
                continue

            ensure_result_attrs(prim)
            update_result_attrs(prim, component_to_values[component_name])
            summary["updatedPrims"] += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("[flownex_bridge] Failed syncing results to prim %s: %s", prim.GetPath(), exc)

    return summary


def _append_history(outputs: Dict[str, Any]) -> None:
    entry = {"utc": _utc_now_iso(), **outputs}
    _simulation_data_history.append(entry)
    max_len = 500
    if len(_simulation_data_history) > max_len:
        del _simulation_data_history[:-max_len]


# ---------------------------------------------------------------------------
# Config / schema API
# ---------------------------------------------------------------------------

def get_status() -> Dict[str, Any]:
    api = _get_api()
    if api is None:
        return {
            "available": False,
            "projectAttached": False,
            "projectPath": "",
            "transientRunning": _transient_running,
        }

    try:
        available = bool(api.IsFnxAvailable())
        attached = getattr(api, "AttachedProject", None) is not None
        project_path = str(getattr(api, "ProjectFile", "") or "")
        return {
            "available": available,
            "projectAttached": attached,
            "projectPath": project_path,
            "transientRunning": _transient_running,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] get_status error: %s", exc)
        return {
            "available": False,
            "projectAttached": False,
            "projectPath": "",
            "transientRunning": _transient_running,
            "error": str(exc),
        }


def get_config() -> Dict[str, Any]:
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
            "resultPollingInterval": float(getattr(setup, "ResultPollingInterval", 1.0) or 1.0),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] get_config error: %s", exc)
        return {"error": str(exc)}


def set_config(patch: Dict[str, Any]) -> Dict[str, Any]:
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
            interval = max(0.1, float(patch["resultPollingInterval"]))
            setup.ResultPollingInterval = str(interval)

        io.Save()

        load_inputs()
        load_static_inputs()
        load_outputs()

        return get_config()
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] set_config error: %s", exc)
        return {"error": str(exc)}


def load_inputs() -> List[Dict[str, Any]]:
    io = _get_io()
    if io is None:
        _dynamic_input_defs.clear()
        return []

    try:
        items = io.LoadDynamicInputs() or []
        out = [_input_def_to_dict(i) for i in items]
        _cache_input_defs("dynamic", out)
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] load_inputs error: %s", exc)
        _dynamic_input_defs.clear()
        return []


def load_static_inputs() -> List[Dict[str, Any]]:
    io = _get_io()
    if io is None:
        _static_input_defs.clear()
        return []

    try:
        items = io.LoadStaticInputs() or []
        out = [_input_def_to_dict(i) for i in items]
        _cache_input_defs("static", out)
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] load_static_inputs error: %s", exc)
        _static_input_defs.clear()
        return []


def load_outputs() -> List[Dict[str, Any]]:
    io = _get_io()
    if io is None:
        _output_defs.clear()
        return []

    try:
        items = io.LoadOutputs() or []
        out = [_output_def_to_dict(o) for o in items]

        # Warn about outputs whose PropertyIdentifier looks truncated because
        # the Outputs.csv was not properly quoted.  Flownex PropertyIdentifier
        # values frequently contain commas inside curly braces, e.g.:
        #   {Flow Element Results,Upstream}Total pressure
        # That field MUST be double-quoted in the CSV.  Without quoting,
        # csv.DictReader splits at the comma and the identifier is silently
        # truncated (e.g. to "{Flow Element Results"), making the output
        # unreadable.
        for defn in out:
            prop_id = defn.get("propertyIdentifier", "")
            if _is_potentially_truncated_prop_id(prop_id):
                log.warning(
                    "[flownex_bridge] output %r has a PropertyIdentifier that looks "
                    "truncated (%r).  Check that Outputs.csv double-quotes fields "
                    "containing commas (e.g. \"{Flow Element Results,Upstream}...\").",
                    defn.get("key", "?"), prop_id,
                )

        _cache_output_defs(out)
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] load_outputs error: %s", exc)
        _output_defs.clear()
        return []


def get_schema() -> Dict[str, Any]:
    dyn = load_inputs() or []
    sta = load_static_inputs() or []
    # Tag each input definition with its scope so the frontend can send the
    # correct scope when calling set_input.  We do this in our wrapper layer
    # (not in the vendor definitions) to avoid modifying vendor files.
    for d in dyn:
        d["scope"] = "dynamic"
    for d in sta:
        d["scope"] = "static"
    return {
        "inputs": dyn + sta,
        "outputs": load_outputs() or [],
    }


# ---------------------------------------------------------------------------
# Session / project lifecycle
# ---------------------------------------------------------------------------

def open_flownex() -> Dict[str, Any]:
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}

    project_path = _current_project_path()
    if not project_path:
        return {"ok": False, "message": "No project path configured."}

    try:
        ok = bool(api.LaunchFlownexIfNeeded(project_path))
        return {
            "ok": ok,
            "message": f"Flownex ready for project: {project_path}" if ok else "Failed to launch or attach Flownex.",
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] open_flownex error: %s", exc)
        return {"ok": False, "message": str(exc)}


def open_project() -> Dict[str, Any]:
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}

    project_path = _current_project_path()
    if not project_path:
        return {"ok": False, "message": "No project path configured. Configure first."}

    try:
        api.AttachToProject(project_path)
        attached = getattr(api, "AttachedProject", None) is not None
        if attached:
            load_inputs()
            load_static_inputs()
            load_outputs()
            return {"ok": True, "message": f"Attached to project: {project_path}"}
        return {"ok": False, "message": f"Failed to attach to project: {project_path}"}
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] open_project error: %s", exc)
        return {"ok": False, "message": str(exc)}


def close_project() -> Dict[str, Any]:
    global _transient_running
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}

    try:
        api.CloseProject()
        _transient_running = False
        return {"ok": True, "message": "Project closed."}
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] close_project error: %s", exc)
        return {"ok": False, "message": str(exc)}


def exit_app() -> Dict[str, Any]:
    global _transient_running
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}

    try:
        api.ExitApplication()
        _transient_running = False
        return {"ok": True, "message": "Flownex closed."}
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] exit_app error: %s", exc)
        return {"ok": False, "message": str(exc)}


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def get_input_values() -> Dict[str, Dict[str, Any]]:
    return {
        "dynamic": dict(_input_values["dynamic"]),
        "static": dict(_input_values["static"]),
    }


def set_input_value(scope: str, key: str, value: Any) -> Dict[str, Any]:
    scope = str(scope or "").strip().lower()
    if scope not in ("dynamic", "static"):
        return {"ok": False, "message": f"Invalid scope: {scope!r}"}

    defn = _get_input_def(scope, key)
    if defn is None:
        return {"ok": False, "message": f"Unknown input key for scope {scope!r}: {key!r}"}

    _input_values[scope][key] = value

    try:
        if getattr(_get_api(), "AttachedProject", None) is not None:
            _set_property_from_definition(defn, value)
            return {"ok": True, "message": f"Set {scope} input {key!r} in Flownex."}
        return {"ok": True, "message": f"Cached {scope} input {key!r}; project not attached yet."}
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] set_input_value error for %s.%s: %s", scope, key, exc)
        return {"ok": False, "message": str(exc)}


def load_defaults() -> Dict[str, Any]:
    dyn = load_inputs()
    sta = load_static_inputs()

    for item in dyn:
        key = str(item.get("key", "") or "")
        if key:
            _input_values["dynamic"][key] = item.get("defaultValue")

    for item in sta:
        key = str(item.get("key", "") or "")
        if key:
            _input_values["static"][key] = item.get("defaultValue")

    if getattr(_get_api(), "AttachedProject", None) is not None:
        for key, value in _input_values["dynamic"].items():
            defn = _dynamic_input_defs.get(key)
            if defn is not None:
                _set_property_from_definition(defn, value)
        for key, value in _input_values["static"].items():
            defn = _static_input_defs.get(key)
            if defn is not None:
                _set_property_from_definition(defn, value)

    return {
        "ok": True,
        "message": "Loaded default inputs.",
        "inputs": get_input_values(),
    }


# ---------------------------------------------------------------------------
# Outputs / solve / history
# ---------------------------------------------------------------------------

def read_outputs() -> Dict[str, Any]:
    defs = _get_output_defs()
    outputs: Dict[str, Any] = {}

    if getattr(_get_api(), "AttachedProject", None) is None:
        return {
            "ok": False,
            "message": "No project attached.",
            "outputs": {},
            "usdSync": {"updatedPrims": 0, "matchedComponents": 0, "skippedOutputs": 0},
        }

    # Read each output independently so a single bad value never prevents the
    # rest from being broadcast.  _read_output_from_definition already logs a
    # warning for vendor error strings and returns None; we mirror that here
    # for unexpected per-key exceptions.
    read_errors: int = 0
    for key, defn in defs.items():
        try:
            outputs[key] = _read_output_from_definition(defn)
        except Exception as exc:  # noqa: BLE001
            log.warning("[flownex_bridge] read_outputs: skipping output %r due to error: %s", key, exc)
            outputs[key] = None
            read_errors += 1

    try:
        _output_values.update(outputs)
        _append_history(outputs)
        usd_sync = _sync_outputs_to_usd(outputs)

        msg = "Outputs refreshed."
        if read_errors:
            msg = f"Outputs refreshed ({read_errors} output(s) skipped due to read errors)."

        return {
            "ok": True,
            "message": msg,
            "outputs": dict(outputs),
            "usdSync": usd_sync,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] read_outputs error: %s", exc)
        return {
            "ok": False,
            "message": str(exc),
            "outputs": dict(outputs),
            "usdSync": {"updatedPrims": 0, "matchedComponents": 0, "skippedOutputs": 0},
        }


def run_steady() -> Dict[str, Any]:
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available", "outputs": {}}

    project_path = _current_project_path()
    if not project_path:
        return {"ok": False, "message": "No project configured.", "outputs": {}}

    if getattr(api, "AttachedProject", None) is None:
        api.AttachToProject(project_path)

    if getattr(api, "AttachedProject", None) is None:
        return {"ok": False, "message": "Could not attach to the configured Flownex project.", "outputs": {}}

    try:
        success = bool(api.RunSteadyStateSimulationBlocking())
        if not success:
            return {"ok": False, "message": "Steady-state simulation failed.", "outputs": {}}

        read_result = read_outputs()
        return {
            "ok": read_result.get("ok", True),
            "message": "Steady-state simulation completed.",
            "outputs": read_result.get("outputs", {}),
            "usdSync": read_result.get("usdSync", {}),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] run_steady error: %s", exc)
        return {"ok": False, "message": str(exc), "outputs": {}}


def load_defaults_and_run_steady() -> Dict[str, Any]:
    defaults_result = load_defaults()
    if not defaults_result.get("ok"):
        return {"ok": False, "message": defaults_result.get("message", "Failed loading defaults."), "outputs": {}}
    return run_steady()


# ---------------------------------------------------------------------------
# State snapshot
# ---------------------------------------------------------------------------

def get_state_snapshot() -> Dict[str, Any]:
    return {
        "connected_project": _current_project_path(),
        "io_directory": _current_io_dir(),
        "inputs": get_input_values(),
        "outputs": dict(_output_values),
        "history": list(_simulation_data_history),
        "transientRunning": _transient_running,
    }


def get_poll_interval() -> float:
    cfg = get_config()
    try:
        return max(0.1, float(cfg.get("resultPollingInterval", 1.0)))
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# Transient controls
# ---------------------------------------------------------------------------

def start_transient() -> Dict[str, Any]:
    global _transient_running
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}

    project_path = _current_project_path()
    if not project_path:
        return {"ok": False, "message": "No project configured."}

    if getattr(api, "AttachedProject", None) is None:
        api.AttachToProject(project_path)

    if getattr(api, "AttachedProject", None) is None:
        return {"ok": False, "message": "Could not attach to the configured Flownex project."}

    try:
        success = bool(api.StartTransientSimulation())
        _transient_running = success
        return {
            "ok": success,
            "message": "Transient simulation started." if success else "Failed to start transient simulation.",
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] start_transient error: %s", exc)
        _transient_running = False
        return {"ok": False, "message": str(exc)}


def stop_transient() -> Dict[str, Any]:
    global _transient_running
    api = _get_api()
    if api is None:
        return {"ok": False, "message": "Flownex API not available"}

    try:
        success = bool(api.StopTransientSimulation())
        _transient_running = False
        return {
            "ok": success,
            "message": "Transient simulation stopped." if success else "Failed to stop transient simulation.",
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[flownex_bridge] stop_transient error: %s", exc)
        _transient_running = False
        return {"ok": False, "message": str(exc)}


def is_transient_running() -> bool:
    return _transient_running
