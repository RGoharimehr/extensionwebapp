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
    apply_saved_config,
    handle_bridge_connect,
    handle_bridge_message,
    set_browse_callback,
)
from omnicool.webapp.backend import config_store
from omnicool.webapp.backend.ws_handlers import handle_ws_message
from omnicool.webapp.transport.http_server import (
    _StaticHandler,
    _ensure_aiohttp_installed,
    _ensure_aiortc_installed,
)
from omnicool.webapp.transport.webrtc_server import WebRTCSignalingServer
from omnicool.webapp.backend import config_store
import os

ext_path = os.path.dirname(__file__)
config_path = os.path.join(ext_path, "webapp_config.json")

print("[startup] ext_path =", ext_path)
print("[startup] config_path =", config_path)

config_store.set_path(config_path)

class OmnicoolWebAppExt(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        self._ext_id = ext_id

        self._httpd = None
        self._http_thread = None

        self._ws_server = None
        self._ws_task = None

        self._bridge_ws_server = None
        self._bridge_ws_task = None

        self._webrtc_server: WebRTCSignalingServer | None = None
        self._webrtc_task = None

        settings = carb.settings.get_settings()
        base = "/exts/omnicool.webapp"

        self._auto = self._get_bool_setting(settings, f"{base}/autoLaunch", True)
        self._open_browser = self._get_bool_setting(settings, f"{base}/openBrowser", True)
        self._webrtc_enabled = self._get_bool_setting(settings, f"{base}/webrtcEnabled", False)

        self._host = str(settings.get(f"{base}/host") or "127.0.0.1")
        self._port = int(settings.get(f"{base}/port") or 3001)
        self._web_root_rel = str(settings.get(f"{base}/webRoot") or "data/webapp")

        self._ws_host = str(settings.get(f"{base}/wsHost") or "127.0.0.1")
        self._ws_port = int(settings.get(f"{base}/wsPort") or 8899)

        self._bridge_ws_host = str(settings.get(f"{base}/bridgeWsHost") or "127.0.0.1")
        self._bridge_ws_port = int(settings.get(f"{base}/bridgeWsPort") or 8001)

        self._webrtc_host = str(settings.get(f"{base}/webrtcHost") or "127.0.0.1")
        self._webrtc_port = int(settings.get(f"{base}/webrtcPort") or 8900)

        mgr = omni.kit.app.get_app().get_extension_manager()
        ext_path = mgr.get_extension_path(ext_id)
        self._web_root = os.path.join(ext_path, self._web_root_rel)

        config_store.set_path(os.path.join(ext_path, "data", "omnicool_config.json"))
        apply_saved_config()

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

        set_browse_callback(None)

    def on_shutdown(self):
        set_browse_callback(None)
        self._stop_webrtc()
        self._stop_bridge_ws()
        self._stop_ws()
        self._stop_http()

    @staticmethod
    def _get_bool_setting(settings, key: str, default: bool) -> bool:
        value = settings.get(key)
        if value is None:
            return default
        return bool(value)

    def _start_http(self):
        if self._httpd:
            return

        index_html = os.path.join(self._web_root, "index.html")
        if not os.path.isfile(index_html):
            carb.log_error(
                "[omnicool.webapp][http] index.html not found. "
                f"Expected: {index_html}. "
                "Copy your web build into data/webapp/."
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

    async def _browse_file(self, mode: str, filters: list) -> str:
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
                    tk_types = []
                    for f in filters or []:
                        label = str(f.get("label", "Files"))
                        ext = str(f.get("extension", "*.*")).replace(";", " ")
                        tk_types.append((label, ext))
                    if not tk_types:
                        tk_types = [("All Files", "*.*")]
                    path = filedialog.askopenfilename(parent=root, filetypes=tk_types)

                root.destroy()
                return path or ""
            except Exception as exc:
                carb.log_warn(f"[omnicool.webapp][browse] dialog error: {exc}")
                return ""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run_dialog)

    def _start_ws(self):
        if self._ws_task:
            return

        async def _run():
            runner = None
            try:
                await _ensure_aiohttp_installed()
                import aiohttp
                import aiohttp.web as web

                async def ws_handler(request):
                    ws = web.WebSocketResponse()
                    await ws.prepare(request)
                    carb.log_info("[omnicool.webapp][ws] client connected")
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                resp = await handle_ws_message(msg.data)
                                await ws.send_str(json.dumps(resp))
                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                                break
                    except Exception as e:
                        carb.log_warn(f"[omnicool.webapp][ws] client handler ended: {e}")
                    finally:
                        carb.log_info("[omnicool.webapp][ws] client disconnected")
                    return ws

                app = web.Application()
                app.router.add_get("/", ws_handler)
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, self._ws_host, self._ws_port)
                await site.start()
                self._ws_server = runner

                carb.log_info(f"[omnicool.webapp][ws] Serving ws://{self._ws_host}:{self._ws_port}")
                await asyncio.Future()

            except asyncio.CancelledError:
                pass
            except Exception as e:
                carb.log_error(f"[omnicool.webapp][ws] server failed: {e}")
            finally:
                if runner:
                    try:
                        await runner.cleanup()
                    except Exception:
                        pass
                self._ws_server = None

        loop = asyncio.get_event_loop()
        self._ws_task = loop.create_task(_run())

    def _stop_ws(self):
        if self._ws_task:
            try:
                self._ws_task.cancel()
            except Exception:
                pass
            self._ws_task = None
        self._ws_server = None

    def _start_bridge_ws(self):
        if self._bridge_ws_task:
            return

        async def _run():
            runner = None
            try:
                await _ensure_aiohttp_installed()
                await _ensure_aiortc_installed()
                import aiohttp
                import aiohttp.web as web

                class _WS:
                    def __init__(self, ws):
                        self._ws = ws

                    async def send(self, data: str) -> None:
                        await self._ws.send_str(data)

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
                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                                break
                    except Exception as e:
                        carb.log_warn(f"[omnicool.webapp][bridge_ws] client handler ended: {e}")
                    finally:
                        carb.log_info("[omnicool.webapp][bridge_ws] client disconnected")
                    return ws

                _CORS_HEADERS = {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                }

                _webrtc_sessions: set = set()

                async def cors_preflight_handler(request):
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
                            asyncio.ensure_future(_handle_dc_message(channel, message))

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
                        carb.log_warn(f"[omnicool.webapp][bridge_ws/webrtc] dc message error: {e}")

                async def status_handler(request):
                    return web.json_response(
                        {"active_connections": len(_webrtc_sessions)},
                        headers=_CORS_HEADERS,
                    )

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
        self._bridge_ws_server = None

    def _start_webrtc(self):
        if self._webrtc_task:
            return

        async def _run():
            try:
                self._webrtc_server = WebRTCSignalingServer(message_handler=handle_ws_message)
                await self._webrtc_server.start(host=self._webrtc_host, port=self._webrtc_port)
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
