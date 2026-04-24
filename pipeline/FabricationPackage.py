"""End-to-end fabrication package generator for OBJ exhibition/furniture models."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from bom_generator import generate_bom, group_parts, write_bom_csv, write_bom_json
from classification import build_assembly_context, classify_object, placement_for_component
from fabrication_drawings import (
    generate_assembly_and_elevation_drawings,
    generate_part_detail_drawings,
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
    bom_csv_path: Path,
    bom_json_path: Path,
    assembly_records: dict[str, Any],
    part_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a JSON-friendly manifest of generated fabrication artifacts."""
    return {
        "root": str(package_root),
        "analysis_json": str(analysis_path),
        "assembly": assembly_records.get("assembly", []),
        "elevations": assembly_records.get("elevations", []),
        "parts": part_records,
        "bom": {
            "csv": str(bom_csv_path),
            "json": str(bom_json_path),
        },
    }


def prepare_package_root(package_root: Path) -> tuple[Path, Path]:
    """Reset generated subfolders so repeated runs do not leave stale artifacts behind."""
    analysis_dir = package_root / "analysis"
    bom_dir = package_root / "bom"
    assembly_dir = package_root / "assembly"
    elevations_dir = package_root / "elevations"
    parts_dir = package_root / "parts"

    for subdirectory in (analysis_dir, bom_dir, assembly_dir, elevations_dir, parts_dir):
        subdirectory.mkdir(parents=True, exist_ok=True)

    cleanup_patterns = {
        assembly_dir: ("*.png", "*.pdf", "*.dxf"),
        elevations_dir: ("*.png", "*.pdf", "*.dxf"),
        parts_dir: ("*.png", "*.pdf", "*.dxf"),
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
    part_records = generate_part_detail_drawings(part_groups, package_root)

    bom_csv_path = bom_dir / "bom.csv"
    bom_json_path = bom_dir / "bom.json"
    write_bom_csv(bom_rows, bom_csv_path)
    write_bom_json(bom_rows, bom_json_path)

    analysis_path = analysis_dir / f"{model_slug}_analysis.json"
    payload["fabrication"] = {
        "assembly_context": {
            key: round_number(float(value))
            for key, value in assembly_context.items()
        },
        "part_groups": serializable_part_groups(part_groups, part_records),
        "bom": bom_rows,
    }
    payload["fabrication"]["output_structure"] = build_output_structure(
        package_root=package_root,
        analysis_path=analysis_path,
        bom_csv_path=bom_csv_path,
        bom_json_path=bom_json_path,
        assembly_records=assembly_records,
        part_records=part_records,
    )
    analysis_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "package_root": package_root,
        "analysis_json": analysis_path,
        "assembly": assembly_records.get("assembly", []),
        "elevations": assembly_records.get("elevations", []),
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
