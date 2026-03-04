"""
USD customData-based metadata for a Flownex Controller "asset" prim.

Stored at:  prim.customData["omnicool:flownexController"]

Public API summary
------------------
Core read/write
  ensure_controller_metadata(prim)          -> dict  (init defaults if missing)
  get_controller_metadata(prim)             -> dict
  set_controller_metadata(prim, meta)
  patch_controller_metadata(prim, patch)    -> dict

Ready / runtime / cache snapshots
  set_ready_snapshot(prim, *, attachedProject, simulationController, networkBuilder)
  set_runtime_state(prim, *, state, lastAction, ok, message)
  set_last_run(prim, *, run_type, started_utc, ended_utc, duration_ms)
  set_cache_summary(prim, *, enabled, count, keys)

Intent
  set_intent_mode(prim, mode)
  set_steady_timeout_ms(prim, timeout_ms)
  request_transient(prim, action)           # "start" | "stop" | "none"

Desired / observed properties (Flownex component bindings)
  set_desired_property(prim, componentIdentifier, propertyIdentifier, value, *, unit, value_type)
  remove_desired_property(prim, componentIdentifier, propertyIdentifier)
  get_desired_properties(prim)              -> dict
  set_observed_property(prim, componentIdentifier, propertyIdentifier, value)
  get_observed_properties(prim)            -> dict

Command queue
  enqueue_command(prim, op, *, args)        -> cmd_id str
  list_commands(prim, status)               -> list
  mark_command_status(prim, cmd_id, *, status, error)  -> bool
  pop_next_pending_command(prim)            -> dict | None

Parameter table (UI definition + binding)
  load_parameter_table_rows(prim, rows)     -> dict  (loads from CSV/table rows)
  upsert_parameter_def(prim, *, key, ...)   -> dict
  get_parameters(prim)                      -> dict
  set_parameters(prim, parameters)          -> dict
  set_parameter_value(prim, key, value)     -> dict
  get_parameter_value(prim, key)            -> Any
  sync_parameters_to_desired_properties(prim) -> dict

Flownex adapter hooks
  apply_desired_properties_to_flownex(prim, flownex_api)
  refresh_observed_properties_from_flownex(prim, flownex_api)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pxr import Usd


# ---------------------------------------------------------------------------
# Constants / schema version
# ---------------------------------------------------------------------------

META_KEY = "omnicool:flownexController"
SCHEMA_VERSION = 1

RuntimeState = Literal["idle", "steady_running", "transient_running", "error"]
IntentMode = Literal["steady", "transient"]
CommandStatus = Literal["pending", "applied", "failed"]


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_prim(prim: Usd.Prim) -> None:
    if prim is None or not prim.IsValid():
        raise ValueError("prim is invalid")


def _as_dict(x: Any, name: str) -> Dict[str, Any]:
    if x is None:
        return {}
    if not isinstance(x, dict):
        raise TypeError(f"{name} must be a dict, got {type(x)}")
    return x


def _deepcopy_jsonish(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _deepcopy_jsonish(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deepcopy_jsonish(v) for v in obj]
    return obj


def _to_float(x: Any) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except Exception:
        return None


_GROUP_RE = re.compile(r"\{([^{}]+)\}")


def _extract_group(property_identifier: str) -> Optional[str]:
    """Return the last non-'Script' {Group} token from a propertyIdentifier string."""
    if not property_identifier:
        return None
    groups = _GROUP_RE.findall(property_identifier)
    filtered = [g.strip() for g in groups if g.strip().lower() != "script"]
    return filtered[-1] if filtered else None


# ---------------------------------------------------------------------------
# Default metadata structure
# ---------------------------------------------------------------------------

def default_flownex_controller_metadata() -> Dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,

        "ready": {
            "attachedProject": False,
            "simulationController": False,
            "networkBuilder": False,
            "lastCheckedUtc": None,
        },

        "intent": {
            "mode": "steady",
            "steady": {"timeoutMs": 120000},
            "transient": {"resetTimeBeforeStart": True, "requested": "none"},
        },

        # desiredProperties[componentId][propertyId] = {value, unit?, type?}
        "desiredProperties": {},

        # Action queue for decoupled control
        "commandQueue": [],

        # Read-back values from GetPropertyValue() for UI/debug
        "observedProperties": {},

        "runtime": {
            "state": "idle",
            "lastAction": None,
            "lastResult": None,
            "lastRun": None,
        },

        "cache": {
            "enabled": True,
            "count": 0,
        },

        # UI parameter definitions (key → definition + current value)
        "parameters": {},
    }


# ---------------------------------------------------------------------------
# Core prim read / write
# ---------------------------------------------------------------------------

def get_controller_metadata(prim: Usd.Prim) -> Dict[str, Any]:
    """Return the metadata dict at prim.customData[META_KEY], or {} if absent."""
    _require_prim(prim)
    cd = prim.GetCustomData() or {}
    raw = cd.get(META_KEY, None)
    if raw is None:
        return {}
    # Stored as JSON string to avoid USD type-inference issues with nested lists/dicts.
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return {}
        return _as_dict(data, f"customData[{META_KEY}]")
    # Fallback: accept pre-existing plain-dict format
    return _as_dict(raw, f"customData[{META_KEY}]")


def set_controller_metadata(prim: Usd.Prim, meta: Dict[str, Any]) -> None:
    """Overwrite prim.customData[META_KEY] with *meta* (serialised as a JSON string)."""
    _require_prim(prim)
    meta = _as_dict(meta, "meta")
    meta.setdefault("schemaVersion", SCHEMA_VERSION)
    cd = prim.GetCustomData() or {}
    cd[META_KEY] = json.dumps(meta)
    prim.SetCustomData(cd)


def ensure_controller_metadata(prim: Usd.Prim) -> Dict[str, Any]:
    """
    Ensure metadata exists on *prim*.  Creates defaults when absent.
    Also forward-fills any missing top-level keys added in later schema versions.
    Returns the current (possibly freshly created) metadata dict.
    """
    _require_prim(prim)
    meta = get_controller_metadata(prim)
    if not meta:
        meta = default_flownex_controller_metadata()
        set_controller_metadata(prim, meta)
    else:
        meta = _deepcopy_jsonish(meta)
        meta.setdefault("schemaVersion", SCHEMA_VERSION)
        for k, v in default_flownex_controller_metadata().items():
            meta.setdefault(k, _deepcopy_jsonish(v))
        set_controller_metadata(prim, meta)
    return meta


def patch_controller_metadata(prim: Usd.Prim, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow-merge *patch* into existing metadata (top-level keys only)."""
    _require_prim(prim)
    patch = _as_dict(patch, "patch")
    meta = ensure_controller_metadata(prim)
    meta.update(patch)
    set_controller_metadata(prim, meta)
    return meta


# ---------------------------------------------------------------------------
# Ready / runtime / cache helpers
# ---------------------------------------------------------------------------

def set_ready_snapshot(
    prim: Usd.Prim,
    *,
    attachedProject: bool,
    simulationController: bool,
    networkBuilder: bool,
) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    meta["ready"] = {
        "attachedProject": bool(attachedProject),
        "simulationController": bool(simulationController),
        "networkBuilder": bool(networkBuilder),
        "lastCheckedUtc": utc_now_iso(),
    }
    set_controller_metadata(prim, meta)
    return meta


def set_cache_summary(
    prim: Usd.Prim,
    *,
    enabled: bool,
    count: int,
    keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    cache = meta.get("cache", {})
    cache["enabled"] = bool(enabled)
    cache["count"] = int(count)
    if keys is not None:
        cache["keys"] = list(keys)
    meta["cache"] = cache
    set_controller_metadata(prim, meta)
    return meta


def set_runtime_state(
    prim: Usd.Prim,
    *,
    state: RuntimeState,
    lastAction: Optional[str] = None,
    ok: Optional[bool] = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    runtime = meta.get("runtime", {})
    runtime["state"] = state
    if lastAction is not None:
        runtime["lastAction"] = lastAction
    if ok is not None or message is not None:
        runtime["lastResult"] = {
            "ok": bool(ok) if ok is not None else False,
            "message": message or "",
            "utc": utc_now_iso(),
        }
    meta["runtime"] = runtime
    set_controller_metadata(prim, meta)
    return meta


def set_last_run(
    prim: Usd.Prim,
    *,
    run_type: IntentMode,
    started_utc: str,
    ended_utc: str,
    duration_ms: int,
) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    runtime = meta.get("runtime", {})
    runtime["lastRun"] = {
        "type": run_type,
        "startedUtc": started_utc,
        "endedUtc": ended_utc,
        "durationMs": int(duration_ms),
    }
    meta["runtime"] = runtime
    set_controller_metadata(prim, meta)
    return meta


# ---------------------------------------------------------------------------
# Intent helpers
# ---------------------------------------------------------------------------

def set_intent_mode(prim: Usd.Prim, mode: IntentMode) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    intent = meta.get("intent", {})
    intent["mode"] = mode
    meta["intent"] = intent
    set_controller_metadata(prim, meta)
    return meta


def set_steady_timeout_ms(prim: Usd.Prim, timeout_ms: int) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    intent = meta.get("intent", {})
    steady = intent.get("steady", {})
    steady["timeoutMs"] = int(timeout_ms)
    intent["steady"] = steady
    meta["intent"] = intent
    set_controller_metadata(prim, meta)
    return meta


def request_transient(prim: Usd.Prim, action: Literal["start", "stop", "none"]) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    intent = meta.get("intent", {})
    transient = intent.get("transient", {})
    transient["requested"] = action
    intent["transient"] = transient
    intent["mode"] = "transient"
    meta["intent"] = intent
    set_controller_metadata(prim, meta)
    return meta


# ---------------------------------------------------------------------------
# Desired / observed properties
# ---------------------------------------------------------------------------

def set_desired_property(
    prim: Usd.Prim,
    componentIdentifier: str,
    propertyIdentifier: str,
    value: str,
    *,
    unit: Optional[str] = None,
    value_type: str = "string",
) -> Dict[str, Any]:
    """Store the intended value to apply with SetPropertyValue()."""
    meta = ensure_controller_metadata(prim)
    desired = _as_dict(meta.get("desiredProperties", {}), "desiredProperties")
    comp = _as_dict(desired.get(componentIdentifier, {}), f"desiredProperties[{componentIdentifier}]")

    entry: Dict[str, Any] = {"value": str(value), "type": value_type}
    if unit:
        entry["unit"] = unit

    comp[propertyIdentifier] = entry
    desired[componentIdentifier] = comp
    meta["desiredProperties"] = desired
    set_controller_metadata(prim, meta)
    return meta


def remove_desired_property(
    prim: Usd.Prim,
    componentIdentifier: str,
    propertyIdentifier: str,
) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    desired = _as_dict(meta.get("desiredProperties", {}), "desiredProperties")
    comp = _as_dict(desired.get(componentIdentifier, {}), "component dict")

    comp.pop(propertyIdentifier, None)
    if not comp:
        desired.pop(componentIdentifier, None)
    else:
        desired[componentIdentifier] = comp

    meta["desiredProperties"] = desired
    set_controller_metadata(prim, meta)
    return meta


def get_desired_properties(prim: Usd.Prim) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    return _as_dict(meta.get("desiredProperties", {}), "desiredProperties")


def set_observed_property(
    prim: Usd.Prim,
    componentIdentifier: str,
    propertyIdentifier: str,
    value: Optional[str],
) -> Dict[str, Any]:
    """Store a snapshot from GetPropertyValue() for UI/debug."""
    meta = ensure_controller_metadata(prim)
    observed = _as_dict(meta.get("observedProperties", {}), "observedProperties")
    comp = _as_dict(observed.get(componentIdentifier, {}), "observed component dict")

    comp[propertyIdentifier] = {
        "value": None if value is None else str(value),
        "readUtc": utc_now_iso(),
    }
    observed[componentIdentifier] = comp
    meta["observedProperties"] = observed
    set_controller_metadata(prim, meta)
    return meta


def get_observed_properties(prim: Usd.Prim) -> Dict[str, Any]:
    meta = ensure_controller_metadata(prim)
    return _as_dict(meta.get("observedProperties", {}), "observedProperties")


# ---------------------------------------------------------------------------
# Command queue
# ---------------------------------------------------------------------------

def enqueue_command(
    prim: Usd.Prim,
    op: str,
    *,
    args: Optional[Dict[str, Any]] = None,
) -> str:
    """Add a command to commandQueue and return its id."""
    meta = ensure_controller_metadata(prim)
    q = meta.get("commandQueue", [])
    if not isinstance(q, list):
        q = []

    cmd_id = f"cmd-{uuid4().hex[:10]}"
    cmd = {
        "id": cmd_id,
        "op": op,
        "args": _as_dict(args, "args") if args is not None else {},
        "createdUtc": utc_now_iso(),
        "status": "pending",
        "error": None,
    }
    q.append(cmd)
    meta["commandQueue"] = q
    set_controller_metadata(prim, meta)
    return cmd_id


def list_commands(
    prim: Usd.Prim,
    status: Optional[CommandStatus] = None,
) -> List[Dict[str, Any]]:
    meta = ensure_controller_metadata(prim)
    q = meta.get("commandQueue", [])
    if not isinstance(q, list):
        return []
    if status is None:
        return list(q)
    return [c for c in q if isinstance(c, dict) and c.get("status") == status]


def mark_command_status(
    prim: Usd.Prim,
    cmd_id: str,
    *,
    status: CommandStatus,
    error: Optional[str] = None,
) -> bool:
    meta = ensure_controller_metadata(prim)
    q = meta.get("commandQueue", [])
    if not isinstance(q, list):
        return False

    for c in q:
        if isinstance(c, dict) and c.get("id") == cmd_id:
            c["status"] = status
            c["updatedUtc"] = utc_now_iso()
            c["error"] = error
            set_controller_metadata(prim, meta)
            return True
    return False


def pop_next_pending_command(prim: Usd.Prim) -> Optional[Dict[str, Any]]:
    """
    Return the next pending command without removing it.
    Typical flow:
      cmd = pop_next_pending_command(prim)
      # execute...
      mark_command_status(prim, cmd["id"], status="applied"/"failed")
    """
    pending = list_commands(prim, status="pending")
    return pending[0] if pending else None


# ---------------------------------------------------------------------------
# Parameter table  (UI definition + Flownex component/property binding)
# ---------------------------------------------------------------------------

def get_parameters(prim: Usd.Prim) -> Dict[str, Any]:
    """Return the parameters section of the metadata."""
    meta = ensure_controller_metadata(prim)
    return _as_dict(meta.get("parameters", {}), "parameters")


def set_parameters(prim: Usd.Prim, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Replace the entire parameters section."""
    meta = ensure_controller_metadata(prim)
    meta["parameters"] = _as_dict(parameters, "parameters")
    set_controller_metadata(prim, meta)
    return meta


def upsert_parameter_def(
    prim: Usd.Prim,
    *,
    key: str,
    description: str,
    componentIdentifier: str,
    propertyIdentifier: str,
    editType: str,
    min_val: Optional[float],
    max_val: Optional[float],
    step: Optional[float],
    unit: str,
    defaultValue: Optional[float],
    group: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert or update a single parameter definition."""
    meta = ensure_controller_metadata(prim)
    params = _as_dict(meta.get("parameters", {}), "parameters")

    if group is None:
        group = _extract_group(propertyIdentifier)

    # Preserve current value if already set; otherwise start at defaultValue
    old = params.get(key, {})
    if not isinstance(old, dict):
        old = {}
    current_value = old.get("value", defaultValue)

    params[key] = {
        "description": description,
        "componentIdentifier": componentIdentifier,
        "propertyIdentifier": propertyIdentifier,
        "editType": editType,
        "min": min_val,
        "max": max_val,
        "step": step,
        "unit": unit,
        "defaultValue": defaultValue,
        "group": group,
        "value": current_value,
    }

    meta["parameters"] = params
    set_controller_metadata(prim, meta)
    return meta


def load_parameter_table_rows(
    prim: Usd.Prim,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Load parameter definitions from a list of table-row dicts.

    Each row should have these keys (matching the CSV column names):
      Key, Description, ComponentIdentifier, PropertyIdentifier,
      EditType, Min, Max, Step, Unit, DefaultValue

    Example row::

        {
            "Key": "P_IT_rack",
            "Description": "Total Rack IT Load",
            "ComponentIdentifier": "Rack Power Script",
            "PropertyIdentifier": "{Script}Script...{Common Inputs}Total Rack IT Load",
            "EditType": "slider",
            "Min": 100, "Max": 250, "Step": 50,
            "Unit": "kW", "DefaultValue": 250,
        }
    """
    for r in rows:
        upsert_parameter_def(
            prim,
            key=str(r.get("Key", "")).strip(),
            description=str(r.get("Description", "")).strip(),
            componentIdentifier=str(r.get("ComponentIdentifier", "")).strip(),
            propertyIdentifier=str(r.get("PropertyIdentifier", "")).strip(),
            editType=str(r.get("EditType", "")).strip(),
            min_val=_to_float(r.get("Min")),
            max_val=_to_float(r.get("Max")),
            step=_to_float(r.get("Step")),
            unit=str(r.get("Unit", "")).strip(),
            defaultValue=_to_float(r.get("DefaultValue")),
            group=None,  # auto-extracted from {Group} in propertyIdentifier
        )
    return get_controller_metadata(prim)


def set_parameter_value(prim: Usd.Prim, key: str, value: Any) -> Dict[str, Any]:
    """Update parameters[key].value (as the UI would do on slider change)."""
    meta = ensure_controller_metadata(prim)
    params = _as_dict(meta.get("parameters", {}), "parameters")
    if key not in params or not isinstance(params[key], dict):
        raise KeyError(f"Unknown parameter key: {key!r}")

    v_num = _to_float(value)
    params[key]["value"] = v_num if v_num is not None else str(value)

    meta["parameters"] = params
    set_controller_metadata(prim, meta)
    return meta


def get_parameter_value(prim: Usd.Prim, key: str) -> Any:
    """Return parameters[key].value, falling back to defaultValue."""
    params = get_parameters(prim)
    if key not in params or not isinstance(params[key], dict):
        return None
    return params[key].get("value", params[key].get("defaultValue"))


def sync_parameters_to_desired_properties(prim: Usd.Prim) -> Dict[str, Any]:
    """
    Copy parameters[*].value into desiredProperties using each parameter's
    componentIdentifier / propertyIdentifier binding.

    Call this before apply_desired_properties_to_flownex() to ensure
    desiredProperties always reflects the current UI state.
    """
    meta = ensure_controller_metadata(prim)
    params = _as_dict(meta.get("parameters", {}), "parameters")

    for key, p in params.items():
        if not isinstance(p, dict):
            continue
        comp = p.get("componentIdentifier")
        prop = p.get("propertyIdentifier")
        if not comp or not prop:
            continue
        value = p.get("value", p.get("defaultValue"))
        if value is None:
            continue
        unit = p.get("unit") or None
        set_desired_property(
            prim,
            str(comp),
            str(prop),
            str(value),
            unit=str(unit) if unit else None,
            value_type="string",
        )

    return get_controller_metadata(prim)


# ---------------------------------------------------------------------------
# Flownex adapter hooks
# ---------------------------------------------------------------------------

def apply_desired_properties_to_flownex(prim: Usd.Prim, flownex_api: Any) -> None:
    """
    Call flownex_api.SetPropertyValue(componentId, propertyId, valueStr)
    for every entry in desiredProperties.
    Does not run a simulation — only applies settings.
    """
    desired = get_desired_properties(prim)
    for comp_id, props in desired.items():
        if not isinstance(props, dict):
            continue
        for prop_id, entry in props.items():
            if not isinstance(entry, dict):
                continue
            val = entry.get("value")
            if val is None:
                continue
            flownex_api.SetPropertyValue(comp_id, prop_id, str(val))
    set_runtime_state(
        prim,
        state="idle",
        lastAction="applyDesiredProperties",
        ok=True,
        message="Applied desiredProperties",
    )


def refresh_observed_properties_from_flownex(prim: Usd.Prim, flownex_api: Any) -> None:
    """
    Read all desiredProperties keys back from Flownex via GetPropertyValue()
    and store the results in observedProperties.
    """
    desired = get_desired_properties(prim)
    for comp_id, props in desired.items():
        if not isinstance(props, dict):
            continue
        for prop_id in props.keys():
            val = flownex_api.GetPropertyValue(comp_id, prop_id)
            set_observed_property(prim, comp_id, prop_id, val)
    set_runtime_state(
        prim,
        state="idle",
        lastAction="refreshObservedProperties",
        ok=True,
        message="Refreshed observedProperties",
    )
