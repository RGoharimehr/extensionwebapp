"""
Stage-wide Flownex attribute utilities.

These helpers operate on an entire USD stage (or a sub-tree of it) rather than
on a single component prim.  They are intentionally kept separate from
``flownex_metadata.py`` and ``flownex_results.py``, which work at the
single-prim level.

Public API
----------
deinstance_and_add_flownex(root="/World") -> str
    De-instances every instanceable prim under *root*, then stamps the full
    Flownex attribute family onto every valid *simulation* prim that does not
    already carry each attribute.  The family consists of:

    * ``flownex:componentName``  (String) – display name assigned by the user
    * ``flownex:volumetricFlowrate`` (Float, default 0.0)
    * ``flownex:pressure``           (Float, default 0.0)
    * ``flownex:temperature``        (Float, default 0.0)
    * ``flownex:massFlowrate``       (Float, default 0.0)
    * ``flownex:quality``            (Float, default 0.0)
    * ``flownex:density``            (Float, default 0.0)

    All attributes are created with ``displayGroup = 'Flownex'`` so they appear
    under a *Flownex* group inside "Raw USD Properties" in standard USD tooling
    (e.g. Omniverse Stage panel).

    **Skipped prim types**: Material, Shader, NodeGraph, GeomSubset, Camera,
    all UsdLux light types, and any prim under a ``Looks`` path scope.  Creating
    custom attributes on those prims (defined in referenced layers) can produce
    USD "Empty typeName for <attr>" stage errors in the Omniverse viewport.
    Those prims do not participate in Flownex simulation regardless.

    Returns a human-readable summary string.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Full attribute family stamped on every qualifying prim.
# Each entry: (USD token, SDF type name constant, default value)
# The SDF type constants are resolved lazily inside the function so that this
# module can be imported without pxr available (e.g. during unit tests).
# ---------------------------------------------------------------------------
_RESULT_ATTRS_SPEC = [
    ("flownex:volumetricFlowrate", "Float", 0.0),
    ("flownex:pressure",           "Float", 0.0),
    ("flownex:temperature",        "Float", 0.0),
    ("flownex:massFlowrate",       "Float", 0.0),
    ("flownex:quality",            "Float", 0.0),
    ("flownex:density",            "Float", 0.0),
]

# ---------------------------------------------------------------------------
# Prim types that must NOT receive Flownex simulation attributes.
#
# Material, Shader, and related prims are commonly defined in *referenced*
# layers (e.g. under /Looks/).  When USD tries to create a custom attribute
# on such a prim via the root-layer edit target it produces an "over" spec
# that lacks a typeName, which causes the USD stage to log:
#   "Empty typeName for <path.flownex:volumetricFlowrate>"
# Skipping these prim types entirely avoids the error and is semantically
# correct – they never participate in a Flownex thermal simulation.
# ---------------------------------------------------------------------------
_SKIP_PRIM_TYPES: frozenset = frozenset({
    # Shading / material graph
    "Material",
    "Shader",
    "NodeGraph",
    # Geometry helpers
    "GeomSubset",
    # Cameras
    "Camera",
    # Light types (UsdLux schema names)
    "SphereLight",
    "DistantLight",
    "DomeLight",
    "DiskLight",
    "CylinderLight",
    "PortalLight",
    "RectLight",
    "GeometryLight",
    "PluginLight",
    "LightFilter",
})


def _is_flownex_target(prim) -> bool:
    """Return ``True`` if *prim* should receive Flownex result attributes.

    Prims are excluded when they:
    * carry a known non-simulation schema type (Material, Shader, lights, …)
    * live under a ``Looks`` path scope (USD convention for material content)
    """
    if prim.GetTypeName() in _SKIP_PRIM_TYPES:
        return False
    # Any prim nested under a scope named "Looks" is material/shader content.
    if "Looks" in prim.GetPath().pathString.split("/"):
        return False
    return True


def deinstance_and_add_flownex(root: str = "/World") -> str:
    """
    De-instance prims and stamp the full Flownex attribute family onto every
    valid simulation prim under *root* that does not already have each attribute.

    **Skipped prim types**: Material, Shader, NodeGraph, GeomSubset, Camera,
    light types, and any prim under a ``Looks`` path scope.  Creating custom
    attributes on those prims (which are typically defined in referenced layers)
    can produce USD "Empty typeName" errors, and they do not participate in
    Flownex simulation regardless.

    All created attributes carry::

        attr.SetMetadata('displayGroup', 'Flownex')

    so that they appear grouped under *Flownex* in standard USD tooling.

    Parameters
    ----------
    root:
        USD path prefix used to filter the stage traversal.
        Defaults to ``"/World"``.

    Returns
    -------
    str
        A summary message of the form::

            "De-instanced 3, added Flownex attrs to 12 prims (componentName + 6 result attrs). Total prims with name: 0."
    """
    from pxr import Sdf, Usd
    import omni.usd

    st = omni.usd.get_context().get_stage()
    if not st:
        return "No stage loaded."

    # Resolve SDF type constants once (avoid repeated attribute lookups)
    _result_attrs = [
        (token, getattr(Sdf.ValueTypeNames, sdf_name), default)
        for token, sdf_name, default in _RESULT_ATTRS_SPEC
    ]

    # ------------------------------------------------------------------
    # Step 1: De-instance prims
    # ------------------------------------------------------------------
    deinstanced = 0
    for prim in st.Traverse():
        if prim.GetPath().pathString.startswith(root) and prim.IsInstance():
            prim.SetInstanceable(False)
            deinstanced += 1

    # ------------------------------------------------------------------
    # Step 2: Stamp flownex:componentName + all result attributes
    # ------------------------------------------------------------------
    st.SetEditTarget(Usd.EditTarget(st.GetRootLayer()))
    added = 0
    with Sdf.ChangeBlock():
        for prim in st.Traverse():
            if (
                not prim.IsValid()
                or not prim.GetPath().pathString.startswith(root)
                or prim.IsInstanceProxy()
                or not prim.IsDefined()
                or not _is_flownex_target(prim)
            ):
                continue

            stamped = False

            # componentName (String)
            if not prim.HasAttribute("flownex:componentName"):
                attr = prim.CreateAttribute(
                    "flownex:componentName", Sdf.ValueTypeNames.String, custom=True
                )
                attr.SetMetadata("displayGroup", "Flownex")
                stamped = True

            # Six result Float attributes
            for token, sdf_type, default_val in _result_attrs:
                if not prim.HasAttribute(token):
                    a = prim.CreateAttribute(token, sdf_type, custom=True)
                    a.SetMetadata("displayGroup", "Flownex")
                    a.Set(default_val)
                    stamped = True

            if stamped:
                added += 1

    # ------------------------------------------------------------------
    # Step 3: Count prims that have a non-empty componentName assigned
    # ------------------------------------------------------------------
    final_named_count = 0
    for prim in st.Traverse():
        if not prim.IsValid() or not prim.GetPath().pathString.startswith(root):
            continue
        a = prim.GetAttribute("flownex:componentName")
        if a and a.Get():
            final_named_count += 1

    return (
        f"De-instanced {deinstanced}, added Flownex attrs to {added} prims "
        f"(componentName + 6 result attrs). Total prims with name: {final_named_count}."
    )
