import os
import json
import threading
import webbrowser
import asyncio
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import omni.ext
import omni.kit.app
import carb
import omni.kit.viewport.utility as vp_utils
import omni.usd
from pxr import UsdGeom


# -----------------------------
# Static HTTP server (Method A)
# -----------------------------
class _StaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        carb.log_info("[omnicool.webapp][http] " + (fmt % args))


# -----------------------------
# USD helpers (runs on Kit thread)
# -----------------------------
def _stage():
    return omni.usd.get_context().get_stage()


def _get_selection_paths():
    """
    Omniverse-native "what user clicked/selected" source of truth.
    Works for Kit App Template and Kit CAE streaming.
    """
    sel = omni.usd.get_context().get_selection()
    return [str(p) for p in sel.get_selected_prim_paths()]


def _prim_exists(stage, prim_path: str) -> bool:
    if not prim_path:
        return False
    prim = stage.GetPrimAtPath(prim_path)
    return prim.IsValid()


def _list_children(stage, prim_path: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    return [str(p.GetPath()) for p in prim.GetChildren()]


def _list_attrs(stage, prim_path: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    return [a.GetName() for a in prim.GetAttributes()]


def _get_attr(stage, prim_path: str, attr_name: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr:
        raise RuntimeError(f"Attribute not found: {attr_name}")
    val = attr.Get()
    return val


def _set_attr(stage, prim_path: str, attr_name: str, value):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr:
        raise RuntimeError(f"Attribute not found: {attr_name}")

    # Best-effort type handling:
    # USD will coerce some basic python types automatically.
    ok = attr.Set(value)
    if not ok:
        raise RuntimeError("USD attr.Set returned False")
    return True


def _get_xform(stage, prim_path: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")

    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        raise RuntimeError(f"Prim is not Xformable: {prim_path}")

    # Local transform (not world). If you want world, we can add UsdGeom.XformCache.
    mat, _ = xformable.GetLocalTransformation()
    # Convert matrix to nested lists for JSON
    return [[float(mat[r][c]) for c in range(4)] for r in range(4)]



def _pick_prim_path(norm_x: float, norm_y: float) -> str:
    """
    Pick a prim in the active viewport using normalized coordinates [0..1].
    Returns prim path string or "" if nothing hit.
    """
    try:
        vp = vp_utils.get_active_viewport_window()
        if vp is None:
            return ""

        # Viewport pixel size
        w, h = vp.get_texture_resolution()
        if not w or not h:
            return ""

        px = int(norm_x * w)
        py = int(norm_y * h)

        # picking expects window coords (origin differs by API version).
        # We'll try common form: y from top -> convert to bottom origin.
        py_flipped = int((1.0 - norm_y) * h)

        # Try both ways to be robust across kit builds
        hit = picking.pick_prim(px, py_flipped)
        if not hit or not getattr(hit, "prim_path", None):
            hit = picking.pick_prim(px, py)

        prim_path = getattr(hit, "prim_path", "") or ""
        return str(prim_path)
    except Exception as e:
        carb.log_warn(f"[omnicool.webapp][pick] failed: {e}")
        return ""

def _json_safe(value):
    # Convert common USD / pxr types into JSON-serializable values
    try:
        # Many pxr types are iterable; try list(...) first
        if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
            return [_json_safe(v) for v in list(value)]
    except Exception:
        pass

    # Fallbacks
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value

    # pxr Vec/Matrix often stringify well
    try:
        return float(value)
    except Exception:
        pass

    return str(value)


# -----------------------------
# WebSocket server
# -----------------------------
async def _ensure_websockets_installed():
    """
    Tries to import websockets.
    If missing, attempts to install via omni.kit.pipapi (one-time).
    This keeps Method A for your web UI (no Node), but WS needs a python lib.
    """
    try:
        import websockets  # noqa: F401
        return
    except Exception:
        pass

    # Try runtime pip install (may require internet/proxy)
    try:
        import omni.kit.pipapi as pipapi
        carb.log_warn("[omnicool.webapp][ws] 'websockets' not found. Installing via pip...")
        pipapi.install("websockets==12.0")
        import websockets  # noqa: F401
        carb.log_info("[omnicool.webapp][ws] 'websockets' installed successfully.")
    except Exception as e:
        carb.log_error(
            "[omnicool.webapp][ws] Failed to import/install 'websockets'. "
            f"WS bridge will NOT start. Error: {e}"
        )
        raise


class OmnicoolWebAppExt(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        self._ext_id = ext_id

        # HTTP server state
        self._httpd = None
        self._http_thread = None

        # WS server state
        self._ws_server = None
        self._ws_task = None

        settings = carb.settings.get_settings()
        base = "/exts/omnicool.webapp"
        self._auto = bool(settings.get(f"{base}/autoLaunch") or True)
        self._open_browser = bool(settings.get(f"{base}/openBrowser") or True)

        self._host = str(settings.get(f"{base}/host") or "127.0.0.1")
        self._port = int(settings.get(f"{base}/port") or 3001)
        self._web_root_rel = str(settings.get(f"{base}/webRoot") or "data/webapp")

        self._ws_host = str(settings.get(f"{base}/wsHost") or "127.0.0.1")
        self._ws_port = int(settings.get(f"{base}/wsPort") or 8899)

        mgr = omni.kit.app.get_app().get_extension_manager()
        ext_path = mgr.get_extension_path(ext_id)
        self._web_root = os.path.join(ext_path, self._web_root_rel)

        carb.log_info(f"[omnicool.webapp] web_root={self._web_root}")
        carb.log_info(f"[omnicool.webapp] http=http://{self._host}:{self._port}")
        carb.log_info(f"[omnicool.webapp] ws=ws://{self._ws_host}:{self._ws_port}")

        if self._auto:
            self._start_http()
            self._start_ws()

    def on_shutdown(self):
        self._stop_ws()
        self._stop_http()

    # -----------------
    # HTTP
    # -----------------
    def _start_http(self):
        if self._httpd:
            return

        index_html = os.path.join(self._web_root, "index.html")
        if not os.path.isfile(index_html):
            carb.log_error(
                "[omnicool.webapp][http] index.html not found. "
                f"Expected: {index_html}. "
                "Copy your CRA build/ contents into data/webapp/."
            )
            return

        os.chdir(self._web_root)
        self._httpd = ThreadingHTTPServer((self._host, self._port), _StaticHandler)

        def _serve():
            carb.log_info(f"[omnicool.webapp][http] Serving http://{self._host}:{self._port}")
            try:
                self._httpd.serve_forever()
            except Exception as e:
                carb.log_error(f"[omnicool.webapp][http] Server error: {e}")

        self._http_thread = threading.Thread(target=_serve, daemon=True)
        self._http_thread.start()

        if self._open_browser:
            webbrowser.open(f"http://{self._host}:{self._port}")

    def _stop_http(self):
        if not self._httpd:
            return
        try:
            carb.log_info("[omnicool.webapp][http] Stopping server...")
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception as e:
            carb.log_warn(f"[omnicool.webapp][http] shutdown issue: {e}")
        finally:
            self._httpd = None
            self._http_thread = None

    # -----------------
    # WebSocket USD bridge
    # -----------------
    def _start_ws(self):
        # Start WS server in Kit's asyncio loop
        if self._ws_task:
            return

        async def _run():
            try:
                await _ensure_websockets_installed()
                import websockets

                async def handler(websocket):
                    carb.log_info("[omnicool.webapp][ws] client connected")
                    try:
                        async for msg in websocket:
                            resp = await self._handle_ws_message(msg)
                            await websocket.send(json.dumps(resp))
                    except Exception as e:
                        carb.log_warn(f"[omnicool.webapp][ws] client handler ended: {e}")
                    finally:
                        carb.log_info("[omnicool.webapp][ws] client disconnected")

                self._ws_server = await websockets.serve(handler, self._ws_host, self._ws_port)
                carb.log_info(f"[omnicool.webapp][ws] Serving ws://{self._ws_host}:{self._ws_port}")

                # Keep alive until cancelled
                await asyncio.Future()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                carb.log_error(f"[omnicool.webapp][ws] server failed: {e}")

        loop = asyncio.get_event_loop()
        self._ws_task = loop.create_task(_run())

    def _stop_ws(self):
        if self._ws_task:
            try:
                self._ws_task.cancel()
            except Exception:
                pass
            self._ws_task = None

        if self._ws_server:
            try:
                self._ws_server.close()
            except Exception:
                pass
            self._ws_server = None

    async def _handle_ws_message(self, msg: str):
        """
        Protocol:
        Request: {"id":"123","type":"usd.get_attr","payload":{...}}
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
            # Ensure stage exists
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

            # ✅ NEW: Omniverse-native selection query
            if typ == "usd.get_selection":
                paths = _get_selection_paths()
                return {"id": req_id, "ok": True, "payload": {"paths": paths}}

            # ✅ NEW: list available attribute names
            if typ == "usd.list_attrs":
                prim_path = payload.get("primPath", "")
                attrs = _list_attrs(stage, prim_path)
                return {"id": req_id, "ok": True, "payload": {"attrs": attrs}}

            if typ == "usd.prim_exists":
                prim_path = payload.get("primPath", "")
                return {"id": req_id, "ok": True, "payload": {"exists": _prim_exists(stage, prim_path)}}

            if typ == "usd.list_children":
                prim_path = payload.get("primPath", "/World")
                children = _list_children(stage, prim_path)
                return {"id": req_id, "ok": True, "payload": {"children": children}}

            if typ == "usd.get_attr":
                prim_path = payload.get("primPath", "")
                attr = payload.get("attr", "")
                val = _get_attr(stage, prim_path, attr)
                return {"id": req_id, "ok": True, "payload": {"value": _json_safe(val)}}

            if typ == "usd.set_attr":
                prim_path = payload.get("primPath", "")
                attr = payload.get("attr", "")
                value = payload.get("value", None)
                _set_attr(stage, prim_path, attr, value)
                return {"id": req_id, "ok": True, "payload": {"set": True}}

            if typ == "usd.get_xform":
                prim_path = payload.get("primPath", "")
                mat = _get_xform(stage, prim_path)
                return {"id": req_id, "ok": True, "payload": {"matrix4x4": mat}}

            return {"id": req_id, "ok": False, "error": f"Unknown type: {typ}"}

        except Exception as e:
            return {"id": req_id, "ok": False, "error": str(e)}
