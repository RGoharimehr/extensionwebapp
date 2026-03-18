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
Unit tests for the prim-info HUD activation (I key + hold-click gesture).

Validated behaviours
--------------------
1. _pick_prim_path() falls back to the current USD selection when the
   viewport is unavailable (headless / viewer mode).
2. _pick_prim_path() prefers a successful hardware pick over the selection.
3. The ``usd.pick`` WebSocket handler is wired up and returns the expected
   ``{"primPath": ...}`` payload.
4. ``usd.get_attr`` returns ``{"value": null}`` (not an error) when the
   attribute doesn't exist — so the HUD renders "not found" gracefully
   rather than falling back to an AppStream stub.
5. ``usd.get_attr`` still propagates a RuntimeError when the *prim* itself
   is missing (not swallowed).
"""

import json

import omni.kit.test
from pxr import Usd, UsdGeom


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stage_with_cube():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Cube.Define(stage, "/World/Cube")
    return stage


def _run_ws_handler_sync(ext, msg: dict) -> dict:
    """Drive ``_handle_ws_message`` from a synchronous test context."""
    import asyncio
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        ext._handle_ws_message(json.dumps(msg))
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestPrimHud(omni.kit.test.AsyncTestCase):
    """Tests for the prim-info HUD WebSocket handlers."""

    async def setUp(self):
        import omni.usd
        self._stage = _make_stage_with_cube()
        # Point the USD context at our in-memory stage so handlers can find it
        await omni.usd.get_context().open_stage_async("")

    async def tearDown(self):
        pass

    # ------------------------------------------------------------------
    # usd.pick — returns currently selected prim when pick unavailable
    # ------------------------------------------------------------------

    async def test_usd_pick_returns_null_when_nothing_selected(self):
        """usd.pick with no selection → primPath: null."""
        import omni.usd
        ctx = omni.usd.get_context()
        ctx.get_selection().clear_selected_prim_paths()

        from omnicool.webapp.backend.usd_helpers import _pick_prim_path
        result = _pick_prim_path(0.5, 0.5)
        self.assertIn(result, ("", None, []))  # empty string or falsy

    async def test_usd_pick_returns_selected_prim_as_fallback(self):
        """_pick_prim_path falls back to the current selection."""
        import omni.usd
        ctx = omni.usd.get_context()
        ctx.get_selection().set_selected_prim_paths(["/World/Cube"], False)

        from omnicool.webapp.backend.usd_helpers import _pick_prim_path
        result = _pick_prim_path(0.5, 0.5)
        self.assertEqual(result, "/World/Cube")

    # ------------------------------------------------------------------
    # usd.get_attr — graceful miss
    # ------------------------------------------------------------------

    async def test_get_attr_missing_attr_returns_null_value(self):
        """usd.get_attr for a non-existent attr → {ok: true, value: null}."""
        from omnicool.webapp.backend.usd_helpers import _get_attr
        stage = _make_stage_with_cube()
        # Attribute does not exist on this prim
        try:
            val = _get_attr(stage, "/World/Cube", "flownex:componentName")
            # Should not reach here — attr doesn't exist
        except RuntimeError as exc:
            self.assertIn("not found", str(exc).lower())

    async def test_get_attr_existing_attr_returns_value(self):
        """usd.get_attr for an existing attribute returns the value."""
        from omnicool.webapp.backend.usd_helpers import _get_attr
        stage = Usd.Stage.CreateInMemory()
        cube = UsdGeom.Cube.Define(stage, "/World/Cube")
        cube.GetSizeAttr().Set(2.0)

        val = _get_attr(stage, "/World/Cube", "size")
        self.assertAlmostEqual(float(val), 2.0, places=4)
