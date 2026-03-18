import os
import json
import threading
import webbrowser
import asyncio
import functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import omni.ext
import omni.kit.app
import carb
import omni.kit.viewport.utility as vp_utils
import omni.usd
from pxr import UsdGeom, Sdf, Gf, Usd, Tf

from omnicool.webapp.backend import flownex_metadata as _fx
from omnicool.webapp.backend import flownex_attr_tools as _fat
from omnicool.webapp.transport.webrtc_server import WebRTCSignalingServer


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
    Uses SourceType.ALL to include both native USD and Fabric-backed selection.
    Works for Kit App Template and Kit CAE streaming.
    """
    ctx = omni.usd.get_context()
    sel = ctx.get_selection() if ctx else None
    if not sel:
        return []
    try:
        paths = list(sel.get_selected_prim_paths(omni.usd.Selection.SourceType.ALL))
    except TypeError:
        # Backward-compat: some environments may not support the source parameter.
        paths = list(sel.get_selected_prim_paths())
    return [str(p) for p in paths if p]


def _filter_to_valid_usd_prims(stage: "Usd.Stage", prim_paths: list) -> list:
    """
    When SourceType.ALL is used, results can include Fabric-only paths that don't
    resolve to a valid prim on the USD stage. Keep only USD-valid prims.
    """
    out = []
    for p in prim_paths:
        try:
            prim = stage.GetPrimAtPath(p)
        except Exception:
            continue
        if prim and prim.IsValid():
            out.append(p)
    return out


def _selection_source_from_string(source: str):
    """Map a string token ('usd'/'fabric'/'all') to the SourceType enum."""
    source = (source or "all").strip().lower()
    if source == "usd":
        return omni.usd.Selection.SourceType.USD
    if source == "fabric":
        return omni.usd.Selection.SourceType.FABRIC
    return omni.usd.Selection.SourceType.ALL


async def _get_selected_prim_paths_async(
    *,
    source: str = "all",
    wait_frames: int = 2,
) -> list:
    """
    Read selected prim paths with a small frame-wait retry to mitigate selection
    propagation races (UI events and network messages arriving in the same frame).
    """
    ctx = omni.usd.get_context()
    sel = ctx.get_selection() if ctx else None
    if not sel:
        return []

    src_enum = _selection_source_from_string(source)

    for attempt in range(max(0, int(wait_frames)) + 1):
        try:
            paths = list(sel.get_selected_prim_paths(src_enum))
        except TypeError:
            paths = list(sel.get_selected_prim_paths())

        paths = [str(p) for p in paths if p]
        if paths:
            return paths

        if attempt < wait_frames:
            await omni.kit.app.get_app().next_update_async()

    return []


def _usd_value_to_json(value):
    """
    Convert common pxr/USD Python types into JSON-serializable values.
    Handles Vec*, Matrix*, Vt arrays, paths, tokens, and scalar types.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    # Common scalar pxr types
    if isinstance(value, (Sdf.Path, Sdf.AssetPath)):
        return str(value)
    try:
        if isinstance(value, Tf.Token):
            return str(value)
    except Exception:
        pass

    # Gf vector/quaternion types
    try:
        if isinstance(value, (
            Gf.Vec2f, Gf.Vec3f, Gf.Vec4f,
            Gf.Vec2d, Gf.Vec3d, Gf.Vec4d,
            Gf.Vec2i, Gf.Vec3i, Gf.Vec4i,
            Gf.Quatf, Gf.Quatd,
        )):
            return [float(x) for x in value]
    except Exception:
        pass

    # Gf matrix types -> nested lists
    try:
        if isinstance(value, (Gf.Matrix2d, Gf.Matrix3d, Gf.Matrix4d)):
            return [[float(c) for c in row] for row in value]
    except Exception:
        pass

    # Generic iterables: Vt arrays, lists, tuples, etc.
    try:
        if hasattr(value, "__iter__") and not isinstance(value, (bytes, bytearray)):
            return [_usd_value_to_json(v) for v in list(value)]
    except Exception:
        pass

    # Scalar fallback
    try:
        return float(value)
    except Exception:
        return str(value)


def _read_attribute_from_prim(prim, attr_full_name: str, *, time_code=None) -> dict:
    """
    Read a named attribute from a validated USD prim.
    attr_full_name must be the full token including namespace (e.g. 'physics:mass').
    Returns a structured dict with 'found', 'typeName', 'value', 'time' fields.
    """
    if not prim or not prim.IsValid():
        raise ValueError("Prim is invalid.")
    if not attr_full_name or not isinstance(attr_full_name, str):
        raise ValueError("attr_full_name must be a non-empty string.")

    if not prim.HasAttribute(attr_full_name):
        return {"found": False, "reason": "attribute_missing", "attr": attr_full_name}

    attr = prim.GetAttribute(attr_full_name)
    if not attr or not attr.IsValid():
        return {"found": False, "reason": "attribute_missing", "attr": attr_full_name}

    type_name = attr.GetTypeName()
    type_str = str(type_name) if type_name else None

    if time_code is None:
        value = attr.Get()
        time_repr = "default"
    else:
        tc = Usd.TimeCode(float(time_code))
        value = attr.Get(tc)
        time_repr = float(time_code)

    return {
        "found": True,
        "attr": attr_full_name,
        "typeName": type_str,
        "time": time_repr,
        "value": _usd_value_to_json(value),
    }


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


_USD_VEC_TYPES = {
    "float2": Gf.Vec2f, "float3": Gf.Vec3f, "float4": Gf.Vec4f,
    "double2": Gf.Vec2d, "double3": Gf.Vec3d, "double4": Gf.Vec4d,
    "half2": Gf.Vec2h, "half3": Gf.Vec3h, "half4": Gf.Vec4h,
    "int2": Gf.Vec2i, "int3": Gf.Vec3i, "int4": Gf.Vec4i,
    "color3f": Gf.Vec3f, "color4f": Gf.Vec4f,
    "color3d": Gf.Vec3d, "color4d": Gf.Vec4d,
    "normal3f": Gf.Vec3f, "normal3d": Gf.Vec3d,
    "point3f": Gf.Vec3f, "point3d": Gf.Vec3d,
    "vector3f": Gf.Vec3f, "vector3d": Gf.Vec3d,
    "texCoord2f": Gf.Vec2f, "texCoord3f": Gf.Vec3f,
    "matrix2d": Gf.Matrix2d, "matrix3d": Gf.Matrix3d, "matrix4d": Gf.Matrix4d,
    "quatf": Gf.Quatf, "quatd": Gf.Quatd,
}


def _coerce_value_for_attr(attr, value):
    """Convert a JSON-decoded value to the correct Python/USD type for the attribute."""
    if value is None:
        return value
    try:
        type_name = attr.GetTypeName()
        if not type_name:
            return value
        type_str = str(type_name)
        if type_str in ("float", "double", "half"):
            return float(value)
        if type_str in ("int", "int64", "uint", "uint64", "uchar"):
            return int(value)
        if type_str == "bool":
            return bool(value)
        if type_str in ("string", "token", "asset"):
            return str(value)
        if isinstance(value, (list, tuple)):
            gf_type = _USD_VEC_TYPES.get(type_str)
            if gf_type:
                return gf_type(*value)
    except Exception:
        pass
    return value


def _set_attr(stage, prim_path: str, attr_name: str, value):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr:
        raise RuntimeError(f"Attribute not found: {attr_name}")
    coerced = _coerce_value_for_attr(attr, value)
    ok = attr.Set(coerced)
    if not ok:
        raise RuntimeError("USD attr.Set returned False")
    return True


def _create_attr(stage, prim_path: str, attr_name: str, type_name_str: str, value=None):
    """Create a new attribute on a prim with the given SdfValueTypeName string."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    sdf_type = Sdf.ValueTypeNames.Find(type_name_str)
    if not sdf_type:
        raise RuntimeError(f"Unknown USD type name: {type_name_str}")
    attr = prim.CreateAttribute(attr_name, sdf_type)
    if not attr:
        raise RuntimeError(f"Failed to create attribute: {attr_name}")
    if value is not None:
        coerced = _coerce_value_for_attr(attr, value)
        attr.Set(coerced)
    return True


def _delete_attr(stage, prim_path: str, attr_name: str):
    """Remove an attribute from a prim."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr:
        raise RuntimeError(f"Attribute not found: {attr_name}")
    prim.RemoveProperty(attr_name)
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

    Tries hardware raycast picking via omni.kit.raycast.query when the viewport
    is available.  Falls back to returning the first currently-selected prim so
    the workflow "select a prim, then hold I + click to inspect it" always works
    even when GPU picking is unavailable (e.g., headless or viewer mode).

    Returns the prim path string or "" if nothing is found.
    """
    try:
        vp = vp_utils.get_active_viewport_window()
        if vp is not None:
            try:
                w, h = vp.get_texture_resolution()
            except Exception:
                w, h = 0, 0
            if w and h:
                px = int(norm_x * w)
                # y from top -> bottom-origin for Kit's picking API
                py_flipped = int((1.0 - norm_y) * h)
                import importlib
                for api in ("omni.kit.raycast.query",):
                    try:
                        mod = importlib.import_module(api)
                        pick_fn = getattr(mod, "pick_prim", None)
                        if pick_fn is not None:
                            hit = pick_fn(px, py_flipped)
                            if hit and getattr(hit, "prim_path", None):
                                return str(hit.prim_path)
                            # Also try top-origin coords in case API differs
                            hit = pick_fn(px, int(norm_y * h))
                            if hit and getattr(hit, "prim_path", None):
                                return str(hit.prim_path)
                    except Exception:
                        pass
    except Exception as e:
        carb.log_warn(f"[omnicool.webapp][pick] viewport pick failed: {e}")

    # Reliable fallback: return the first currently selected prim.
    # The documented user workflow is to select a prim first and then
    # trigger the HUD gesture, so this covers the common case.
    paths = _get_selection_paths()
    return paths[0] if paths else ""

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

        # WebRTC signaling server state
        self._webrtc_server: WebRTCSignalingServer | None = None
        self._webrtc_task = None

        settings = carb.settings.get_settings()
        base = "/exts/omnicool.webapp"
        self._auto = bool(settings.get(f"{base}/autoLaunch") or True)
        self._open_browser = bool(settings.get(f"{base}/openBrowser") or True)

        self._host = str(settings.get(f"{base}/host") or "127.0.0.1")
        self._port = int(settings.get(f"{base}/port") or 3001)
        self._web_root_rel = str(settings.get(f"{base}/webRoot") or "data/webapp")

        self._ws_host = str(settings.get(f"{base}/wsHost") or "127.0.0.1")
        self._ws_port = int(settings.get(f"{base}/wsPort") or 8899)

        self._webrtc_enabled = bool(settings.get(f"{base}/webrtcEnabled") or False)
        self._webrtc_host = str(settings.get(f"{base}/webrtcHost") or "127.0.0.1")
        self._webrtc_port = int(settings.get(f"{base}/webrtcPort") or 8900)

        mgr = omni.kit.app.get_app().get_extension_manager()
        ext_path = mgr.get_extension_path(ext_id)
        self._web_root = os.path.join(ext_path, self._web_root_rel)

        carb.log_info(f"[omnicool.webapp] web_root={self._web_root}")
        carb.log_info(f"[omnicool.webapp] http=http://{self._host}:{self._port}")
        carb.log_info(f"[omnicool.webapp] ws=ws://{self._ws_host}:{self._ws_port}")
        carb.log_info(f"[omnicool.webapp] webrtc enabled={self._webrtc_enabled} "
                      f"http://{self._webrtc_host}:{self._webrtc_port}")

        if self._auto:
            self._start_http()
            self._start_ws()
            if self._webrtc_enabled:
                self._start_webrtc()

    def on_shutdown(self):
        self._stop_webrtc()
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

        handler = functools.partial(_StaticHandler, directory=self._web_root)
        self._httpd = ThreadingHTTPServer((self._host, self._port), handler)

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

    # -----------------
    # WebRTC signaling (aiortc — pure Python, same process as Kit)
    # -----------------
    def _start_webrtc(self):
        """Start the aiortc-based WebRTC signaling server in Kit's asyncio loop."""
        if self._webrtc_task:
            return

        async def _run():
            try:
                self._webrtc_server = WebRTCSignalingServer(
                    message_handler=self._handle_ws_message
                )
                await self._webrtc_server.start(
                    host=self._webrtc_host, port=self._webrtc_port
                )
                carb.log_info(
                    f"[omnicool.webapp][webrtc] signaling server started — "
                    f"POST http://{self._webrtc_host}:{self._webrtc_port}/webrtc/offer"
                )
                await asyncio.Future()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                carb.log_error(f"[omnicool.webapp][webrtc] server failed: {e}")
            finally:
                if self._webrtc_server:
                    await self._webrtc_server.stop()
                    self._webrtc_server = None

        loop = asyncio.get_event_loop()
        self._webrtc_task = loop.create_task(_run())

    def _stop_webrtc(self):
        if self._webrtc_task:
            try:
                self._webrtc_task.cancel()
            except Exception:
                pass
            self._webrtc_task = None

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

            # ✅ NEW: list available attribute names
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
                    msg = str(exc).lower()
                    if "attribute not found" in msg:
                        # Return null value so the HUD shows "not_found" gracefully
                        # instead of bubbling an error that triggers stub fallbacks.
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

                # Stage guard (stage already validated above, but re-check after await)
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

                # Re-acquire stage after await in case it changed
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
