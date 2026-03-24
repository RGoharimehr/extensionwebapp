import json
import os

_CONFIG_PATH = None


def set_path(path: str):
    global _CONFIG_PATH
    _CONFIG_PATH = path


def load_config():
    if not _CONFIG_PATH:
        return {}
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict):
    if not _CONFIG_PATH:
        raise RuntimeError("Config path not set")
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
