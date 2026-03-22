"""Lightweight JSON persistence for Flownex connection settings.

Saves / loads project-file path, IO-directory, solve-on-change flag, and
result-polling interval to / from a single JSON file alongside the extension
data.  No Flownex runtime is required — this module only does file I/O.

Typical usage
-------------
In the host extension (on_startup):

    config_store.set_path(os.path.join(ext_path, "data", "omnicool_config.json"))

In the WS handler (on "configure"):

    config_store.save({"projectFile": path, "ioDirectory": io_dir, ...})

On the next startup the saved values are recovered with:

    saved = config_store.load()
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_config_path: str = ""

_DEFAULTS: Dict[str, Any] = {
    "projectFile": "",
    "ioDirectory": "",
    "solveOnChange": False,
    "resultPollingInterval": 1.0,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def set_path(path: str) -> None:
    """Set the filesystem path to the JSON config file.

    Must be called once (e.g. from ``on_startup``) before :func:`save` or
    :func:`load` are used.  If *path* is empty, both functions become no-ops
    / return defaults — safe to call without a path set.
    """
    global _config_path
    _config_path = str(path or "")


def load() -> Dict[str, Any]:
    """Return the persisted config dict.

    Falls back to :data:`_DEFAULTS` when the file does not exist, is empty,
    or is corrupt.  Never raises.
    """
    if not _config_path:
        return dict(_DEFAULTS)
    try:
        with open(_config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        out = dict(_DEFAULTS)
        out.update({k: v for k, v in data.items() if k in _DEFAULTS})
        return out
    except FileNotFoundError:
        return dict(_DEFAULTS)
    except Exception as exc:  # noqa: BLE001
        log.warning("[config_store] failed to load %s: %s", _config_path, exc)
        return dict(_DEFAULTS)


def save(cfg: Dict[str, Any]) -> None:
    """Merge *cfg* into the current persisted config and write to disk.

    Only keys that are present in :data:`_DEFAULTS` are persisted; unknown
    keys are silently ignored.  If :func:`set_path` has not been called the
    function returns immediately without writing anything.
    """
    if not _config_path:
        return
    current = load()
    current.update({k: v for k, v in cfg.items() if k in _DEFAULTS})
    try:
        dir_name = os.path.dirname(_config_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(_config_path, "w", encoding="utf-8") as fh:
            json.dump(current, fh, indent=2)
        log.info("[config_store] config saved to %s", _config_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("[config_store] failed to save %s: %s", _config_path, exc)
