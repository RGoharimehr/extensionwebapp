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


async def _ensure_websockets_installed():
    """
    Ensures the ``websockets`` library is available, installing it via
    ``omni.kit.pipapi`` on first use if necessary.
    """
    try:
        import websockets  # noqa: F401
        return
    except Exception:
        pass

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
