"""Generate simple CAD-style bounding-box views for booth components."""

from __future__ import annotations

import math

from src.extraction.dimensions import combined_bounding_box
from src.extraction.models import ComponentInstance, ExtractedComponent


def _rectangle_segments(width: float, height: float) -> list[dict[str, object]]:
    return [
        {"start": (0.0, 0.0), "end": (width, 0.0)},
        {"start": (width, 0.0), "end": (width, height)},
        {"start": (width, height), "end": (0.0, height)},
        {"start": (0.0, height), "end": (0.0, 0.0)},
    ]


def _rectangle_points(width: float, height: float) -> list[tuple[float, float]]:
    return [
        (0.0, 0.0),
        (width, 0.0),
        (width, height),
        (0.0, height),
    ]


def _iso_projection(width: float, depth: float, height: float) -> list[dict[str, object]]:
    cos30 = math.cos(math.radians(30.0))
    sin30 = math.sin(math.radians(30.0))

    points_3d = {
        "A": (0.0, 0.0, 0.0),
        "B": (width, 0.0, 0.0),
        "C": (width, depth, 0.0),
        "D": (0.0, depth, 0.0),
        "E": (0.0, 0.0, height),
        "F": (width, 0.0, height),
        "G": (width, depth, height),
        "H": (0.0, depth, height),
    }

    def project(point: tuple[float, float, float]) -> tuple[float, float]:
        x, y, z = point
        return ((x - y) * cos30, z + (x + y) * sin30 * 0.35)

    projected = {name: project(point) for name, point in points_3d.items()}
    ordered_edges = [
        ("A", "B"),
        ("B", "C"),
        ("C", "D"),
        ("D", "A"),
        ("E", "F"),
        ("F", "G"),
        ("G", "H"),
        ("H", "E"),
        ("A", "E"),
        ("B", "F"),
        ("C", "G"),
        ("D", "H"),
    ]
    return [{"start": projected[first], "end": projected[second]} for first, second in ordered_edges]


def _offset_segments(segments: list[dict[str, object]], offset_x: float, offset_y: float) -> list[dict[str, object]]:
    return [
        {
            "start": (float(segment["start"][0]) + offset_x, float(segment["start"][1]) + offset_y),
            "end": (float(segment["end"][0]) + offset_x, float(segment["end"][1]) + offset_y),
        }
        for segment in segments
    ]


def generate_component_views(component: ExtractedComponent) -> dict[str, dict[str, object]]:
    width = float(component.dimensions.width)
    height = float(component.dimensions.height)
    depth = float(component.dimensions.depth)
    quantity_label = f"QTY - {component.quantity:02d} NOS."

    return {
        "front": {
            "name": "front",
            "title": "FRONT VIEW",
            "geometry": _rectangle_segments(width, height),
            "dimensions": [
                {"orientation": "horizontal", "points": ((0.0, 0.0), (width, 0.0)), "text": f"{int(round(width))} mm"},
                {"orientation": "vertical", "points": ((width, 0.0), (width, height)), "text": f"{int(round(height))} mm"},
            ],
            "callout_anchor": (width * 0.55, height * 0.65),
            "callout_text": [quantity_label, component.material or "MATERIAL - TBD"],
        },
        "top": {
            "name": "top",
            "title": "TOP VIEW",
            "geometry": _rectangle_segments(width, depth),
            "dimensions": [
                {"orientation": "horizontal", "points": ((0.0, 0.0), (width, 0.0)), "text": f"{int(round(width))} mm"},
                {"orientation": "vertical", "points": ((width, 0.0), (width, depth)), "text": f"{int(round(depth))} mm"},
            ],
            "callout_anchor": (width * 0.45, depth * 0.65),
            "callout_text": [component.category.upper()],
        },
        "side": {
            "name": "side",
            "title": "SIDE VIEW",
            "geometry": _rectangle_segments(depth, height),
            "dimensions": [
                {"orientation": "horizontal", "points": ((0.0, 0.0), (depth, 0.0)), "text": f"{int(round(depth))} mm"},
                {"orientation": "vertical", "points": ((depth, 0.0), (depth, height)), "text": f"{int(round(height))} mm"},
            ],
            "callout_anchor": (depth * 0.55, height * 0.55),
            "callout_text": [f"CONF. {int(round(component.confidence * 100.0))}%"],
        },
        "iso": {
            "name": "iso",
            "title": "ISOMETRIC VIEW",
            "geometry": _iso_projection(width, depth, height),
            "dimensions": [],
            "callout_anchor": (width * 0.15, height * 0.85),
            "callout_text": [component.name.upper()],
        },
    }


def generate_overview_footprint_view(components: list[ExtractedComponent]) -> dict[str, object]:
    bbox = combined_bounding_box(components)
    width = max(float(bbox.maximum[0] - bbox.minimum[0]), 1.0)
    depth = max(float(bbox.maximum[1] - bbox.minimum[1]), 1.0)
    return {
        "name": "overview_top",
        "title": "SELECTED FOOTPRINT",
        "geometry": _rectangle_segments(width, depth),
        "dimensions": [
            {"orientation": "horizontal", "points": ((0.0, 0.0), (width, 0.0)), "text": f"{int(round(width))} mm"},
            {"orientation": "vertical", "points": ((width, 0.0), (width, depth)), "text": f"{int(round(depth))} mm"},
        ],
        "callout_anchor": (width * 0.5, depth * 0.6),
        "callout_text": ["REPRESENTATIVE SELECTED ENVELOPE"],
    }


def generate_booth_overall_views(instances: list[ComponentInstance]) -> dict[str, dict[str, object]]:
    if not instances:
        return {
            "top": {
                "name": "booth_top",
                "title": "OVERALL TOP VIEW",
                "geometry": _rectangle_segments(1.0, 1.0),
                "dimensions": [],
                "callout_anchor": (0.5, 0.5),
                "callout_text": ["NO BOOTH INSTANCES AVAILABLE"],
            }
        }

    min_x = min(float(instance.bounding_box.minimum[0]) for instance in instances)
    min_y = min(float(instance.bounding_box.minimum[1]) for instance in instances)
    min_z = min(float(instance.bounding_box.minimum[2]) for instance in instances)
    max_x = max(float(instance.bounding_box.maximum[0]) for instance in instances)
    max_y = max(float(instance.bounding_box.maximum[1]) for instance in instances)
    max_z = max(float(instance.bounding_box.maximum[2]) for instance in instances)

    overall_width = max(max_x - min_x, 1.0)
    overall_depth = max(max_y - min_y, 1.0)
    overall_height = max(max_z - min_z, 1.0)

    top_geometry: list[dict[str, object]] = []
    front_geometry: list[dict[str, object]] = []
    side_geometry: list[dict[str, object]] = []
    iso_geometry: list[dict[str, object]] = []

    for instance in instances:
        bbox = instance.bounding_box
        x0, y0, z0 = [float(value) for value in bbox.minimum]
        x1, y1, z1 = [float(value) for value in bbox.maximum]
        width = max(x1 - x0, 1.0)
        depth = max(y1 - y0, 1.0)
        height = max(z1 - z0, 1.0)

        top_geometry.extend(_offset_segments(_rectangle_segments(width, depth), x0 - min_x, y0 - min_y))
        front_geometry.extend(_offset_segments(_rectangle_segments(width, height), x0 - min_x, z0 - min_z))
        side_geometry.extend(_offset_segments(_rectangle_segments(depth, height), y0 - min_y, z0 - min_z))
        iso_geometry.extend(_offset_segments(_iso_projection(width, depth, height), x0 - min_x, z0 - min_z))

    return {
        "top": {
            "name": "booth_top",
            "title": "OVERALL TOP VIEW",
            "geometry": top_geometry,
            "dimensions": [
                {"orientation": "horizontal", "points": ((0.0, 0.0), (overall_width, 0.0)), "text": f"{int(round(overall_width))} mm"},
                {"orientation": "vertical", "points": ((overall_width, 0.0), (overall_width, overall_depth)), "text": f"{int(round(overall_depth))} mm"},
            ],
            "callout_anchor": (overall_width * 0.5, overall_depth * 0.55),
            "callout_text": ["BOOTH PLAN / FOOTPRINT"],
        },
        "front": {
            "name": "booth_front",
            "title": "OVERALL FRONT VIEW",
            "geometry": front_geometry,
            "dimensions": [
                {"orientation": "horizontal", "points": ((0.0, 0.0), (overall_width, 0.0)), "text": f"{int(round(overall_width))} mm"},
                {"orientation": "vertical", "points": ((overall_width, 0.0), (overall_width, overall_height)), "text": f"{int(round(overall_height))} mm"},
            ],
            "callout_anchor": (overall_width * 0.5, overall_height * 0.6),
            "callout_text": ["BOOTH FRONT ELEVATION"],
        },
        "side": {
            "name": "booth_side",
            "title": "OVERALL SIDE VIEW",
            "geometry": side_geometry,
            "dimensions": [
                {"orientation": "horizontal", "points": ((0.0, 0.0), (overall_depth, 0.0)), "text": f"{int(round(overall_depth))} mm"},
                {"orientation": "vertical", "points": ((overall_depth, 0.0), (overall_depth, overall_height)), "text": f"{int(round(overall_height))} mm"},
            ],
            "callout_anchor": (overall_depth * 0.5, overall_height * 0.6),
            "callout_text": ["BOOTH SIDE ELEVATION"],
        },
        "iso": {
            "name": "booth_iso",
            "title": "OVERALL ISOMETRIC VIEW",
            "geometry": iso_geometry,
            "dimensions": [],
            "callout_anchor": (overall_width * 0.25, overall_height * 0.85),
            "callout_text": ["OVERALL BOOTH RESULT"],
        },
    }


def generate_booth_context_view(
    instances: list[ComponentInstance],
    highlighted_instance_ids: list[str],
) -> dict[str, object]:
    if not instances:
        return {
            "name": "booth_context",
            "title": "LOCATION IN BOOTH",
            "geometry": _rectangle_segments(1.0, 1.0),
            "dimensions": [],
            "callout_anchor": (0.5, 0.5),
            "callout_text": ["NO BOOTH INSTANCES AVAILABLE"],
        }

    highlight_ids = set(highlighted_instance_ids)
    min_x = min(float(instance.bounding_box.minimum[0]) for instance in instances)
    min_y = min(float(instance.bounding_box.minimum[1]) for instance in instances)
    max_x = max(float(instance.bounding_box.maximum[0]) for instance in instances)
    max_y = max(float(instance.bounding_box.maximum[1]) for instance in instances)
    overall_width = max(max_x - min_x, 1.0)
    overall_depth = max(max_y - min_y, 1.0)

    geometry: list[dict[str, object]] = []
    fills: list[dict[str, object]] = []
    for instance in instances:
        bbox = instance.bounding_box
        x0, y0 = float(bbox.minimum[0]), float(bbox.minimum[1])
        x1, y1 = float(bbox.maximum[0]), float(bbox.maximum[1])
        width = max(x1 - x0, 1.0)
        depth = max(y1 - y0, 1.0)
        is_highlighted = instance.id in highlight_ids
        color = "#BA2D0B" if is_highlighted else "#B9C0CA"
        lineweight = 1.5 if is_highlighted else 0.7
        if is_highlighted:
            fills.append(
                {
                    "points": [
                        (point[0] + (x0 - min_x), point[1] + (y0 - min_y))
                        for point in _rectangle_points(width, depth)
                    ],
                    "facecolor": "#D94841",
                    "edgecolor": "#BA2D0B",
                    "alpha": 0.28,
                    "linewidth": 1.0,
                }
            )
        for segment in _offset_segments(_rectangle_segments(width, depth), x0 - min_x, y0 - min_y):
            geometry.append(
                {
                    "start": segment["start"],
                    "end": segment["end"],
                    "color": color,
                    "linewidth": lineweight,
                }
            )

    callout_text = [
        "SELECTED PART HIGHLIGHTED",
        f"INSTANCES: {', '.join(highlighted_instance_ids) if highlighted_instance_ids else '-'}",
    ]
    return {
        "name": "booth_context",
        "title": "LOCATION IN BOOTH",
        "fills": fills,
        "geometry": geometry,
        "dimensions": [
            {"orientation": "horizontal", "points": ((0.0, 0.0), (overall_width, 0.0)), "text": f"{int(round(overall_width))} mm"},
            {"orientation": "vertical", "points": ((overall_width, 0.0), (overall_width, overall_depth)), "text": f"{int(round(overall_depth))} mm"},
        ],
        "callout_anchor": (overall_width * 0.02, overall_depth * 0.85),
        "callout_text": callout_text,
    }
