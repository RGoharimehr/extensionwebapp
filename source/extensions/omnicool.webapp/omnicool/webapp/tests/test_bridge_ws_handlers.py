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
Tests for omnicool.webapp.backend.bridge_ws_handlers.

Covers:
  - _state_json() includes savedProjectPath / savedIoDir aliases
  - config.browse_file handler: responds with browse_result
  - config.browse_file with no callback returns empty path
  - set_browse_callback / clear callback
"""

import json

import omni.kit.test

import omnicool.webapp.backend.bridge_ws_handlers as bwh
import omnicool.webapp.backend.flownex_bridge as fb


# ---------------------------------------------------------------------------
# Minimal WS stub that captures outgoing messages
# ---------------------------------------------------------------------------

class _FakeWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, data: str) -> None:
        self.sent.append(data)

    def messages(self) -> list[dict]:
        return [json.loads(m) for m in self.sent]

    def last(self) -> dict:
        return json.loads(self.sent[-1])


# ---------------------------------------------------------------------------
# Minimal flownex stubs so _state_json() can run without a Flownex install
# ---------------------------------------------------------------------------

class _MockSetup:
    FlownexProject = "/path/to/project.proj"
    IOFileDirectory = "/path/to/io"
    SolveOnChange = False
    ResultPollingInterval = "1.0"


class _MockIO:
    @property
    def Setup(self):
        return _MockSetup()

    def Save(self):
        pass

    def LoadDynamicInputs(self):
        return []

    def LoadStaticInputs(self):
        return []

    def LoadOutputs(self):
        return []


class _MockApi:
    FlownexInstalltionDetected = True
    AttachedProject = object()
    ProjectFile = "/path/to/project.proj"

    def IsFnxAvailable(self):
        return True

    def AttachToProject(self, path):
        pass

    def CloseProject(self):
        pass

    def ExitApplication(self):
        pass

    def RunSteadyStateSimulationBlocking(self):
        return True


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestBridgeWsHandlers(omni.kit.test.AsyncTestCase):
    """Unit tests for bridge_ws_handlers — no Flownex runtime required."""

    def setUp(self):
        fb.reset_singletons(api=_MockApi(), io=_MockIO())
        bwh.set_browse_callback(None)

    def tearDown(self):
        fb.reset_singletons(api=None, io=None)
        bwh.set_browse_callback(None)

    # ------------------------------------------------------------------
    # _state_json aliases
    # ------------------------------------------------------------------

    async def test_state_json_includes_saved_project_path(self):
        """_state_json payload must contain savedProjectPath."""
        msg = json.loads(bwh._state_json())
        self.assertIn("savedProjectPath", msg["payload"])

    async def test_state_json_includes_saved_io_dir(self):
        """_state_json payload must contain savedIoDir."""
        msg = json.loads(bwh._state_json())
        self.assertIn("savedIoDir", msg["payload"])

    async def test_state_json_saved_project_path_matches_connected_project(self):
        """savedProjectPath must equal connected_project."""
        msg = json.loads(bwh._state_json())
        payload = msg["payload"]
        self.assertEqual(payload["savedProjectPath"], payload["connected_project"])

    async def test_state_json_saved_io_dir_matches_io_directory(self):
        """savedIoDir must equal io_directory."""
        msg = json.loads(bwh._state_json())
        payload = msg["payload"]
        self.assertEqual(payload["savedIoDir"], payload["io_directory"])

    # ------------------------------------------------------------------
    # config.browse_file — no callback registered
    # ------------------------------------------------------------------

    async def test_browse_file_no_callback_returns_empty_path(self):
        """When no browse callback is set, browse_result path must be ''."""
        ws = _FakeWS()
        req = json.dumps({
            "type": "config.browse_file",
            "id": "req-001",
            "payload": {"mode": "file", "filters": [], "requestId": "req-001"},
        })
        await bwh.handle_bridge_message(req, ws)

        result = ws.last()
        self.assertEqual(result["type"], "browse_result")
        self.assertEqual(result["payload"]["requestId"], "req-001")
        self.assertEqual(result["payload"]["path"], "")

    async def test_browse_file_no_callback_returns_browse_result_type(self):
        """Response type must be 'browse_result' even without a callback."""
        ws = _FakeWS()
        req = json.dumps({
            "type": "config.browse_file",
            "id": "abc",
            "payload": {"mode": "directory", "requestId": "abc"},
        })
        await bwh.handle_bridge_message(req, ws)
        self.assertEqual(ws.last()["type"], "browse_result")

    # ------------------------------------------------------------------
    # config.browse_file — callback registered
    # ------------------------------------------------------------------

    async def test_browse_file_callback_path_returned(self):
        """When callback returns a path, browse_result carries it."""
        async def _cb(mode, filters):
            return "/chosen/path/project.proj"

        bwh.set_browse_callback(_cb)
        ws = _FakeWS()
        req = json.dumps({
            "type": "config.browse_file",
            "id": "req-42",
            "payload": {"mode": "file", "filters": [], "requestId": "req-42"},
        })
        await bwh.handle_bridge_message(req, ws)

        result = ws.last()
        self.assertEqual(result["type"], "browse_result")
        self.assertEqual(result["payload"]["path"], "/chosen/path/project.proj")
        self.assertEqual(result["payload"]["requestId"], "req-42")

    async def test_browse_file_callback_cancelled_empty_path(self):
        """When callback returns '' (cancelled), browse_result path is ''."""
        async def _cb(mode, filters):
            return ""

        bwh.set_browse_callback(_cb)
        ws = _FakeWS()
        req = json.dumps({
            "type": "config.browse_file",
            "id": "req-cancel",
            "payload": {"mode": "file", "requestId": "req-cancel"},
        })
        await bwh.handle_bridge_message(req, ws)

        self.assertEqual(ws.last()["payload"]["path"], "")

    async def test_browse_file_callback_exception_returns_empty_path(self):
        """If callback raises, browse_result path falls back to ''."""
        async def _cb(mode, filters):
            raise RuntimeError("dialog failed")

        bwh.set_browse_callback(_cb)
        ws = _FakeWS()
        req = json.dumps({
            "type": "config.browse_file",
            "id": "req-err",
            "payload": {"mode": "file", "requestId": "req-err"},
        })
        await bwh.handle_bridge_message(req, ws)

        result = ws.last()
        self.assertEqual(result["type"], "browse_result")
        self.assertEqual(result["payload"]["path"], "")

    # ------------------------------------------------------------------
    # set_browse_callback / clear
    # ------------------------------------------------------------------

    async def test_set_browse_callback_stores_callback(self):
        """set_browse_callback stores the provided callable."""
        async def _cb(m, f):
            return "/x"

        bwh.set_browse_callback(_cb)
        self.assertIs(bwh._browse_callback, _cb)

    async def test_set_browse_callback_none_clears_callback(self):
        """set_browse_callback(None) removes the callback."""
        async def _cb(m, f):
            return "/x"

        bwh.set_browse_callback(_cb)
        bwh.set_browse_callback(None)
        self.assertIsNone(bwh._browse_callback)

    async def test_browse_file_request_id_forwarded_from_payload(self):
        """requestId in payload is echoed back even when top-level id is absent."""
        ws = _FakeWS()
        req = json.dumps({
            "type": "config.browse_file",
            "payload": {"mode": "file", "requestId": "payload-id"},
        })
        await bwh.handle_bridge_message(req, ws)
        self.assertEqual(ws.last()["payload"]["requestId"], "payload-id")
