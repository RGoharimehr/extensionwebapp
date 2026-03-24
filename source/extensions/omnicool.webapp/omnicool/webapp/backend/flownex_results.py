"""
Helper utilities for managing standard Flownex result attributes on USD prims.

Each USD component prim that participates in a Flownex simulation should carry
the six standard result attributes so that they can be read by any downstream
consumer (UI, export, etc.) without needing to inspect customData.

Public API
----------
RESULT_ATTRS
    Ordered dict describing each result attribute: USD attribute token,
    Flownex property identifier, SDF type, and default value.

ensure_result_attrs(prim)
    Guarantee that all six result USD attributes exist on *prim*, creating
    them with their default values when absent.  Existing attributes are
    left unchanged.

update_result_attrs(prim, values)
    Write a partial-or-full mapping of plain result name → float value onto
    the USD attributes already established by ``ensure_result_attrs``.
    ``None`` values and unknown keys are silently skipped.

fetch_and_update_from_flownex(prim, component_name, flownex_api)
    Fetch all six standard results from Flownex for *component_name* and
    persist them on *prim* via ``update_result_attrs``.  Returns a dict of
    plain result name → fetched float value (``None`` when unavailable).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Optional

from pxr import Sdf, Usd


# ---------------------------------------------------------------------------
# Standard result attribute catalogue
# ---------------------------------------------------------------------------

#: Ordered catalogue of the six standard Flownex result attributes.
#:
#: Keys are the *plain* result names used throughout the Python API
#: (e.g. ``"pressure"``).  Each entry carries:
#:
#:   ``attr``      – USD attribute token (e.g. ``"flownex:pressure"``)
#:   ``fnx_prop``  – Flownex property identifier string passed to
#:                   ``GetPropertyValue`` / ``GetPropertyValueUnit``
#:   ``sdf_type``  – ``Sdf.ValueTypeNames`` token for USD attribute creation
#:   ``default``   – default ``float`` written when the attribute is first created
RESULT_ATTRS: Dict[str, Dict[str, Any]] = OrderedDict(
    [
        (
            "volumetricFlowrate",
            {
                "attr": "flownex:volumetricFlowrate",
                "fnx_prop": "Volumetric Flow Rate",
                "sdf_type": Sdf.ValueTypeNames.Float,
                "default": 0.0,
            },
        ),
        (
            "pressure",
            {
                "attr": "flownex:pressure",
                "fnx_prop": "Pressure",
                "sdf_type": Sdf.ValueTypeNames.Float,
                "default": 0.0,
            },
        ),
        (
            "temperature",
            {
                "attr": "flownex:temperature",
                "fnx_prop": "Temperature",
                "sdf_type": Sdf.ValueTypeNames.Float,
                "default": 0.0,
            },
        ),
        (
            "massFlowrate",
            {
                "attr": "flownex:massFlowrate",
                "fnx_prop": "Mass Flow Rate",
                "sdf_type": Sdf.ValueTypeNames.Float,
                "default": 0.0,
            },
        ),
        (
            "quality",
            {
                "attr": "flownex:quality",
                "fnx_prop": "Quality",
                "sdf_type": Sdf.ValueTypeNames.Float,
                "default": 0.0,
            },
        ),
        (
            "density",
            {
                "attr": "flownex:density",
                "fnx_prop": "Density",
                "sdf_type": Sdf.ValueTypeNames.Float,
                "default": 0.0,
            },
        ),
        (
            "T_Case",
            {
                "attr": "flownex:T_Case",
                "fnx_prop": "T Case",
                "sdf_type": Sdf.ValueTypeNames.Float,
                "default": 0.0,
            },
        ),
    ]
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_valid_prim(prim: Usd.Prim) -> None:
    if prim is None or not prim.IsValid():
        raise ValueError("prim is invalid or None")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_result_attrs(prim: Usd.Prim) -> None:
    """
    Create the six standard Flownex result USD attributes on *prim* if they
    do not already exist.  Existing attributes are left unchanged.

    Call this once per component prim before any simulation data is written,
    e.g. during stage setup or when a component prim is first registered.
    """
    _require_valid_prim(prim)
    for _name, info in RESULT_ATTRS.items():
        token = info["attr"]
        if not prim.HasAttribute(token):
            attr = prim.CreateAttribute(token, info["sdf_type"], custom=True)
            attr.Set(float(info["default"]))


def update_result_attrs(
    prim: Usd.Prim,
    values: Dict[str, Optional[float]],
) -> None:
    """
    Write *values* onto the result USD attributes of *prim*.

    Parameters
    ----------
    prim:
        The USD prim that owns the result attributes.  Its attributes must
        already exist (call :func:`ensure_result_attrs` first).
    values:
        Mapping of **plain result name** (e.g. ``"pressure"``) to ``float``
        or ``None``.  Unknown keys and ``None`` values are silently skipped.
    """
    _require_valid_prim(prim)
    for name, val in values.items():
        if name not in RESULT_ATTRS or val is None:
            continue
        token = RESULT_ATTRS[name]["attr"]
        attr = prim.GetAttribute(token)
        if attr and attr.IsValid():
            try:
                attr.Set(float(val))
            except Exception as exc:
                print(
                    f"[flownex_results] Failed to set {token} on "
                    f"{prim.GetPath()}: {exc}"
                )


def fetch_and_update_from_flownex(
    prim: Usd.Prim,
    component_name: str,
    flownex_api: Any,
) -> Dict[str, Optional[float]]:
    """
    Fetch the six standard result variables from Flownex for *component_name*
    and write them onto *prim* via :func:`update_result_attrs`.

    Parameters
    ----------
    prim:
        The USD prim that represents this Flownex component.  Its result
        attributes will be created (if absent) and updated in-place.
    component_name:
        The Flownex component identifier string, e.g. ``"pipe-1"``.
    flownex_api:
        Any object exposing
        ``GetPropertyValue(componentId: str, propertyId: str) -> Optional[str]``.
        Compatible with the ``FNXApi`` class used elsewhere in this project.

    Returns
    -------
    dict
        Mapping of plain result name → fetched ``float`` value, or ``None``
        when the value could not be retrieved from Flownex.
    """
    _require_valid_prim(prim)
    ensure_result_attrs(prim)

    fetched: Dict[str, Optional[float]] = {}
    for name, info in RESULT_ATTRS.items():
        raw: Optional[str] = None
        try:
            raw = flownex_api.GetPropertyValue(component_name, info["fnx_prop"])
        except Exception as exc:
            print(
                f"[flownex_results] GetPropertyValue({component_name!r}, "
                f"{info['fnx_prop']!r}) raised: {exc}"
            )
        if raw is not None:
            try:
                fetched[name] = float(raw)
            except (TypeError, ValueError):
                fetched[name] = None
        else:
            fetched[name] = None

    update_result_attrs(prim, fetched)
    return fetched
