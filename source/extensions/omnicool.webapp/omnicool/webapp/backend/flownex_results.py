from pxr import Sdf

FLOWNEX_DYNAMIC_PROPERTIES = [
    (
        "volumetricFlowrate",
        {
            "attr": "flownex:volumetricFlowrate",
            "fnx_prop": "Volumetric Flow Rate",
            "unit": "m^3/s",
            "sdf_type": Sdf.ValueTypeNames.Float,
            "default": 0.0,
        },
    ),
    (
        "pressure",
        {
            "attr": "flownex:pressure",
            "fnx_prop": "Pressure",
            "unit": "psi",
            "sdf_type": Sdf.ValueTypeNames.Float,
            "default": 0.0,
        },
    ),
    (
        "temperature",
        {
            "attr": "flownex:temperature",
            "fnx_prop": "Temperature",
            "unit": "°C",
            "sdf_type": Sdf.ValueTypeNames.Float,
            "default": 0.0,
        },
    ),
    (
        "massFlowrate",
        {
            "attr": "flownex:massFlowrate",
            "fnx_prop": "Mass Flow Rate",
            "unit": "kg/s",
            "sdf_type": Sdf.ValueTypeNames.Float,
            "default": 0.0,
        },
    ),
    (
        "quality",
        {
            "attr": "flownex:quality",
            "fnx_prop": "Quality",
            "unit": "-",
            "sdf_type": Sdf.ValueTypeNames.Float,
            "default": 0.0,
        },
    ),
    (
        "density",
        {
            "attr": "flownex:density",
            "fnx_prop": "Density",
            "unit": "kg/m^3",
            "sdf_type": Sdf.ValueTypeNames.Float,
            "default": 0.0,
        },
    ),
    (
        "T_Case",
        {
            "attr": "flownex:T_Case",
            "fnx_prop": "T_Case",
            "unit": "°C",
            "sdf_type": Sdf.ValueTypeNames.Float,
            "default": 0.0,
        },
    ),
]


def _match_component_outputs(component_name: str, outputs: dict) -> dict:
    if not component_name or not outputs:
        return {}

    component_name_l = str(component_name).lower()
    return {
        k: v for k, v in outputs.items()
        if component_name_l in str(k).lower()
    }


def _find_value_for_property(component_outputs: dict, fnx_prop_name: str):
    if not component_outputs:
        return None

    fnx_prop_name_l = fnx_prop_name.lower()
    for k, v in component_outputs.items():
        if fnx_prop_name_l in str(k).lower():
            return v
    return None


def sync_flownex_outputs_to_usd(stage, outputs: dict):
    """
    Write selected Flownex outputs to USD prim attributes.

    Rules:
    - Prim must already have flownex:componentName
    - Only these specific dynamic attrs are written:
        flownex:volumetricFlowrate
        flownex:pressure
        flownex:temperature
        flownex:massFlowrate
        flownex:quality
        flownex:density
        flownex:T_Case
    - Only changed values are written (performance)
    - Unit metadata is stored on the USD attribute
    """
    if stage is None or not outputs:
        return

    for prim in stage.Traverse():
        if not prim.IsValid():
            continue

        comp_attr = prim.GetAttribute("flownex:componentName")
        if not comp_attr:
            continue

        component_name = comp_attr.Get()
        if not component_name:
            continue

        component_outputs = _match_component_outputs(component_name, outputs)
        if not component_outputs:
            continue

        for _, prop in FLOWNEX_DYNAMIC_PROPERTIES:
            attr_name = prop["attr"]
            fnx_name = prop["fnx_prop"]
            sdf_type = prop["sdf_type"]
            unit = prop["unit"]

            value = _find_value_for_property(component_outputs, fnx_name)
            if value is None:
                continue

            try:
                new_val = float(value)
            except Exception:
                continue

            usd_attr = prim.GetAttribute(attr_name)
            if not usd_attr:
                usd_attr = prim.CreateAttribute(attr_name, sdf_type)

            old_val = usd_attr.Get()
            if old_val == new_val:
                continue

            usd_attr.Set(new_val)
            usd_attr.SetMetadata("unit", unit)
