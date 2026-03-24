"""
Unit tests for omnicool.webapp.backend.config_store.

Covers:
  - load() returns defaults when no path is set
  - load() returns defaults when the file does not exist
  - save() is a no-op when no path is set
  - save() / load() round-trip persists and recovers values
  - save() merges with existing values (partial update)
  - load() returns defaults on corrupt JSON
"""

import json
import os
import tempfile
import unittest

import omni.kit.test

import omnicool.webapp.backend.config_store as cs


class TestConfigStore(omni.kit.test.AsyncTestCase):
    """Tests for config_store.save() / load() / set_path()."""

    def setUp(self):
        # Each test gets a fresh temp file; reset the module path between tests
        self._tmpdir = tempfile.mkdtemp()
        self._cfg_file = os.path.join(self._tmpdir, "omnicool_config.json")
        cs.set_path("")  # start with no path

    def tearDown(self):
        cs.set_path("")  # reset so other tests aren't affected
        # Clean up temp file
        try:
            if os.path.isfile(self._cfg_file):
                os.remove(self._cfg_file)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # load() defaults when no path is set
    # ------------------------------------------------------------------

    async def test_load_no_path_returns_defaults(self):
        """load() must return a copy of _DEFAULTS when no path is configured."""
        result = cs.load()
        self.assertIn("projectFile", result)
        self.assertIn("ioDirectory", result)
        self.assertIn("solveOnChange", result)
        self.assertIn("resultPollingInterval", result)
        self.assertEqual(result["projectFile"], "")
        self.assertEqual(result["ioDirectory"], "")

    # ------------------------------------------------------------------
    # load() defaults when file does not exist
    # ------------------------------------------------------------------

    async def test_load_missing_file_returns_defaults(self):
        """load() must return defaults when the JSON file is absent."""
        cs.set_path(self._cfg_file)
        result = cs.load()
        self.assertEqual(result["projectFile"], "")
        self.assertEqual(result["resultPollingInterval"], 1.0)

    # ------------------------------------------------------------------
    # save() no-op when no path is set
    # ------------------------------------------------------------------

    async def test_save_no_path_does_not_create_file(self):
        """save() must not create any file when set_path has not been called."""
        cs.save({"projectFile": "/some/path.proj"})
        self.assertFalse(os.path.isfile(self._cfg_file))

    # ------------------------------------------------------------------
    # Round-trip: save() then load()
    # ------------------------------------------------------------------

    async def test_round_trip_project_file(self):
        """Saved projectFile must be recovered by load()."""
        cs.set_path(self._cfg_file)
        cs.save({"projectFile": "C:/Projects/sim.proj"})
        result = cs.load()
        self.assertEqual(result["projectFile"], "C:/Projects/sim.proj")

    async def test_round_trip_io_directory(self):
        """Saved ioDirectory must be recovered by load()."""
        cs.set_path(self._cfg_file)
        cs.save({"ioDirectory": "D:/IO/Files"})
        result = cs.load()
        self.assertEqual(result["ioDirectory"], "D:/IO/Files")

    async def test_round_trip_result_polling_interval(self):
        """Saved resultPollingInterval must be recovered by load()."""
        cs.set_path(self._cfg_file)
        cs.save({"resultPollingInterval": 2.5})
        result = cs.load()
        self.assertAlmostEqual(result["resultPollingInterval"], 2.5)

    async def test_round_trip_solve_on_change(self):
        """Saved solveOnChange must be recovered by load()."""
        cs.set_path(self._cfg_file)
        cs.save({"solveOnChange": True})
        result = cs.load()
        self.assertTrue(result["solveOnChange"])

    # ------------------------------------------------------------------
    # Partial update: save() merges, does not overwrite unmentioned keys
    # ------------------------------------------------------------------

    async def test_partial_save_preserves_other_keys(self):
        """A partial save() must not reset other persisted keys."""
        cs.set_path(self._cfg_file)
        cs.save({"projectFile": "/p.proj", "ioDirectory": "/io"})
        cs.save({"resultPollingInterval": 3.0})  # only update interval
        result = cs.load()
        self.assertEqual(result["projectFile"], "/p.proj")
        self.assertEqual(result["ioDirectory"], "/io")
        self.assertAlmostEqual(result["resultPollingInterval"], 3.0)

    # ------------------------------------------------------------------
    # Unknown keys are ignored
    # ------------------------------------------------------------------

    async def test_unknown_keys_not_persisted(self):
        """Keys not in _DEFAULTS must be silently ignored."""
        cs.set_path(self._cfg_file)
        cs.save({"projectFile": "/x.proj", "unknownKey": "value"})
        with open(self._cfg_file, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertNotIn("unknownKey", raw)

    # ------------------------------------------------------------------
    # Corrupt JSON file → falls back to defaults
    # ------------------------------------------------------------------

    async def test_corrupt_json_returns_defaults(self):
        """load() must return defaults if the JSON file is corrupt."""
        cs.set_path(self._cfg_file)
        with open(self._cfg_file, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json !!!")
        result = cs.load()
        self.assertEqual(result["projectFile"], "")
        self.assertEqual(result["resultPollingInterval"], 1.0)

    # ------------------------------------------------------------------
    # File is created if parent directory exists
    # ------------------------------------------------------------------

    async def test_save_creates_file(self):
        """save() must create the JSON file on the first call."""
        cs.set_path(self._cfg_file)
        self.assertFalse(os.path.isfile(self._cfg_file))
        cs.save({"projectFile": "/created.proj"})
        self.assertTrue(os.path.isfile(self._cfg_file))
