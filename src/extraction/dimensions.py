"""Dimension helpers for per-component bounding boxes."""

from __future__ import annotations

from typing import Iterable

from .models import BoundingBox3D, ComponentDimensions, ExtractedComponent


def round_mm(value: float) -> float:
    return round(float(value), 3)


def build_bounding_box(minimum: Iterable[float], maximum: Iterable[float]) -> BoundingBox3D:
    return BoundingBox3D(
        minimum=[round_mm(value) for value in minimum],
        maximum=[round_mm(value) for value in maximum],
    )


def build_dimensions_from_bbox_size(size: Iterable[float]) -> ComponentDimensions:
    size_values = [abs(round_mm(value)) for value in size]
    if len(size_values) != 3:
        raise ValueError("Bounding-box size must contain exactly three values.")

    horizontal = sorted(size_values[:2], reverse=True)
    return ComponentDimensions(
        width=horizontal[0],
        depth=horizontal[1],
        height=size_values[2],
        unit="mm",
    )


def format_size(component: ExtractedComponent) -> str:
    dims = component.dimensions
    return (
        f"W {int(round(dims.width))} x "
        f"H {int(round(dims.height))} x "
        f"D {int(round(dims.depth))} mm"
    )


def combined_bounding_box(components: list[ExtractedComponent]) -> BoundingBox3D:
    if not components:
        return BoundingBox3D(minimum=[0.0, 0.0, 0.0], maximum=[0.0, 0.0, 0.0])

    mins = [component.bounding_box.minimum for component in components]
    maxs = [component.bounding_box.maximum for component in components]
    return BoundingBox3D(
        minimum=[round_mm(min(values[index] for values in mins)) for index in range(3)],
        maximum=[round_mm(max(values[index] for values in maxs)) for index in range(3)],
    )
