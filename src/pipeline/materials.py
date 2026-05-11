"""Material defaults and thickness assignment for fabrication output."""

from __future__ import annotations

from typing import Any


MATERIAL_CATALOG: dict[str, dict[str, Any]] = {
    "mdf": {
        "display_name": "MDF",
        "available_thicknesses_mm": [6, 9, 12, 18, 25],
    },
    "hmr_mdf": {
        "display_name": "HMR MDF",
        "available_thicknesses_mm": [12, 18, 25],
    },
    "plywood": {
        "display_name": "Plywood",
        "available_thicknesses_mm": [12, 18, 25],
    },
    "birch_ply": {
        "display_name": "Birch Ply",
        "available_thicknesses_mm": [12, 18, 24],
    },
    "pvc_foam_board": {
        "display_name": "PVC Foam Board",
        "available_thicknesses_mm": [3, 5, 10, 18],
    },
    "acrylic": {
        "display_name": "Acrylic",
        "available_thicknesses_mm": [3, 5, 8, 10, 12],
    },
    "acp": {
        "display_name": "ACP",
        "available_thicknesses_mm": [3, 4, 6],
    },
    "tempered_glass": {
        "display_name": "Tempered Glass",
        "available_thicknesses_mm": [6, 8, 10, 12],
    },
    "aluminum_extrusion": {
        "display_name": "Aluminum Extrusion",
        "available_thicknesses_mm": [20, 25, 30, 40, 50],
    },
    "ms_powder_coated": {
        "display_name": "MS Powder Coated",
        "available_thicknesses_mm": [20, 25, 30, 40, 50],
    },
    "stainless_steel": {
        "display_name": "Stainless Steel",
        "available_thicknesses_mm": [20, 25, 30, 40, 50],
    },
}

OBJECT_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "wall_panel": {"material_key": "mdf", "preferred_thickness_mm": 12},
    "floor_panel": {"material_key": "plywood", "preferred_thickness_mm": 18},
    "shelf": {"material_key": "mdf", "preferred_thickness_mm": 18},
    "counter": {"material_key": "plywood", "preferred_thickness_mm": 18},
    "table_top": {"material_key": "plywood", "preferred_thickness_mm": 25},
    "partition": {"material_key": "hmr_mdf", "preferred_thickness_mm": 18},
    "back_panel": {"material_key": "mdf", "preferred_thickness_mm": 6},
    "frame": {"material_key": "ms_powder_coated", "preferred_thickness_mm": 30},
    "pole": {"material_key": "stainless_steel", "preferred_thickness_mm": 50},
    "acrylic_logo": {"material_key": "acrylic", "preferred_thickness_mm": 5},
    # Primitive-based fallback types
    "cylinder_part": {"material_key": "aluminum_extrusion", "preferred_thickness_mm": 40},
    "flat_part": {"material_key": "mdf", "preferred_thickness_mm": 18},
    "box_part": {"material_key": "plywood", "preferred_thickness_mm": 18},
    "generic_part": {"material_key": "mdf", "preferred_thickness_mm": 18},
    # Freeform shapes
    "sphere": {"material_key": "ms_powder_coated", "preferred_thickness_mm": 20},
    "unknown": {"material_key": "mdf", "preferred_thickness_mm": 18},
}


def snap_nominal_thickness(material_key: str, measured_thickness_mm: float, preferred_thickness_mm: float) -> float:
    """Snap a measured thickness to the nearest available stock thickness."""
    material = MATERIAL_CATALOG[material_key]
    available = [float(value) for value in material["available_thicknesses_mm"]]
    target = measured_thickness_mm if measured_thickness_mm > 0.0 else preferred_thickness_mm
    minimum_available = min(available)
    maximum_available = max(available)

    if target < (minimum_available * 0.5) or target > (maximum_available * 1.5):
        return float(preferred_thickness_mm)

    return min(available, key=lambda thickness: (abs(thickness - target), abs(thickness - preferred_thickness_mm)))


def assign_material_and_thickness(object_type: str, measured_thickness_mm: float) -> dict[str, Any]:
    """Return the default material family and nominal stock thickness for an object type."""
    defaults = OBJECT_TYPE_DEFAULTS.get(object_type, OBJECT_TYPE_DEFAULTS["unknown"])
    material_key = defaults["material_key"]
    nominal_thickness_mm = snap_nominal_thickness(
        material_key,
        measured_thickness_mm=float(measured_thickness_mm),
        preferred_thickness_mm=float(defaults["preferred_thickness_mm"]),
    )
    material = MATERIAL_CATALOG[material_key]

    return {
        "material": material["display_name"],
        "material_family": material_key,
        "nominal_thickness_mm": nominal_thickness_mm,
    }
