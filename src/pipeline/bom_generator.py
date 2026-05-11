"""Part grouping and bill-of-material generation helpers."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


VIEW_ORDER = ("front", "top", "side")


def rounded_dimensions(component: dict[str, Any], precision: int = 3) -> dict[str, float]:
    """Return stable rounded dimensions for grouping and BOM rows."""
    dimensions = component["dimensions"]
    return {
        "length": round(float(dimensions["length"]), precision),
        "width": round(float(dimensions["width"]), precision),
        "height": round(float(dimensions["height"]), precision),
        "thickness": round(float(component["nominal_thickness_mm"]), precision),
    }


def build_edge_signature(component: dict[str, Any], precision: int = 3) -> str:
    """Create a stable hash from normalized orthographic edge geometry."""
    geometry_views = component["geometry"]["views"]
    serializable: list[dict[str, Any]] = []
    for view_name in VIEW_ORDER:
        edges = geometry_views.get(view_name, {}).get("edges", [])
        serializable.append(
            {
                "view": view_name,
                "edges": [
                    {
                        "start": [round(float(value), precision) for value in edge["start"]],
                        "end": [round(float(value), precision) for value in edge["end"]],
                    }
                    for edge in edges
                ],
            }
        )

    return hashlib.sha1(
        json.dumps(serializable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_part_signature(component: dict[str, Any]) -> str:
    """Build the grouping signature for one fabrication component."""
    signature_payload = {
        "object_type": component["object_type"],
        "material": component["material"],
        "material_family": component["material_family"],
        "parent_assembly": component.get("parent_assembly", "UNASSIGNED"),
        "nominal_thickness_mm": round(float(component["nominal_thickness_mm"]), 3),
        "dimensions": rounded_dimensions(component),
        "edge_signature": build_edge_signature(component),
    }
    return hashlib.sha1(
        json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def group_parts(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group identical fabrication parts and assign stable part group IDs."""
    grouped: dict[str, dict[str, Any]] = {}

    for component in components:
        signature = build_part_signature(component)
        component["part_signature"] = signature
        if signature not in grouped:
            grouped[signature] = {
                "signature": signature,
                "representative_component_id": component["instance_id"],
                "representative_component": component,
                "instance_ids": [],
                "component_ids": [],
                "quantity": 0,
                "object_type": component["object_type"],
                "part_name": component["part_name"],
                "material": component["material"],
                "material_family": component["material_family"],
                "nominal_thickness_mm": component["nominal_thickness_mm"],
                "dimensions": rounded_dimensions(component),
                "source_name": component.get("source_name", "unknown"),
                "component_name": component.get("component_name", component.get("source_name", "unknown")),
                "parent_assembly": component.get("parent_assembly", "UNASSIGNED"),
                "subassembly_id": component.get("subassembly_id", "A000"),
                "manual_review_required": component.get("fabrication", {}).get("manual_review_required", False),
                "shape": component.get("shape", "unknown"),
            }

        group = grouped[signature]
        group["instance_ids"].append(component["instance_id"])
        group["component_ids"].append(component["id"])
        group["quantity"] += 1

    part_groups: list[dict[str, Any]] = []
    for index, signature in enumerate(sorted(grouped), start=1):
        group = grouped[signature]
        group["part_group_id"] = f"P{index:03d}"
        group["file_basename"] = f"part_{index:03d}_{group['object_type']}"
        part_groups.append(group)

    group_id_by_signature = {group["signature"]: group["part_group_id"] for group in part_groups}
    for component in components:
        component["part_group_id"] = group_id_by_signature[component["part_signature"]]

    return part_groups


def generate_bom(part_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate grouped BOM rows from unique part groups."""
    rows: list[dict[str, Any]] = []
    for group in part_groups:
        shape = group.get("shape", "")
        dims = group["dimensions"]
        # Use diameter for cylindrical parts instead of width (which equals diameter anyway, but label it clearly)
        diameter_mm: float | None = None
        if shape == "cylinder":
            diameter_mm = round(min(dims.get("length", 0.0), dims.get("width", 0.0)), 3)
        rows.append(
            {
                "part_id": group["part_group_id"],
                "type": group["object_type"],
                "part_name": group["part_name"],
                "length_mm": dims.get("length"),
                "width_mm": dims.get("width"),
                "height_mm": dims.get("height"),
                "diameter_mm": diameter_mm,
                "thickness_mm": group["nominal_thickness_mm"],
                "material": group["material"],
                "quantity": group["quantity"],
                "parent_assembly": group.get("parent_assembly", "UNASSIGNED"),
                "subassembly_id": group.get("subassembly_id", "A000"),
                "source_name": group.get("source_name", "unknown"),
                "component_name": group.get("component_name", group.get("source_name", "unknown")),
                "manual_review_required": group.get("manual_review_required", False),
            }
        )
    return rows


def write_bom_csv(bom_rows: list[dict[str, Any]], output_path: Path) -> None:
    """Export grouped BOM rows as CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not bom_rows:
        output_path.write_text("", encoding="utf-8")
        return

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(bom_rows[0].keys()))
        writer.writeheader()
        writer.writerows(bom_rows)


def write_bom_json(bom_rows: list[dict[str, Any]], output_path: Path) -> None:
    """Export grouped BOM rows as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bom_rows, indent=2), encoding="utf-8")
