"""Luminy frame feasibility validation."""

from __future__ import annotations

from pathlib import Path

from src.db.database import DEFAULT_DB_PATH
from src.db.luminy_repository import LuminyRepository
from .module_combination_solver import find_modular_solutions


STATUSES = (
    "STANDARD_POSSIBLE",
    "MODULAR_COMBINATION_POSSIBLE",
    "POSSIBLE_BY_CUTTING",
    "CUSTOM_REQUIRED",
)


def _is_luminy_component(name: str, category: str) -> bool:
    normalized = f"{name} {category}".lower()
    return "luminy" in normalized and "frame" in normalized


def validate_luminy_frame(
    *,
    width_mm: float,
    height_mm: float,
    component_name: str,
    category: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    tolerance_mm: float = 5.0,
) -> dict | None:
    if not _is_luminy_component(component_name, category):
        return None

    repository = LuminyRepository(db_path)
    all_frames = repository.list_all_frames()
    if not all_frames:
        raise RuntimeError(
            f"Luminy library is empty at {Path(db_path)}. Run `python src/main.py --seed-db` first."
        )

    detected_width = round(float(width_mm), 3)
    detected_height = round(float(height_mm), 3)

    exact_frame = repository.exact_frame(detected_width, detected_height, tolerance_mm=tolerance_mm)
    if exact_frame is not None:
        return {
            "status": "STANDARD_POSSIBLE",
            "detected_width_mm": detected_width,
            "detected_height_mm": detected_height,
            "recommended_solution": {
                "type": "standard_frame",
                "frame_name": exact_frame.name,
                "source_width_mm": exact_frame.width_mm,
                "source_height_mm": exact_frame.height_mm,
                "cut_width_mm": 0,
                "cut_height_mm": 0,
            },
            "alternative_solutions": [],
            "recommendation": f"Use standard {exact_frame.name}.",
            "library_source": str(Path(db_path).resolve()),
        }

    same_height_frames = repository.frames_for_height(detected_height, tolerance_mm=tolerance_mm)
    width_modules = [frame.width_mm for frame in same_height_frames]
    modular_solutions = find_modular_solutions(
        detected_width,
        width_modules,
        tolerance_mm=tolerance_mm,
    )
    exact_modular = [solution for solution in modular_solutions if solution.get("difference_mm", 999999.0) <= tolerance_mm]
    if exact_modular:
        best = exact_modular[0]
        modules_text = " + ".join(
            f"{module['quantity']}x {module['name'].replace('Luminy Frame W', 'W')}"
            for module in best["modules"]
        )
        return {
            "status": "MODULAR_COMBINATION_POSSIBLE",
            "detected_width_mm": detected_width,
            "detected_height_mm": detected_height,
            "recommended_solution": {
                "type": "modular_combination",
                "modules": best["modules"],
                "combined_width_mm": best["combined_width_mm"],
                "difference_mm": best["difference_mm"],
            },
            "alternative_solutions": modular_solutions[1:4],
            "recommendation": f"Use modular combination: {modules_text}.",
            "library_source": str(Path(db_path).resolve()),
        }

    cuttable_frames = repository.cuttable_frames(detected_width, detected_height, tolerance_mm=tolerance_mm)
    if cuttable_frames:
        best = cuttable_frames[0]
        cut_width = max(best.width_mm - detected_width, 0.0)
        cut_height = max(best.height_mm - detected_height, 0.0)
        recommendation = (
            f"Use {best.name} and cut width by {round(cut_width, 3)} mm"
            if cut_width > 0.0
            else f"Use {best.name} and cut height by {round(cut_height, 3)} mm"
        )
        if cut_height > 0.0 and cut_width > 0.0:
            recommendation = (
                f"Use {best.name} and cut width by {round(cut_width, 3)} mm "
                f"and height by {round(cut_height, 3)} mm."
            )
        elif cut_width > 0.0:
            recommendation = f"Use {best.name} and cut width by {round(cut_width, 3)} mm."
        elif cut_height > 0.0:
            recommendation = f"Use {best.name} and cut height by {round(cut_height, 3)} mm."

        return {
            "status": "POSSIBLE_BY_CUTTING",
            "detected_width_mm": detected_width,
            "detected_height_mm": detected_height,
            "recommended_solution": {
                "type": "cut_from_standard",
                "frame_name": best.name,
                "source_width_mm": best.width_mm,
                "source_height_mm": best.height_mm,
                "cut_width_mm": round(cut_width, 3),
                "cut_height_mm": round(cut_height, 3),
            },
            "alternative_solutions": modular_solutions[:3],
            "recommendation": recommendation,
            "library_source": str(Path(db_path).resolve()),
        }

    return {
        "status": "CUSTOM_REQUIRED",
        "detected_width_mm": detected_width,
        "detected_height_mm": detected_height,
        "recommended_solution": None,
        "alternative_solutions": modular_solutions[:3],
        "recommendation": "No standard, modular, or cutting solution found. Custom Luminy fabrication required.",
        "library_source": str(Path(db_path).resolve()),
    }
