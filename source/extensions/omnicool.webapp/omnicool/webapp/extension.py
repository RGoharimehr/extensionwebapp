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
from pxr import UsdGeom, Sdf, Gf

from omnicool.webapp import flownex_metadata as _fx
from omnicool.webapp.webrtc_server import WebRTCSignalingServer


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
# Viewport frame capture (WebRTC video source)
# -----------------------------

_capture_busy = False  # guard against re-entrant captures


async def _capture_viewport_frame_async():
    """
    Capture the current swapchain frame as an RGB numpy array.

    Schedules a GPU-side screenshot via ``omni.renderer.capture`` on the next
    render tick.  The render-thread callback resolves an asyncio ``Future``
    using ``loop.call_soon_threadsafe`` so the await is non-blocking.

    Returns an ``(H, W, 3)`` uint8 numpy array, or ``None`` if the capture
    timed out or failed (e.g. during startup before the first frame renders,
    or in headless mode without a renderer).

    A busy-flag prevents a queue of pending captures from building up when the
    renderer is slower than the WebRTC frame rate.
    """
    global _capture_busy
    if _capture_busy:
        return None
    _capture_busy = True
    try:
        import numpy as np
        import omni.renderer.capture as rc

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()

        def _on_capture(buf, buf_size, width, height, format_enum):
            if fut.done():
                return
            try:
                arr = np.frombuffer(buf, dtype=np.uint8).copy()
                # Omniverse swapchain is BGRA; rearrange channels to RGB for
                # aiortc which encodes frames as rgb24.
                arr = arr[: width * height * 4].reshape(height, width, 4)[:, :, [2, 1, 0]]
                loop.call_soon_threadsafe(fut.set_result, arr)
            except Exception as exc:
                loop.call_soon_threadsafe(fut.set_exception, exc)

        iface = rc.acquire_renderer_capture_interface()
        iface.capture_next_frame_swapchain_async(_on_capture)
        return await asyncio.wait_for(fut, timeout=1.0)
    except asyncio.TimeoutError:
        carb.log_warn("[omnicool.webapp][webrtc] viewport capture timed out — sending placeholder frame")
        return None
    except Exception as exc:
        carb.log_warn(f"[omnicool.webapp][webrtc] viewport capture failed: {exc}")
        return None
    finally:
        _capture_busy = False


# -----------------------------
# Desktop / window frame capture (WebRTC fallback for non-Kit environments)
# -----------------------------

def _get_window_region(title: str):
    """
    Return an mss-style region dict ``{top, left, width, height}`` for the
    first window whose title contains *title* (case-insensitive), or ``None``
    if the window cannot be located.

    Platform support:
    - Windows — ``win32gui`` (pywin32)
    - Linux   — ``xdotool`` CLI utility
    - macOS   — ``osascript`` / AppleScript (requires Accessibility permission)
    """
    if not title:
        return None

    import sys

    if sys.platform == "win32":
        try:
            import win32gui  # pywin32
            matches: list = []

            def _cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd) and title.lower() in win32gui.GetWindowText(hwnd).lower():
                    matches.append(hwnd)

            win32gui.EnumWindows(_cb, None)
            if matches:
                x1, y1, x2, y2 = win32gui.GetWindowRect(matches[0])
                return {
                    "top": y1, "left": x1,
                    "width": max(x2 - x1, 1), "height": max(y2 - y1, 1),
                }
        except Exception:
            pass

    elif sys.platform.startswith("linux"):
        try:
            import subprocess
            res = subprocess.run(
                ["xdotool", "search", "--name", title],
                capture_output=True, text=True, timeout=3,
            )
            if res.returncode == 0 and res.stdout.strip():
                wid = res.stdout.strip().split()[0]
                geo = subprocess.run(
                    ["xdotool", "getwindowgeometry", "--shell", wid],
                    capture_output=True, text=True, timeout=3,
                )
                if geo.returncode == 0:
                    props = dict(
                        line.split("=", 1)
                        for line in geo.stdout.splitlines()
                        if "=" in line
                    )
                    return {
                        "top":    int(props.get("Y", 0)),
                        "left":   int(props.get("X", 0)),
                        "width":  max(int(props.get("WIDTH", 1920)), 1),
                        "height": max(int(props.get("HEIGHT", 1080)), 1),
                    }
        except Exception:
            pass

    elif sys.platform == "darwin":
        try:
            import subprocess
            script = (
                'tell application "System Events"\n'
                f'  set w to first window of (first process whose name contains "{title}")\n'
                '  set p to position of w\n'
                '  set s to size of w\n'
                '  return (item 1 of p) & "," & (item 2 of p) & "," & (item 1 of s) & "," & (item 2 of s)\n'
                'end tell'
            )
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5,
            )
            if res.returncode == 0:
                parts = [int(x.strip()) for x in res.stdout.strip().split(",")]
                if len(parts) == 4:
                    return {
                        "top": parts[1], "left": parts[0],
                        "width": max(parts[2], 1), "height": max(parts[3], 1),
                    }
        except Exception:
            pass

    return None


def _grab_region_rgb(region: dict):
    """
    Synchronous helper: grab *region* (an mss-compatible dict with keys
    ``top``, ``left``, ``width``, ``height``) and return an ``(H, W, 3)``
    uint8 RGB numpy array.
    """
    import mss
    import numpy as np

    with mss.mss() as sct:
        img = sct.grab(region)
        arr = np.frombuffer(img.bgra, dtype=np.uint8).reshape(img.height, img.width, 4)
        return arr[:, :, [2, 1, 0]]  # BGRA → RGB


async def _capture_desktop_frame_async(display_idx: int = 1):
    """
    Capture a full monitor as an ``(H, W, 3)`` uint8 RGB numpy array using
    ``mss``.

    *display_idx* is a 1-based index into the list of monitors that ``mss``
    reports (``0`` = all monitors merged into one virtual desktop; ``1`` = the
    first physical monitor).  If the index is out of range it falls back to the
    first monitor.

    Returns ``None`` if ``mss`` is not installed, ``$DISPLAY`` is absent (Linux
    headless), or any other capture error occurs.
    """
    loop = asyncio.get_running_loop()

    def _grab():
        import mss
        import numpy as np
        with mss.mss() as sct:
            monitors = sct.monitors
            idx = display_idx if 0 <= display_idx < len(monitors) else min(1, len(monitors) - 1)
            img = sct.grab(monitors[idx])
            arr = np.frombuffer(img.bgra, dtype=np.uint8).reshape(img.height, img.width, 4)
            return arr[:, :, [2, 1, 0]]  # BGRA → RGB

    try:
        return await loop.run_in_executor(None, _grab)
    except Exception as exc:
        carb.log_warn(f"[omnicool.webapp][webrtc] desktop capture failed: {exc}")
        return None


async def _capture_window_frame_async(window_title: str, display_idx: int = 1):
    """
    Capture the first window whose title contains *window_title* as an RGB
    array.

    The window coordinates are resolved in a thread-pool worker (because the
    platform helpers may shell out to ``xdotool`` or ``osascript``).  If the
    window cannot be found the call falls back to a full-monitor desktop
    capture using ``display_idx``.

    Returns ``None`` only if both window and desktop capture fail.
    """
    loop = asyncio.get_running_loop()
    region = await loop.run_in_executor(None, _get_window_region, window_title)
    if region is not None:
        try:
            return await loop.run_in_executor(None, _grab_region_rgb, region)
        except Exception as exc:
            carb.log_warn(f"[omnicool.webapp][webrtc] window capture failed: {exc}")
    # Fall back to full monitor
    return await _capture_desktop_frame_async(display_idx)


def _get_capture_fn(mode: str, display_idx: int, window_title: str):
    """
    Return an async frame-capture coroutine function for the given *mode*.

    mode="viewport"  (default) — ``omni.renderer.capture`` (Kit renderer)
    mode="desktop"             — ``mss`` full-monitor capture
    mode="window"              — ``mss`` window-by-title capture (falls back to desktop)
    """
    if mode == "desktop":
        async def _desktop():
            return await _capture_desktop_frame_async(display_idx)
        return _desktop

    if mode == "window":
        async def _window():
            return await _capture_window_frame_async(window_title, display_idx)
        return _window

    # "viewport" or unknown — Omniverse renderer
    return _capture_viewport_frame_async


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

        self._capture_mode = str(settings.get(f"{base}/captureMode") or "viewport")
        self._capture_display = int(settings.get(f"{base}/captureDisplay") or 1)
        self._capture_window_title = str(settings.get(f"{base}/captureWindowTitle") or "")
        self._capture_width = int(settings.get(f"{base}/captureWidth") or 1280)
        self._capture_height = int(settings.get(f"{base}/captureHeight") or 720)

        mgr = omni.kit.app.get_app().get_extension_manager()
        ext_path = mgr.get_extension_path(ext_id)
        self._web_root = os.path.join(ext_path, self._web_root_rel)

        carb.log_info(f"[omnicool.webapp] web_root={self._web_root}")
        carb.log_info(f"[omnicool.webapp] http=http://{self._host}:{self._port}")
        carb.log_info(f"[omnicool.webapp] ws=ws://{self._ws_host}:{self._ws_port}")
        carb.log_info(f"[omnicool.webapp] webrtc enabled={self._webrtc_enabled} "
                      f"http://{self._webrtc_host}:{self._webrtc_port} "
                      f"captureMode={self._capture_mode} "
                      f"streamResolution={self._capture_width}x{self._capture_height}")

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
                    message_handler=self._handle_ws_message,
                    # Select the capture source according to the captureMode
                    # setting: "viewport" (Omniverse renderer), "desktop"
                    # (full monitor via mss), or "window" (mss + window title).
                    video_frame_provider=_get_capture_fn(
                        self._capture_mode,
                        self._capture_display,
                        self._capture_window_title,
                    ),
                    # Stream resolution: all frames (real + placeholder) are
                    # normalised to this size to prevent mid-stream resolution
                    # changes that cause codec glitches in browsers.
                    stream_width=self._capture_width,
                    stream_height=self._capture_height,
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

            if typ == "usd.get_prim_info":
                # Combined pick + attribute fetch for the prim-info HUD.
                # Replaces the multi-round-trip sequence:
                #   usd.pick → usd.list_attrs → N × usd.get_attr
                # with a single request, halving latency for the I-key gesture.
                norm_x = float(payload.get("x", 0.0))
                norm_y = float(payload.get("y", 0.0))
                max_attrs = int(payload.get("maxAttrs", 8))
                prim_path = _pick_prim_path(norm_x, norm_y)
                if not prim_path:
                    return {"id": req_id, "ok": True, "payload": {"primPath": None, "attrs": []}}
                attr_names = _list_attrs(stage, prim_path)[:max_attrs]
                attr_values = []
                for name in attr_names:
                    try:
                        val = _get_attr(stage, prim_path, name)
                        attr_values.append({"name": name, "value": _json_safe(val)})
                    except Exception:
                        attr_values.append({"name": name, "value": None})
                return {
                    "id": req_id,
                    "ok": True,
                    "payload": {"primPath": prim_path, "attrs": attr_values},
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

            return {"id": req_id, "ok": False, "error": f"Unknown type: {typ}"}

        except Exception as e:
            return {"id": req_id, "ok": False, "error": str(e)}
