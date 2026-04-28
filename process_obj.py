"""Process a local OBJ file directly and save the fabrication ZIP package."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path


PIPELINE_DIR = Path(__file__).parent / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from FabricationPackage import build_fabrication_package  # noqa: E402
from geometry_pipeline import ExtractionError  # noqa: E402


VALID_UNITS = ("mm", "cm", "m", "in")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run 3DMax Agent locally for a .obj file and save the generated ZIP package."
    )
    parser.add_argument("obj_path", help="Path to the local .obj file.")
    parser.add_argument(
        "--unit",
        default="mm",
        choices=VALID_UNITS,
        help="Source unit used by the OBJ geometry. Defaults to mm.",
    )
    parser.add_argument(
        "--output-root",
        default="output",
        help="Folder where the unzipped package folder should be generated. Defaults to output/.",
    )
    parser.add_argument(
        "--zip-dir",
        default="downloads",
        help="Folder where the ZIP should be saved. Defaults to downloads/.",
    )
    parser.add_argument(
        "--zip-path",
        default=None,
        help="Optional exact ZIP output path. Overrides --zip-dir.",
    )
    return parser.parse_args()


def validate_obj_path(obj_path: Path) -> None:
    if not obj_path.exists():
        raise SystemExit(f"File not found: {obj_path}")
    if obj_path.suffix.lower() != ".obj":
        raise SystemExit("Only .obj files are supported.")


def package_zip_path(args: argparse.Namespace, package_root: Path) -> Path:
    if args.zip_path:
        return Path(args.zip_path).expanduser()
    return Path(args.zip_dir).expanduser() / f"{package_root.name}_package.zip"


def zip_package(package_root: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in package_root.rglob("*"):
            if item.is_file():
                archive.write(item, item.relative_to(package_root))


def print_summary(results: dict, zip_path: Path) -> None:
    analysis_path = Path(results["analysis_json"])
    component_count = "-"
    part_group_count = "-"
    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        component_count = len(analysis.get("components", []))
        part_group_count = len(analysis.get("fabrication", {}).get("part_groups", []))
    except Exception:
        pass

    print(f"Saved package folder: {results['package_root']}")
    print(f"Saved ZIP: {zip_path}")
    print(f"Components: {component_count}")
    print(f"Part groups: {part_group_count}")


def main() -> int:
    args = parse_args()
    obj_path = Path(args.obj_path).expanduser()
    validate_obj_path(obj_path)

    try:
        results = build_fabrication_package(
            obj_path=str(obj_path),
            source_unit=args.unit,
            output_root=args.output_root,
        )
    except ExtractionError as exc:
        raise SystemExit(f"Pipeline failed: {exc.message}") from exc
    except Exception as exc:
        raise SystemExit(f"Pipeline failed: {exc}") from exc

    package_root = Path(results["package_root"])
    zip_path = package_zip_path(args, package_root)
    zip_package(package_root, zip_path)
    print_summary(results, zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
