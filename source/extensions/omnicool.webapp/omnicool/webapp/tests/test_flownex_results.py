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
Tests for omnicool.webapp.flownex_results.

Each test method uses ``self.prim``, which lives on a fresh in-memory USD
stage (``self._stage``) created in setUp.  Keeping the stage as an instance
variable prevents Python's garbage collector from invalidating the prim
between setUp and the actual test body.

The module only depends on pxr (USD); no Omniverse runtime calls are made,
so these tests run correctly inside omni.kit.test.
"""

import omni.kit.test
from pxr import Sdf, Usd, UsdGeom

import omnicool.webapp.flownex_results as fr


# ---------------------------------------------------------------------------
# Helper mock Flownex API
# ---------------------------------------------------------------------------

class _MockFlownexApi:
    """Minimal stand-in for FNXApi.GetPropertyValue."""

    def __init__(self, return_value="1.0", raise_on=None):
        self.calls = []
        self._return_value = return_value
        self._raise_on = raise_on or set()

    def GetPropertyValue(self, component_name, property_id):
        self.calls.append((component_name, property_id))
        if property_id in self._raise_on:
            raise RuntimeError(f"Simulated error for {property_id}")
        return self._return_value


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestFlownexResults(omni.kit.test.AsyncTestCase):
    """Unit tests for flownex_results.py — no Omniverse runtime required."""

    def setUp(self):
        self._stage = Usd.Stage.CreateInMemory()
        self.prim = UsdGeom.Xform.Define(
            self._stage, "/World/Pipe1"
        ).GetPrim()

    def tearDown(self):
        self._stage = None
        self.prim = None

    # ------------------------------------------------------------------
    # RESULT_ATTRS catalogue sanity checks
    # ------------------------------------------------------------------

    async def test_result_attrs_has_six_entries(self):
        self.assertEqual(len(fr.RESULT_ATTRS), 6)

    async def test_result_attrs_contains_expected_names(self):
        expected = {
            "volumetricFlowrate",
            "pressure",
            "temperature",
            "massFlowrate",
            "quality",
            "density",
        }
        self.assertEqual(set(fr.RESULT_ATTRS.keys()), expected)

    async def test_result_attrs_all_have_required_fields(self):
        for name, info in fr.RESULT_ATTRS.items():
            self.assertIn("attr", info, msg=f"{name} missing 'attr'")
            self.assertIn("fnx_prop", info, msg=f"{name} missing 'fnx_prop'")
            self.assertIn("sdf_type", info, msg=f"{name} missing 'sdf_type'")
            self.assertIn("default", info, msg=f"{name} missing 'default'")

    async def test_result_attrs_usd_tokens_have_flownex_namespace(self):
        for name, info in fr.RESULT_ATTRS.items():
            self.assertTrue(
                info["attr"].startswith("flownex:"),
                msg=f"{name} attr token {info['attr']!r} lacks 'flownex:' prefix",
            )

    async def test_result_attrs_default_values_are_float(self):
        for name, info in fr.RESULT_ATTRS.items():
            self.assertIsInstance(
                info["default"], float,
                msg=f"{name} default should be float",
            )

    # ------------------------------------------------------------------
    # ensure_result_attrs
    # ------------------------------------------------------------------

    async def test_ensure_creates_all_six_attrs(self):
        fr.ensure_result_attrs(self.prim)
        for name, info in fr.RESULT_ATTRS.items():
            self.assertTrue(
                self.prim.HasAttribute(info["attr"]),
                msg=f"Attribute {info['attr']} not found on prim after ensure",
            )

    async def test_ensure_attrs_have_correct_sdf_type(self):
        fr.ensure_result_attrs(self.prim)
        for name, info in fr.RESULT_ATTRS.items():
            attr = self.prim.GetAttribute(info["attr"])
            self.assertTrue(attr.IsValid(), msg=f"{info['attr']} is not valid")
            self.assertEqual(
                attr.GetTypeName(),
                info["sdf_type"],
                msg=f"{info['attr']} has wrong SDF type",
            )

    async def test_ensure_attrs_have_default_values(self):
        fr.ensure_result_attrs(self.prim)
        for name, info in fr.RESULT_ATTRS.items():
            attr = self.prim.GetAttribute(info["attr"])
            self.assertAlmostEqual(
                attr.Get(),
                info["default"],
                msg=f"{info['attr']} default value mismatch",
            )

    async def test_ensure_is_idempotent(self):
        """Calling ensure_result_attrs twice must not reset values set in between."""
        fr.ensure_result_attrs(self.prim)
        # Set pressure to a non-default value
        self.prim.GetAttribute("flownex:pressure").Set(101325.0)

        fr.ensure_result_attrs(self.prim)  # second call

        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:pressure").Get(),
            101325.0,
        )

    async def test_ensure_invalid_prim_raises(self):
        with self.assertRaises(ValueError):
            fr.ensure_result_attrs(None)

    # ------------------------------------------------------------------
    # update_result_attrs
    # ------------------------------------------------------------------

    async def test_update_writes_provided_values(self):
        fr.ensure_result_attrs(self.prim)
        fr.update_result_attrs(
            self.prim,
            {
                "pressure": 200000.0,
                "temperature": 300.5,
                "density": 998.2,
            },
        )
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:pressure").Get(), 200000.0
        )
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:temperature").Get(), 300.5
        )
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:density").Get(), 998.2
        )

    async def test_update_skips_none_values(self):
        fr.ensure_result_attrs(self.prim)
        # First set pressure to a known value
        self.prim.GetAttribute("flownex:pressure").Set(50.0)
        # Update with None — must not overwrite
        fr.update_result_attrs(self.prim, {"pressure": None})
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:pressure").Get(), 50.0
        )

    async def test_update_skips_unknown_keys(self):
        fr.ensure_result_attrs(self.prim)
        # Should not raise
        fr.update_result_attrs(self.prim, {"nonExistentKey": 42.0})

    async def test_update_all_six_attrs(self):
        fr.ensure_result_attrs(self.prim)
        values = {
            "volumetricFlowrate": 0.005,
            "pressure": 101325.0,
            "temperature": 293.15,
            "massFlowrate": 5.0,
            "quality": 0.75,
            "density": 1000.0,
        }
        fr.update_result_attrs(self.prim, values)
        for name, expected in values.items():
            token = fr.RESULT_ATTRS[name]["attr"]
            self.assertAlmostEqual(
                self.prim.GetAttribute(token).Get(),
                expected,
                msg=f"{token} value mismatch",
            )

    async def test_update_invalid_prim_raises(self):
        with self.assertRaises(ValueError):
            fr.update_result_attrs(None, {"pressure": 1.0})

    # ------------------------------------------------------------------
    # fetch_and_update_from_flownex
    # ------------------------------------------------------------------

    async def test_fetch_calls_get_property_value_for_each_result(self):
        api = _MockFlownexApi(return_value="42.0")
        fr.fetch_and_update_from_flownex(self.prim, "pipe-1", api)
        called_props = {prop for (_comp, prop) in api.calls}
        expected_props = {info["fnx_prop"] for info in fr.RESULT_ATTRS.values()}
        self.assertEqual(called_props, expected_props)

    async def test_fetch_uses_correct_component_name(self):
        api = _MockFlownexApi(return_value="1.0")
        fr.fetch_and_update_from_flownex(self.prim, "pipe-1", api)
        for comp, _prop in api.calls:
            self.assertEqual(comp, "pipe-1")

    async def test_fetch_updates_prim_attrs(self):
        api = _MockFlownexApi(return_value="99.9")
        fr.fetch_and_update_from_flownex(self.prim, "pipe-1", api)
        for name, info in fr.RESULT_ATTRS.items():
            self.assertAlmostEqual(
                self.prim.GetAttribute(info["attr"]).Get(),
                99.9,
                msg=f"{info['attr']} not updated",
            )

    async def test_fetch_returns_dict_of_floats(self):
        api = _MockFlownexApi(return_value="7.5")
        result = fr.fetch_and_update_from_flownex(self.prim, "pipe-1", api)
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result.keys()), set(fr.RESULT_ATTRS.keys()))
        for name, val in result.items():
            self.assertAlmostEqual(val, 7.5, msg=f"{name} returned wrong value")

    async def test_fetch_returns_none_when_api_returns_none(self):
        api = _MockFlownexApi(return_value=None)
        result = fr.fetch_and_update_from_flownex(self.prim, "pump-2", api)
        for name, val in result.items():
            self.assertIsNone(val, msg=f"{name} should be None when API returns None")

    async def test_fetch_returns_none_when_api_raises(self):
        # Simulate an error on "Pressure"
        api = _MockFlownexApi(
            return_value="1.0",
            raise_on={"Pressure"},
        )
        result = fr.fetch_and_update_from_flownex(self.prim, "pipe-1", api)
        self.assertIsNone(result["pressure"])

    async def test_fetch_returns_none_for_non_numeric_api_response(self):
        api = _MockFlownexApi(return_value="not-a-number")
        result = fr.fetch_and_update_from_flownex(self.prim, "pipe-1", api)
        for name, val in result.items():
            self.assertIsNone(val, msg=f"{name} should be None for non-numeric value")

    async def test_fetch_creates_attrs_if_absent(self):
        """fetch_and_update_from_flownex must call ensure internally."""
        api = _MockFlownexApi(return_value="1.0")
        # No prior ensure_result_attrs call
        fr.fetch_and_update_from_flownex(self.prim, "pipe-1", api)
        for name, info in fr.RESULT_ATTRS.items():
            self.assertTrue(
                self.prim.HasAttribute(info["attr"]),
                msg=f"Attribute {info['attr']} not created by fetch",
            )

    async def test_fetch_invalid_prim_raises(self):
        api = _MockFlownexApi(return_value="1.0")
        with self.assertRaises(ValueError):
            fr.fetch_and_update_from_flownex(None, "pipe-1", api)

    # ------------------------------------------------------------------
    # Integration: ensure → fetch → verify
    # ------------------------------------------------------------------

    async def test_full_workflow_ensure_then_fetch(self):
        """
        Mirrors the expected runtime flow:
          1. Stage setup: ensure_result_attrs
          2. Simulation step: fetch_and_update_from_flownex
          3. Verify USD attributes carry Flownex results
        """
        # Stage setup
        fr.ensure_result_attrs(self.prim)

        # All attrs start at 0.0
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:pressure").Get(), 0.0
        )

        # Simulate fetching results from Flownex
        responses = {
            "Volumetric Flow Rate": "0.002",
            "Pressure": "150000.0",
            "Temperature": "320.5",
            "Mass Flow Rate": "2.1",
            "Quality": "0.85",
            "Density": "1200.0",
        }

        class _DetailedMockApi:
            def GetPropertyValue(self, comp, prop):
                return responses.get(prop)

        fr.fetch_and_update_from_flownex(self.prim, "pipe-1", _DetailedMockApi())

        # Verify each result attribute was updated
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:pressure").Get(), 150000.0
        )
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:temperature").Get(), 320.5
        )
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:quality").Get(), 0.85
        )
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:density").Get(), 1200.0
        )
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:massFlowrate").Get(), 2.1
        )
        self.assertAlmostEqual(
            self.prim.GetAttribute("flownex:volumetricFlowrate").Get(), 0.002
        )
