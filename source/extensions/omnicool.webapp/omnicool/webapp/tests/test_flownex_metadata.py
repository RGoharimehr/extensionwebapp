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
Tests for omnicool.webapp.flownex_metadata.

Each test method uses ``self.prim``, which lives on a fresh in-memory USD
stage (``self._stage``) created in setUp.  Keeping the stage as an instance
variable prevents Python's garbage collector from invalidating the prim
between setUp and the actual test body.

The module only depends on pxr (USD); no Omniverse runtime calls are made,
so these tests run correctly inside omni.kit.test.
"""

import json

import omni.kit.test
from pxr import Usd, UsdGeom

import omnicool.webapp.flownex_metadata as fx


# ---------------------------------------------------------------------------
# Full set of rows matching the problem-statement parameter table.
# ---------------------------------------------------------------------------

_SAMPLE_ROWS = [
    {
        "Key": "P_IT_rack",
        "Description": "Total Rack IT Load",
        "ComponentIdentifier": "Rack Power Script",
        "PropertyIdentifier": (
            "{Script}Script.Script Inputs And Outputs."
            "{Common Inputs}Total Rack IT Load"
        ),
        "EditType": "slider",
        "Min": 100, "Max": 250, "Step": 50,
        "Unit": "kW", "DefaultValue": 250,
    },
    {
        "Key": "Altitude",
        "Description": "Ambient Altitude",
        "ComponentIdentifier": "Heat Rejection",
        "PropertyIdentifier": (
            "{Script}Script.Script Inputs And Outputs."
            "{Ambient Condition}Ambient Altitude"
        ),
        "EditType": "slider",
        "Min": 0, "Max": 2000, "Step": 500,
        "Unit": "m", "DefaultValue": 0,
    },
    {
        "Key": "T_Ambient",
        "Description": "Ambient Temperature",
        "ComponentIdentifier": "Heat Rejection",
        "PropertyIdentifier": (
            "{Script}Script.Script Inputs And Outputs."
            "{Ambient Condition}Ambient Temperature"
        ),
        "EditType": "slider",
        "Min": 15, "Max": 60, "Step": 5,
        "Unit": "C", "DefaultValue": 35,
    },
    {
        "Key": "Fan_Speed",
        "Description": "Fan Speed",
        "ComponentIdentifier": "Heat Rejection",
        "PropertyIdentifier": (
            "{Script}Script.Script Inputs And Outputs."
            "{Fan}Fan Speed"
        ),
        "EditType": "slider",
        "Min": 75, "Max": 500, "Step": 25,
        "Unit": "rpm", "DefaultValue": 400,
    },
]


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestFlownexMetadata(omni.kit.test.AsyncTestCase):
    """Unit tests for flownex_metadata.py — no Omniverse runtime required."""

    # Each test gets its own fresh in-memory USD stage.
    # The stage is kept on self._stage so it is NOT garbage-collected
    # while the test coroutine is running.
    def setUp(self):
        self._stage = Usd.Stage.CreateInMemory()
        self.prim = UsdGeom.Xform.Define(
            self._stage, "/World/FlownexController"
        ).GetPrim()

    def tearDown(self):
        self._stage = None
        self.prim = None

    # ------------------------------------------------------------------
    # Core read / write
    # ------------------------------------------------------------------

    async def test_ensure_creates_defaults(self):
        meta = fx.ensure_controller_metadata(self.prim)

        self.assertEqual(meta["schemaVersion"], fx.SCHEMA_VERSION)
        self.assertIn("parameters", meta)
        self.assertIn("commandQueue", meta)
        self.assertIn("desiredProperties", meta)
        self.assertIn("observedProperties", meta)
        self.assertIn("runtime", meta)
        self.assertIn("ready", meta)
        self.assertIn("cache", meta)
        self.assertIn("intent", meta)
        self.assertEqual(meta["runtime"]["state"], "idle")

    async def test_get_returns_empty_before_ensure(self):
        self.assertEqual(fx.get_controller_metadata(self.prim), {})

    async def test_set_and_get_roundtrip(self):
        data = {"schemaVersion": 1, "custom": "hello"}
        fx.set_controller_metadata(self.prim, data)
        result = fx.get_controller_metadata(self.prim)
        self.assertEqual(result["custom"], "hello")

    async def test_metadata_stored_as_json_string(self):
        """Verify the underlying USD customData value is a plain JSON string."""
        fx.ensure_controller_metadata(self.prim)
        raw = self.prim.GetCustomData().get(fx.META_KEY)
        self.assertIsInstance(raw, str)
        parsed = json.loads(raw)
        self.assertEqual(parsed["schemaVersion"], fx.SCHEMA_VERSION)

    async def test_patch_merges_top_level(self):
        fx.ensure_controller_metadata(self.prim)
        fx.patch_controller_metadata(self.prim, {"customField": 42})
        self.assertEqual(fx.get_controller_metadata(self.prim)["customField"], 42)
        # existing keys preserved
        self.assertIn("runtime", fx.get_controller_metadata(self.prim))

    async def test_ensure_forward_fills_missing_keys(self):
        """ensure_controller_metadata must add keys absent in older stored schemas."""
        # Simulate an older persisted blob that is missing 'parameters'
        self.prim.SetCustomData(
            {fx.META_KEY: json.dumps({"schemaVersion": 1, "runtime": {"state": "idle"}})}
        )
        meta = fx.ensure_controller_metadata(self.prim)
        self.assertIn("parameters", meta)
        self.assertIn("commandQueue", meta)
        self.assertIn("desiredProperties", meta)

    async def test_invalid_prim_raises(self):
        with self.assertRaises(ValueError):
            fx.ensure_controller_metadata(None)

    # ------------------------------------------------------------------
    # Ready snapshot
    # ------------------------------------------------------------------

    async def test_set_ready_snapshot(self):
        fx.set_ready_snapshot(
            self.prim,
            attachedProject=True,
            simulationController=False,
            networkBuilder=True,
        )
        ready = fx.get_controller_metadata(self.prim)["ready"]
        self.assertTrue(ready["attachedProject"])
        self.assertFalse(ready["simulationController"])
        self.assertTrue(ready["networkBuilder"])
        self.assertIsNotNone(ready["lastCheckedUtc"])

    # ------------------------------------------------------------------
    # Runtime state
    # ------------------------------------------------------------------

    async def test_set_runtime_state_basic(self):
        fx.set_runtime_state(self.prim, state="steady_running")
        self.assertEqual(
            fx.get_controller_metadata(self.prim)["runtime"]["state"],
            "steady_running",
        )

    async def test_set_runtime_state_with_result(self):
        fx.set_runtime_state(
            self.prim,
            state="error",
            lastAction="runSteadyBlocking",
            ok=False,
            message="Timed out",
        )
        runtime = fx.get_controller_metadata(self.prim)["runtime"]
        self.assertEqual(runtime["state"], "error")
        self.assertEqual(runtime["lastAction"], "runSteadyBlocking")
        self.assertFalse(runtime["lastResult"]["ok"])
        self.assertEqual(runtime["lastResult"]["message"], "Timed out")
        self.assertIsNotNone(runtime["lastResult"]["utc"])

    async def test_set_last_run(self):
        fx.set_last_run(
            self.prim,
            run_type="steady",
            started_utc="2026-01-01T00:00:00Z",
            ended_utc="2026-01-01T00:02:00Z",
            duration_ms=120000,
        )
        last_run = fx.get_controller_metadata(self.prim)["runtime"]["lastRun"]
        self.assertEqual(last_run["type"], "steady")
        self.assertEqual(last_run["durationMs"], 120000)

    # ------------------------------------------------------------------
    # Cache summary
    # ------------------------------------------------------------------

    async def test_set_cache_summary(self):
        fx.set_cache_summary(self.prim, enabled=True, count=5, keys=["k1", "k2"])
        cache = fx.get_controller_metadata(self.prim)["cache"]
        self.assertTrue(cache["enabled"])
        self.assertEqual(cache["count"], 5)
        self.assertEqual(cache["keys"], ["k1", "k2"])

    async def test_set_cache_summary_no_keys(self):
        fx.set_cache_summary(self.prim, enabled=False, count=0)
        cache = fx.get_controller_metadata(self.prim)["cache"]
        self.assertFalse(cache["enabled"])
        self.assertNotIn("keys", cache)

    # ------------------------------------------------------------------
    # Intent helpers
    # ------------------------------------------------------------------

    async def test_set_intent_mode(self):
        fx.set_intent_mode(self.prim, "transient")
        self.assertEqual(
            fx.get_controller_metadata(self.prim)["intent"]["mode"], "transient"
        )

    async def test_set_steady_timeout_ms(self):
        fx.set_steady_timeout_ms(self.prim, 60000)
        self.assertEqual(
            fx.get_controller_metadata(self.prim)["intent"]["steady"]["timeoutMs"],
            60000,
        )

    async def test_request_transient_start(self):
        fx.request_transient(self.prim, "start")
        intent = fx.get_controller_metadata(self.prim)["intent"]
        self.assertEqual(intent["mode"], "transient")
        self.assertEqual(intent["transient"]["requested"], "start")

    async def test_request_transient_stop(self):
        fx.request_transient(self.prim, "stop")
        self.assertEqual(
            fx.get_controller_metadata(self.prim)["intent"]["transient"]["requested"],
            "stop",
        )

    # ------------------------------------------------------------------
    # Desired properties
    # ------------------------------------------------------------------

    async def test_set_desired_property(self):
        fx.set_desired_property(
            self.prim, "Condenser_01", "Mass flow rate", "0.25", unit="kg/s"
        )
        props = fx.get_desired_properties(self.prim)
        self.assertIn("Condenser_01", props)
        entry = props["Condenser_01"]["Mass flow rate"]
        self.assertEqual(entry["value"], "0.25")
        self.assertEqual(entry["unit"], "kg/s")

    async def test_set_desired_property_multiple_components(self):
        fx.set_desired_property(self.prim, "CompA", "Prop1", "1.0")
        fx.set_desired_property(self.prim, "CompB", "Prop2", "2.0")
        props = fx.get_desired_properties(self.prim)
        self.assertIn("CompA", props)
        self.assertIn("CompB", props)

    async def test_remove_desired_property_removes_entry(self):
        fx.set_desired_property(self.prim, "Comp", "Prop", "1.0")
        fx.remove_desired_property(self.prim, "Comp", "Prop")
        props = fx.get_desired_properties(self.prim)
        # Component key should be gone when last property is removed
        self.assertNotIn("Comp", props)

    async def test_remove_desired_property_keeps_other_props(self):
        fx.set_desired_property(self.prim, "Comp", "Prop1", "1.0")
        fx.set_desired_property(self.prim, "Comp", "Prop2", "2.0")
        fx.remove_desired_property(self.prim, "Comp", "Prop1")
        props = fx.get_desired_properties(self.prim)
        self.assertIn("Comp", props)
        self.assertNotIn("Prop1", props["Comp"])
        self.assertIn("Prop2", props["Comp"])

    # ------------------------------------------------------------------
    # Observed properties
    # ------------------------------------------------------------------

    async def test_set_and_get_observed_property(self):
        fx.set_observed_property(self.prim, "Heat Rejection", "Fan Speed", "450.5")
        obs = fx.get_observed_properties(self.prim)
        self.assertEqual(obs["Heat Rejection"]["Fan Speed"]["value"], "450.5")
        self.assertIsNotNone(obs["Heat Rejection"]["Fan Speed"]["readUtc"])

    async def test_set_observed_property_none_value(self):
        fx.set_observed_property(self.prim, "Comp", "Prop", None)
        obs = fx.get_observed_properties(self.prim)
        self.assertIsNone(obs["Comp"]["Prop"]["value"])

    # ------------------------------------------------------------------
    # Command queue
    # ------------------------------------------------------------------

    async def test_enqueue_returns_cmd_id(self):
        cmd_id = fx.enqueue_command(
            self.prim, "runSteadyBlocking", args={"timeoutMs": 120000}
        )
        self.assertTrue(cmd_id.startswith("cmd-"))

    async def test_list_commands_all(self):
        fx.enqueue_command(self.prim, "opA")
        fx.enqueue_command(self.prim, "opB")
        cmds = fx.list_commands(self.prim)
        self.assertEqual(len(cmds), 2)

    async def test_list_commands_filter_by_status(self):
        cid = fx.enqueue_command(self.prim, "opA")
        fx.enqueue_command(self.prim, "opB")
        fx.mark_command_status(self.prim, cid, status="applied")
        pending = fx.list_commands(self.prim, status="pending")
        applied = fx.list_commands(self.prim, status="applied")
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["op"], "opA")

    async def test_mark_command_status_applied(self):
        cid = fx.enqueue_command(self.prim, "op")
        found = fx.mark_command_status(self.prim, cid, status="applied")
        self.assertTrue(found)
        self.assertEqual(fx.list_commands(self.prim, status="pending"), [])

    async def test_mark_command_status_failed_with_error(self):
        cid = fx.enqueue_command(self.prim, "op")
        fx.mark_command_status(self.prim, cid, status="failed", error="timeout")
        self.assertEqual(fx.list_commands(self.prim)[0]["error"], "timeout")

    async def test_mark_command_status_unknown_id_returns_false(self):
        found = fx.mark_command_status(
            self.prim, "cmd-doesnotexist", status="applied"
        )
        self.assertFalse(found)

    async def test_pop_next_pending_command(self):
        cid = fx.enqueue_command(self.prim, "firstOp")
        fx.enqueue_command(self.prim, "secondOp")
        cmd = fx.pop_next_pending_command(self.prim)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["id"], cid)
        self.assertEqual(cmd["op"], "firstOp")
        # pop does NOT remove the command
        self.assertEqual(len(fx.list_commands(self.prim, status="pending")), 2)

    async def test_pop_next_pending_command_empty_queue(self):
        self.assertIsNone(fx.pop_next_pending_command(self.prim))

    # ------------------------------------------------------------------
    # Parameter table
    # ------------------------------------------------------------------

    async def test_load_parameter_table_rows_all_four(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        params = fx.get_parameters(self.prim)
        for key in ("P_IT_rack", "Altitude", "T_Ambient", "Fan_Speed"):
            self.assertIn(key, params)

    async def test_parameter_fields_stored_correctly(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        p = fx.get_parameters(self.prim)["P_IT_rack"]
        self.assertEqual(p["unit"], "kW")
        self.assertEqual(p["min"], 100.0)
        self.assertEqual(p["max"], 250.0)
        self.assertEqual(p["step"], 50.0)
        self.assertEqual(p["defaultValue"], 250.0)
        self.assertEqual(p["editType"], "slider")
        self.assertEqual(p["componentIdentifier"], "Rack Power Script")

    async def test_group_auto_extracted_common_inputs(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        self.assertEqual(
            fx.get_parameters(self.prim)["P_IT_rack"]["group"], "Common Inputs"
        )

    async def test_group_auto_extracted_ambient_condition(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        self.assertEqual(
            fx.get_parameters(self.prim)["T_Ambient"]["group"], "Ambient Condition"
        )

    async def test_group_auto_extracted_fan(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        self.assertEqual(
            fx.get_parameters(self.prim)["Fan_Speed"]["group"], "Fan"
        )

    async def test_parameter_value_defaults_to_default_value(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        self.assertEqual(fx.get_parameter_value(self.prim, "T_Ambient"), 35.0)
        self.assertEqual(fx.get_parameter_value(self.prim, "Fan_Speed"), 400.0)

    async def test_set_parameter_value_numeric(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        fx.set_parameter_value(self.prim, "T_Ambient", 40)
        self.assertEqual(fx.get_parameter_value(self.prim, "T_Ambient"), 40.0)

    async def test_set_parameter_value_string_coerced_to_float(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        fx.set_parameter_value(self.prim, "Altitude", "1500")
        self.assertEqual(fx.get_parameter_value(self.prim, "Altitude"), 1500.0)

    async def test_set_parameter_value_unknown_key_raises(self):
        fx.ensure_controller_metadata(self.prim)
        with self.assertRaises(KeyError):
            fx.set_parameter_value(self.prim, "NonExistentKey", 1.0)

    async def test_get_parameter_value_unknown_key_returns_none(self):
        fx.ensure_controller_metadata(self.prim)
        self.assertIsNone(fx.get_parameter_value(self.prim, "NoSuchKey"))

    async def test_upsert_preserves_existing_value(self):
        """Re-upserting a parameter must not reset a value the user already changed."""
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        fx.set_parameter_value(self.prim, "T_Ambient", 50)
        # Re-load same rows (simulates app restart reading config again)
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        self.assertEqual(fx.get_parameter_value(self.prim, "T_Ambient"), 50.0)

    # ------------------------------------------------------------------
    # sync_parameters_to_desired_properties
    # ------------------------------------------------------------------

    async def test_sync_writes_all_parameters_to_desired(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        fx.sync_parameters_to_desired_properties(self.prim)
        desired = fx.get_desired_properties(self.prim)
        self.assertIn("Rack Power Script", desired)
        self.assertIn("Heat Rejection", desired)

    async def test_sync_reflects_updated_value(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        fx.set_parameter_value(self.prim, "T_Ambient", 40)
        fx.sync_parameters_to_desired_properties(self.prim)
        desired = fx.get_desired_properties(self.prim)
        prop_key = (
            "{Script}Script.Script Inputs And Outputs."
            "{Ambient Condition}Ambient Temperature"
        )
        self.assertEqual(desired["Heat Rejection"][prop_key]["value"], "40.0")

    async def test_sync_default_value_before_any_set(self):
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)
        fx.sync_parameters_to_desired_properties(self.prim)
        desired = fx.get_desired_properties(self.prim)
        # Fan_Speed default is 400
        prop_key = (
            "{Script}Script.Script Inputs And Outputs."
            "{Fan}Fan Speed"
        )
        self.assertEqual(desired["Heat Rejection"][prop_key]["value"], "400.0")

    # ------------------------------------------------------------------
    # Adapter hooks (using a simple mock)
    # ------------------------------------------------------------------

    async def test_apply_desired_properties_calls_set_property_value(self):
        fx.set_desired_property(self.prim, "CompA", "Prop1", "1.5", unit="kg/s")
        fx.set_desired_property(self.prim, "CompA", "Prop2", "2.0")

        calls = []

        class MockApi:
            def SetPropertyValue(self, comp, prop, val):
                calls.append((comp, prop, val))

        fx.apply_desired_properties_to_flownex(self.prim, MockApi())
        self.assertEqual(len(calls), 2)
        self.assertIn(("CompA", "Prop1", "1.5"), calls)
        self.assertIn(("CompA", "Prop2", "2.0"), calls)
        # runtime state updated to idle + lastAction
        runtime = fx.get_controller_metadata(self.prim)["runtime"]
        self.assertEqual(runtime["state"], "idle")
        self.assertEqual(runtime["lastAction"], "applyDesiredProperties")

    async def test_refresh_observed_properties_stores_read_values(self):
        fx.set_desired_property(self.prim, "CompA", "Prop1", "1.0")

        class MockApi:
            def GetPropertyValue(self, comp, prop):
                return "99.9"

        fx.refresh_observed_properties_from_flownex(self.prim, MockApi())
        obs = fx.get_observed_properties(self.prim)
        self.assertEqual(obs["CompA"]["Prop1"]["value"], "99.9")
        runtime = fx.get_controller_metadata(self.prim)["runtime"]
        self.assertEqual(runtime["lastAction"], "refreshObservedProperties")

    # ------------------------------------------------------------------
    # End-to-end: problem-statement example workflow
    # ------------------------------------------------------------------

    async def test_full_workflow_from_problem_statement(self):
        """
        Mirrors the exact example from the problem statement:
          1. load rows
          2. set T_Ambient = 40
          3. sync to desiredProperties
          4. verify parameters and desiredProperties
        """
        fx.ensure_controller_metadata(self.prim)
        fx.load_parameter_table_rows(self.prim, _SAMPLE_ROWS)

        fx.set_parameter_value(self.prim, "T_Ambient", 40)
        fx.sync_parameters_to_desired_properties(self.prim)

        meta = fx.get_controller_metadata(self.prim)

        # parameters section
        self.assertEqual(meta["parameters"]["T_Ambient"]["value"], 40.0)

        # desiredProperties section
        prop_key = (
            "{Script}Script.Script Inputs And Outputs."
            "{Ambient Condition}Ambient Temperature"
        )
        desired = meta["desiredProperties"]
        self.assertIn("Heat Rejection", desired)
        self.assertEqual(desired["Heat Rejection"][prop_key]["value"], "40.0")
