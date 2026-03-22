import os
import json
import threading
import webbrowser
import asyncio
import functools
from http.server import ThreadingHTTPServer

import omni.ext
import omni.kit.app
import carb

from omnicool.webapp.backend.bridge_ws_handlers import (
    handle_bridge_connect,
    handle_bridge_message,
    set_browse_callback,
)
from omnicool.webapp.backend.usd_helpers import _get_attr, _pick_prim_path
from omnicool.webapp.backend.ws_handlers import handle_ws_message
from omnicool.webapp.transport.http_server import (
    _StaticHandler,
    _ensure_aiohttp_installed,
    _ensure_aiortc_installed,
    _ensure_websockets_installed,
)
from omnicool.webapp.transport.webrtc_server import WebRTCSignalingServer


class OmnicoolWebAppExt(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        self._ext_id = ext_id

        # HTTP server state
        self._httpd = None
        self._http_thread = None

        # WS server state
        self._ws_server = None
        self._ws_task = None

        # Bridge WS server state (port 8001 — used by the React webapp)
        self._bridge_ws_server = None
        self._bridge_ws_task = None

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

        # The React webapp connects to ws://127.0.0.1:8001 (root path) for its bridge.
        self._bridge_ws_host = str(settings.get(f"{base}/bridgeWsHost") or "127.0.0.1")
        self._bridge_ws_port = int(settings.get(f"{base}/bridgeWsPort") or 8001)

        self._webrtc_enabled = bool(settings.get(f"{base}/webrtcEnabled") or False)
        self._webrtc_host = str(settings.get(f"{base}/webrtcHost") or "127.0.0.1")
        self._webrtc_port = int(settings.get(f"{base}/webrtcPort") or 8900)

        mgr = omni.kit.app.get_app().get_extension_manager()
        ext_path = mgr.get_extension_path(ext_id)
        self._web_root = os.path.join(ext_path, self._web_root_rel)

        carb.log_info(f"[omnicool.webapp] web_root={self._web_root}")
        carb.log_info(f"[omnicool.webapp] http=http://{self._host}:{self._port}")
        carb.log_info(f"[omnicool.webapp] ws=ws://{self._ws_host}:{self._ws_port}")
        carb.log_info(
            f"[omnicool.webapp] bridge+webrtc=ws://{self._bridge_ws_host}:{self._bridge_ws_port} "
            f"and http://{self._bridge_ws_host}:{self._bridge_ws_port}/webrtc/offer"
        )
        if self._webrtc_enabled:
            carb.log_info(
                f"[omnicool.webapp] standalone webrtc=http://{self._webrtc_host}:{self._webrtc_port}"
            )

        if self._auto:
            self._start_http()
            self._start_ws()
            self._start_bridge_ws()
            if self._webrtc_enabled:
                self._start_webrtc()

        set_browse_callback(self._browse_file)

    def on_shutdown(self):
        set_browse_callback(None)
        self._stop_webrtc()
        self._stop_bridge_ws()
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
    # Native file / directory browser
    # -----------------
    async def _browse_file(self, mode: str, filters: list) -> str:
        """Open a native OS file or directory picker and return the chosen path.

        Runs the blocking tkinter dialog in a thread-pool executor so the
        asyncio event loop is not stalled.  Returns an empty string if the
        user cancels or if tkinter is unavailable.

        Args:
            mode: ``"file"`` for a file-open dialog, ``"directory"`` for a
                  folder-browser dialog.
            filters: List of ``{"label": str, "extension": str}`` dicts
                     (e.g. ``[{"label": "Flownex files", "extension":
                     "*.proj;*.fnx"}]``).  Ignored for directory mode.
        """
        def _run_dialog() -> str:
            try:
                import tkinter as tk
                from tkinter import filedialog

                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)

                if mode == "directory":
                    path = filedialog.askdirectory(parent=root)
                else:
                    # Convert {"label": "...", "extension": "*.x;*.y"} →
                    # tkinter's [("label", "*.x *.y"), ...] format.
                    tk_types = []
                    for f in filters or []:
                        label = str(f.get("label", "Files"))
                        ext = str(f.get("extension", "*.*")).replace(";", " ")
                        tk_types.append((label, ext))
                    if not tk_types:
                        tk_types = [("All Files", "*.*")]
                    path = filedialog.askopenfilename(
                        parent=root, filetypes=tk_types
                    )

                root.destroy()
                return path or ""
            except Exception as exc:  # noqa: BLE001
                carb.log_warn(f"[omnicool.webapp][browse] dialog error: {exc}")
                return ""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run_dialog)

    # -----------------
    # WebSocket USD bridge
    # -----------------
    def _start_ws(self):
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
                            resp = await handle_ws_message(msg)
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
    # Bridge WebSocket + WebRTC signaling (port 8001)
    #
    # The React webapp hard-codes ws://127.0.0.1:8001 for the bridge WS and
    # http://127.0.0.1:8001/webrtc/offer for the Python WebRTC signaling.
    # Both are served from a single aiohttp server on port 8001:
    #   GET  /              → WebSocket bridge (Flownex protocol)
    #   POST /webrtc/offer  → WebRTC SDP offer/answer exchange
    #   GET  /webrtc/status → active WebRTC connection count
    # -----------------
    def _start_bridge_ws(self):
        """Start the combined aiohttp server used by the React webapp.

        Serves the Flownex WebSocket bridge at the root path and the Python
        WebRTC signaling endpoints at ``/webrtc/*``, all on the same port so
        the compiled React app can reach both without extra configuration.
        """
        if self._bridge_ws_task:
            return

        async def _run():
            runner = None
            try:
                await _ensure_aiohttp_installed()
                await _ensure_aiortc_installed()
                import aiohttp
                import aiohttp.web as web

                # ----------------------------------------------------------
                # Adapter: aiohttp WS uses send_str(); bridge_ws_handlers
                # expects a plain send() coroutine on the socket object.
                # ----------------------------------------------------------
                class _WS:
                    def __init__(self, ws):
                        self._ws = ws

                    async def send(self, data: str) -> None:
                        await self._ws.send_str(data)

                # ----------------------------------------------------------
                # WebSocket bridge handler (GET /)
                # ----------------------------------------------------------
                async def ws_handler(request):
                    ws = web.WebSocketResponse()
                    await ws.prepare(request)
                    wrapped = _WS(ws)
                    carb.log_info("[omnicool.webapp][bridge_ws] client connected")
                    try:
                        await handle_bridge_connect(wrapped)
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await handle_bridge_message(msg.data, wrapped)
                            elif msg.type in (
                                aiohttp.WSMsgType.ERROR,
                                aiohttp.WSMsgType.CLOSE,
                            ):
                                break
                    except Exception as e:
                        carb.log_warn(
                            f"[omnicool.webapp][bridge_ws] client handler ended: {e}"
                        )
                    finally:
                        carb.log_info(
                            "[omnicool.webapp][bridge_ws] client disconnected"
                        )
                    return ws

                # ----------------------------------------------------------
                # WebRTC signaling handlers (POST /webrtc/offer,
                #                            OPTIONS /webrtc/offer CORS,
                #                            GET  /webrtc/status)
                # ----------------------------------------------------------
                _CORS_HEADERS = {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                }

                _webrtc_sessions: set = set()

                async def cors_preflight_handler(request):
                    """Handle the CORS preflight OPTIONS request the browser sends
                    before POST /webrtc/offer when the page origin differs from the
                    API origin (e.g. http://127.0.0.1:3001 → http://127.0.0.1:8001).
                    Without this 200 response, the browser blocks the actual POST.
                    """
                    return web.Response(status=200, headers=_CORS_HEADERS)

                async def offer_handler(request):
                    try:
                        from aiortc import RTCPeerConnection, RTCSessionDescription
                    except ImportError:
                        return web.Response(
                            status=501,
                            text="aiortc is not installed; WebRTC unavailable.",
                            headers=_CORS_HEADERS,
                        )

                    try:
                        body = await request.json()
                    except Exception:
                        return web.Response(
                            status=400,
                            text="Request body must be valid JSON",
                            headers=_CORS_HEADERS,
                        )

                    sdp = body.get("sdp")
                    sdp_type = body.get("type", "offer")
                    if not sdp or sdp_type != "offer":
                        return web.Response(
                            status=400,
                            text="'sdp' and 'type': 'offer' are required",
                            headers=_CORS_HEADERS,
                        )

                    pc = RTCPeerConnection()
                    _webrtc_sessions.add(pc)

                    @pc.on("datachannel")
                    def on_datachannel(channel):
                        @channel.on("message")
                        def on_message(message: str):
                            asyncio.ensure_future(
                                _handle_dc_message(channel, message)
                            )

                    @pc.on("connectionstatechange")
                    async def on_state():
                        if pc.connectionState in ("closed", "failed", "disconnected"):
                            _webrtc_sessions.discard(pc)

                    offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
                    await pc.setRemoteDescription(offer)
                    answer = await pc.createAnswer()
                    await pc.setLocalDescription(answer)

                    return web.json_response(
                        {
                            "sdp": pc.localDescription.sdp,
                            "type": pc.localDescription.type,
                        },
                        headers=_CORS_HEADERS,
                    )

                async def _handle_dc_message(channel, message: str) -> None:
                    try:
                        resp = await handle_ws_message(message)
                        if channel.readyState == "open":
                            channel.send(json.dumps(resp))
                    except Exception as e:
                        carb.log_warn(
                            f"[omnicool.webapp][bridge_ws/webrtc] dc message error: {e}"
                        )

                async def status_handler(request):
                    return web.json_response(
                        {"active_connections": len(_webrtc_sessions)},
                        headers=_CORS_HEADERS,
                    )

                # ----------------------------------------------------------
                # Build and start aiohttp app
                # ----------------------------------------------------------
                app = web.Application()
                app.router.add_get("/", ws_handler)
                app.router.add_route("OPTIONS", "/webrtc/offer", cors_preflight_handler)
                app.router.add_post("/webrtc/offer", offer_handler)
                app.router.add_get("/webrtc/status", status_handler)

                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, self._bridge_ws_host, self._bridge_ws_port)
                await site.start()
                self._bridge_ws_server = runner

                carb.log_info(
                    f"[omnicool.webapp][bridge_ws] Combined WS+WebRTC server on "
                    f"ws://{self._bridge_ws_host}:{self._bridge_ws_port} "
                    f"and http://{self._bridge_ws_host}:{self._bridge_ws_port}/webrtc/offer"
                )

                # Keep alive until cancelled
                await asyncio.Future()

            except asyncio.CancelledError:
                pass
            except Exception as e:
                carb.log_error(f"[omnicool.webapp][bridge_ws] server failed: {e}")
            finally:
                if runner:
                    try:
                        await runner.cleanup()
                    except Exception:
                        pass
                self._bridge_ws_server = None

        loop = asyncio.get_event_loop()
        self._bridge_ws_task = loop.create_task(_run())

    def _stop_bridge_ws(self):
        if self._bridge_ws_task:
            try:
                self._bridge_ws_task.cancel()
            except Exception:
                pass
            self._bridge_ws_task = None
        # self._bridge_ws_server (AppRunner) is cleaned up in the task's finally block.
        self._bridge_ws_server = None

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
                    message_handler=handle_ws_message
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

    async def _handle_ws_message(self, msg: str) -> dict:
        """Thin wrapper kept for backward compatibility with tests."""
        return await handle_ws_message(msg)
