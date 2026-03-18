"""USD stage utility helpers.

All functions that inspect or manipulate the active USD stage, prim
selection, attribute values, and transforms live here so that
``extension.py`` stays a thin lifecycle wrapper.
"""
from __future__ import annotations

import carb
import omni.kit.app
import omni.kit.viewport.utility as vp_utils
import omni.usd
from pxr import Gf, Sdf, Tf, Usd, UsdGeom


# ---------------------------------------------------------------------------
# Stage accessor
# ---------------------------------------------------------------------------

def _stage() -> "Usd.Stage | None":
    return omni.usd.get_context().get_stage()


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------

def _get_selection_paths() -> list:
    """
    Omniverse-native "what user clicked/selected" source of truth.
    Uses SourceType.ALL to include both native USD and Fabric-backed selection.
    Works for Kit App Template and Kit CAE streaming.
    """
    ctx = omni.usd.get_context()
    sel = ctx.get_selection() if ctx else None
    if not sel:
        return []
    try:
        paths = list(sel.get_selected_prim_paths(omni.usd.Selection.SourceType.ALL))
    except TypeError:
        # Backward-compat: some environments may not support the source parameter.
        paths = list(sel.get_selected_prim_paths())
    return [str(p) for p in paths if p]


def _filter_to_valid_usd_prims(stage: "Usd.Stage", prim_paths: list) -> list:
    """
    When SourceType.ALL is used, results can include Fabric-only paths that
    don't resolve to a valid prim on the USD stage.  Keep only USD-valid prims.
    """
    out = []
    for p in prim_paths:
        try:
            prim = stage.GetPrimAtPath(p)
        except Exception:
            continue
        if prim and prim.IsValid():
            out.append(p)
    return out


def _selection_source_from_string(source: str):
    """Map a string token ('usd'/'fabric'/'all') to the SourceType enum."""
    source = (source or "all").strip().lower()
    if source == "usd":
        return omni.usd.Selection.SourceType.USD
    if source == "fabric":
        return omni.usd.Selection.SourceType.FABRIC
    return omni.usd.Selection.SourceType.ALL


async def _get_selected_prim_paths_async(
    *,
    source: str = "all",
    wait_frames: int = 2,
) -> list:
    """
    Read selected prim paths with a small frame-wait retry to mitigate selection
    propagation races (UI events and network messages arriving in the same frame).
    """
    ctx = omni.usd.get_context()
    sel = ctx.get_selection() if ctx else None
    if not sel:
        return []

    src_enum = _selection_source_from_string(source)

    for attempt in range(max(0, int(wait_frames)) + 1):
        try:
            paths = list(sel.get_selected_prim_paths(src_enum))
        except TypeError:
            paths = list(sel.get_selected_prim_paths())

        paths = [str(p) for p in paths if p]
        if paths:
            return paths

        if attempt < wait_frames:
            await omni.kit.app.get_app().next_update_async()

    return []


# ---------------------------------------------------------------------------
# Value serialisation helpers
# ---------------------------------------------------------------------------

def _usd_value_to_json(value):
    """
    Convert common pxr/USD Python types into JSON-serializable values.
    Handles Vec*, Matrix*, Vt arrays, paths, tokens, and scalar types.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, (Sdf.Path, Sdf.AssetPath)):
        return str(value)
    try:
        if isinstance(value, Tf.Token):
            return str(value)
    except Exception:
        pass

    try:
        if isinstance(value, (
            Gf.Vec2f, Gf.Vec3f, Gf.Vec4f,
            Gf.Vec2d, Gf.Vec3d, Gf.Vec4d,
            Gf.Vec2i, Gf.Vec3i, Gf.Vec4i,
            Gf.Quatf, Gf.Quatd,
        )):
            return [float(x) for x in value]
    except Exception:
        pass

    try:
        if isinstance(value, (Gf.Matrix2d, Gf.Matrix3d, Gf.Matrix4d)):
            return [[float(c) for c in row] for row in value]
    except Exception:
        pass

    try:
        if hasattr(value, "__iter__") and not isinstance(value, (bytes, bytearray)):
            return [_usd_value_to_json(v) for v in list(value)]
    except Exception:
        pass

    try:
        return float(value)
    except Exception:
        return str(value)


def _json_safe(value):
    """Convert common USD/pxr types into JSON-serializable values."""
    try:
        if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
            return [_json_safe(v) for v in list(value)]
    except Exception:
        pass

    if isinstance(value, (int, float, str, bool)) or value is None:
        return value

    try:
        return float(value)
    except Exception:
        pass

    return str(value)


# ---------------------------------------------------------------------------
# Attribute read helpers
# ---------------------------------------------------------------------------

def _read_attribute_from_prim(prim, attr_full_name: str, *, time_code=None) -> dict:
    """
    Read a named attribute from a validated USD prim.
    attr_full_name must be the full token including namespace (e.g. 'physics:mass').
    Returns a structured dict with 'found', 'typeName', 'value', 'time' fields.
    """
    if not prim or not prim.IsValid():
        raise ValueError("Prim is invalid.")
    if not attr_full_name or not isinstance(attr_full_name, str):
        raise ValueError("attr_full_name must be a non-empty string.")

    if not prim.HasAttribute(attr_full_name):
        return {"found": False, "reason": "attribute_missing", "attr": attr_full_name}

    attr = prim.GetAttribute(attr_full_name)
    if not attr or not attr.IsValid():
        return {"found": False, "reason": "attribute_missing", "attr": attr_full_name}

    type_name = attr.GetTypeName()
    type_str = str(type_name) if type_name else None

    if time_code is None:
        value = attr.Get()
        time_repr = "default"
    else:
        tc = Usd.TimeCode(float(time_code))
        value = attr.Get(tc)
        time_repr = float(time_code)

    return {
        "found": True,
        "attr": attr_full_name,
        "typeName": type_str,
        "time": time_repr,
        "value": _usd_value_to_json(value),
    }


# ---------------------------------------------------------------------------
# Prim / stage query helpers
# ---------------------------------------------------------------------------

def _prim_exists(stage, prim_path: str) -> bool:
    if not prim_path:
        return False
    prim = stage.GetPrimAtPath(prim_path)
    return prim.IsValid()


def _list_children(stage, prim_path: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    return [str(p.GetPath()) for p in prim.GetChildren()]


def _list_attrs(stage, prim_path: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    return [a.GetName() for a in prim.GetAttributes()]


def _get_attr(stage, prim_path: str, attr_name: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr:
        raise RuntimeError(f"Attribute not found: {attr_name}")
    val = attr.Get()
    return val


# ---------------------------------------------------------------------------
# Attribute write helpers
# ---------------------------------------------------------------------------

_USD_VEC_TYPES = {
    "float2": Gf.Vec2f, "float3": Gf.Vec3f, "float4": Gf.Vec4f,
    "double2": Gf.Vec2d, "double3": Gf.Vec3d, "double4": Gf.Vec4d,
    "half2": Gf.Vec2h, "half3": Gf.Vec3h, "half4": Gf.Vec4h,
    "int2": Gf.Vec2i, "int3": Gf.Vec3i, "int4": Gf.Vec4i,
    "color3f": Gf.Vec3f, "color4f": Gf.Vec4f,
    "color3d": Gf.Vec3d, "color4d": Gf.Vec4d,
    "normal3f": Gf.Vec3f, "normal3d": Gf.Vec3d,
    "point3f": Gf.Vec3f, "point3d": Gf.Vec3d,
    "vector3f": Gf.Vec3f, "vector3d": Gf.Vec3d,
    "texCoord2f": Gf.Vec2f, "texCoord3f": Gf.Vec3f,
    "matrix2d": Gf.Matrix2d, "matrix3d": Gf.Matrix3d, "matrix4d": Gf.Matrix4d,
    "quatf": Gf.Quatf, "quatd": Gf.Quatd,
}


def _coerce_value_for_attr(attr, value):
    """Convert a JSON-decoded value to the correct Python/USD type for the attribute."""
    if value is None:
        return value
    try:
        type_name = attr.GetTypeName()
        if not type_name:
            return value
        type_str = str(type_name)
        if type_str in ("float", "double", "half"):
            return float(value)
        if type_str in ("int", "int64", "uint", "uint64", "uchar"):
            return int(value)
        if type_str == "bool":
            return bool(value)
        if type_str in ("string", "token", "asset"):
            return str(value)
        if isinstance(value, (list, tuple)):
            gf_type = _USD_VEC_TYPES.get(type_str)
            if gf_type:
                return gf_type(*value)
    except Exception:
        pass
    return value


def _set_attr(stage, prim_path: str, attr_name: str, value):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr:
        raise RuntimeError(f"Attribute not found: {attr_name}")
    coerced = _coerce_value_for_attr(attr, value)
    ok = attr.Set(coerced)
    if not ok:
        raise RuntimeError("USD attr.Set returned False")
    return True


def _create_attr(stage, prim_path: str, attr_name: str, type_name_str: str, value=None):
    """Create a new attribute on a prim with the given SdfValueTypeName string."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    sdf_type = Sdf.ValueTypeNames.Find(type_name_str)
    if not sdf_type:
        raise RuntimeError(f"Unknown USD type name: {type_name_str}")
    attr = prim.CreateAttribute(attr_name, sdf_type)
    if not attr:
        raise RuntimeError(f"Failed to create attribute: {attr_name}")
    if value is not None:
        coerced = _coerce_value_for_attr(attr, value)
        attr.Set(coerced)
    return True


def _delete_attr(stage, prim_path: str, attr_name: str):
    """Remove an attribute from a prim."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr:
        raise RuntimeError(f"Attribute not found: {attr_name}")
    prim.RemoveProperty(attr_name)
    return True


# ---------------------------------------------------------------------------
# Transform helper
# ---------------------------------------------------------------------------

def _get_xform(stage, prim_path: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Prim not found: {prim_path}")

    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        raise RuntimeError(f"Prim is not Xformable: {prim_path}")

    mat, _ = xformable.GetLocalTransformation()
    return [[float(mat[r][c]) for c in range(4)] for r in range(4)]


# ---------------------------------------------------------------------------
# Viewport pick helper
# ---------------------------------------------------------------------------

def _pick_prim_path(norm_x: float, norm_y: float) -> str:
    """
    Pick a prim in the active viewport using normalized coordinates [0..1].

    Tries hardware raycast picking via omni.kit.raycast.query when the viewport
    is available.  Falls back to returning the first currently-selected prim so
    the workflow "select a prim, then trigger inspection" always works even when
    GPU picking is unavailable (e.g., headless or viewer mode).

    Returns the prim path string or "" if nothing is found.
    """
    try:
        vp = vp_utils.get_active_viewport_window()
        if vp is not None:
            try:
                w, h = vp.get_texture_resolution()
            except Exception:
                w, h = 0, 0
            if w and h:
                px = int(norm_x * w)
                py_flipped = int((1.0 - norm_y) * h)
                import importlib
                for api in ("omni.kit.raycast.query",):
                    try:
                        mod = importlib.import_module(api)
                        pick_fn = getattr(mod, "pick_prim", None)
                        if pick_fn is not None:
                            hit = pick_fn(px, py_flipped)
                            if hit and getattr(hit, "prim_path", None):
                                return str(hit.prim_path)
                            hit = pick_fn(px, int(norm_y * h))
                            if hit and getattr(hit, "prim_path", None):
                                return str(hit.prim_path)
                    except Exception:
                        pass
    except Exception as e:
        carb.log_warn(f"[omnicool.webapp][pick] viewport pick failed: {e}")

    paths = _get_selection_paths()
    return paths[0] if paths else ""
