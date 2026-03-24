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

    **Mesh-only**: only prims whose USD type is ``Mesh`` receive Flownex
    attributes.  Xform groups, Scopes, Cameras, lights, Material/Shader prims,
    and all other non-geometry types are ignored.  This prevents USD
    "Empty typeName" errors that arise from authoring custom attributes on
    prims defined in referenced layers (e.g. ``Looks/Diffuse``), and ensures
    Flownex simulation data is only attached to actual geometry.

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
    ("flownex:T_Case",             "Float", 0.0),
]

# ---------------------------------------------------------------------------
# Only these USD prim types receive Flownex simulation attributes.
#
# Flownex models thermal/fluid behaviour of physical components, which are
# represented as UsdGeom.Mesh prims in a scene.  Every other prim type
# (Xform groups, Scope, Camera, lights, Material, Shader, …) is irrelevant
# to the simulation and must NOT be stamped.  Using an allowlist (rather than
# a blocklist) is more robust: new prim types added in future USD versions
# are automatically excluded unless explicitly added here.
#
# Using an allowlist also avoids the "Empty typeName for <attr>" USD stage
# error that occurs when custom attributes are authored (via an "over" in the
# root layer) on prims defined inside referenced layers such as Looks/Diffuse.
# ---------------------------------------------------------------------------
_MESH_PRIM_TYPES: frozenset = frozenset({
    "Mesh",
})


def _is_flownex_target(prim) -> bool:
    """Return ``True`` if *prim* should receive Flownex result attributes.

    Only prims whose USD type is ``Mesh`` qualify.  All other prim types
    (Xform, Scope, Camera, lights, Material, Shader, …) are excluded.
    """
    return prim.GetTypeName() in _MESH_PRIM_TYPES


def deinstance_and_add_flownex(root: str = "/World") -> str:
    """
    De-instance prims and stamp the full Flownex attribute family onto every
    **Mesh** prim under *root* that does not already have each attribute.

    Only prims whose USD type is ``Mesh`` are stamped.  All other prim types
    (Xform groups, Scope, Camera, lights, Material, Shader, …) are skipped.
    This prevents USD "Empty typeName" errors from prims defined in referenced
    layers (e.g. ``Looks/Diffuse``) and ensures Flownex simulation data is
    only attached to actual geometry.

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
        f"(componentName + 7 result attrs). Total prims with name: {final_named_count}."
    )


def map_outputs_to_prims(
    io_dir: str = "",
    outputs_filename: str = "Outputs.csv",
    root: str = "/World",
    out_name: str = "FlownexMapping.json",
) -> tuple:
    """
    Read *Outputs.csv* and build a mapping from Flownex component identifiers to
    USD prim paths by matching the ``flownex:componentName`` attribute.

    An optional JSON file is written with the mapping when *io_dir* and
    *out_name* are both provided.

    Parameters
    ----------
    io_dir:
        Directory that contains *outputs_filename*.  If empty, the current
        working directory is used.
    outputs_filename:
        CSV file listing Flownex outputs (must contain a
        ``ComponentIdentifier`` column).
    root:
        Only prims under this USD path are considered.
    out_name:
        Filename for the JSON mapping file written to *io_dir*.
        Pass an empty string to skip writing.

    Returns
    -------
    tuple
        ``(summary_message: str, output_file_path: str)``
    """
    import csv  # noqa: PLC0415
    import json  # noqa: PLC0415
    import os  # noqa: PLC0415

    outputs_path = (
        os.path.join(io_dir, outputs_filename) if io_dir else outputs_filename
    )

    if not os.path.isfile(outputs_path):
        return (f"Outputs file not found: {outputs_path}", "")

    # Collect component identifiers from Outputs.csv
    components: set = set()
    try:
        with open(outputs_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                comp = (row.get("ComponentIdentifier") or "").strip()
                if comp:
                    components.add(comp)
    except Exception as exc:  # noqa: BLE001
        return (f"Error reading {outputs_path}: {exc}", "")

    if not components:
        return ("No component identifiers found in Outputs.csv.", "")

    # Traverse USD stage and match against flownex:componentName
    import omni.usd  # noqa: PLC0415
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return ("No USD stage loaded.", "")

    mapping: dict = {}
    for prim in stage.Traverse():
        if not prim.IsValid():
            continue
        if not prim.GetPath().pathString.startswith(root):
            continue
        attr = prim.GetAttribute("flownex:componentName")
        if not attr or not attr.IsValid():
            continue
        comp_name = str(attr.Get() or "")
        if comp_name and comp_name in components:
            mapping[comp_name] = str(prim.GetPath())

    matched = len(mapping)
    total = len(components)

    # Write mapping JSON if requested
    out_path = ""
    if io_dir and out_name:
        out_path = os.path.join(io_dir, out_name)
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(mapping, fh, indent=2)
        except Exception as exc:  # noqa: BLE001
            return (f"Error writing {out_path}: {exc}", "")

    msg = (
        f"Mapped {matched}/{total} Flownex components to USD prims."
        + (f" Mapping saved to: {out_path}" if out_path else "")
    )
    return (msg, out_path)

