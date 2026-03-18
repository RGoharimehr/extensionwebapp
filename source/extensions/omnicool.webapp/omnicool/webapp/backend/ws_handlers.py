"""WebSocket message dispatcher.

Translates incoming WebSocket JSON messages into USD stage operations,
delegating to the appropriate helper modules.  No Omniverse extension
lifecycle state is required — this is pure business logic.
"""
from __future__ import annotations

import json

import omni.usd

from omnicool.webapp.backend import flownex_attr_tools as _fat
from omnicool.webapp.backend import flownex_metadata as _fx
from omnicool.webapp.backend.usd_helpers import (
    _create_attr,
    _delete_attr,
    _filter_to_valid_usd_prims,
    _get_attr,
    _get_selected_prim_paths_async,
    _get_xform,
    _json_safe,
    _list_attrs,
    _list_children,
    _pick_prim_path,
    _prim_exists,
    _read_attribute_from_prim,
    _set_attr,
    _stage,
)


async def handle_ws_message(msg: str) -> dict:
    """
    Protocol:
    Request:  {"id":"123","type":"usd.get_attr","payload":{...}}
    Response: {"id":"123","ok":true,"payload":{...}} or {"ok":false,"error":"..."}
    """
    try:
        data = json.loads(msg)
    except Exception:
        return {"id": None, "ok": False, "error": "Invalid JSON"}

    req_id = data.get("id")
    typ = data.get("type")
    payload = data.get("payload") or {}

    try:
        stage = _stage()
        if stage is None:
            raise RuntimeError("No USD stage available")

        if typ == "usd.get_selection":
            ctx = omni.usd.get_context()
            sel = ctx.get_selection()
            paths = sel.get_selected_prim_paths() if sel else []
            return {
                "id": req_id,
                "ok": True,
                "payload": {"paths": list(paths)}
            }

        if typ == "usd.ping":
            return {"id": req_id, "ok": True, "payload": {"pong": True}}

        if typ == "usd.list_attrs":
            prim_path = payload.get("primPath", "")
            attrs = _list_attrs(stage, prim_path)
            return {"id": req_id, "ok": True, "payload": {"attrs": attrs}}

        if typ == "usd.prim_exists":
            prim_path = payload.get("primPath", "")
            return {"id": req_id, "ok": True, "payload": {"exists": _prim_exists(stage, prim_path)}}

        if typ == "usd.pick":
            norm_x = float(payload.get("x", 0.0))
            norm_y = float(payload.get("y", 0.0))
            prim_path = _pick_prim_path(norm_x, norm_y)
            return {"id": req_id, "ok": True, "payload": {"primPath": prim_path or None}}

        if typ == "usd.list_children":
            prim_path = payload.get("primPath", "/World")
            children = _list_children(stage, prim_path)
            return {"id": req_id, "ok": True, "payload": {"children": children}}

        if typ == "usd.get_attr":
            prim_path = payload.get("primPath", "")
            attr = payload.get("attr", "")
            try:
                val = _get_attr(stage, prim_path, attr)
                return {"id": req_id, "ok": True, "payload": {"value": _json_safe(val)}}
            except RuntimeError as exc:
                if "attribute not found" in str(exc).lower():
                    # Return null value so callers show "not found" gracefully.
                    return {"id": req_id, "ok": True, "payload": {"value": None}}
                raise

        if typ == "usd.set_attr":
            prim_path = payload.get("primPath", "")
            attr = payload.get("attr", "")
            value = payload.get("value", None)
            _set_attr(stage, prim_path, attr, value)
            return {"id": req_id, "ok": True, "payload": {"set": True}}

        if typ == "usd.create_attr":
            prim_path = payload.get("primPath", "")
            attr = payload.get("attr", "")
            type_name_str = payload.get("typeName", "float")
            value = payload.get("value", None)
            _create_attr(stage, prim_path, attr, type_name_str, value)
            return {"id": req_id, "ok": True, "payload": {"created": True}}

        if typ == "usd.delete_attr":
            prim_path = payload.get("primPath", "")
            attr = payload.get("attr", "")
            _delete_attr(stage, prim_path, attr)
            return {"id": req_id, "ok": True, "payload": {"deleted": True}}

        if typ == "usd.get_xform":
            prim_path = payload.get("primPath", "")
            mat = _get_xform(stage, prim_path)
            return {"id": req_id, "ok": True, "payload": {"matrix4x4": mat}}

        if typ == "usd.get_selected_attr":
            attr_full_name = payload.get("attr", "")
            if not attr_full_name:
                return {
                    "id": req_id,
                    "ok": False,
                    "error": "Missing required payload field: attr",
                }

            selection_source = payload.get("selectionSource", "all")
            wait_frames = int(payload.get("waitFrames", 2))
            allow_multiple = bool(payload.get("allowMultiple", False))
            time_code = payload.get("timeCode", None)

            raw_paths = await _get_selected_prim_paths_async(
                source=selection_source,
                wait_frames=wait_frames,
            )

            if not raw_paths:
                return {
                    "id": req_id,
                    "ok": True,
                    "payload": {
                        "primPaths": [],
                        "reason": "no_selection",
                    },
                }

            # Re-acquire stage after await in case it changed.
            stage_now = _stage()
            if stage_now is None:
                return {"id": req_id, "ok": False, "error": "No USD stage available"}

            usd_paths = _filter_to_valid_usd_prims(stage_now, raw_paths)
            if not usd_paths:
                return {
                    "id": req_id,
                    "ok": True,
                    "payload": {
                        "primPaths": [],
                        "reason": "selection_not_on_usd_stage",
                        "rawSelectionPaths": raw_paths,
                    },
                }

            if (not allow_multiple) and len(usd_paths) != 1:
                return {
                    "id": req_id,
                    "ok": True,
                    "payload": {
                        "primPaths": usd_paths,
                        "reason": "multiple_selection",
                    },
                }

            results = []
            for p in (usd_paths if allow_multiple else [usd_paths[0]]):
                prim = stage_now.GetPrimAtPath(p)
                if not prim or not prim.IsValid():
                    results.append({
                        "primPath": p,
                        "found": False,
                        "reason": "prim_invalid",
                        "attr": attr_full_name,
                    })
                    continue
                item = _read_attribute_from_prim(prim, attr_full_name, time_code=time_code)
                item["primPath"] = p
                item["primTypeName"] = str(prim.GetTypeName())
                results.append(item)

            return {
                "id": req_id,
                "ok": True,
                "payload": {
                    "primPaths": usd_paths if allow_multiple else [usd_paths[0]],
                    "results": results,
                },
            }

        # -----------------------------------------------------------------
        # Flownex controller metadata  (flownex.*)
        # All handlers resolve the prim from payload["primPath"].
        # -----------------------------------------------------------------
        if typ.startswith("flownex."):
            prim_path = payload.get("primPath", "")
            prim = stage.GetPrimAtPath(prim_path)
            if not prim.IsValid():
                return {"id": req_id, "ok": False, "error": f"Prim not found: {prim_path}"}

            if typ == "flownex.ensure_metadata":
                meta = _fx.ensure_controller_metadata(prim)
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.get_metadata":
                meta = _fx.get_controller_metadata(prim)
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.patch_metadata":
                patch = payload.get("patch", {})
                meta = _fx.patch_controller_metadata(prim, patch)
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.set_runtime_state":
                meta = _fx.set_runtime_state(
                    prim,
                    state=payload.get("state", "idle"),
                    lastAction=payload.get("lastAction"),
                    ok=payload.get("ok"),
                    message=payload.get("message"),
                )
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.set_intent_mode":
                meta = _fx.set_intent_mode(prim, payload.get("mode", "steady"))
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.set_steady_timeout":
                meta = _fx.set_steady_timeout_ms(prim, int(payload.get("timeoutMs", 120000)))
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.request_transient":
                meta = _fx.request_transient(prim, payload.get("action", "none"))
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.set_desired_property":
                meta = _fx.set_desired_property(
                    prim,
                    payload.get("componentIdentifier", ""),
                    payload.get("propertyIdentifier", ""),
                    str(payload.get("value", "")),
                    unit=payload.get("unit"),
                    value_type=payload.get("valueType", "string"),
                )
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.remove_desired_property":
                meta = _fx.remove_desired_property(
                    prim,
                    payload.get("componentIdentifier", ""),
                    payload.get("propertyIdentifier", ""),
                )
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.get_desired_properties":
                props = _fx.get_desired_properties(prim)
                return {"id": req_id, "ok": True, "payload": {"desiredProperties": props}}

            if typ == "flownex.set_observed_property":
                meta = _fx.set_observed_property(
                    prim,
                    payload.get("componentIdentifier", ""),
                    payload.get("propertyIdentifier", ""),
                    payload.get("value"),
                )
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.get_observed_properties":
                props = _fx.get_observed_properties(prim)
                return {"id": req_id, "ok": True, "payload": {"observedProperties": props}}

            if typ == "flownex.enqueue_command":
                cmd_id = _fx.enqueue_command(
                    prim,
                    payload.get("op", ""),
                    args=payload.get("args"),
                )
                return {"id": req_id, "ok": True, "payload": {"cmdId": cmd_id}}

            if typ == "flownex.list_commands":
                cmds = _fx.list_commands(prim, status=payload.get("status"))
                return {"id": req_id, "ok": True, "payload": {"commands": cmds}}

            if typ == "flownex.mark_command_status":
                found = _fx.mark_command_status(
                    prim,
                    payload.get("cmdId", ""),
                    status=payload.get("status", "applied"),
                    error=payload.get("error"),
                )
                return {"id": req_id, "ok": True, "payload": {"found": found}}

            if typ == "flownex.pop_next_pending_command":
                cmd = _fx.pop_next_pending_command(prim)
                return {"id": req_id, "ok": True, "payload": {"command": cmd}}

            if typ == "flownex.get_parameters":
                params = _fx.get_parameters(prim)
                return {"id": req_id, "ok": True, "payload": {"parameters": params}}

            if typ == "flownex.set_parameter_value":
                meta = _fx.set_parameter_value(
                    prim,
                    payload.get("key", ""),
                    payload.get("value"),
                )
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.get_parameter_value":
                val = _fx.get_parameter_value(prim, payload.get("key", ""))
                return {"id": req_id, "ok": True, "payload": {"value": val}}

            if typ == "flownex.load_parameter_table_rows":
                meta = _fx.load_parameter_table_rows(prim, payload.get("rows", []))
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.sync_parameters":
                meta = _fx.sync_parameters_to_desired_properties(prim)
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            return {"id": req_id, "ok": False, "error": f"Unknown flownex type: {typ}"}

        # -----------------------------------------------------------------
        # Flownex stage-wide tools  (flownex_tools.*)
        # These handlers do NOT require a primPath — they work on the whole
        # stage (or a sub-tree) and delegate to flownex_attr_tools.
        # -----------------------------------------------------------------
        if typ == "flownex_tools.deinstance_and_add_flownex":
            root = payload.get("root", "/World")
            summary = _fat.deinstance_and_add_flownex(root)
            return {"id": req_id, "ok": True, "payload": {"summary": summary}}

        return {"id": req_id, "ok": False, "error": f"Unknown type: {typ}"}

    except Exception as e:
        return {"id": req_id, "ok": False, "error": str(e)}
