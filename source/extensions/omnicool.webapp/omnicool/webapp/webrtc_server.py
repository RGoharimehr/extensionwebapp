# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
Pure-Python WebRTC signaling server using `aiortc`.

Why Python / aiortc instead of Node.js
---------------------------------------
Node.js WebRTC libraries load a separate V8 JavaScript runtime inside the
process.  That adds memory overhead and requires marshalling every value
that crosses the Python ↔ V8 boundary.  `aiortc` runs entirely in the same
CPython interpreter as Omniverse Kit, so USD prim data can be passed by
reference with zero serialisation cost.

Architecture
------------
A lightweight aiohttp HTTP server is started alongside the existing
WebSocket USD-bridge.  Two endpoints are exposed:

  POST /webrtc/offer
      Body:  {"sdp": "<SDP string>", "type": "offer"}
      Reply: {"sdp": "<answer SDP>",  "type": "answer"}

      The browser (or any WebRTC peer) sends its SDP offer; the server
      creates an RTCPeerConnection, processes the offer, and returns the
      answer.  From that point the data channel is used for messaging.

  GET  /webrtc/status
      Returns {"active_connections": <int>}.

RTCDataChannel protocol
-----------------------
The data channel reuses the same JSON request/response protocol already
used by the WebSocket USD bridge:

  Request:  {"id": "123", "type": "usd.ping",   "payload": {}}
  Response: {"id": "123", "ok": true,  "payload": {"pong": true}}
  Error:    {"id": "123", "ok": false, "error":  "message"}

The ``message_handler`` callback is injected by the caller (extension.py)
so that WebRTC data-channel messages go through exactly the same routing
logic as WebSocket messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional, Set

log = logging.getLogger(__name__)

MessageHandler = Callable[[str], Awaitable[dict]]


# ---------------------------------------------------------------------------
# Optional: viewport video track
# ---------------------------------------------------------------------------

try:
    # aiortc ships VideoStreamTrack; av (PyAV) ships VideoFrame.
    # Both are installed as dependencies of aiortc, so if aiortc is present
    # then both are available.
    from aiortc.mediastreams import VideoStreamTrack as _VideoStreamTrack  # noqa: F401

    class OmniViewportVideoTrack(_VideoStreamTrack):
        """
        A WebRTC video track that streams frames from the Omniverse viewport.

        ``frame_provider`` is an async callable that returns a numpy ndarray of
        shape ``(H, W, 3)`` or ``(H, W, 4)`` in uint8 RGB/RGBA order, or
        ``None`` when no frame is available yet.  A black 1280×720 placeholder
        frame is sent whenever the provider returns ``None`` so the
        ``RTCPeerConnection`` stays alive while the renderer is warming up.

        The caller (``extension.py``) supplies ``_capture_viewport_frame_async``
        as the provider.
        """

        kind = "video"

        def __init__(self, frame_provider: Optional[Callable] = None) -> None:
            super().__init__()
            self._frame_provider = frame_provider
            self._blank: Optional[Any] = None  # lazily-created black numpy array

        async def recv(self):  # -> av.VideoFrame
            import av
            import numpy as np

            pts, time_base = await self.next_timestamp()

            arr: Optional[Any] = None
            if self._frame_provider is not None:
                try:
                    # Await the provider directly — _capture_viewport_frame_async
                    # already enforces its own 1-second timeout internally, so an
                    # extra outer wait_for is unnecessary and counterproductive
                    # (a 0.4 s outer deadline would race and cancel the inner
                    # coroutine before the render thread has a chance to deliver
                    # the frame, resulting in permanent black/blank output).
                    arr = await self._frame_provider()
                except Exception:
                    arr = None

            if arr is not None:
                # Handle both 3-channel (RGB) and 4-channel (BGRA) arrays.
                # Kit's swapchain capture returns BGRA; rearrange to RGB for
                # the aiortc encoder.  A plain 3-channel array from a test
                # provider is passed through untouched.
                if arr.ndim == 3 and arr.shape[2] == 4:
                    arr = arr[:, :, [2, 1, 0]]  # BGRA → RGB
                frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            else:
                # Placeholder: a black frame keeps the stream alive
                if self._blank is None:
                    self._blank = np.zeros((720, 1280, 3), dtype=np.uint8)
                frame = av.VideoFrame.from_ndarray(self._blank, format="rgb24")

            frame.pts = pts
            frame.time_base = time_base
            return frame

except ImportError:
    OmniViewportVideoTrack = None  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def _import_aiortc():
    """Import aiortc, raising ImportError with a helpful message if absent."""
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription  # noqa: F401
        return True
    except ImportError as exc:
        raise ImportError(
            "aiortc is required for WebRTC support. "
            "Install it with: pip install aiortc\n"
            f"Original error: {exc}"
        ) from exc


def _import_aiohttp():
    """Import aiohttp, raising ImportError with a helpful message if absent."""
    try:
        import aiohttp  # noqa: F401
        return True
    except ImportError as exc:
        raise ImportError(
            "aiohttp is required for WebRTC signaling. "
            "Install it with: pip install aiohttp\n"
            f"Original error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# WebRTC peer connection wrapper
# ---------------------------------------------------------------------------

class _PeerSession:
    """Wraps a single RTCPeerConnection and its data channel."""

    def __init__(
        self,
        pc,  # RTCPeerConnection
        message_handler: MessageHandler,
    ):
        self._pc = pc
        self._message_handler = message_handler
        self._channel = None

        # Wire up channel registration
        @pc.on("datachannel")
        def on_datachannel(channel):
            self._channel = channel
            log.info("[webrtc] data channel opened: %s", channel.label)

            @channel.on("message")
            def on_message(message: str):
                asyncio.ensure_future(self._on_message(message))

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            state = pc.connectionState
            log.info("[webrtc] connection state → %s", state)

    async def _on_message(self, message: str):
        try:
            resp = await self._message_handler(message)
            if self._channel and self._channel.readyState == "open":
                self._channel.send(json.dumps(resp))
        except Exception as exc:
            log.warning("[webrtc] message handler error: %s", exc)

    async def close(self):
        try:
            await self._pc.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Signaling server
# ---------------------------------------------------------------------------

class WebRTCSignalingServer:
    """
    Lightweight aiohttp-based HTTP signaling server.

    Lifecycle
    ---------
    1. Caller provides a ``message_handler`` coroutine and, optionally, a
       ``video_frame_provider`` coroutine that returns viewport frames.
    2. Call ``start(host, port)``  to begin serving.
    3. Call ``stop()``             to shut down cleanly.

    Video streaming
    ---------------
    When ``video_frame_provider`` is supplied and aiortc is installed, an
    :class:`OmniViewportVideoTrack` is added to every new
    ``RTCPeerConnection`` before the SDP answer is created.  The browser
    peer must include a ``recvonly`` video transceiver in its offer for the
    video m-line to be negotiated.
    """

    def __init__(
        self,
        message_handler: MessageHandler,
        video_frame_provider: Optional[Callable] = None,
    ) -> None:
        self._message_handler = message_handler
        self._video_frame_provider = video_frame_provider
        self._sessions: Set[_PeerSession] = set()
        self._runner = None
        self._site = None
        self._host: str = "127.0.0.1"
        self._port: int = 8900

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    async def start(self, host: str = "127.0.0.1", port: int = 8900) -> None:
        """Start the signaling HTTP server."""
        _import_aiortc()
        _import_aiohttp()

        import aiohttp.web as web

        self._host = host
        self._port = port

        app = web.Application()
        app.router.add_post("/webrtc/offer", self._handle_offer)
        app.router.add_route("OPTIONS", "/webrtc/offer", self._handle_options)
        app.router.add_get("/webrtc/status", self._handle_status)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()
        log.info("[webrtc] signaling server listening on http://%s:%d", host, port)

    async def stop(self) -> None:
        """Close all peer connections and stop the HTTP server."""
        for session in list(self._sessions):
            await session.close()
        self._sessions.clear()

        if self._runner:
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None
            self._site = None
        log.info("[webrtc] signaling server stopped")

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    async def _handle_offer(self, request) -> Any:
        """
        POST /webrtc/offer
        Consumes an SDP offer from the browser and returns an SDP answer.
        """
        import aiohttp.web as web
        from aiortc import RTCPeerConnection, RTCSessionDescription

        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Request body must be valid JSON")

        sdp = body.get("sdp")
        sdp_type = body.get("type", "offer")
        if not sdp or sdp_type != "offer":
            raise web.HTTPBadRequest(reason="'sdp' and 'type': 'offer' are required")

        pc = RTCPeerConnection()
        session = _PeerSession(pc, self._message_handler)
        self._sessions.add(session)

        @pc.on("connectionstatechange")
        async def _remove_on_closed():
            if pc.connectionState in ("closed", "failed", "disconnected"):
                self._sessions.discard(session)

        offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
        await pc.setRemoteDescription(offer)

        # Add a viewport video track so the browser <video> element receives
        # the Omniverse renderer output.  The track must be added AFTER
        # setRemoteDescription (so we know what the offer contains) and BEFORE
        # createAnswer() so the SDP answer advertises the video m-line.
        # If the browser offer contains no video transceiver the track is
        # silently ignored during SDP negotiation.
        if OmniViewportVideoTrack is not None and self._video_frame_provider is not None:
            pc.addTrack(OmniViewportVideoTrack(frame_provider=self._video_frame_provider))
            log.debug("[webrtc] viewport video track added to peer connection")

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        # Safety: wait until ICE gathering is complete before reading
        # localDescription.sdp.  aiortc ≥ 1.3 awaits gathering inside
        # setLocalDescription, but older builds return before it finishes.
        # Polling avoids a hard dependency on a specific aiortc version.
        _loop = asyncio.get_running_loop()
        _deadline = _loop.time() + 5.0
        while pc.iceGatheringState != "complete" and _loop.time() < _deadline:
            await asyncio.sleep(0.05)

        return web.json_response(
            {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def _handle_options(self, request) -> Any:
        """
        OPTIONS /webrtc/offer
        Respond to the browser CORS preflight so cross-origin ``fetch()``
        calls (e.g., from http://localhost:3001 to http://localhost:8900)
        are allowed without a browser security error.
        """
        import aiohttp.web as web

        return web.Response(
            status=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    async def _handle_status(self, request) -> Any:
        """GET /webrtc/status — returns number of active connections."""
        import aiohttp.web as web

        return web.json_response(
            {"active_connections": len(self._sessions)},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active_connection_count(self) -> int:
        return len(self._sessions)

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"
