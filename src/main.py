"""Terminal-first selected-component CAD package generator."""

from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime
from pathlib import Path
from typing import Iterable

from src.ai.fusion import apply_manifest_to_components, merge_ai_analysis
from src.ai.gemini_prompts import build_component_analysis_prompt
from src.db import DEFAULT_DB_PATH, seed_luminy_library
from src.extraction.component_extractor import extract_components
from src.extraction.dimensions import format_size
from src.extraction.models import ExtractedComponent
from src.output.manifest_writer import (
    build_component_manifest_payload,
    ensure_output_structure,
    write_component_manifest,
    write_manifest_payload,
    write_selected_manifest,
)
from src.pdf.pdf_generator import generate_component_preview_images, generate_selected_components_pdf
from src.selection.terminal_selector import SelectionError, select_components


VALID_UNITS = ("mm", "cm", "m", "in")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse an OBJ, select booth components, and generate selected-component CAD-style PDF sheets."
    )
    parser.add_argument("--input", required=False, help="Path to the Wavefront OBJ file.")
    parser.add_argument(
        "--select",
        default=None,
        help='Optional component selection. Use "all" or comma-separated indexes like 1,3,5.',
    )
    parser.add_argument(
        "--output",
        default="assembly_output",
        help="Output directory. Defaults to assembly_output.",
    )
    parser.add_argument(
        "--unit",
        default="mm",
        choices=VALID_UNITS,
        help="Source unit used in the OBJ geometry. Defaults to mm.",
    )
    parser.add_argument("--use-gemini", action="store_true", help="Enable Gemini AI visual enrichment before selection.")
    parser.add_argument("--require-gemini", action="store_true", help="Fail the run if Gemini enrichment cannot complete.")
    parser.add_argument("--photos", nargs="*", default=[], help="Optional booth photos to send with the Gemini prompt.")
    parser.add_argument("--seed-db", action="store_true", help="Seed the Luminy SQLite component library and exit.")
    parser.add_argument("--validate-library", action="store_true", help="Enable Luminy library validation during extraction.")
    return parser.parse_args()


def _print_component(component: ExtractedComponent) -> None:
    print(f"[{component.index}] {component.name}")
    print(f"    Category: {component.category}")
    print(f"    Size: {format_size(component)}")
    print(f"    Qty: {component.quantity}")
    if component.material:
        material_line = f"    Material: {component.material}"
        if component.finish:
            material_line += f" | Finish: {component.finish}"
        print(material_line)
    if component.ai:
        print(f"    AI Confidence: {int(round(float(component.ai.get('confidence', component.confidence)) * 100.0))}%")
    else:
        print(f"    Confidence: {int(round(component.confidence * 100.0))}%")
    if component.luminy_validation:
        print(f"    Luminy Status: {component.luminy_validation.get('status')}")
        recommendation = component.luminy_validation.get("recommendation")
        if recommendation:
            print(f"    Luminy Recommendation: {recommendation}")
    for note in component.notes[:3]:
        if "Repeated component group detected" in note:
            continue
        print(f"    Note: {note}")
    print()


def _print_component_list(components: Iterable[ExtractedComponent]) -> None:
    print("Detected Components:\n")
    for component in components:
        _print_component(component)


def _print_selected_components(components: list[ExtractedComponent]) -> None:
    print("Selected Components:")
    for component in components:
        print(f"[{component.index}] {component.name}")
    print()


def _resolve_photo_paths(photo_paths: list[str]) -> tuple[list[str], list[str]]:
    valid_paths: list[str] = []
    warnings: list[str] = []
    for raw_path in photo_paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            warnings.append(f"Warning: photo path does not exist and will be skipped: {path}")
            continue
        valid_paths.append(str(path.resolve()))
    return valid_paths, warnings


def _gemini_preview_subset(preview_paths: list[Path], max_images: int = 12) -> list[str]:
    iso_paths = [path for path in preview_paths if path.stem.endswith("_iso")]
    selected = iso_paths if iso_paths else preview_paths
    return [str(path.resolve()) for path in selected[:max_images]]


def _run_gemini_enrichment(
    *,
    components: list[ExtractedComponent],
    component_manifest: dict,
    preview_paths: list[Path],
    photo_paths: list[str],
    require_gemini: bool,
    output_root: Path,
) -> tuple[dict, list[ExtractedComponent], list[str]]:
    warnings: list[str] = []
    print("Gemini AI enrichment: enabled")
    print(f"Photos provided: {len(photo_paths)}")
    print("Analyzing booth visuals...")

    try:
        from src.ai.gemini_client import GeminiVisionClient

        client = GeminiVisionClient()
        prompt = build_component_analysis_prompt(component_manifest)
        image_paths = list(photo_paths)
        preview_subset = _gemini_preview_subset(preview_paths)
        if preview_subset:
            image_paths.extend(preview_subset)
        ai_result, image_warnings = client.analyze_components(prompt, image_paths)
        warnings.extend(image_warnings)
        merged_manifest = merge_ai_analysis(component_manifest, ai_result)
        apply_manifest_to_components(components, merged_manifest)
        ai_manifest_path = write_manifest_payload(output_root, "component_manifest_ai.json", merged_manifest)
        print("AI enrichment completed.")
        print(f"AI manifest saved:\n{ai_manifest_path}")
        print()
        return merged_manifest, components, warnings
    except Exception as exc:
        message = f"Gemini AI enrichment failed:\n{exc}"
        if require_gemini:
            raise RuntimeError(message) from exc
        print(message)
        print("Continuing with geometry-only classification.\n")
        return component_manifest, components, warnings


def main() -> int:
    args = parse_args()
    generated_at = datetime.now().strftime("%Y-%m-%d")

    try:
        if args.seed_db:
            seeded_count = seed_luminy_library(DEFAULT_DB_PATH)
            print(f"Luminy database seeded successfully:\n{DEFAULT_DB_PATH.resolve()}")
            print(f"Frames seeded: {seeded_count}")
            return 0

        if not args.input:
            raise ValueError("--input is required unless --seed-db is used.")

        input_path = Path(args.input).expanduser()
        if not input_path.exists():
            raise FileNotFoundError(f"input file does not exist: {input_path}")
        if input_path.suffix.lower() != ".obj":
            raise ValueError(f"input file must be an .obj: {input_path}")

        print(f"Parsing file: {input_path.name}")
        print("Unit: mm\n")
        extraction = extract_components(
            input_path,
            unit=args.unit,
            validate_library=args.validate_library,
            library_db_path=DEFAULT_DB_PATH,
        )
        if not extraction.components:
            raise ValueError("OBJ has no valid mesh geometry.")

        for warning in extraction.warnings:
            print(warning)
        if extraction.warnings:
            print()

        output_dirs = ensure_output_structure(args.output)

        component_manifest_path = write_component_manifest(
            output_dirs["root"],
            input_path=str(input_path.resolve()),
            unit="mm",
            generated_at=generated_at,
            warnings=extraction.warnings,
            components=extraction.components,
        )
        component_manifest = build_component_manifest_payload(
            input_path=str(input_path.resolve()),
            unit="mm",
            generated_at=generated_at,
            warnings=extraction.warnings,
            components=extraction.components,
        )

        try:
            preview_paths = generate_component_preview_images(extraction.components, output_dirs["previews"])
        except Exception as exc:
            preview_paths = []
            print(f"Warning: component preview generation failed before AI enrichment: {exc}\n")

        if args.use_gemini or args.require_gemini:
            photo_paths, photo_warnings = _resolve_photo_paths(args.photos)
            for warning in photo_warnings:
                print(warning)
            if photo_warnings:
                print()
            component_manifest, _components, ai_warnings = _run_gemini_enrichment(
                components=extraction.components,
                component_manifest=component_manifest,
                preview_paths=preview_paths,
                photo_paths=photo_paths,
                require_gemini=args.require_gemini,
                output_root=output_dirs["root"],
            )
            for warning in ai_warnings:
                print(warning)
            if ai_warnings:
                print()

        _print_component_list(extraction.components)
        selected_components = select_components(extraction.components, selection_arg=args.select)
        if not selected_components:
            raise SelectionError("No components were selected.")

        _print_selected_components(selected_components)

        pdf_path, _preview_paths = generate_selected_components_pdf(
            all_components=extraction.components,
            all_instances=extraction.instances,
            selected_components=selected_components,
            input_path=str(input_path.resolve()),
            drawings_dir=output_dirs["drawings"],
            previews_dir=output_dirs["previews"],
            generated_at=generated_at,
        )
        selected_manifest_path = write_selected_manifest(
            output_dirs["root"],
            input_path=str(input_path.resolve()),
            unit="mm",
            generated_at=generated_at,
            selected_components=selected_components,
            pdf_path=str(pdf_path),
        )
    except (FileNotFoundError, ValueError, SelectionError) as exc:
        print(f"Error: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1
    except OSError as exc:
        print(f"Error: unable to write output: {exc}")
        return 1
    except Exception as exc:
        print(f"Error: unexpected failure: {exc}")
        return 1

    print(f"PDF generated successfully:\n{pdf_path}")
    print()
    print(f"Manifest saved:\n{component_manifest_path}")
    print()
    print(f"Selected components saved:\n{selected_manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
