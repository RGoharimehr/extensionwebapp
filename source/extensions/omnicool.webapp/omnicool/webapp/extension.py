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

from omnicool.webapp.backend.usd_helpers import _get_attr, _pick_prim_path
from omnicool.webapp.backend.ws_handlers import handle_ws_message
from omnicool.webapp.transport.http_server import _StaticHandler, _ensure_websockets_installed
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
