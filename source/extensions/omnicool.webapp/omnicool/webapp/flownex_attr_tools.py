"""
Stage-wide Flownex attribute utilities.

These helpers operate on an entire USD stage (or a sub-tree of it) rather than
on a single component prim.  They are intentionally kept separate from
``flownex_metadata.py`` and ``flownex_results.py``, which work at the
single-prim level.

Public API
----------
deinstance_and_add_flownex(root="/World") -> str
    De-instances every instanceable prim under *root*, then stamps a custom
    ``flownex:componentName`` String attribute (with ``displayGroup = 'Flownex'``)
    onto every valid, non-proxy, defined prim that does not already carry the
    attribute.  Returns a human-readable summary string.
"""

from __future__ import annotations


def deinstance_and_add_flownex(root: str = "/World") -> str:
    """
    De-instance prims and add a ``flownex:componentName`` attribute to every
    valid prim under *root* that does not already have one.

    The attribute is created with::

        attr.SetMetadata('displayGroup', 'Flownex')

    so that it appears under a *Flownex* group inside "Raw USD Properties" in
    standard USD tooling (e.g. Omniverse Stage panel).

    Parameters
    ----------
    root:
        USD path prefix used to filter the stage traversal.
        Defaults to ``"/World"``.

    Returns
    -------
    str
        A summary message of the form::

            "De-instanced 3, added Flownex attribute to 12 prims.
             Total prims with name: 0."
    """
    from pxr import Sdf, Usd
    import omni.usd

    st = omni.usd.get_context().get_stage()
    if not st:
        return "No stage loaded."

    # ------------------------------------------------------------------
    # Step 1: De-instance prims
    # ------------------------------------------------------------------
    deinstanced = 0
    for prim in st.Traverse():
        if prim.GetPath().pathString.startswith(root) and prim.IsInstance():
            prim.SetInstanceable(False)
            deinstanced += 1

    # ------------------------------------------------------------------
    # Step 2: Add flownex:componentName attribute with Flownex displayGroup
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
            ):
                continue

            # Skip prims that already carry the attribute
            if prim.HasAttribute("flownex:componentName"):
                continue

            attr = prim.CreateAttribute(
                "flownex:componentName", Sdf.ValueTypeNames.String, custom=True
            )
            attr.SetMetadata("displayGroup", "Flownex")
            added += 1

    # ------------------------------------------------------------------
    # Step 3: Count prims that have a non-empty name assigned
    # ------------------------------------------------------------------
    final_named_count = 0
    for prim in st.Traverse():
        if not prim.IsValid() or not prim.GetPath().pathString.startswith(root):
            continue
        a = prim.GetAttribute("flownex:componentName")
        if a and a.Get():
            final_named_count += 1

    return (
        f"De-instanced {deinstanced}, added Flownex attribute to {added} prims. "
        f"Total prims with name: {final_named_count}."
    )
