"""Convert parsed OBJ meshes into grouped selectable components."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Iterable

from src.parser.obj_parser import parse_obj_file
from src.validation.luminy_validator import validate_luminy_frame

from .classifier import classify_component, normalize_group_name
from .dimensions import build_bounding_box, build_dimensions_from_bbox_size
from .models import ComponentInstance, ExtractedComponent


from src.pipeline.geometry_pipeline import build_component_record, split_components


CATEGORY_SORT_ORDER = {
    "Frame": 1,
    "Curved Frame": 2,
    "Panel": 3,
    "Signage": 4,
    "Unknown": 5,
}


@dataclass
class ExtractionResult:
    components: list[ExtractedComponent]
    instances: list[ComponentInstance]
    warnings: list[str] = field(default_factory=list)


def _unique(items: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _component_group_key(instance: ComponentInstance) -> tuple[object, ...]:
    dims = instance.dimensions
    return (
        instance.category.lower(),
        normalize_group_name(instance.name, instance.category),
        round(float(dims.width), 1),
        round(float(dims.height), 1),
        round(float(dims.depth), 1),
        instance.shape.lower(),
    )


def _sort_key(component: ExtractedComponent) -> tuple[object, ...]:
    return (
        CATEGORY_SORT_ORDER.get(component.category, 99),
        component.name.lower(),
        -component.quantity,
        component.dimensions.height,
        component.dimensions.width,
    )


def extract_components(
    obj_path: str | Path,
    unit: str = "mm",
    *,
    validate_library: bool = False,
    library_db_path: str | Path | None = None,
) -> ExtractionResult:
    parsed = parse_obj_file(obj_path, unit=unit)
    instances: list[ComponentInstance] = []
    warnings = list(parsed.warnings)
    instance_counter = 1

    for candidate in parsed.candidates:
        split_meshes = split_components([(candidate.mesh_id, candidate.mesh)])
        if len(split_meshes) > 1 and not (candidate.object_name or candidate.group_name):
            warnings.append(
                f"Warning: unnamed mesh {candidate.mesh_id} was split into {len(split_meshes)} connected components."
            )

        for split_index, (_, mesh) in enumerate(split_meshes, start=1):
            analysis = build_component_record(
                component_id=instance_counter,
                mesh=mesh,
                source_name=candidate.source_label,
            )
            bbox = analysis["geometry"]["bounding_box"]
            dimensions = build_dimensions_from_bbox_size(bbox["size"])
            classification = classify_component(
                source_label=candidate.source_label,
                original_name=candidate.source_label,
                object_name=candidate.object_name,
                group_name=candidate.group_name,
                shape=str(analysis.get("shape", "unknown")),
                orientation=str(analysis.get("orientation", "unknown")),
                dimensions=dimensions,
            )

            notes = list(candidate.notes)
            notes.extend(classification.notes)
            instance = ComponentInstance(
                id=f"instance_{instance_counter:03d}",
                mesh_id=f"{candidate.mesh_id}_{split_index:02d}",
                source_label=candidate.source_label,
                original_name=candidate.source_label,
                object_name=candidate.object_name,
                group_name=candidate.group_name,
                material_name=candidate.material_name,
                name=classification.name,
                category=classification.category,
                confidence=classification.confidence,
                quantity=1,
                dimensions=dimensions,
                bounding_box=build_bounding_box(bbox["min"], bbox["max"]),
                mesh_ids=[f"{candidate.mesh_id}_{split_index:02d}"],
                material=classification.material,
                notes=notes,
                manual_review_required=classification.confidence < 0.6 or any(
                    "verify" in note.lower() or "uncertain" in note.lower() for note in notes
                ),
                shape=str(analysis.get("shape", "unknown")),
                orientation=str(analysis.get("orientation", "unknown")),
                classification_key=classification.classification_key,
                analysis=analysis,
            )
            instances.append(instance)
            instance_counter += 1

    grouped_map: dict[tuple[object, ...], list[ComponentInstance]] = {}
    for instance in instances:
        grouped_map.setdefault(_component_group_key(instance), []).append(instance)

    grouped_components: list[ExtractedComponent] = []
    for grouped_instances in grouped_map.values():
        representative = max(grouped_instances, key=lambda item: item.confidence)
        notes = _unique(note for instance in grouped_instances for note in instance.notes)
        if len(grouped_instances) > 1:
            notes.append(f"Repeated component group detected from {len(grouped_instances)} instances.")

        grouped_components.append(
            ExtractedComponent(
                id="",
                index=0,
                name=representative.name,
                original_name=representative.original_name,
                category=representative.category,
                confidence=max(instance.confidence for instance in grouped_instances),
                quantity=len(grouped_instances),
                dimensions=representative.dimensions,
                bounding_box=representative.bounding_box,
                mesh_ids=[mesh_id for instance in grouped_instances for mesh_id in instance.mesh_ids],
                instance_ids=[instance.id for instance in grouped_instances],
                source_object_names=_unique(instance.object_name for instance in grouped_instances),
                source_group_names=_unique(instance.group_name for instance in grouped_instances),
                material=representative.material,
                notes=notes,
                manual_review_required=any(instance.manual_review_required for instance in grouped_instances),
                shape=representative.shape,
                orientation=representative.orientation,
                classification_key=representative.classification_key,
                representative_instance_id=representative.id,
                analysis=representative.analysis,
            )
        )

    grouped_components.sort(key=_sort_key)
    for index, component in enumerate(grouped_components, start=1):
        component.index = index
        component.id = f"component_{index:03d}"

    if validate_library:
        from src.fabrication import FabricationSolver
        solver = FabricationSolver()
        for component in grouped_components:
            # We apply fabrication solving to any Frame or Wall category, or if the original name has luminy
            cat_lower = component.category.lower()
            orig_name = (component.original_name or "").lower()
            if "frame" in cat_lower or "wall" in cat_lower or "luminy" in orig_name:
                validation = solver.solve(
                    width_mm=component.dimensions.width,
                    height_mm=component.dimensions.height,
                )
                component.luminy_validation = validation
                
                # Update notes for display purposes
                component.notes.extend(validation.get("notes", []))
                
                # Check if custom filler was needed and set manual review if true
                if len(validation.get("recommended_solution", {}).get("custom_fillers", [])) > 0:
                    component.manual_review_required = True


    return ExtractionResult(
        components=grouped_components,
        instances=instances,
        warnings=warnings,
    )
