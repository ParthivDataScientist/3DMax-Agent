"""Fabrication-oriented object classification helpers."""

from __future__ import annotations

from typing import Any


FLOOR_TOLERANCE_MM = 20.0


def build_assembly_context(components: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive assembly-level placement references from the component set."""
    if not components:
        return {"floor_z_mm": 0.0}

    floor_z_mm = min(
        float(component["geometry"]["bounding_box"]["min"][2])
        for component in components
    )
    return {"floor_z_mm": floor_z_mm}


def placement_for_component(component_record: dict[str, Any], assembly_context: dict[str, Any]) -> dict[str, Any]:
    """Compute simple placement metadata used by fabrication rules."""
    bounding_box = component_record["geometry"]["bounding_box"]
    minimum = [float(value) for value in bounding_box["min"]]
    maximum = [float(value) for value in bounding_box["max"]]
    bottom_z = minimum[2]
    top_z = maximum[2]
    center_z = (bottom_z + top_z) / 2.0
    on_floor = abs(bottom_z - float(assembly_context["floor_z_mm"])) <= FLOOR_TOLERANCE_MM

    return {
        "bottom_z": bottom_z,
        "top_z": top_z,
        "center_z": center_z,
        "on_floor": on_floor,
    }


def classify_object(component_analysis: dict[str, Any], assembly_context: dict[str, Any]) -> str:
    """Classify one component into a fabrication product type."""
    dimensions = component_analysis["dimensions"]
    shape = str(component_analysis.get("shape", "unknown")).lower()
    orientation = str(component_analysis.get("orientation", "unknown")).lower()
    placement = placement_for_component(component_analysis, assembly_context)

    length = float(dimensions["length"])
    width = float(dimensions["width"])
    height = float(dimensions["height"])
    thickness = float(dimensions["thickness"])
    largest_planar_size = max(length, width)
    smallest_cross_section = min(width, height)
    footprint_max = max(length, width)
    footprint_min = min(length, width)
    elongation_ratio = max(length, width, height) / max(thickness, 1.0)
    top_elevation = placement["top_z"]

    if shape == "cylinder" and orientation == "vertical" and 20.0 <= width <= 150.0:
        return "pole"

    if thickness <= 10.0 and largest_planar_size <= 1500.0 and (length * width) <= 1_200_000.0:
        return "acrylic_logo"

    if orientation == "vertical" and 6.0 <= thickness <= 25.0 and height >= 1800.0:
        return "wall_panel"

    if orientation == "vertical" and 12.0 <= thickness <= 40.0 and 1200.0 <= height <= 2200.0:
        return "partition"

    if orientation == "vertical" and 3.0 <= thickness <= 10.0 and 300.0 <= height <= 1800.0:
        return "back_panel"

    if orientation == "horizontal" and placement["on_floor"] and 12.0 <= thickness <= 40.0 and footprint_min >= 300.0:
        return "floor_panel"

    if orientation == "horizontal" and 18.0 <= thickness <= 40.0 and 650.0 <= top_elevation <= 800.0 and footprint_min >= 400.0:
        return "table_top"

    if orientation == "horizontal" and 12.0 <= thickness <= 30.0 and 150.0 <= width <= 600.0:
        return "shelf"

    if 700.0 <= height <= 1200.0 and footprint_min >= 400.0 and top_elevation >= 850.0 and shape in {"box", "irregular"}:
        return "counter"

    if elongation_ratio >= 4.0 and smallest_cross_section <= 80.0:
        return "frame"

    return "unknown"
