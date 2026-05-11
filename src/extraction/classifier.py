"""Booth-aware component classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import sys

from .models import ComponentDimensions


from src.pipeline.materials import assign_material_and_thickness

POSITIONAL_TOKENS = {"left", "right", "front", "back", "upper", "lower", "top", "bottom"}


@dataclass
class ClassificationResult:
    name: str
    category: str
    confidence: float
    classification_key: str
    material: str | None = None
    notes: list[str] = field(default_factory=list)


def _tokens(*values: str | None) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if not value:
            continue
        tokens.update(token for token in re.split(r"[^a-z0-9]+", value.lower()) if token)
    return tokens


def _fallback_material(category: str, depth_mm: float) -> str:
    object_type_map = {
        "Frame": "frame",
        "Panel": "wall_panel",
        "Signage": "acrylic_logo",
        "Curved Frame": "frame",
        "Unknown": "unknown",
    }
    assignment = assign_material_and_thickness(object_type_map.get(category, "unknown"), measured_thickness_mm=depth_mm)
    return str(assignment["material"])


def _infer_material(tokens: set[str], category: str, depth_mm: float) -> str:
    if "luminy" in tokens:
        return "Aluminum Extrusion"
    if "logo" in tokens:
        return "Acrylic"
    if "switch" in tokens or "board" in tokens:
        return "HMR MDF"
    if "wooden" in tokens or "fascia" in tokens or "arc" in tokens:
        return "Plywood"
    return _fallback_material(category, depth_mm)


def _curved_note(shape: str, dimensions: ComponentDimensions) -> list[str]:
    if shape not in {"cylinder", "capsule"}:
        return []
    approx_radius = round(min(dimensions.width, dimensions.depth) / 2.0, 1)
    return [f"CURVED / ARC COMPONENT - VERIFY RADIUS (APPROX. R {approx_radius} mm)"]


def classify_component(
    source_label: str,
    original_name: str | None,
    object_name: str | None,
    group_name: str | None,
    shape: str,
    orientation: str,
    dimensions: ComponentDimensions,
) -> ClassificationResult:
    tokens = _tokens(source_label, original_name, object_name, group_name)
    notes: list[str] = []

    if "luminy" in tokens:
        category = "Frame"
        name = "Luminy Frame"
        confidence = 0.87
        key = "luminy_frame"
    elif "switch" in tokens and ("panel" in tokens or "board" in tokens):
        category = "Panel"
        name = "Switch Board Panel"
        confidence = 0.82
        key = "switch_board_panel"
    elif "logo" in tokens:
        category = "Signage"
        name = "Logo Panel"
        confidence = 0.84
        key = "logo_panel"
    elif ("arc" in tokens or "fascia" in tokens) and "wooden" in tokens:
        category = "Curved Frame"
        name = "Wooden Arc Fascia"
        confidence = 0.83
        key = "wooden_arc_fascia"
    elif "wooden" in tokens and "frame" in tokens:
        category = "Frame"
        name = "Custom Wooden Frame"
        confidence = 0.82
        key = "custom_wooden_frame"
    elif "frame" in tokens or "post" in tokens:
        category = "Frame"
        name = "Frame Component"
        confidence = 0.76
        key = "frame_component"
    elif "panel" in tokens or "blocking" in tokens or "display" in tokens:
        category = "Panel"
        name = "Panel Component"
        confidence = 0.74
        key = "panel_component"
    else:
        width = dimensions.width
        height = dimensions.height
        depth = dimensions.depth

        if shape in {"cylinder", "capsule"}:
            category = "Curved Frame"
            name = "Curved / Arc Component"
            confidence = 0.64
            key = "curved_component"
        elif orientation == "vertical" and height >= 1800.0 and depth <= 180.0:
            category = "Frame"
            name = "Standard Frame"
            confidence = 0.68
            key = "standard_frame"
        elif orientation == "vertical" and depth <= 120.0 and width >= 600.0:
            category = "Panel"
            name = "Blocking Panel"
            confidence = 0.66
            key = "blocking_panel"
        elif orientation == "vertical" and width <= 1200.0 and height <= 1600.0 and depth <= 120.0:
            category = "Panel"
            name = "Switch Board Panel"
            confidence = 0.61
            key = "switch_board_panel"
        elif width >= 800.0 and depth <= 60.0:
            category = "Signage"
            name = "Logo Panel"
            confidence = 0.58
            key = "logo_panel"
        else:
            category = "Unknown"
            name = "Unknown Component"
            confidence = 0.40
            key = "unknown_component"
            notes.append("Classification uncertain. Please verify manually.")

    notes.extend(_curved_note(shape, dimensions))
    if confidence < 0.55 and "Classification uncertain. Please verify manually." not in notes:
        notes.append("Classification uncertain. Please verify manually.")

    material = _infer_material(tokens, category, dimensions.depth)
    return ClassificationResult(
        name=name,
        category=category,
        confidence=confidence,
        classification_key=key,
        material=material,
        notes=notes,
    )


def normalize_group_name(name: str, category: str) -> str:
    tokens = [token for token in re.split(r"[^a-z0-9]+", name.lower()) if token and not token.isdigit()]
    filtered = [token for token in tokens if token not in POSITIONAL_TOKENS]
    if not filtered:
        return category.lower()
    return "_".join(filtered)
