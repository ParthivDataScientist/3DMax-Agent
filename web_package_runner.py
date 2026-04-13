"""Run fabrication pipeline for web API and produce a zip package."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from FabricationPackage import build_fabrication_package


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--obj-path", required=True)
    parser.add_argument("--source-unit", required=True, choices=("mm", "cm", "m"))
    parser.add_argument("--work-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    work_dir = Path(args.work_dir)
    output_root = work_dir / "output"

    results = build_fabrication_package(
        obj_path=args.obj_path,
        source_unit=args.source_unit,
        output_root=str(output_root),
    )

    package_root = Path(results["package_root"])
    zip_base = work_dir / f"{package_root.name}_package"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=str(package_root))

    print(
        json.dumps(
            {
                "zip_path": zip_path,
                "base_name": package_root.name,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
