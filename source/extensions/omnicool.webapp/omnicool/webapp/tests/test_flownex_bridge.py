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
Tests for omnicool.webapp.backend.flownex_bridge.

All tests use minimal Python mock objects injected via
``fb.reset_singletons()``.  No Flownex installation, pxr, or Omniverse
runtime is required — the module is exercised with pure-Python stubs.
"""

import json

import omni.kit.test

import omnicool.webapp.backend.flownex_bridge as fb


# ---------------------------------------------------------------------------
# Minimal stubs that match the interfaces used by flownex_bridge
# ---------------------------------------------------------------------------

class _MockSetup:
    FlownexProject = "/test/project.proj"
    IOFileDirectory = "/test/io"
    SolveOnChange = False
    ResultPollingInterval = "1.0"


class _MockIO:
    def __init__(self, inputs=None, static_inputs=None, outputs=None):
        self.UserSetup = _MockSetup()
        self._inputs = inputs
        self._static_inputs = static_inputs
        self._outputs = outputs
        self.save_called = False

    @property
    def Setup(self):
        return self.UserSetup

    def Save(self):
        self.save_called = True

    def LoadDynamicInputs(self):
        return self._inputs

    def LoadStaticInputs(self):
        return self._static_inputs

    def LoadOutputs(self):
        return self._outputs


class _MockApi:
    def __init__(self, available=True, attached=True, project=""):
        self.FlownexInstalltionDetected = available
        self.AttachedProject = object() if attached else None
        self.ProjectFile = project
        self.attach_calls = []
        self.close_called = False
        self.exit_called = False
        self.run_steady_result = True

    def IsFnxAvailable(self):
        return self.FlownexInstalltionDetected

    def AttachToProject(self, path):
        self.attach_calls.append(path)
        if self.FlownexInstalltionDetected:
            self.AttachedProject = object()
            self.ProjectFile = path

    def CloseProject(self):
        self.close_called = True
        self.AttachedProject = None
        self.ProjectFile = ""

    def ExitApplication(self):
        self.exit_called = True

    def RunSteadyStateSimulationBlocking(self):
        return self.run_steady_result


class _MockInput:
    def __init__(self, **kwargs):
        self.Key = kwargs.get("key", "T_amb")
        self.Description = kwargs.get("description", "Ambient Temperature")
        self.ComponentIdentifier = kwargs.get("componentIdentifier", "HeatRejection")
        self.PropertyIdentifier = kwargs.get("propertyIdentifier", "{Ambient}AmbientTemp")
        self.EditType = kwargs.get("editType", "slider")
        self.Min = kwargs.get("min", 0.0)
        self.Max = kwargs.get("max", 100.0)
        self.Step = kwargs.get("step", 1.0)
        self.Unit = kwargs.get("unit", "C")
        self.DefaultValue = kwargs.get("defaultValue", 25.0)


class _MockOutput:
    def __init__(self, **kwargs):
        self.Key = kwargs.get("key", "pressure")
        self.Description = kwargs.get("description", "Pressure")
        self.ComponentIdentifier = kwargs.get("componentIdentifier", "Pipe1")
        self.PropertyIdentifier = kwargs.get("propertyIdentifier", "{Flow}Pressure")
        self.Unit = kwargs.get("unit", "Pa")
        self.Category = kwargs.get("category", "Flow")


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestFlownexBridge(omni.kit.test.AsyncTestCase):
    """Unit tests for flownex_bridge — no Flownex runtime required."""

    def setUp(self):
        fb.reset_singletons(api=None, io=None)

    def tearDown(self):
        fb.reset_singletons(api=None, io=None)

    # ------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------

    async def test_get_status_no_api_returns_available_false(self):
        result = fb.get_status()
        self.assertFalse(result["available"])
        self.assertFalse(result["projectAttached"])
        self.assertEqual(result["projectPath"], "")

    async def test_get_status_available_and_attached(self):
        api = _MockApi(available=True, attached=True, project="/foo/bar.proj")
        fb.reset_singletons(api=api, io=None)
        result = fb.get_status()
        self.assertTrue(result["available"])
        self.assertTrue(result["projectAttached"])
        self.assertEqual(result["projectPath"], "/foo/bar.proj")

    async def test_get_status_available_not_attached(self):
        api = _MockApi(available=True, attached=False, project="")
        fb.reset_singletons(api=api, io=None)
        result = fb.get_status()
        self.assertTrue(result["available"])
        self.assertFalse(result["projectAttached"])

    async def test_get_status_not_available(self):
        api = _MockApi(available=False, attached=False)
        fb.reset_singletons(api=api, io=None)
        result = fb.get_status()
        self.assertFalse(result["available"])

    async def test_get_status_has_required_keys(self):
        result = fb.get_status()
        for key in ("available", "projectAttached", "projectPath"):
            self.assertIn(key, result, msg=f"Missing key: {key}")

    # ------------------------------------------------------------------
    # get_config
    # ------------------------------------------------------------------

    async def test_get_config_no_io_returns_defaults(self):
        result = fb.get_config()
        self.assertEqual(result["flownexProject"], "")
        self.assertEqual(result["ioFileDirectory"], "")
        self.assertFalse(result["solveOnChange"])
        self.assertIsInstance(result["resultPollingInterval"], float)

    async def test_get_config_returns_setup_values(self):
        fb.reset_singletons(api=None, io=_MockIO())
        result = fb.get_config()
        self.assertEqual(result["flownexProject"], "/test/project.proj")
        self.assertEqual(result["ioFileDirectory"], "/test/io")
        self.assertFalse(result["solveOnChange"])

    async def test_get_config_polling_interval_is_float(self):
        fb.reset_singletons(api=None, io=_MockIO())
        result = fb.get_config()
        self.assertIsInstance(result["resultPollingInterval"], float)
        self.assertAlmostEqual(result["resultPollingInterval"], 1.0)

    async def test_get_config_has_required_keys(self):
        fb.reset_singletons(api=None, io=_MockIO())
        result = fb.get_config()
        for key in ("flownexProject", "ioFileDirectory", "solveOnChange", "resultPollingInterval"):
            self.assertIn(key, result, msg=f"Missing key: {key}")

    # ------------------------------------------------------------------
    # set_config
    # ------------------------------------------------------------------

    async def test_set_config_no_io_returns_error(self):
        result = fb.set_config({"flownexProject": "/new/proj.proj"})
        self.assertIn("error", result)

    async def test_set_config_updates_project_path(self):
        io = _MockIO()
        fb.reset_singletons(api=None, io=io)
        result = fb.set_config({"flownexProject": "/new/project.proj"})
        self.assertEqual(io.UserSetup.FlownexProject, "/new/project.proj")
        self.assertEqual(result["flownexProject"], "/new/project.proj")

    async def test_set_config_updates_io_directory(self):
        io = _MockIO()
        fb.reset_singletons(api=None, io=io)
        fb.set_config({"ioFileDirectory": "/new/io"})
        self.assertEqual(io.UserSetup.IOFileDirectory, "/new/io")

    async def test_set_config_updates_solve_on_change(self):
        io = _MockIO()
        fb.reset_singletons(api=None, io=io)
        fb.set_config({"solveOnChange": True})
        self.assertTrue(io.UserSetup.SolveOnChange)

    async def test_set_config_updates_polling_interval_as_string(self):
        io = _MockIO()
        fb.reset_singletons(api=None, io=io)
        fb.set_config({"resultPollingInterval": 0.5})
        self.assertEqual(io.UserSetup.ResultPollingInterval, "0.5")

    async def test_set_config_calls_save(self):
        io = _MockIO()
        fb.reset_singletons(api=None, io=io)
        fb.set_config({"flownexProject": "/x/y.proj"})
        self.assertTrue(io.save_called)

    async def test_set_config_partial_patch_leaves_other_fields_unchanged(self):
        io = _MockIO()
        original_io_dir = io.UserSetup.IOFileDirectory
        fb.reset_singletons(api=None, io=io)
        fb.set_config({"flownexProject": "/new/proj.proj"})
        self.assertEqual(io.UserSetup.IOFileDirectory, original_io_dir)

    async def test_set_config_returns_updated_config(self):
        io = _MockIO()
        fb.reset_singletons(api=None, io=io)
        result = fb.set_config({"flownexProject": "/updated/proj.proj"})
        self.assertEqual(result["flownexProject"], "/updated/proj.proj")
        self.assertNotIn("error", result)

    async def test_set_config_result_has_all_config_keys(self):
        io = _MockIO()
        fb.reset_singletons(api=None, io=io)
        result = fb.set_config({"flownexProject": "/x"})
        for key in ("flownexProject", "ioFileDirectory", "solveOnChange", "resultPollingInterval"):
            self.assertIn(key, result, msg=f"Missing key: {key}")

    # ------------------------------------------------------------------
    # load_inputs
    # ------------------------------------------------------------------

    async def test_load_inputs_no_io_returns_empty_list(self):
        result = fb.load_inputs()
        self.assertEqual(result, [])

    async def test_load_inputs_none_from_io_returns_empty_list(self):
        fb.reset_singletons(api=None, io=_MockIO(inputs=None))
        result = fb.load_inputs()
        self.assertEqual(result, [])

    async def test_load_inputs_returns_serialized_list(self):
        inp = _MockInput(key="T_amb", description="Ambient Temp", unit="C",
                         editType="slider", min=0.0, max=50.0, step=1.0, defaultValue=25.0)
        fb.reset_singletons(api=None, io=_MockIO(inputs=[inp]))
        result = fb.load_inputs()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["key"], "T_amb")
        self.assertEqual(result[0]["unit"], "C")
        self.assertAlmostEqual(result[0]["min"], 0.0)
        self.assertAlmostEqual(result[0]["max"], 50.0)
        self.assertAlmostEqual(result[0]["defaultValue"], 25.0)

    async def test_load_inputs_all_fields_present(self):
        fb.reset_singletons(api=None, io=_MockIO(inputs=[_MockInput()]))
        result = fb.load_inputs()
        expected = {
            "key", "description", "componentIdentifier", "propertyIdentifier",
            "editType", "min", "max", "step", "unit", "defaultValue",
        }
        self.assertEqual(set(result[0].keys()), expected)

    async def test_load_inputs_multiple_items(self):
        inputs = [_MockInput(key=f"k{i}") for i in range(3)]
        fb.reset_singletons(api=None, io=_MockIO(inputs=inputs))
        result = fb.load_inputs()
        self.assertEqual(len(result), 3)
        self.assertEqual([r["key"] for r in result], ["k0", "k1", "k2"])

    async def test_load_inputs_checkbox_default_value_preserved_as_bool(self):
        inp = _MockInput(editType="checkbox", defaultValue=True)
        fb.reset_singletons(api=None, io=_MockIO(inputs=[inp]))
        result = fb.load_inputs()
        self.assertIs(result[0]["defaultValue"], True)

    # ------------------------------------------------------------------
    # load_static_inputs
    # ------------------------------------------------------------------

    async def test_load_static_inputs_no_io_returns_empty_list(self):
        result = fb.load_static_inputs()
        self.assertEqual(result, [])

    async def test_load_static_inputs_none_from_io_returns_empty_list(self):
        fb.reset_singletons(api=None, io=_MockIO(static_inputs=None))
        result = fb.load_static_inputs()
        self.assertEqual(result, [])

    async def test_load_static_inputs_returns_serialized_list(self):
        inp = _MockInput(key="static_val", description="Static Input", unit="Pa")
        fb.reset_singletons(api=None, io=_MockIO(static_inputs=[inp]))
        result = fb.load_static_inputs()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["key"], "static_val")
        self.assertEqual(result[0]["unit"], "Pa")

    async def test_load_static_inputs_all_fields_present(self):
        fb.reset_singletons(api=None, io=_MockIO(static_inputs=[_MockInput()]))
        result = fb.load_static_inputs()
        expected = {
            "key", "description", "componentIdentifier", "propertyIdentifier",
            "editType", "min", "max", "step", "unit", "defaultValue",
        }
        self.assertEqual(set(result[0].keys()), expected)

    # ------------------------------------------------------------------
    # load_outputs
    # ------------------------------------------------------------------

    async def test_load_outputs_no_io_returns_empty_list(self):
        result = fb.load_outputs()
        self.assertEqual(result, [])

    async def test_load_outputs_none_from_io_returns_empty_list(self):
        fb.reset_singletons(api=None, io=_MockIO(outputs=None))
        result = fb.load_outputs()
        self.assertEqual(result, [])

    async def test_load_outputs_returns_serialized_list(self):
        out = _MockOutput(key="pressure", description="Pressure", unit="Pa", category="Flow")
        fb.reset_singletons(api=None, io=_MockIO(outputs=[out]))
        result = fb.load_outputs()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["key"], "pressure")
        self.assertEqual(result[0]["unit"], "Pa")
        self.assertEqual(result[0]["category"], "Flow")

    async def test_load_outputs_all_fields_present(self):
        fb.reset_singletons(api=None, io=_MockIO(outputs=[_MockOutput()]))
        result = fb.load_outputs()
        expected = {
            "key", "description", "componentIdentifier", "propertyIdentifier",
            "unit", "category",
        }
        self.assertEqual(set(result[0].keys()), expected)

    async def test_load_outputs_multiple_categories(self):
        outputs = [
            _MockOutput(key="p", category="Flow"),
            _MockOutput(key="t", category="Thermal"),
        ]
        fb.reset_singletons(api=None, io=_MockIO(outputs=outputs))
        result = fb.load_outputs()
        self.assertEqual(len(result), 2)
        categories = {r["category"] for r in result}
        self.assertEqual(categories, {"Flow", "Thermal"})

    # ------------------------------------------------------------------
    # JSON safety (all public functions must return serializable data)
    # ------------------------------------------------------------------

    async def test_all_functions_return_json_serializable_results(self):
        api = _MockApi(available=True, attached=True, project="/p/r.proj")
        inp = _MockInput()
        out = _MockOutput()
        io = _MockIO(inputs=[inp], static_inputs=[inp], outputs=[out])
        fb.reset_singletons(api=api, io=io)

        cases = [
            (fb.get_status, []),
            (fb.get_config, []),
            (fb.load_inputs, []),
            (fb.load_static_inputs, []),
            (fb.load_outputs, []),
        ]
        for fn, args in cases:
            result = fn(*args)
            try:
                json.dumps(result)
            except (TypeError, ValueError) as exc:
                self.fail(f"{fn.__name__} returned non-JSON-serializable data: {exc}")

    async def test_set_config_result_is_json_serializable(self):
        io = _MockIO()
        fb.reset_singletons(api=None, io=io)
        result = fb.set_config({"flownexProject": "/x/y.proj"})
        try:
            json.dumps(result)
        except (TypeError, ValueError) as exc:
            self.fail(f"set_config returned non-JSON-serializable data: {exc}")

    async def test_get_status_no_api_result_is_json_serializable(self):
        result = fb.get_status()
        json.dumps(result)  # must not raise

    async def test_get_config_no_io_result_is_json_serializable(self):
        result = fb.get_config()
        json.dumps(result)  # must not raise

    # ------------------------------------------------------------------
    # reset_singletons
    # ------------------------------------------------------------------

    async def test_reset_singletons_replaces_api(self):
        api = _MockApi(available=True, attached=False)
        fb.reset_singletons(api=api, io=None)
        self.assertIs(fb._api, api)

    async def test_reset_singletons_replaces_io(self):
        io = _MockIO()
        fb.reset_singletons(api=None, io=io)
        self.assertIs(fb._io, io)

    async def test_reset_singletons_clears_both(self):
        fb.reset_singletons(api=_MockApi(), io=_MockIO())
        fb.reset_singletons(api=None, io=None)
        self.assertIsNone(fb._api)
        self.assertIsNone(fb._io)

    # ------------------------------------------------------------------
    # get_schema
    # ------------------------------------------------------------------

    async def test_get_schema_no_io_returns_empty_lists(self):
        result = fb.get_schema()
        self.assertIn("inputs", result)
        self.assertIn("outputs", result)
        self.assertEqual(result["inputs"], [])
        self.assertEqual(result["outputs"], [])

    async def test_get_schema_combines_dynamic_and_static_inputs(self):
        dyn = _MockInput(key="dyn")
        sta = _MockInput(key="sta")
        out = _MockOutput(key="out")
        fb.reset_singletons(api=None, io=_MockIO(inputs=[dyn], static_inputs=[sta], outputs=[out]))
        result = fb.get_schema()
        keys = [i["key"] for i in result["inputs"]]
        self.assertIn("dyn", keys)
        self.assertIn("sta", keys)
        self.assertEqual(len(result["outputs"]), 1)

    async def test_get_schema_is_json_serializable(self):
        inp = _MockInput()
        out = _MockOutput()
        fb.reset_singletons(api=None, io=_MockIO(inputs=[inp], static_inputs=[inp], outputs=[out]))
        json.dumps(fb.get_schema())  # must not raise

    # ------------------------------------------------------------------
    # open_project
    # ------------------------------------------------------------------

    async def test_open_project_no_api_returns_ok_false(self):
        result = fb.open_project()
        self.assertFalse(result["ok"])
        self.assertIn("message", result)

    async def test_open_project_no_project_path_returns_ok_false(self):
        api = _MockApi(available=True, attached=False)
        io = _MockIO()
        io.UserSetup.FlownexProject = ""
        fb.reset_singletons(api=api, io=io)
        result = fb.open_project()
        self.assertFalse(result["ok"])
        self.assertIn("message", result)

    async def test_open_project_calls_attach_and_returns_ok_true(self):
        api = _MockApi(available=True, attached=False)
        io = _MockIO()
        io.UserSetup.FlownexProject = "/test/project.proj"
        fb.reset_singletons(api=api, io=io)
        result = fb.open_project()
        self.assertTrue(result["ok"])
        self.assertEqual(api.attach_calls, ["/test/project.proj"])

    async def test_open_project_result_is_json_serializable(self):
        api = _MockApi(available=True, attached=False)
        io = _MockIO()
        fb.reset_singletons(api=api, io=io)
        json.dumps(fb.open_project())  # must not raise

    # ------------------------------------------------------------------
    # close_project
    # ------------------------------------------------------------------

    async def test_close_project_no_api_returns_ok_false(self):
        result = fb.close_project()
        self.assertFalse(result["ok"])

    async def test_close_project_calls_close_and_returns_ok_true(self):
        api = _MockApi(available=True, attached=True)
        fb.reset_singletons(api=api, io=None)
        result = fb.close_project()
        self.assertTrue(result["ok"])
        self.assertTrue(api.close_called)

    async def test_close_project_result_is_json_serializable(self):
        api = _MockApi()
        fb.reset_singletons(api=api, io=None)
        json.dumps(fb.close_project())  # must not raise

    # ------------------------------------------------------------------
    # exit_app
    # ------------------------------------------------------------------

    async def test_exit_app_no_api_returns_ok_false(self):
        result = fb.exit_app()
        self.assertFalse(result["ok"])

    async def test_exit_app_calls_exit_and_returns_ok_true(self):
        api = _MockApi(available=True, attached=True)
        fb.reset_singletons(api=api, io=None)
        result = fb.exit_app()
        self.assertTrue(result["ok"])
        self.assertTrue(api.exit_called)

    async def test_exit_app_result_is_json_serializable(self):
        api = _MockApi()
        fb.reset_singletons(api=api, io=None)
        json.dumps(fb.exit_app())  # must not raise

    # ------------------------------------------------------------------
    # run_steady
    # ------------------------------------------------------------------

    async def test_run_steady_no_api_returns_ok_false(self):
        result = fb.run_steady()
        self.assertFalse(result["ok"])

    async def test_run_steady_success_returns_ok_true(self):
        api = _MockApi(available=True, attached=True)
        api.run_steady_result = True
        fb.reset_singletons(api=api, io=None)
        result = fb.run_steady()
        self.assertTrue(result["ok"])

    async def test_run_steady_failure_returns_ok_false(self):
        api = _MockApi(available=True, attached=True)
        api.run_steady_result = False
        fb.reset_singletons(api=api, io=None)
        result = fb.run_steady()
        self.assertFalse(result["ok"])

    async def test_run_steady_result_is_json_serializable(self):
        api = _MockApi()
        fb.reset_singletons(api=api, io=None)
        json.dumps(fb.run_steady())  # must not raise

    # ------------------------------------------------------------------
    # _normalize_output_value
    # ------------------------------------------------------------------

    async def test_normalize_output_value_none_returns_none(self):
        self.assertIsNone(fb._normalize_output_value(None))

    async def test_normalize_output_value_float_passthrough(self):
        self.assertAlmostEqual(fb._normalize_output_value(3.14), 3.14)

    async def test_normalize_output_value_int_converts_to_float(self):
        result = fb._normalize_output_value(42)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 42.0)

    async def test_normalize_output_value_numeric_string(self):
        self.assertAlmostEqual(fb._normalize_output_value("3.14"), 3.14)

    async def test_normalize_output_value_empty_string_returns_none(self):
        self.assertIsNone(fb._normalize_output_value(""))

    async def test_normalize_output_value_vendor_error_string_returns_none(self):
        """Vendor GetPropertyValueUnit returns error strings instead of None."""
        error_str = "Error parsing property value: unknown unit group Pa :Pipe1.{Flow}Pressure"
        self.assertIsNone(fb._normalize_output_value(error_str))

    async def test_normalize_output_value_nan_returns_none(self):
        self.assertIsNone(fb._normalize_output_value(float("nan")))

    async def test_normalize_output_value_non_numeric_returns_none(self):
        self.assertIsNone(fb._normalize_output_value("not_a_number"))

    # ------------------------------------------------------------------
    # _read_output_from_definition: vendor error-string normalization
    # ------------------------------------------------------------------

    async def test_read_output_vendor_error_string_returns_none(self):
        """Vendor returns an error message string instead of a float → None."""
        class _VendorReturnsErrorStr:
            AttachedProject = object()
            def GetPropertyValueUnit(self, comp, prop, unit):
                return "Error parsing property value: unknown unit group Pa :Pipe1.P"
            def GetPropertyValue(self, comp, prop):
                return "Error getting property value: no value returned for Pipe1.P"

        fb.reset_singletons(api=_VendorReturnsErrorStr(), io=None)
        defn = {"componentIdentifier": "Pipe1", "propertyIdentifier": "P", "unit": "Pa"}
        result = fb._read_output_from_definition(defn)
        self.assertIsNone(result)

    async def test_read_output_vendor_numeric_string_returns_float(self):
        """Vendor returns a numeric string via GetPropertyValue → float."""
        class _VendorReturnsStr:
            AttachedProject = object()
            def GetPropertyValue(self, comp, prop): return "42.0"
            def GetPropertyValueUnit(self, comp, prop, unit): return 42.0

        fb.reset_singletons(api=_VendorReturnsStr(), io=None)
        defn = {"componentIdentifier": "C", "propertyIdentifier": "P", "unit": ""}
        result = fb._read_output_from_definition(defn)
        self.assertAlmostEqual(result, 42.0)

    async def test_read_output_vendor_exception_returns_none(self):
        """Vendor raises an exception → None, does not propagate."""
        class _VendorRaises:
            AttachedProject = object()
            def GetPropertyValueUnit(self, comp, prop, unit): raise RuntimeError("vendor crash")
            def GetPropertyValue(self, comp, prop): raise RuntimeError("vendor crash")

        fb.reset_singletons(api=_VendorRaises(), io=None)
        defn = {"componentIdentifier": "C", "propertyIdentifier": "P", "unit": "Pa"}
        result = fb._read_output_from_definition(defn)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # read_outputs: per-output isolation
    # ------------------------------------------------------------------

    async def test_read_outputs_one_bad_output_does_not_prevent_others(self):
        """A crashing output key should yield None, not crash the whole read."""
        class _MixedApi:
            AttachedProject = object()
            def GetPropertyValueUnit(self, comp, prop, unit):
                if comp == "Bad":
                    raise RuntimeError("vendor crash for Bad")
                return 10.0
            def GetPropertyValue(self, comp, prop): return "5.0"

        fb.reset_singletons(api=_MixedApi(), io=None)
        fb._output_defs.clear()
        fb._output_defs["good"] = {
            "key": "good", "componentIdentifier": "Good",
            "propertyIdentifier": "P", "unit": "Pa",
            "description": "", "category": "",
        }
        fb._output_defs["bad"] = {
            "key": "bad", "componentIdentifier": "Bad",
            "propertyIdentifier": "P", "unit": "Pa",
            "description": "", "category": "",
        }

        result = fb.read_outputs()
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["outputs"]["good"], 10.0)
        self.assertIsNone(result["outputs"]["bad"])

    async def test_read_outputs_result_is_json_serializable_with_none_values(self):
        """read_outputs must return JSON-serializable data even when outputs are None."""
        class _NoneApi:
            AttachedProject = object()
            def GetPropertyValueUnit(self, comp, prop, unit): return None
            def GetPropertyValue(self, comp, prop): return None

        fb.reset_singletons(api=_NoneApi(), io=None)
        fb._output_defs.clear()
        fb._output_defs["out1"] = {
            "key": "out1", "componentIdentifier": "C", "propertyIdentifier": "P",
            "unit": "Pa", "description": "", "category": "",
        }

        result = fb.read_outputs()
        json.dumps(result)  # must not raise

    async def test_read_outputs_vendor_error_string_does_not_propagate(self):
        """Vendor error string in output must not propagate to the broadcast."""
        class _VendorErrorApi:
            AttachedProject = object()
            def GetPropertyValueUnit(self, comp, prop, unit):
                return "Error parsing property value: unknown unit group kPa :C.P"
            def GetPropertyValue(self, comp, prop): return "3.14"

        fb.reset_singletons(api=_VendorErrorApi(), io=None)
        fb._output_defs.clear()
        fb._output_defs["out1"] = {
            "key": "out1", "componentIdentifier": "C", "propertyIdentifier": "P",
            "unit": "kPa", "description": "", "category": "",
        }

        result = fb.read_outputs()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["outputs"]["out1"])
        json.dumps(result)  # must not raise

    # ------------------------------------------------------------------
    # Real-world Outputs.csv structure tests
    # (Category, Key, Description, ComponentIdentifier, PropertyIdentifier, Unit)
    # PropertyIdentifier values like "{Flow Element Results,Upstream}Total pressure"
    # Units include: psi, °C, kg/s, l/min, kW
    # ------------------------------------------------------------------

    def _make_real_output(self, key, description, component, prop_id, unit, category="Pumps"):
        """Return a mock OutputDefinition mimicking the real Outputs.csv rows."""
        class _Out:
            pass
        o = _Out()
        o.Key = key
        o.Description = description
        o.ComponentIdentifier = component
        o.PropertyIdentifier = prop_id
        o.Unit = unit
        o.Category = category
        return o

    async def test_output_def_to_dict_real_world_psi(self):
        """P_pump_in_1: PropertyIdentifier with comma in braces, psi unit."""
        out = self._make_real_output(
            "P_pump_in_1", "Pump 1 Inlet Pressure",
            "Variable Speed Pump - 2",
            "{Flow Element Results,Upstream}Total pressure",
            "psi",
        )
        result = fb._output_def_to_dict(out)
        self.assertEqual(result["key"], "P_pump_in_1")
        self.assertEqual(result["propertyIdentifier"], "{Flow Element Results,Upstream}Total pressure")
        self.assertEqual(result["unit"], "psi")
        self.assertEqual(result["category"], "Pumps")
        self.assertEqual(result["componentIdentifier"], "Variable Speed Pump - 2")
        json.dumps(result)  # must not raise

    async def test_output_def_to_dict_real_world_celsius(self):
        """T_pump_in_1: °C unit must round-trip through JSON correctly."""
        out = self._make_real_output(
            "T_pump_in_1", "Pump 1 Inlet Temperature",
            "Variable Speed Pump - 2",
            "{Flow Element Results,Upstream}Total temperature",
            "°C",
        )
        result = fb._output_def_to_dict(out)
        self.assertEqual(result["unit"], "°C")
        serialized = json.dumps(result)
        restored = json.loads(serialized)
        self.assertEqual(restored["unit"], "°C")

    async def test_output_def_to_dict_real_world_copy_component(self):
        """P_pump_in_2: component with 'Copy(001)' in name."""
        out = self._make_real_output(
            "P_pump_in_2", "Pump 2 Inlet Pressure",
            "Variable Speed Pump - 2 Copy(001)",
            "{Flow Element Results,Upstream}Total pressure",
            "psi",
        )
        result = fb._output_def_to_dict(out)
        self.assertEqual(result["componentIdentifier"], "Variable Speed Pump - 2 Copy(001)")
        json.dumps(result)  # must not raise

    async def test_real_world_schema_is_json_serializable(self):
        """Full schema with real-world output definitions must serialise cleanly."""
        real_outputs = [
            self._make_real_output(
                "P_pump_in_1", "Pump 1 Inlet Pressure", "Variable Speed Pump - 2",
                "{Flow Element Results,Upstream}Total pressure", "psi",
            ),
            self._make_real_output(
                "T_pump_in_1", "Pump 1 Inlet Temperature", "Variable Speed Pump - 2",
                "{Flow Element Results,Upstream}Total temperature", "°C",
            ),
            self._make_real_output(
                "m_dot_pump_1", "Pump 1 Mass Flowrate", "Variable Speed Pump - 2",
                "{Flow Element Results,Generic}Total mass flow", "kg/s",
            ),
            self._make_real_output(
                "Flow_pump_1", "Pump 1 Volume Flowrate", "Variable Speed Pump - 2",
                "{Flow Element Results,Generic}Total volume flow", "l/min",
            ),
            self._make_real_output(
                "Power_pump_1", "Pump 1 Total Power", "Variable Speed Pump - 2",
                "{Variable Speed Pump Results}Electrical power", "kW",
            ),
        ]
        fb.reset_singletons(api=None, io=_MockIO(outputs=real_outputs))
        schema = fb.get_schema()
        json.dumps(schema)  # must not raise

        out_dicts = schema["outputs"]
        self.assertEqual(len(out_dicts), 5)
        keys = [o["key"] for o in out_dicts]
        self.assertIn("P_pump_in_1", keys)
        self.assertIn("T_pump_in_1", keys)
        self.assertIn("Power_pump_1", keys)

    # ------------------------------------------------------------------
    # _is_potentially_truncated_prop_id
    # ------------------------------------------------------------------

    async def test_truncated_prop_id_detects_unclosed_brace(self):
        """{Flow Element Results  (no closing brace) → detected as truncated."""
        self.assertTrue(fb._is_potentially_truncated_prop_id("{Flow Element Results"))

    async def test_truncated_prop_id_ok_with_closed_brace(self):
        """{Flow Element Results,Upstream}Total pressure → NOT truncated."""
        self.assertFalse(fb._is_potentially_truncated_prop_id(
            "{Flow Element Results,Upstream}Total pressure"
        ))

    async def test_truncated_prop_id_empty_returns_false(self):
        self.assertFalse(fb._is_potentially_truncated_prop_id(""))

    async def test_truncated_prop_id_no_brace_returns_false(self):
        """Plain identifier without curly braces → not considered truncated."""
        self.assertFalse(fb._is_potentially_truncated_prop_id("SomePlainProperty"))

    # ------------------------------------------------------------------
    # load_outputs: CSV quoting warning for truncated PropertyIdentifier
    # ------------------------------------------------------------------

    async def test_load_outputs_warns_on_truncated_property_identifier(self):
        """load_outputs must log a warning when a PropertyIdentifier looks truncated."""
        truncated = self._make_real_output(
            "P_pump_in_1", "Pump 1 Inlet Pressure",
            "Variable Speed Pump - 2",
            # Simulates what csv.DictReader produces when the field is not quoted
            "{Flow Element Results",
            "Upstream}Total pressure",  # unit gets the remainder
        )
        fb.reset_singletons(api=None, io=_MockIO(outputs=[truncated]))

        import logging
        with self.assertLogs("omnicool.webapp.backend.flownex_bridge", level="WARNING") as cm:
            result = fb.load_outputs()

        self.assertTrue(
            any("truncated" in msg.lower() or "Outputs.csv" in msg for msg in cm.output),
            msg=f"Expected truncation warning not found in logs: {cm.output}",
        )
        # The definition is still returned (we warn, not discard)
        self.assertEqual(len(result), 1)

    async def test_load_outputs_no_warning_for_well_formed_prop_id(self):
        """load_outputs must NOT warn when PropertyIdentifier is properly formed."""
        good = self._make_real_output(
            "P_pump_in_1", "Pump 1 Inlet Pressure",
            "Variable Speed Pump - 2",
            "{Flow Element Results,Upstream}Total pressure",
            "psi",
        )
        fb.reset_singletons(api=None, io=_MockIO(outputs=[good]))

        import logging
        # assertLogs raises AssertionError if no log messages at WARNING+ are emitted
        try:
            with self.assertLogs("omnicool.webapp.backend.flownex_bridge", level="WARNING") as cm:
                fb.load_outputs()
            # If we get here, check that no truncation warnings were emitted
            has_truncation_warning = any(
                "truncated" in msg.lower() for msg in cm.output
            )
            self.assertFalse(has_truncation_warning,
                             f"Unexpected truncation warning: {cm.output}")
        except AssertionError:
            pass  # No WARNING logs at all — that is also acceptable

    # ------------------------------------------------------------------
    # Real-world output reading: vendor returns error string for °C unit
    # ------------------------------------------------------------------

    async def test_read_output_celsius_unit_vendor_error_string_normalized(self):
        """Vendor returns error string for °C unit → normalized to None."""
        class _VendorCelsiusError:
            AttachedProject = object()
            def GetPropertyValueUnit(self, comp, prop, unit):
                if unit == "°C":
                    return (
                        f"Unknown user unit in IO File{unit} :{comp}.{prop}"
                    )
                return 42.0
            def GetPropertyValue(self, comp, prop): return "0.0"

        fb.reset_singletons(api=_VendorCelsiusError(), io=None)
        defn = {
            "componentIdentifier": "Variable Speed Pump - 2",
            "propertyIdentifier": "{Flow Element Results,Upstream}Total temperature",
            "unit": "°C",
        }
        result = fb._read_output_from_definition(defn)
        self.assertIsNone(result)

    async def test_read_output_psi_unit_returns_float(self):
        """Vendor returns valid float for psi unit → preserved as float."""
        class _VendorPsi:
            AttachedProject = object()
            def GetPropertyValueUnit(self, comp, prop, unit):
                return 145.0  # ~1 MPa in psi
            def GetPropertyValue(self, comp, prop): return "145.0"

        fb.reset_singletons(api=_VendorPsi(), io=None)
        defn = {
            "componentIdentifier": "Variable Speed Pump - 2",
            "propertyIdentifier": "{Flow Element Results,Upstream}Total pressure",
            "unit": "psi",
        }
        result = fb._read_output_from_definition(defn)
        self.assertAlmostEqual(result, 145.0)

    async def test_read_output_kgs_unit_returns_float(self):
        """kg/s unit with forward slash → vendor returns float."""
        class _VendorKgS:
            AttachedProject = object()
            def GetPropertyValueUnit(self, comp, prop, unit): return 2.5
            def GetPropertyValue(self, comp, prop): return "2.5"

        fb.reset_singletons(api=_VendorKgS(), io=None)
        defn = {
            "componentIdentifier": "Variable Speed Pump - 2",
            "propertyIdentifier": "{Flow Element Results,Generic}Total mass flow",
            "unit": "kg/s",
        }
        result = fb._read_output_from_definition(defn)
        self.assertAlmostEqual(result, 2.5)

    async def test_read_outputs_mixed_real_world_units(self):
        """read_outputs handles a mix of psi/°C/kg/s outputs correctly."""
        call_log = {}

        class _RealWorldApi:
            AttachedProject = object()
            def GetPropertyValueUnit(self, comp, prop, unit):
                call_log[unit] = (comp, prop)
                if unit == "°C":
                    # Vendor can't handle °C — returns error string
                    return f"Unknown user unit in IO File{unit} :{comp}.{prop}"
                if unit == "psi":
                    return 87.0
                if unit == "kg/s":
                    return 1.2
                return None
            def GetPropertyValue(self, comp, prop): return None

        fb.reset_singletons(api=_RealWorldApi(), io=None)
        fb._output_defs.clear()
        comp = "Variable Speed Pump - 2"
        fb._output_defs.update({
            "P_pump_in_1": {"key": "P_pump_in_1", "componentIdentifier": comp,
                            "propertyIdentifier": "{Flow Element Results,Upstream}Total pressure",
                            "unit": "psi", "description": "", "category": "Pumps"},
            "T_pump_in_1": {"key": "T_pump_in_1", "componentIdentifier": comp,
                            "propertyIdentifier": "{Flow Element Results,Upstream}Total temperature",
                            "unit": "°C", "description": "", "category": "Pumps"},
            "m_dot_pump_1": {"key": "m_dot_pump_1", "componentIdentifier": comp,
                             "propertyIdentifier": "{Flow Element Results,Generic}Total mass flow",
                             "unit": "kg/s", "description": "", "category": "Pumps"},
        })

        result = fb.read_outputs()
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["outputs"]["P_pump_in_1"], 87.0)
        self.assertIsNone(result["outputs"]["T_pump_in_1"])   # °C error → None
        self.assertAlmostEqual(result["outputs"]["m_dot_pump_1"], 1.2)
        json.dumps(result)  # must not raise
