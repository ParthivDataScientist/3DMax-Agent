"""End-to-end fabrication package generator for OBJ exhibition/furniture models."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from bom_generator import generate_bom, group_parts, write_bom_csv, write_bom_json
from classification import build_assembly_context, classify_object, placement_for_component
from fabrication_drawings import (
    generate_assembly_and_elevation_drawings,
    generate_part_detail_drawings,
    generate_subassembly_drawings,
    slugify,
)
from geometry_pipeline import ExtractionError, extract_measurements, round_number
from materials import assign_material_and_thickness


def normalize_path_argument(path_parts: list[str]) -> Path:
    """Join CLI path tokens so unquoted paths with spaces still work."""
    return Path(" ".join(path_parts)).expanduser()


def display_part_name(object_type: str) -> str:
    """Convert a snake_case object type into a fabrication title."""
    return object_type.replace("_", " ").upper()


ASSEMBLY_PREFIXES = (
    ("floor_platform", "BOOTH FLOOR"),
    ("back_wall", "BOOTH WALLS"),
    ("left_wall", "BOOTH WALLS"),
    ("right_wall", "BOOTH WALLS"),
    ("front_left_square_post", "BOOTH FRAME"),
    ("front_right_square_post", "BOOTH FRAME"),
    ("back_left_square_post", "BOOTH FRAME"),
    ("back_right_square_post", "BOOTH FRAME"),
    ("mid_back_square_post", "BOOTH FRAME"),
    ("front_open_header", "BOOTH FRAME"),
    ("back_header", "BOOTH FRAME"),
    ("left_header", "BOOTH FRAME"),
    ("right_header", "BOOTH FRAME"),
    ("backlit_brand", "BRAND SIGNAGE"),
    ("small_logo", "BRAND SIGNAGE"),
    ("center_table", "CENTER TABLE"),
    ("shoe_rack", "SHOE RACK"),
    ("front_demo_counter", "FRONT DEMO COUNTER"),
    ("left_display", "LEFT DISPLAY SHELVES"),
    ("brochure_stand", "BROCHURE STAND"),
    ("brochure_holder", "BROCHURE STAND"),
)


def clean_display_name(value: str) -> str:
    """Convert an OBJ object name into a readable all-caps label."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", value).strip()
    return normalized.upper() or "UNNAMED COMPONENT"


def parent_assembly_name(source_name: str, object_type: str) -> str:
    """Derive the parent/subassembly name for a component."""
    normalized = source_name.strip().lower()
    for prefix, display_name in ASSEMBLY_PREFIXES:
        if normalized.startswith(prefix):
            return display_name

    tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if token]
    if len(tokens) >= 2:
        return clean_display_name("_".join(tokens[:2]))
    if tokens:
        return clean_display_name(tokens[0])
    return display_part_name(object_type)


def assign_subassembly_metadata(components: list[dict[str, Any]]) -> None:
    """Attach component and parent-assembly names used by drawings and schedules."""
    for component in components:
        source_name = str(component.get("source_name") or "")
        object_type = str(component.get("object_type") or "generic_part")
        component["component_name"] = clean_display_name(source_name)
        component["parent_assembly"] = parent_assembly_name(source_name, object_type)

    ordered_names = sorted({str(component.get("parent_assembly") or "UNASSIGNED") for component in components})
    subassembly_ids = {name: f"A{index:03d}" for index, name in enumerate(ordered_names, start=1)}
    for component in components:
        component["subassembly_id"] = subassembly_ids[str(component.get("parent_assembly") or "UNASSIGNED")]


def enrich_fabrication_metadata(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Classify components, assign materials, group identical parts, and build BOM rows."""
    components = payload.get("components", [])
    assembly_context = build_assembly_context(components)
    object_type_counts: Counter[str] = Counter()

    for index, component in enumerate(components, start=1):
        object_type = classify_object(component, assembly_context)
        measured_thickness_mm = float(component["dimensions"]["thickness"])
        material_assignment = assign_material_and_thickness(object_type, measured_thickness_mm)
        placement = placement_for_component(component, assembly_context)

        component["instance_id"] = f"C{index:03d}"
        component["object_type"] = object_type
        component["part_name"] = display_part_name(object_type)
        component["measured_thickness_mm"] = round_number(measured_thickness_mm)
        component["placement"] = {
            key: round_number(float(value)) if key != "on_floor" else bool(value)
            for key, value in placement.items()
        }
        component.update(material_assignment)
        object_type_counts[object_type] += 1

    assign_subassembly_metadata(components)
    part_groups = group_parts(components)
    bom_rows = generate_bom(part_groups)
    payload.setdefault("component_summary", {})["object_type_counts"] = dict(object_type_counts)
    return part_groups, bom_rows, assembly_context


def serializable_part_groups(
    part_groups: list[dict[str, Any]],
    drawing_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove in-memory object references before writing the enriched analysis JSON."""
    drawings_by_group_id = {record["part_group_id"]: record for record in drawing_records}
    serialized: list[dict[str, Any]] = []

    for group in part_groups:
        drawing_record = drawings_by_group_id.get(group["part_group_id"], {})
        serialized.append(
            {
                "part_group_id": group["part_group_id"],
                "signature": group["signature"],
                "object_type": group["object_type"],
                "part_name": group["part_name"],
                "material": group["material"],
                "material_family": group["material_family"],
                "nominal_thickness_mm": group["nominal_thickness_mm"],
                "quantity": group["quantity"],
                "instance_ids": list(group["instance_ids"]),
                "component_ids": list(group["component_ids"]),
                "representative_component_id": group["representative_component_id"],
                "dimensions": group["dimensions"],
                "file_basename": group["file_basename"],
                "source_name": group.get("source_name", "unknown"),
                "component_name": group.get("component_name", group.get("source_name", "unknown")),
                "parent_assembly": group.get("parent_assembly", "UNASSIGNED"),
                "subassembly_id": group.get("subassembly_id", "A000"),
                "manual_review_required": group.get("manual_review_required", False),
                "shape": group.get("shape", "unknown"),
                "files": drawing_record.get("files", []),
                "sheet": drawing_record.get("sheet"),
                "scale": drawing_record.get("scale"),
            }
        )

    return serialized


def build_output_structure(
    package_root: Path,
    analysis_path: Path,
    component_schedule_path: Path,
    bom_csv_path: Path,
    bom_json_path: Path,
    assembly_records: dict[str, Any],
    subassembly_records: list[dict[str, Any]],
    part_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a JSON-friendly manifest of generated fabrication artifacts."""
    return {
        "root": str(package_root),
        "analysis": {
            "json": str(analysis_path),
            "component_schedule_csv": str(component_schedule_path),
        },
        "analysis_json": str(analysis_path),
        "assembly": assembly_records.get("assembly", []),
        "elevations": assembly_records.get("elevations", []),
        "sheets": assembly_records.get("sheets", []),
        "subassemblies": subassembly_records,
        "parts": part_records,
        "bom": {
            "csv": str(bom_csv_path),
            "json": str(bom_json_path),
        },
    }


def component_schedule_rows(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create a flat component measurement schedule for booth review."""
    rows: list[dict[str, Any]] = []
    for component in components:
        dimensions = component.get("dimensions", {})
        placement = component.get("placement", {})
        bounding_box = component.get("geometry", {}).get("bounding_box", {})
        bbox_size = bounding_box.get("size", [None, None, None])
        flags = component.get("fabrication", {}).get("flags", [])
        rows.append(
            {
                "instance_id": component.get("instance_id"),
                "source_name": component.get("source_name"),
                "component_name": component.get("component_name"),
                "parent_assembly": component.get("parent_assembly"),
                "subassembly_id": component.get("subassembly_id"),
                "object_type": component.get("object_type"),
                "part_group_id": component.get("part_group_id"),
                "part_name": component.get("part_name"),
                "shape": component.get("shape"),
                "orientation": component.get("orientation"),
                "material": component.get("material"),
                "nominal_thickness_mm": component.get("nominal_thickness_mm"),
                "measured_thickness_mm": component.get("measured_thickness_mm"),
                "length_mm": dimensions.get("length"),
                "width_mm": dimensions.get("width"),
                "height_mm": dimensions.get("height"),
                "thickness_mm": dimensions.get("thickness"),
                "bbox_x_mm": bbox_size[0] if len(bbox_size) > 0 else None,
                "bbox_y_mm": bbox_size[1] if len(bbox_size) > 1 else None,
                "bbox_z_mm": bbox_size[2] if len(bbox_size) > 2 else None,
                "bottom_z_mm": placement.get("bottom_z"),
                "top_z_mm": placement.get("top_z"),
                "on_floor": placement.get("on_floor"),
                "manual_review_required": component.get("fabrication", {}).get("manual_review_required", False),
                "flags": ";".join(str(flag) for flag in flags),
            }
        )
    return rows


def write_component_schedule_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Write a human-readable CSV schedule for per-component measurements."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "instance_id",
        "source_name",
        "component_name",
        "parent_assembly",
        "subassembly_id",
        "object_type",
        "part_group_id",
        "part_name",
        "shape",
        "orientation",
        "material",
        "nominal_thickness_mm",
        "measured_thickness_mm",
        "length_mm",
        "width_mm",
        "height_mm",
        "thickness_mm",
        "bbox_x_mm",
        "bbox_y_mm",
        "bbox_z_mm",
        "bottom_z_mm",
        "top_z_mm",
        "on_floor",
        "manual_review_required",
        "flags",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def prepare_package_root(package_root: Path) -> tuple[Path, Path]:
    """Reset generated subfolders so repeated runs do not leave stale artifacts behind."""
    analysis_dir = package_root / "analysis"
    bom_dir = package_root / "bom"
    assembly_dir = package_root / "assembly"
    elevations_dir = package_root / "elevations"
    parts_dir = package_root / "parts"
    subassemblies_dir = package_root / "subassemblies"

    for subdirectory in (analysis_dir, bom_dir, assembly_dir, elevations_dir, parts_dir, subassemblies_dir):
        subdirectory.mkdir(parents=True, exist_ok=True)

    cleanup_patterns = {
        analysis_dir: ("*.json", "*.csv"),
        assembly_dir: ("*.png", "*.pdf", "*.dxf"),
        elevations_dir: ("*.png", "*.pdf", "*.dxf"),
        parts_dir: ("*.png", "*.pdf", "*.dxf"),
        subassemblies_dir: ("*.png", "*.pdf", "*.dxf"),
        bom_dir: ("*.csv", "*.json"),
    }
    for directory, patterns in cleanup_patterns.items():
        for pattern in patterns:
            for file_path in directory.glob(pattern):
                if not file_path.is_file():
                    continue
                try:
                    file_path.unlink()
                except PermissionError:
                    continue

    return analysis_dir, bom_dir


def build_fabrication_package(obj_path: str, source_unit: str, output_root: str = "output") -> dict[str, Any]:
    """Run the complete fabrication pipeline for one OBJ model."""
    obj_file = Path(obj_path).expanduser()
    payload = extract_measurements(str(obj_file), source_unit=source_unit)

    part_groups, bom_rows, assembly_context = enrich_fabrication_metadata(payload)
    model_slug = slugify(obj_file.stem)
    package_root = Path(output_root).expanduser() / model_slug
    analysis_dir, bom_dir = prepare_package_root(package_root)

    assembly_records = generate_assembly_and_elevation_drawings(payload, package_root)
    subassembly_records = generate_subassembly_drawings(payload, package_root)
    part_records = generate_part_detail_drawings(part_groups, package_root)

    bom_csv_path = bom_dir / "bom.csv"
    bom_json_path = bom_dir / "bom.json"
    write_bom_csv(bom_rows, bom_csv_path)
    write_bom_json(bom_rows, bom_json_path)

    analysis_path = analysis_dir / f"{model_slug}_analysis.json"
    component_schedule_path = analysis_dir / "component_schedule.csv"
    component_schedule = component_schedule_rows(payload.get("components", []))
    write_component_schedule_csv(component_schedule, component_schedule_path)
    payload["fabrication"] = {
        "assembly_context": {
            key: round_number(float(value))
            for key, value in assembly_context.items()
        },
        "component_schedule": component_schedule,
        "subassemblies": subassembly_records,
        "part_groups": serializable_part_groups(part_groups, part_records),
        "bom": bom_rows,
    }
    payload["fabrication"]["output_structure"] = build_output_structure(
        package_root=package_root,
        analysis_path=analysis_path,
        component_schedule_path=component_schedule_path,
        bom_csv_path=bom_csv_path,
        bom_json_path=bom_json_path,
        assembly_records=assembly_records,
        subassembly_records=subassembly_records,
        part_records=part_records,
    )
    analysis_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "package_root": package_root,
        "analysis_json": analysis_path,
        "component_schedule_csv": component_schedule_path,
        "assembly": assembly_records.get("assembly", []),
        "elevations": assembly_records.get("elevations", []),
        "sheets": assembly_records.get("sheets", []),
        "subassemblies": subassembly_records,
        "bom_csv": bom_csv_path,
        "bom_json": bom_json_path,
        "parts": part_records,
    }


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the fabrication package generator."""
    parser = argparse.ArgumentParser(
        description="Build a fabrication drawing package from an OBJ file."
    )
    parser.add_argument("obj_path", nargs="+", help="Path to the Wavefront OBJ file.")
    parser.add_argument(
        "--source-unit",
        required=True,
        choices=("mm", "cm", "m", "in"),
        help="Unit used by the source OBJ geometry before normalization to millimeters.",
    )
    parser.add_argument(
        "--output-root",
        default="output",
        help="Root folder where the package directory should be created.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint for the fabrication package workflow."""
    args = parse_args()
    obj_path = normalize_path_argument(args.obj_path)

    try:
        results = build_fabrication_package(
            obj_path=str(obj_path),
            source_unit=args.source_unit,
            output_root=args.output_root,
        )
    except ExtractionError as exc:
        print(f"Fabrication package failed: {exc.message}")
        return 1
    except Exception as exc:  # pragma: no cover - CLI fallback for unexpected runtime errors.
        print(f"Fabrication package failed: Unexpected error: {exc}")
        return 1

    print(f"Saved package to {results['package_root']}")
    print(f"Saved analysis JSON to {results['analysis_json']}")
    print(f"Saved BOM CSV to {results['bom_csv']}")
    print(f"Saved BOM JSON to {results['bom_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
