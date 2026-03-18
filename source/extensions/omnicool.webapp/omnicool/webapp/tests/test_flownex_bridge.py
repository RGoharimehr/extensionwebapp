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

    def IsFnxAvailable(self):
        return self.FlownexInstalltionDetected


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
