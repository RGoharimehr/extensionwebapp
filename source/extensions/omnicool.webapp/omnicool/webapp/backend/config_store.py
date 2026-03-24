"""Lightweight persistence for the omnicool webapp configuration.

Stores ``{projectFile, ioDirectory, solveOnChange, resultPollingInterval}``
to a JSON file inside the extension's ``data/`` directory.

Public API
----------
set_path(path: str) -> None
    Set the filesystem path of the JSON config file.  Must be called once
    (e.g. in ``on_startup``) before ``load_config`` or ``save_config`` are used.

load_config() -> dict
    Load configuration from the JSON file.  Returns ``{}`` if the file does
    not exist or cannot be read.

save_config(cfg: dict) -> None
    Persist *cfg* to the JSON file.  Creates the file (and any parent
    directories) if they do not already exist.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

log = logging.getLogger(__name__)

_config_path: str = ""


def set_path(path: str) -> None:
    """Set the filesystem path of the JSON config file."""
    global _config_path
    _config_path = str(path or "")
    log.info("[config_store] config path = %s", _config_path)


def load_config() -> Dict[str, Any]:
    """Load config from the JSON file.  Returns ``{}`` on any error."""
    if not _config_path:
        return {}
    try:
        with open(_config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return dict(data) if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        log.warning("[config_store] load_config error: %s", exc)
        return {}


def save_config(cfg: Dict[str, Any]) -> None:
    """Persist *cfg* to the JSON config file."""
    if not _config_path:
        log.warning("[config_store] save_config called before set_path()")
        return
    try:
        parent = os.path.dirname(_config_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(_config_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception as exc:  # noqa: BLE001
        log.warning("[config_store] save_config error: %s", exc)
