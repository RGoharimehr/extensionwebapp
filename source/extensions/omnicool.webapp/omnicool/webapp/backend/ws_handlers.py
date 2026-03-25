"""WebSocket message dispatcher.

Translates incoming WebSocket JSON messages into USD stage operations,
delegating to the appropriate helper modules. No Omniverse extension
lifecycle state is required — this is pure business logic.
"""
from __future__ import annotations

import json

from omnicool.webapp.backend import flownex_attr_tools as _fat
from omnicool.webapp.backend import flownex_bridge as _fb
from omnicool.webapp.backend import flownex_metadata as _fx
from omnicool.webapp.backend.usd_helpers import (
    _create_attr,
    _delete_attr,
    _get_attr,
    _get_selected_attr_results,
    _get_selection_paths,
    _get_xform,
    _json_safe,
    _list_attrs,
    _list_children,
    _pick_prim_path,
    _prim_exists,
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
        # -----------------------------------------------------------------
        # Legacy AppStream prim query message
        # Sent by the WebRTC HUD logic in App.js through the data channel:
        # {
        #   "type": "get_prim_property",
        #   "prim_path": "",
        #   "pick": {"x": 0.5, "y": 0.5}
        # }
        #
        # Mapping is read from USD:
        #   flownex:componentName
        #
        # Live values are also read from USD:
        #   flownex:volumetricFlowrate
        #   flownex:pressure
        #   flownex:temperature
        #   flownex:massFlowrate
        #   flownex:quality
        #   flownex:density
        #   flownex:T_Case
        #
        # Response:
        # {
        #   "type": "prim_property_result",
        #   "prim_path": "...",
        #   "component": "...",
        #   "outputs": {...}
        # }
        # -----------------------------------------------------------------
        if typ == "get_prim_property":
            stage = _stage()
            if stage is None:
                return {
                    "type": "prim_property_result",
                    "prim_path": None,
                    "component": None,
                    "outputs": {},
                    "error": "No USD stage available",
                }

            prim_path = str(data.get("prim_path", "") or "")
            pick = data.get("pick") or {}

            if not prim_path:
                try:
                    norm_x = float(pick.get("x", 0.0))
                    norm_y = float(pick.get("y", 0.0))
                    prim_path = _pick_prim_path(norm_x, norm_y) or ""
                except Exception:
                    prim_path = ""

            if not prim_path:
                return {
                    "type": "prim_property_result",
                    "prim_path": None,
                    "component": None,
                    "outputs": {},
                }

            component_name = None
            try:
                component_name = _get_attr(stage, prim_path, "flownex:componentName")
                component_name = _json_safe(component_name)
            except Exception:
                component_name = None

            usd_props = [
                "flownex:volumetricFlowrate",
                "flownex:pressure",
                "flownex:temperature",
                "flownex:massFlowrate",
                "flownex:quality",
                "flownex:density",
                "flownex:T_Case",
            ]

            outputs = {}
            for attr_name in usd_props:
                try:
                    val = _get_attr(stage, prim_path, attr_name)
                    if val is not None:
                        outputs[attr_name] = _json_safe(val)
                except Exception:
                    pass

            return {
                "type": "prim_property_result",
                "prim_path": prim_path,
                "component": component_name,
                "outputs": outputs,
            }

        # -----------------------------------------------------------------
        # Flownex bridge commands — no USD stage required
        # These must be dispatched before the stage guard below.
        # -----------------------------------------------------------------
        if typ == "flownex.get_status":
            return {"id": req_id, "ok": True, "payload": _fb.get_status()}

        if typ == "flownex.get_config":
            return {"id": req_id, "ok": True, "payload": _fb.get_config()}

        if typ == "flownex.set_config":
            result = _fb.set_config(payload)
            if "error" in result:
                return {"id": req_id, "ok": False, "error": result["error"]}
            return {"id": req_id, "ok": True, "payload": result}

        if typ == "flownex.load_inputs":
            return {"id": req_id, "ok": True, "payload": {"inputs": _fb.load_inputs()}}

        if typ == "flownex.load_static_inputs":
            return {"id": req_id, "ok": True, "payload": {"inputs": _fb.load_static_inputs()}}

        if typ == "flownex.load_outputs":
            return {"id": req_id, "ok": True, "payload": {"outputs": _fb.load_outputs()}}

        if typ == "flownex.get_schema":
            return {"id": req_id, "ok": True, "payload": _fb.get_schema()}

        if typ == "flownex.open_flownex":
            result = _fb.open_flownex()
            if result.get("ok"):
                return {"id": req_id, "ok": True, "payload": result}
            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to open Flownex"),
            }

        if typ == "flownex.open_project":
            result = _fb.open_project()
            if result.get("ok"):
                return {"id": req_id, "ok": True, "payload": result}
            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to open project"),
            }

        if typ == "flownex.close_project":
            result = _fb.close_project()
            if result.get("ok"):
                return {"id": req_id, "ok": True, "payload": result}
            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to close project"),
            }

        if typ == "flownex.close_app":
            result = _fb.exit_app()
            if result.get("ok"):
                return {"id": req_id, "ok": True, "payload": result}
            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to close application"),
            }

        if typ == "flownex.get_input_values":
            return {"id": req_id, "ok": True, "payload": _fb.get_input_values()}

        if typ == "flownex.get_state_snapshot":
            return {"id": req_id, "ok": True, "payload": _fb.get_state_snapshot()}

        if typ == "flownex.set_input_value":
            scope = payload.get("scope", "")
            key = payload.get("key", "")
            value = payload.get("value")
            result = _fb.set_input_value(scope, key, value)
            if result.get("ok"):
                return {"id": req_id, "ok": True, "payload": result}
            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to set input value"),
            }

        if typ == "flownex.load_defaults":
            result = _fb.load_defaults()
            if result.get("ok"):
                return {"id": req_id, "ok": True, "payload": result}
            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to load defaults"),
            }

        if typ == "flownex.run_steady":
            result = _fb.run_steady()
            if result.get("ok"):
                stage = _stage()
                outputs_result = _fb.read_outputs()
                outputs = outputs_result.get("outputs", {}) if outputs_result else {}

                if stage is not None and outputs:
                    from omnicool.webapp.backend.flownex_results import sync_flownex_outputs_to_usd
                    sync_flownex_outputs_to_usd(stage, outputs)

                return {"id": req_id, "ok": True, "payload": result}

            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to run steady-state simulation"),
            }

        if typ == "flownex.load_defaults_and_run_steady":
            result = _fb.load_defaults_and_run_steady()
            if result.get("ok"):
                return {"id": req_id, "ok": True, "payload": result}
            return {
                "id": req_id,
                "ok": False,
                "error": result.get(
                    "message",
                    "Failed to load defaults and run steady-state simulation",
                ),
            }

        if typ == "flownex.start_transient":
            result = _fb.start_transient()
            if result.get("ok"):
                return {"id": req_id, "ok": True, "payload": result}
            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to start transient simulation"),
            }

        if typ == "flownex.stop_transient":
            result = _fb.stop_transient()
            if result.get("ok"):
                return {"id": req_id, "ok": True, "payload": result}
            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to stop transient simulation"),
            }

        if typ == "flownex.read_outputs":
            result = _fb.read_outputs()
            if result.get("ok"):
                stage = _stage()
                if stage is not None:
                    from omnicool.webapp.backend.flownex_results import sync_flownex_outputs_to_usd
                    sync_flownex_outputs_to_usd(stage, result.get("outputs", {}))

                return {"id": req_id, "ok": True, "payload": result}

            return {
                "id": req_id,
                "ok": False,
                "error": result.get("message", "Failed to read outputs"),
            }

        # -----------------------------------------------------------------
        # USD-dependent commands (active stage required)
        # -----------------------------------------------------------------
        stage = _stage()
        if stage is None:
            raise RuntimeError("No USD stage available")

        if typ == "usd.get_selection":
            paths = _get_selection_paths()
            return {
                "id": req_id,
                "ok": True,
                "payload": {"paths": paths},
            }

        if typ == "usd.ping":
            return {"id": req_id, "ok": True, "payload": {"pong": True}}

        if typ == "usd.list_attrs":
            prim_path = payload.get("primPath", "")
            attrs = _list_attrs(stage, prim_path)
            return {"id": req_id, "ok": True, "payload": {"attrs": attrs}}

        if typ == "usd.prim_exists":
            prim_path = payload.get("primPath", "")
            return {
                "id": req_id,
                "ok": True,
                "payload": {"exists": _prim_exists(stage, prim_path)},
            }

        if typ == "usd.pick":
            norm_x = float(payload.get("x", 0.0))
            norm_y = float(payload.get("y", 0.0))
            prim_path = _pick_prim_path(norm_x, norm_y)
            return {
                "id": req_id,
                "ok": True,
                "payload": {"primPath": prim_path or None},
            }

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
            result = await _get_selected_attr_results(
                attr_full_name,
                selection_source=payload.get("selectionSource", "all"),
                wait_frames=int(payload.get("waitFrames", 2)),
                allow_multiple=bool(payload.get("allowMultiple", False)),
                time_code=payload.get("timeCode", None),
            )
            return {"id": req_id, **result}

        # -----------------------------------------------------------------
        # Visualization (reads values directly from USD attrs)
        # -----------------------------------------------------------------
        if typ == "visualize_property":
            from omnicool.webapp.backend.viz_utils import visualize_property_layer

            prop = payload.get("property", "")
            if not prop:
                return {
                    "id": req_id,
                    "ok": False,
                    "error": "Missing property",
                }

            try:
                result = visualize_property_layer(prop)
                return {
                    "id": req_id,
                    "ok": True,
                    "payload": {
                        "status": "visualized",
                        "property": prop,
                        "result": result,
                    },
                }
            except Exception as e:
                return {
                    "id": req_id,
                    "ok": False,
                    "error": str(e),
                }

        if typ == "flownex.deinstance_and_add":
            root = payload.get("root", "/World")
            msg_txt = _fat.deinstance_and_add_flownex(root=root)
            return {"id": req_id, "ok": True, "payload": {"message": msg_txt}}

        if typ == "flownex.map_outputs_to_prims":
            io_dir = payload.get("ioDir", "")
            outputs_filename = payload.get("outputsFilename", "Outputs.csv")
            root = payload.get("root", "/World")
            out_name = payload.get("outName", "FlownexMapping.json")
            msg_txt, out_path = _fat.map_outputs_to_prims(
                io_dir=io_dir,
                outputs_filename=outputs_filename,
                root=root,
                out_name=out_name,
            )
            return {
                "id": req_id,
                "ok": True,
                "payload": {"message": msg_txt, "outPath": out_path},
            }

        # -----------------------------------------------------------------
        # Flownex controller metadata (flownex.*)
        # All handlers below this point resolve the prim from payload["primPath"].
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
                    args=payload.get("args", {}),
                )
                return {"id": req_id, "ok": True, "payload": {"cmdId": cmd_id}}

            if typ == "flownex.list_commands":
                status = payload.get("status")
                cmds = _fx.list_commands(prim, status=status)
                return {"id": req_id, "ok": True, "payload": {"commands": cmds}}

            if typ == "flownex.mark_command_status":
                ok = _fx.mark_command_status(
                    prim,
                    payload.get("cmdId", ""),
                    status=payload.get("status", "pending"),
                    error=payload.get("error"),
                )
                return {"id": req_id, "ok": True, "payload": {"updated": ok}}

            if typ == "flownex.pop_next_pending_command":
                cmd = _fx.pop_next_pending_command(prim)
                return {"id": req_id, "ok": True, "payload": {"command": cmd}}

            if typ == "flownex.load_parameter_table_rows":
                rows = payload.get("rows", [])
                meta = _fx.load_parameter_table_rows(prim, rows)
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.upsert_parameter_def":
                meta = _fx.upsert_parameter_def(
                    prim,
                    key=payload.get("key", ""),
                    description=payload.get("description", ""),
                    componentIdentifier=payload.get("componentIdentifier", ""),
                    propertyIdentifier=payload.get("propertyIdentifier", ""),
                    unit=payload.get("unit", ""),
                    defaultValue=payload.get("defaultValue"),
                    value=payload.get("value"),
                    minValue=payload.get("minValue"),
                    maxValue=payload.get("maxValue"),
                    step=payload.get("step"),
                    group=payload.get("group"),
                    editType=payload.get("editType"),
                )
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.get_parameters":
                params = _fx.get_parameters(prim)
                return {"id": req_id, "ok": True, "payload": {"parameters": params}}

            if typ == "flownex.set_parameters":
                params = payload.get("parameters", {})
                meta = _fx.set_parameters(prim, params)
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.set_parameter_value":
                meta = _fx.set_parameter_value(
                    prim,
                    payload.get("key", ""),
                    payload.get("value"),
                )
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

            if typ == "flownex.get_parameter_value":
                value = _fx.get_parameter_value(prim, payload.get("key", ""))
                return {"id": req_id, "ok": True, "payload": {"value": value}}

            if typ == "flownex.sync_parameters_to_desired_properties":
                meta = _fx.sync_parameters_to_desired_properties(prim)
                return {"id": req_id, "ok": True, "payload": {"meta": meta}}

        return {"id": req_id, "ok": False, "error": f"Unknown message type: {typ}"}

    except Exception as exc:
        return {"id": req_id, "ok": False, "error": str(exc)}
