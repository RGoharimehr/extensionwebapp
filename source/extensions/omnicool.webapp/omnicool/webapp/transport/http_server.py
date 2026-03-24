"""Static HTTP server handler and WebSocket dependency installer.

Both pieces are pure infrastructure — they have no knowledge of USD or
application logic — so they live here in the transport layer.
"""
from __future__ import annotations

from http.server import SimpleHTTPRequestHandler

import carb


class _StaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        carb.log_info("[omnicool.webapp][http] " + (fmt % args))


async def _ensure_aiohttp_installed():
    """
    Ensures the ``aiohttp`` library is available, installing it via
    ``omni.kit.pipapi`` on first use if necessary.
    """
    try:
        import aiohttp  # noqa: F401
        return
    except Exception:
        pass

    try:
        import omni.kit.pipapi as pipapi
        carb.log_warn("[omnicool.webapp][bridge] 'aiohttp' not found. Installing via pip...")
        pipapi.install("aiohttp")
        import aiohttp  # noqa: F401
        carb.log_info("[omnicool.webapp][bridge] 'aiohttp' installed successfully.")
    except Exception as e:
        carb.log_error(
            "[omnicool.webapp][bridge] Failed to import/install 'aiohttp'. "
            f"Combined bridge server will NOT start. Error: {e}"
        )
        raise


async def _ensure_aiortc_installed():
    """
    Ensures the ``aiortc`` library is available, installing it via
    ``omni.kit.pipapi`` on first use if necessary.

    ``aiortc`` is optional — if it cannot be installed the WebRTC signaling
    endpoint will respond with HTTP 501 and log a warning, but the WebSocket
    bridge continues to function normally.
    """
    try:
        import aiortc  # noqa: F401
        return
    except Exception:
        pass

    try:
        import omni.kit.pipapi as pipapi
        carb.log_warn("[omnicool.webapp][webrtc] 'aiortc' not found. Installing via pip...")
        pipapi.install("aiortc")
        import aiortc  # noqa: F401
        carb.log_info("[omnicool.webapp][webrtc] 'aiortc' installed successfully.")
    except Exception as e:
        carb.log_warn(
            "[omnicool.webapp][webrtc] Could not install 'aiortc'. "
            f"WebRTC will not be available; WS bridge is unaffected. Error: {e}"
        )
