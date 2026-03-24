"""Visualization utilities for Flownex simulation results on USD prims.

These helpers apply visual overrides to USD prims based on Flownex simulation
values stored as USD attributes (``flownex:<property>``).  Values are always
read from USD attributes — **not** from a JSON file.

Public API
----------
visualize_property_layer(property_name, stage=None, root="/World",
                         colormap="jet") -> dict
    Read ``flownex:<property_name>`` USD attributes from prims under *root*
    and return a summary dict with per-prim values and colours.

clear_visualization(stage=None, root="/World") -> int
    Remove any visualization colour overrides previously applied.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Recognised Flownex result property names (plain keys, no namespace)
# ---------------------------------------------------------------------------

FLOWNEX_PROPERTIES: List[str] = [
    "volumetricFlowrate",
    "pressure",
    "temperature",
    "massFlowrate",
    "quality",
    "density",
    "T_Case",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_stage(stage=None):
    """Return the active USD stage; uses omni.usd when *stage* is ``None``."""
    if stage is not None:
        return stage
    try:
        import omni.usd  # noqa: PLC0415
        return omni.usd.get_context().get_stage()
    except Exception:  # noqa: BLE001
        return None


def _get_colormap_rgb(t: float) -> Tuple[float, float, float]:
    """
    Built-in jet-like colormap mapping *t* ∈ [0, 1] to (r, g, b) ∈ [0, 1].

    colour scale: blue (0) → cyan → green → yellow → red (1).
    """
    t = max(0.0, min(1.0, float(t)))
    if t < 0.25:
        r, g, b = 0.0, t * 4.0, 1.0
    elif t < 0.5:
        r, g, b = 0.0, 1.0, 1.0 - (t - 0.25) * 4.0
    elif t < 0.75:
        r, g, b = (t - 0.5) * 4.0, 1.0, 0.0
    else:
        r, g, b = 1.0, 1.0 - (t - 0.75) * 4.0, 0.0
    return (r, g, b)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def visualize_property_layer(
    property_name: str,
    stage=None,
    root: str = "/World",
    colormap: str = "jet",
) -> Dict[str, Any]:
    """
    Read ``flownex:<property_name>`` USD attributes from all prims under
    *root* and compute per-prim colours from the value range.

    Values are read **directly from USD attributes** — not from a JSON file.

    Parameters
    ----------
    property_name:
        Plain Flownex result name, e.g. ``"pressure"`` or ``"temperature"``.
    stage:
        Optional USD stage.  When ``None`` the active ``omni.usd`` stage is used.
    root:
        Only prims whose path starts with *root* are considered.
    colormap:
        Colormap name (built-in jet-like map is always used regardless of value).

    Returns
    -------
    dict
        ``{"ok": bool, "property": str, "count": int,
           "min": float, "max": float,
           "prim_values": {path: float},
           "prim_colors": {path: [r, g, b]}}``
    """
    print(f"[viz] property = {property_name}")

    attr_token = f"flownex:{property_name}"
    st = _get_stage(stage)
    if st is None:
        log.warning("[viz] No USD stage available for property=%s", property_name)
        return {
            "ok": False,
            "property": property_name,
            "error": "No USD stage available",
            "count": 0,
            "min": 0.0,
            "max": 0.0,
            "prim_values": {},
            "prim_colors": {},
        }

    prim_values: Dict[str, float] = {}
    for prim in st.Traverse():
        if not prim.IsValid():
            continue
        if not prim.GetPath().pathString.startswith(root):
            continue
        attr = prim.GetAttribute(attr_token)
        if not attr or not attr.IsValid():
            continue
        raw = attr.Get()
        if raw is None:
            continue
        try:
            prim_values[str(prim.GetPath())] = float(raw)
        except (TypeError, ValueError):
            pass

    if not prim_values:
        print(f"[viz] count = 0, min = 0.0, max = 0.0")
        return {
            "ok": True,
            "property": property_name,
            "count": 0,
            "min": 0.0,
            "max": 0.0,
            "prim_values": {},
            "prim_colors": {},
        }

    values = list(prim_values.values())
    vmin = min(values)
    vmax = max(values)
    print(f"[viz] count = {len(prim_values)}, min = {vmin}, max = {vmax}")

    span = vmax - vmin if vmax != vmin else 1.0
    prim_colors: Dict[str, List[float]] = {}
    for path, val in prim_values.items():
        t = (val - vmin) / span
        r, g, b = _get_colormap_rgb(t)
        prim_colors[path] = [round(r, 4), round(g, 4), round(b, 4)]

    return {
        "ok": True,
        "property": property_name,
        "count": len(prim_values),
        "min": vmin,
        "max": vmax,
        "prim_values": prim_values,
        "prim_colors": prim_colors,
    }


def clear_visualization(stage=None, root: str = "/World") -> int:
    """
    Remove Flownex visualisation colour overrides from prims under *root*.

    Returns the number of prims that were cleared.
    """
    st = _get_stage(stage)
    if st is None:
        return 0

    cleared = 0
    try:
        from pxr import UsdGeom  # noqa: PLC0415
        for prim in st.Traverse():
            if not prim.IsValid():
                continue
            if not prim.GetPath().pathString.startswith(root):
                continue
            gprim = UsdGeom.Gprim(prim)
            if gprim:
                color_attr = gprim.GetDisplayColorAttr()
                if color_attr and color_attr.IsValid() and color_attr.HasAuthoredValue():
                    color_attr.Clear()
                    cleared += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("[viz] clear_visualization error: %s", exc)

    return cleared
