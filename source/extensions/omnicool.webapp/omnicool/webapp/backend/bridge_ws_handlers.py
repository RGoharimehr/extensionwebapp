import json
import carb

from omnicool.webapp.backend import config_store
from omnicool.webapp.backend import flownex_bridge as bridge

_browse_callback = None


def set_browse_callback(cb):
    global _browse_callback
    _browse_callback = cb


def apply_saved_config():
    try:
        cfg = config_store.load_config()
        if not cfg:
            return

        bridge.set_config(cfg)
        carb.log_info("[bridge] applied saved config")
    except Exception as e:
        carb.log_warn(f"[bridge] failed to apply saved config: {e}")


async def handle_bridge_connect(ws):
    try:
        state = bridge.get_state_snapshot()
        await ws.send(json.dumps({
            "type": "state",
            "payload": state
        }))
    except Exception as e:
        carb.log_warn(f"[bridge] connect error: {e}")


async def handle_bridge_message(message: str, ws):
    try:
        data = json.loads(message)
        msg_type = data.get("type")
        payload = data.get("payload", {})
        msg_id = data.get("id")

        result = None

        # -------------------------------------
        # CONFIG / CONNECT
        # -------------------------------------
        if msg_type == "configure":
            project = payload.get("projectFile", "")
            io_dir = payload.get("ioDirectory", "")
            poll_interval = payload.get("resultPollingInterval", 1.0)

            cfg = {
                "flownexProject": project,
                "ioFileDirectory": io_dir,
                "resultPollingInterval": poll_interval,
            }

            config_store.save_config(cfg)
            bridge.set_config(cfg)

            result = {
                "status": "configured",
                "config": cfg,
            }

        elif msg_type == "open_flownex":
            result = bridge.open_flownex()

        elif msg_type == "close_flownex":
            result = bridge.exit_app()

        elif msg_type == "open_project":
            result = bridge.open_project()

        elif msg_type == "connect":
            open_app_result = bridge.open_flownex()
            open_project_result = bridge.open_project()
            result = {
                "status": "connected",
                "open_flownex": open_app_result,
                "open_project": open_project_result,
            }

        # -------------------------------------
        # INPUTS
        # -------------------------------------
        elif msg_type == "set_input":
            scope = payload.get("scope", "")
            key = payload.get("key", "")
            value = payload.get("value")
            result = bridge.set_input_value(scope, key, value)

        # -------------------------------------
        # SIMULATION
        # -------------------------------------
        elif msg_type == "run":
            result = bridge.run_steady()

        elif msg_type == "load_defaults":
            result = bridge.load_defaults()

        elif msg_type == "load_defaults_and_run":
            load_result = bridge.load_defaults()
            run_result = bridge.run_steady()
            result = {
                "status": "defaults_loaded_and_run",
                "load_defaults": load_result,
                "run_steady": run_result,
            }

        elif msg_type == "start_transient":
            result = bridge.start_transient()

        elif msg_type == "stop_transient":
            result = bridge.stop_transient()

        elif msg_type == "read_outputs":
            result = bridge.read_outputs()

        # -------------------------------------
        # STATE / SCHEMA
        # -------------------------------------
        elif msg_type == "get_state":
            result = bridge.get_state_snapshot()

        elif msg_type == "get_schema":
            result = {"schema": bridge.get_schema()}

        # -------------------------------------
        # FILE BROWSER
        # -------------------------------------
        elif msg_type == "browse_file":
            if _browse_callback:
                mode = payload.get("mode", "file")
                filters = payload.get("filters", [])
                path = await _browse_callback(mode, filters)
                result = {"path": path}
            else:
                result = {
                    "error": "Browse is not available in this environment. Paste path manually."
                }

        # -------------------------------------
        # MAPPING / USD
        # -------------------------------------
        elif msg_type == "generate_mapping_config":
            from omnicool.webapp.backend.flownex_attr_tools import generate_mapping_config
            generate_mapping_config()
            result = {"status": "mapping_generated"}

        elif msg_type == "prim_property_override":
            from omnicool.webapp.backend.flownex_attr_tools import add_flownex_attributes

            prim_path = payload.get("primPath")
            if prim_path:
                add_flownex_attributes(prim_path)
                result = {"status": "attribute_added", "primPath": prim_path}
            else:
                result = {"error": "missing primPath"}

        else:
            result = {"error": f"Unknown message type: {msg_type}"}

        response = {
            "type": "response",
            "payload": result,
        }
        if msg_id:
            response["id"] = msg_id

        await ws.send(json.dumps(response))

        try:
            state = bridge.get_state_snapshot()
            await ws.send(json.dumps({
                "type": "state",
                "payload": state
            }))
        except Exception as e:
            carb.log_warn(f"[bridge] failed to push state: {e}")

    except Exception as e:
        carb.log_error(f"[bridge] message handling failed: {e}")
        await ws.send(json.dumps({
            "type": "error",
            "payload": str(e)
        }))
