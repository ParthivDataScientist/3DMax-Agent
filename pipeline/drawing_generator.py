"""Generate engineering-grade orthographic drawings from analysis JSON files."""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np


import tempfile as _tempfile
CACHE_DIR = Path(_tempfile.gettempdir()) / "obj-agent-cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_DIR))
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_DIR / "matplotlib" / str(os.getpid())))
os.environ.setdefault("EZDXF_DISABLE_CACHING", "1")
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import ezdxf
from ezdxf import units as ezdxf_units
from ezdxf.enums import TextEntityAlignment

import matplotlib

matplotlib.use("Agg")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


OUTPUT_DIR = Path("output")
MM_PER_INCH = 25.4
MIN_FIGURE_WIDTH_INCHES = 11.69
MIN_FIGURE_HEIGHT_INCHES = 8.27
MM_PER_INCH_DRAWING_SCALE = 180.0

AXIS_LABELS = {
    "x": "Width",
    "y": "Depth",
    "z": "Height",
}

VIEW_ORDER = ("front", "top", "side")
VIEW_TITLES = {
    "front": "FRONT VIEW",
    "top": "TOP VIEW",
    "side": "RIGHT SIDE VIEW",
}

DIMENSION_POSITIONS = {
    "front": {"horizontal": "bottom", "vertical": "left"},
    "top": {"horizontal": "top", "vertical": "left"},
    "side": {"horizontal": "bottom", "vertical": "right"},
}


class DrawingGenerationError(Exception):
    """Raised when drawing outputs cannot be generated from the JSON payload."""


@dataclass(frozen=True)
class DrawingMetadata:
    """Sheet metadata shown in the title block."""

    drawing_name: str
    source_name: str
    units: str
    material: str = "SPECIFY"
    revision: str = "01"
    date_str: str = ""
    drafter: str = "AUTO"
    scale_label: str = "1:1"
    sheet_label: str = ""


@dataclass(frozen=True)
class ViewSpec:
    """Normalized view definition for both visual and DXF output."""

    name: str
    title: str
    width_mm: float
    height_mm: float
    dimension_width_mm: float
    dimension_height_mm: float
    depth_mm: float
    plane: str
    horizontal_axis: str
    vertical_axis: str
    depth_axis: str
    projected_edges: tuple[tuple[tuple[float, float], tuple[float, float]], ...]
    projected_entities: tuple[dict[str, Any], ...] = ()
    origin_x: float = 0.0
    origin_y: float = 0.0


@dataclass(frozen=True)
class DrawingStyle:
    """Computed drawing style values in millimeters."""

    max_dimension_mm: float
    view_gap_mm: float
    border_margin_mm: float
    dimension_offset_mm: float
    extension_gap_mm: float
    extension_overrun_mm: float
    title_offset_mm: float
    geometry_linewidth_pt: float
    dimension_linewidth_pt: float
    arrow_mutation_scale_pt: float
    text_height_mm: float
    title_text_height_mm: float
    header_text_height_mm: float
    title_block_width_mm: float
    title_block_height_mm: float
    sheet_padding_mm: float


@dataclass(frozen=True)
class SheetLayout:
    """Sheet extents and title block placement."""

    sheet_width_mm: float
    sheet_height_mm: float
    title_block_origin_x: float
    title_block_origin_y: float
    title_block_width_mm: float
    title_block_height_mm: float


def format_mm(value: float) -> str:
    """Format an engineering dimension value.
    Smooths micro-anomalies (like 199.917 to 200) assuming tight manufacturing tolerances.
    """
    nearest_int = round(value)
    if abs(value - nearest_int) <= 0.15:
        return str(int(nearest_int))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def require_number(value: Any, field_name: str) -> float:
    """Validate that a field contains a positive number."""
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise DrawingGenerationError(f"Invalid numeric value for '{field_name}': {value!r}") from exc

    if numeric <= 0.0:
        raise DrawingGenerationError(f"Expected '{field_name}' to be positive, got {numeric}.")
    return numeric


def require_float(value: Any, field_name: str) -> float:
    """Validate that a field contains any finite float."""
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise DrawingGenerationError(f"Invalid numeric value for '{field_name}': {value!r}") from exc

    if not np.isfinite(numeric):
        raise DrawingGenerationError(f"Expected '{field_name}' to be finite, got {numeric}.")
    return numeric


def load_analysis_json(json_path: Path) -> dict[str, Any]:
    """Load the analysis JSON payload from disk."""
    if not json_path.exists():
        raise DrawingGenerationError(f"JSON file not found: {json_path}")

    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DrawingGenerationError(f"Invalid JSON file: {exc}") from exc


def extract_metadata(payload: dict[str, Any], json_path: Path) -> DrawingMetadata:
    """Extract sheet metadata from the analysis payload."""
    input_payload = payload.get("input", {})
    if not isinstance(input_payload, dict):
        input_payload = {}

    units = str(input_payload.get("unit", "mm")).strip() or "mm"
    if units.lower() != "mm":
        raise DrawingGenerationError(f"Expected millimeter input units, got {units!r}.")

    drawing_name = str(input_payload.get("mesh_name") or json_path.stem).strip() or json_path.stem
    source_name = str(input_payload.get("file_name") or json_path.name).strip() or json_path.name
    return DrawingMetadata(
        drawing_name=f"{drawing_name.upper()} ORTHOGRAPHIC DRAWING",
        source_name=source_name,
        units=units.lower(),
    )


def extract_views(payload: dict[str, Any]) -> list[ViewSpec]:
    """Normalize the top/front/side views from the JSON payload."""
    views = payload.get("views")
    if not isinstance(views, dict):
        raise DrawingGenerationError("Input JSON is missing the top-level 'views' object.")

    normalized_views: list[ViewSpec] = []
    for view_name in VIEW_ORDER:
        view_payload = views.get(view_name)
        if not isinstance(view_payload, dict):
            raise DrawingGenerationError(f"Input JSON is missing views.{view_name}.")

        dimensions = view_payload.get("dimensions")
        if not isinstance(dimensions, dict):
            raise DrawingGenerationError(f"Input JSON is missing views.{view_name}.dimensions.")

        dimension_width_mm = require_number(dimensions.get("width"), f"views.{view_name}.dimensions.width")
        dimension_height_mm = require_number(dimensions.get("height"), f"views.{view_name}.dimensions.height")
        depth_mm = require_number(dimensions.get("depth"), f"views.{view_name}.dimensions.depth")

        bounds_2d = view_payload.get("bounds_2d")
        if not isinstance(bounds_2d, dict):
            raise DrawingGenerationError(f"Input JSON is missing views.{view_name}.bounds_2d.")

        bounds_size = bounds_2d.get("size")
        if not isinstance(bounds_size, (list, tuple)) or len(bounds_size) != 2:
            raise DrawingGenerationError(f"Input JSON is missing views.{view_name}.bounds_2d.size.")

        width_mm = require_number(bounds_size[0], f"views.{view_name}.bounds_2d.size[0]")
        height_mm = require_number(bounds_size[1], f"views.{view_name}.bounds_2d.size[1]")

        edge_payloads = view_payload.get("edges")
        if not isinstance(edge_payloads, list):
            raise DrawingGenerationError(f"Input JSON is missing views.{view_name}.edges.")

        projected_edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for edge_index, edge_payload in enumerate(edge_payloads):
            if not isinstance(edge_payload, dict):
                raise DrawingGenerationError(f"Invalid edge payload for views.{view_name}.edges[{edge_index}].")

            start = edge_payload.get("start")
            end = edge_payload.get("end")
            if not isinstance(start, (list, tuple)) or not isinstance(end, (list, tuple)) or len(start) != 2 or len(end) != 2:
                raise DrawingGenerationError(
                    f"Invalid projected segment for views.{view_name}.edges[{edge_index}]."
                )

            projected_edges.append(
                (
                    (
                        require_float(start[0], f"views.{view_name}.edges[{edge_index}].start[0]"),
                        require_float(start[1], f"views.{view_name}.edges[{edge_index}].start[1]"),
                    ),
                    (
                        require_float(end[0], f"views.{view_name}.edges[{edge_index}].end[0]"),
                        require_float(end[1], f"views.{view_name}.edges[{edge_index}].end[1]"),
                    ),
                )
            )

        projected_entities = tuple(view_payload.get("entities", []))

        horizontal_axis = str(view_payload.get("horizontal_axis", "")).strip().lower()
        vertical_axis = str(view_payload.get("vertical_axis", "")).strip().lower()
        depth_axis = str(view_payload.get("depth_axis", "")).strip().lower()

        if horizontal_axis not in AXIS_LABELS:
            raise DrawingGenerationError(
                f"Unsupported horizontal axis for views.{view_name}: {horizontal_axis!r}"
            )
        if vertical_axis not in AXIS_LABELS:
            raise DrawingGenerationError(
                f"Unsupported vertical axis for views.{view_name}: {vertical_axis!r}"
            )
        if depth_axis not in AXIS_LABELS:
            raise DrawingGenerationError(
                f"Unsupported depth axis for views.{view_name}: {depth_axis!r}"
            )

        normalized_views.append(
            ViewSpec(
                name=view_name,
                title=VIEW_TITLES[view_name],
                width_mm=width_mm,
                height_mm=height_mm,
                dimension_width_mm=dimension_width_mm,
                dimension_height_mm=dimension_height_mm,
                depth_mm=depth_mm,
                plane=str(view_payload.get("plane", "")).strip().upper(),
                horizontal_axis=horizontal_axis,
                vertical_axis=vertical_axis,
                depth_axis=depth_axis,
                projected_edges=tuple(projected_edges),
                projected_entities=projected_entities,
            )
        )

    return normalized_views


def build_drawing_style(view_specs: list[ViewSpec]) -> DrawingStyle:
    """Scale drawing style from the largest view dimension."""
    max_dimension = max(max(view.width_mm, view.height_mm, view.depth_mm) for view in view_specs)
    total_span = sum(view.width_mm for view in view_specs)

    return DrawingStyle(
        max_dimension_mm=max_dimension,
        view_gap_mm=max(180.0, max_dimension * 0.22),
        border_margin_mm=max(25.0, max_dimension * 0.025),
        dimension_offset_mm=max(85.0, max_dimension * 0.12),
        extension_gap_mm=max(10.0, max_dimension * 0.012),
        extension_overrun_mm=max(16.0, max_dimension * 0.018),
        title_offset_mm=max(70.0, max_dimension * 0.10),
        geometry_linewidth_pt=1.8,
        dimension_linewidth_pt=0.95,
        arrow_mutation_scale_pt=max(10.0, max_dimension * 0.010),
        text_height_mm=max(24.0, max_dimension * 0.028),
        title_text_height_mm=max(28.0, max_dimension * 0.034),
        header_text_height_mm=max(18.0, max_dimension * 0.022),
        title_block_width_mm=max(360.0, min(total_span * 0.34, 520.0)),
        title_block_height_mm=max(130.0, max_dimension * 0.14),
        sheet_padding_mm=max(40.0, max_dimension * 0.040),
    )


def layout_views(view_specs: list[ViewSpec], style: DrawingStyle) -> list[ViewSpec]:
    """Place front/top/right views using a standard engineering layout."""
    view_map = {view.name: view for view in view_specs}

    missing_views = [name for name in VIEW_ORDER if name not in view_map]
    if missing_views:
        raise DrawingGenerationError(f"Missing required orthographic views: {', '.join(missing_views)}")

    left_reserve = style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    right_reserve = style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    top_reserve = (
        style.border_margin_mm
        + style.dimension_offset_mm
        + style.title_offset_mm
        + style.sheet_padding_mm
    )
    bottom_reserve = (
        style.border_margin_mm
        + style.title_block_height_mm
        + style.dimension_offset_mm
        + style.sheet_padding_mm
    )

    front = replace(view_map["front"], origin_x=left_reserve, origin_y=bottom_reserve)
    top = replace(
        view_map["top"],
        origin_x=front.origin_x + (front.width_mm - view_map["top"].width_mm) / 2.0,
        origin_y=front.origin_y + front.height_mm + style.view_gap_mm,
    )
    side = replace(
        view_map["side"],
        origin_x=front.origin_x + front.width_mm + style.view_gap_mm,
        origin_y=front.origin_y + (front.height_mm - view_map["side"].height_mm) / 2.0,
    )

    laid_out = [front, top, side]
    min_x = min(view.origin_x for view in laid_out)
    min_y = min(view.origin_y for view in laid_out)
    offset_x = style.sheet_padding_mm - min_x if min_x < style.sheet_padding_mm else 0.0
    offset_y = style.sheet_padding_mm - min_y if min_y < style.sheet_padding_mm else 0.0

    normalized = [
        replace(
            view,
            origin_x=view.origin_x + offset_x,
            origin_y=view.origin_y + offset_y,
        )
        for view in laid_out
    ]

    max_x = max(view.origin_x + view.width_mm for view in normalized)
    max_y = max(view.origin_y + view.height_mm for view in normalized)
    if max_x + right_reserve <= 0.0 or max_y + top_reserve <= 0.0:
        raise DrawingGenerationError("Invalid view layout generated for drawing.")

    return normalized


def build_sheet_layout(view_specs: list[ViewSpec], style: DrawingStyle) -> SheetLayout:
    """Compute sheet extents around the views and title block."""
    max_x = max(view.origin_x + view.width_mm for view in view_specs)
    max_y = max(view.origin_y + view.height_mm for view in view_specs)

    sheet_width = max_x + style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    sheet_height = (
        max_y
        + style.border_margin_mm
        + style.dimension_offset_mm
        + style.title_offset_mm
        + style.sheet_padding_mm
    )

    return SheetLayout(
        sheet_width_mm=sheet_width,
        sheet_height_mm=sheet_height,
        title_block_origin_x=sheet_width - style.border_margin_mm - style.title_block_width_mm,
        title_block_origin_y=style.border_margin_mm,
        title_block_width_mm=style.title_block_width_mm,
        title_block_height_mm=style.title_block_height_mm,
    )


def rectangle_edges(
    origin_x: float,
    origin_y: float,
    width_mm: float,
    height_mm: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return the rectangle boundary as four ordered line segments."""
    return [
        ((origin_x, origin_y), (origin_x + width_mm, origin_y)),
        ((origin_x + width_mm, origin_y), (origin_x + width_mm, origin_y + height_mm)),
        ((origin_x + width_mm, origin_y + height_mm), (origin_x, origin_y + height_mm)),
        ((origin_x, origin_y + height_mm), (origin_x, origin_y)),
    ]


def draw_rectangle(
    target: Any,
    origin_x: float,
    origin_y: float,
    width_mm: float,
    height_mm: float,
    *,
    backend: str,
    layer: str = "geometry",
    lineweight: float = 1.8,
) -> None:
    """Draw a rectangular view boundary in matplotlib or DXF."""
    if backend == "matplotlib":
        rectangle = Rectangle(
            (origin_x, origin_y),
            width_mm,
            height_mm,
            fill=False,
            edgecolor="black",
            linewidth=lineweight,
        )
        target.add_patch(rectangle)
        return

    if backend == "dxf":
        for start, end in rectangle_edges(origin_x, origin_y, width_mm, height_mm):
            target.add_line(start, end, dxfattribs={"layer": layer})
        return

    raise DrawingGenerationError(f"Unsupported drawing backend: {backend}")


def draw_edges(target: Any, view_spec: ViewSpec, *, backend: str, style: DrawingStyle) -> None:
    """Draw projected view geometry as line segments."""
    if backend == "matplotlib":
        for start, end in view_spec.projected_edges:
            target.plot(
                [view_spec.origin_x + start[0], view_spec.origin_x + end[0]],
                [view_spec.origin_y + start[1], view_spec.origin_y + end[1]],
                color="black",
                linewidth=style.geometry_linewidth_pt,
                solid_capstyle="butt",
            )
        return

    if backend == "dxf":
        for start, end in view_spec.projected_edges:
            target.add_line(
                (view_spec.origin_x + start[0], view_spec.origin_y + start[1]),
                (view_spec.origin_x + end[0], view_spec.origin_y + end[1]),
                dxfattribs={"layer": "geometry"},
            )
        return

    raise DrawingGenerationError(f"Unsupported drawing backend: {backend}")


def draw_entities(target: Any, view_spec: ViewSpec, *, backend: str, style: DrawingStyle, layer: str = "geometry") -> None:
    """Draw high level projected entities, always including a view-outline rectangle."""
    # Always draw the view bounding-box outline so the view is readable
    # even for meshes that contribute no edge projections.
    draw_rectangle(
        target,
        view_spec.origin_x,
        view_spec.origin_y,
        view_spec.width_mm,
        view_spec.height_mm,
        backend=backend,
        layer=layer,
        lineweight=style.geometry_linewidth_pt,
    )
    if backend == "matplotlib":
        # We rely on draw_edges to draw the lines since matplotlib currently only renders the segments.
        draw_edges(target, view_spec, backend=backend, style=style)
        return

    if backend == "dxf":
        for ent in view_spec.projected_entities:
            ety = ent.get("type", "LINE")
            ent_layer = ent.get("layer", layer)
            if ety == "LINE":
                target.add_line(
                    (view_spec.origin_x + ent["start"][0], view_spec.origin_y + ent["start"][1]),
                    (view_spec.origin_x + ent["end"][0], view_spec.origin_y + ent["end"][1]),
                    dxfattribs={"layer": ent_layer},
                )
            elif ety == "LWPOLYLINE":
                points = [(view_spec.origin_x + pt[0], view_spec.origin_y + pt[1]) for pt in ent["points"]]
                target.add_lwpolyline(points, close=ent.get("closed", False), dxfattribs={"layer": ent_layer})
            elif ety == "CIRCLE":
                target.add_circle(
                    (view_spec.origin_x + ent["center"][0], view_spec.origin_y + ent["center"][1]),
                    ent["radius"],
                    dxfattribs={"layer": ent_layer}
                )
        return

    raise DrawingGenerationError(f"Unsupported drawing backend: {backend}")

def draw_centerlines(target: Any, pt1: tuple[float, float], pt2: tuple[float, float], *, backend: str, style: DrawingStyle) -> None:
    """Draw a classic long-dash-short-dash centerline."""
    if backend == "matplotlib":
        target.plot([pt1[0], pt2[0]], [pt1[1], pt2[1]], color="gray", linewidth=0.5, linestyle="dashdot")
        return
    if backend == "dxf":
        target.add_line(pt1, pt2, dxfattribs={"layer": "center", "linetype": "CENTER", "color": 3})
        return
    raise DrawingGenerationError(f"Unsupported drawing backend: {backend}")

def draw_datum(target: Any, label: str, loc: tuple[float, float], *, backend: str, style: DrawingStyle) -> None:
    """Draw an ASME standard datum box [ A ] at the specified location."""
    box_w = 6.0
    box_h = 6.0
    x, y = loc[0], loc[1]
    # Draw box attached to the point
    pts = [
        (x - box_w/2, y),
        (x + box_w/2, y),
        (x + box_w/2, y + box_h),
        (x - box_w/2, y + box_h),
        (x - box_w/2, y)
    ]
    if backend == "matplotlib":
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        target.plot(xs, ys, color="black", linewidth=0.8)
        target.text(x, y + box_h/2, label, ha="center", va="center", fontsize=8, fontweight="bold")
    elif backend == "dxf":
        target.add_lwpolyline(pts, dxfattribs={"layer": "datum"})
        txt = target.add_text(label, dxfattribs={"layer": "datum", "height": 3.0})
        txt.set_placement((x, y + box_h/2), align=TextEntityAlignment.MIDDLE_CENTER)
    else:
        raise DrawingGenerationError(f"Unsupported backend {backend}")


def draw_dimension_line(
    target: Any,
    *,
    backend: str,
    orientation: str,
    p1: tuple[float, float],
    p2: tuple[float, float],
    dimension_coordinate: float,
    text: str,
    style: DrawingStyle,
) -> None:
    """Draw a standards-style dimension line with extension lines and arrows."""
    dimension_color = "#6A7077"

    if orientation == "horizontal":
        y_ref = p1[1]
        sign = 1.0 if dimension_coordinate >= y_ref else -1.0
        start = (p1[0], dimension_coordinate)
        end = (p2[0], dimension_coordinate)
        ext1_start = (p1[0], y_ref + sign * style.extension_gap_mm)
        ext1_end = (p1[0], dimension_coordinate + sign * style.extension_overrun_mm)
        ext2_start = (p2[0], y_ref + sign * style.extension_gap_mm)
        ext2_end = (p2[0], dimension_coordinate + sign * style.extension_overrun_mm)
        text_position = ((p1[0] + p2[0]) / 2.0, dimension_coordinate)
        text_rotation = 0.0
        angle = 0.0
    elif orientation == "vertical":
        x_ref = p1[0]
        sign = 1.0 if dimension_coordinate >= x_ref else -1.0
        start = (dimension_coordinate, p1[1])
        end = (dimension_coordinate, p2[1])
        ext1_start = (x_ref + sign * style.extension_gap_mm, p1[1])
        ext1_end = (dimension_coordinate + sign * style.extension_overrun_mm, p1[1])
        ext2_start = (x_ref + sign * style.extension_gap_mm, p2[1])
        ext2_end = (dimension_coordinate + sign * style.extension_overrun_mm, p2[1])
        text_position = (dimension_coordinate, (p1[1] + p2[1]) / 2.0)
        text_rotation = 90.0
        angle = 90.0
    else:
        raise DrawingGenerationError(f"Unsupported dimension orientation: {orientation}")

    if backend == "matplotlib":
        target.plot(
            [ext1_start[0], ext1_end[0]],
            [ext1_start[1], ext1_end[1]],
            color=dimension_color,
            linewidth=style.dimension_linewidth_pt,
            solid_capstyle="butt",
        )
        target.plot(
            [ext2_start[0], ext2_end[0]],
            [ext2_start[1], ext2_end[1]],
            color=dimension_color,
            linewidth=style.dimension_linewidth_pt,
            solid_capstyle="butt",
        )
        target.add_patch(
            FancyArrowPatch(
                start,
                end,
                arrowstyle="<->",
                mutation_scale=style.arrow_mutation_scale_pt,
                linewidth=style.dimension_linewidth_pt,
                color=dimension_color,
                shrinkA=0.0,
                shrinkB=0.0,
            )
        )
        target.text(
            text_position[0],
            text_position[1],
            text,
            ha="center",
            va="center",
            rotation=text_rotation,
            fontsize=max(8.0, style.text_height_mm * 0.33),
            color=dimension_color,
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.6},
        )
        return

    if backend == "dxf":
        dimension = target.add_linear_dim(
            base=start,
            p1=p1,
            p2=p2,
            angle=angle,
            dxfattribs={"layer": "dimensions", "dimstyle": "ENG_DIM"},
            override={
                "dimtxt": style.text_height_mm,
                "dimasz": max(10.0, style.text_height_mm * 0.75),
                "dimexo": style.extension_gap_mm,
                "dimexe": style.extension_overrun_mm,
                "dimdec": 3,
                "dimzin": 8,
                "dimclrd": 8,
                "dimclre": 8,
                "dimclrt": 8,
                "dimtfill": 1,
                "dimtfillclr": 7,
            },
        )
        dimension.render()
        geometry_block_name = dimension.dimension.dxf.geometry
        if geometry_block_name:
            geometry_block = target.doc.blocks.get(geometry_block_name)
            for entity in geometry_block:
                if entity.dxftype() == "POINT":
                    continue
                entity.dxf.layer = "dimensions"
        return

    raise DrawingGenerationError(f"Unsupported drawing backend: {backend}")


def draw_view_dimensions(target: Any, view_spec: ViewSpec, *, backend: str, style: DrawingStyle) -> None:
    """Draw the width and height dimensions for one orthographic view."""
    positions = DIMENSION_POSITIONS[view_spec.name]
    x0 = view_spec.origin_x
    y0 = view_spec.origin_y
    x1 = x0 + view_spec.width_mm
    y1 = y0 + view_spec.height_mm

    horizontal_dimension_y = (
        y1 + style.dimension_offset_mm if positions["horizontal"] == "top" else y0 - style.dimension_offset_mm
    )
    vertical_dimension_x = (
        x1 + style.dimension_offset_mm if positions["vertical"] == "right" else x0 - style.dimension_offset_mm
    )

    draw_dimension_line(
        target,
        backend=backend,
        orientation="horizontal",
        p1=(x0, y0 if positions["horizontal"] == "bottom" else y1),
        p2=(x1, y0 if positions["horizontal"] == "bottom" else y1),
        dimension_coordinate=horizontal_dimension_y,
        text=format_mm(view_spec.dimension_width_mm),
        style=style,
    )
    draw_dimension_line(
        target,
        backend=backend,
        orientation="vertical",
        p1=(x0 if positions["vertical"] == "left" else x1, y0),
        p2=(x0 if positions["vertical"] == "left" else x1, y1),
        dimension_coordinate=vertical_dimension_x,
        text=format_mm(view_spec.dimension_height_mm),
        style=style,
    )

    # Inject ASME datums and centerlines for symmetric components
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    if view_spec.name == "top":
        draw_centerlines(target, (x0 - 10.0, cy), (x1 + 10.0, cy), backend=backend, style=style)
        draw_centerlines(target, (cx, y0 - 10.0), (cx, y1 + 10.0), backend=backend, style=style)
        draw_datum(target, "A", (cx, y1 + 15.0), backend=backend, style=style)
    elif view_spec.name == "front":
        draw_centerlines(target, (cx, y0 - 10.0), (cx, y1 + 10.0), backend=backend, style=style)
        draw_datum(target, "B", (cx, y0 - 15.0), backend=backend, style=style)


def draw_view_title(target: Any, view_spec: ViewSpec, *, backend: str, style: DrawingStyle) -> None:
    """Draw the view label: TOP VIEW above its box; FRONT/SIDE below theirs."""
    title_x = view_spec.origin_x + view_spec.width_mm / 2.0

    if view_spec.name == "top":
        # Place ABOVE the top view, above the dimension line
        title_y = view_spec.origin_y + view_spec.height_mm + style.dimension_offset_mm + style.title_offset_mm * 0.7
    else:
        # Place BELOW the front / side view, below the dimension line
        title_y = view_spec.origin_y - style.dimension_offset_mm - style.title_offset_mm * 0.7

    if backend == "matplotlib":
        target.text(
            title_x,
            title_y,
            view_spec.title,
            ha="center",
            va="center",
            fontsize=max(6.0, style.title_text_height_mm * 0.28),
            fontweight="bold",
            color="black",
        )
        return

    if backend == "dxf":
        text = target.add_text(
            view_spec.title,
            dxfattribs={"layer": "text", "height": style.title_text_height_mm},
        )
        text.set_placement((title_x, title_y), align=TextEntityAlignment.MIDDLE_CENTER)
        return

    raise DrawingGenerationError(f"Unsupported drawing backend: {backend}")


def draw_sheet_border(target: Any, sheet_layout: SheetLayout, *, backend: str, style: DrawingStyle) -> None:
    """Draw a border rectangle around the sheet."""
    x = style.border_margin_mm
    y = style.border_margin_mm
    width = sheet_layout.sheet_width_mm - (2.0 * style.border_margin_mm)
    height = sheet_layout.sheet_height_mm - (2.0 * style.border_margin_mm)
    draw_rectangle(
        target,
        x,
        y,
        width,
        height,
        backend=backend,
        layer="geometry",
        lineweight=1.2,
    )


def add_centered_text(
    target: Any,
    text_value: str,
    insert: tuple[float, float],
    *,
    backend: str,
    height_mm: float,
    layer: str = "text",
    bold: bool = False,
) -> None:
    """Add centered text to either backend."""
    if backend == "matplotlib":
        target.text(
            insert[0],
            insert[1],
            text_value,
            ha="center",
            va="center",
            fontsize=max(8.0, height_mm * 0.30),
            fontweight="bold" if bold else "normal",
            color="black",
        )
        return

    if backend == "dxf":
        text = target.add_text(
            text_value,
            dxfattribs={"layer": layer, "height": height_mm},
        )
        text.set_placement(insert, align=TextEntityAlignment.MIDDLE_CENTER)
        return

    raise DrawingGenerationError(f"Unsupported drawing backend: {backend}")


def add_left_text(
    target: Any,
    text_value: str,
    insert: tuple[float, float],
    *,
    backend: str,
    height_mm: float,
    layer: str = "text",
    bold: bool = False,
) -> None:
    """Add left-aligned text to either backend."""
    if backend == "matplotlib":
        target.text(
            insert[0],
            insert[1],
            text_value,
            ha="left",
            va="center",
            fontsize=max(7.5, height_mm * 0.30),
            fontweight="bold" if bold else "normal",
            color="black",
        )
        return

    if backend == "dxf":
        text = target.add_text(
            text_value,
            dxfattribs={"layer": layer, "height": height_mm},
        )
        text.set_placement(insert, align=TextEntityAlignment.MIDDLE_LEFT)
        return

    raise DrawingGenerationError(f"Unsupported drawing backend: {backend}")


def draw_title_block(
    target: Any,
    metadata: DrawingMetadata,
    sheet_layout: SheetLayout,
    *,
    backend: str,
    style: DrawingStyle,
) -> None:
    """Draw an ISO/ASME standard engineering title block."""
    x = sheet_layout.title_block_origin_x
    y = sheet_layout.title_block_origin_y
    width = sheet_layout.title_block_width_mm
    height = sheet_layout.title_block_height_mm
    
    row_h = height / 4.0
    r1 = y + height - row_h
    r2 = r1 - row_h
    r3 = r2 - row_h
    r4 = y
    
    c2_mid = x + width * 0.50
    c3_1 = x + width * 0.22
    c3_2 = c3_1 + width * 0.18
    c3_3 = c3_2 + width * 0.35
    c4_1 = x + width * 0.22
    c4_2 = c4_1 + width * 0.25
    c4_3 = c4_2 + width * 0.28
    
    draw_rectangle(target, x, y, width, height, backend=backend, layer="geometry", lineweight=1.0)
    
    lines = [
        ((x, r1), (x + width, r1)),
        ((x, r2), (x + width, r2)),
        ((x, r3), (x + width, r3)),
        ((c2_mid, r2), (c2_mid, r1)),
        ((c3_1, r3), (c3_1, r2)),
        ((c3_2, r3), (c3_2, r2)),
        ((c3_3, r3), (c3_3, r2)),
        ((c4_1, r4), (c4_1, r3)),
        ((c4_2, r4), (c4_2, r3)),
        ((c4_3, r4), (c4_3, r3)),
        ((c3_3, r4), (c3_3, r3)),
    ]
    
    if backend == "matplotlib":
        for start, end in lines:
            target.plot([start[0], end[0]], [start[1], end[1]], color="black", linewidth=0.9)
    elif backend == "dxf":
        for start, end in lines:
            target.add_line(start, end, dxfattribs={"layer": "geometry"})
    else:
        raise DrawingGenerationError(f"Unsupported drawing backend: {backend}")

    header_h = style.header_text_height_mm
    value_h = style.text_height_mm
    
    def _header(txt: str, loc_x: float, loc_y: float) -> None:
        add_left_text(target, txt, (loc_x + 5.0, loc_y - header_h * 0.8), backend=backend, height_mm=header_h, bold=True)
        
    def _val(txt: str, loc_x: float, loc_y: float) -> None:
        add_left_text(target, txt, (loc_x + 5.0, loc_y + row_h * 0.35), backend=backend, height_mm=value_h)

    _header("DRAWING NAME", x, r1 + row_h)
    _val(metadata.drawing_name, x, r1)
    
    _header("SOURCE / PART ID", x, r2 + row_h)
    _val(metadata.source_name, x, r2)
    _header("MATERIAL", c2_mid, r2 + row_h)
    _val(metadata.material, c2_mid, r2)
    
    _header("DATE", x, r3 + row_h)
    _val(metadata.date_str, x, r3)
    _header("REV", c3_1, r3 + row_h)
    _val(metadata.revision, c3_1, r3)
    _header("DRAFTER", c3_2, r3 + row_h)
    _val(metadata.drafter, c3_2, r3)
    _header("GENERAL TOLERANCES", c3_3, r3 + row_h)
    add_left_text(target, "LINEAR: ± 0.1 mm", (c3_3 + 5.0, r3 + row_h * 0.45), backend=backend, height_mm=header_h)
    add_left_text(target, "ANGULAR: ± 0.5°", (c3_3 + 5.0, r3 + row_h * 0.15), backend=backend, height_mm=header_h)
    
    _header("UNITS", x, r4 + row_h)
    _val(metadata.units.upper(), x, r4)
    _header("SCALE", c4_1, r4 + row_h)
    _val(metadata.scale_label, c4_1, r4)
    _header("SHEET", c4_2, r4 + row_h)
    _val(metadata.sheet_label, c4_2, r4)
    _header("PROJECTION", c4_3, r4 + row_h)
    _val("THIRD ANGLE", c4_3, r4)


def output_paths(json_path: Path) -> dict[str, Path]:
    """Resolve PNG, PDF, and DXF output paths."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    base_name = json_path.stem
    return {
        "png": OUTPUT_DIR / f"{base_name}_drawing.png",
        "pdf": OUTPUT_DIR / f"{base_name}_drawing.pdf",
        "dxf": OUTPUT_DIR / f"{base_name}_drawing.dxf",
    }


def generate_matplotlib_drawing(
    metadata: DrawingMetadata,
    view_specs: list[ViewSpec],
    sheet_layout: SheetLayout,
    style: DrawingStyle,
    png_path: Path,
    pdf_path: Path,
) -> None:
    """Generate a professional technical sheet in PNG and PDF."""
    figure_width_inches = max(MIN_FIGURE_WIDTH_INCHES, sheet_layout.sheet_width_mm / MM_PER_INCH_DRAWING_SCALE)
    figure_height_inches = max(MIN_FIGURE_HEIGHT_INCHES, sheet_layout.sheet_height_mm / MM_PER_INCH_DRAWING_SCALE)

    figure, axis = plt.subplots(figsize=(figure_width_inches, figure_height_inches))
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlim(0.0, sheet_layout.sheet_width_mm)
    axis.set_ylim(0.0, sheet_layout.sheet_height_mm)
    axis.axis("off")

    draw_sheet_border(axis, sheet_layout, backend="matplotlib", style=style)
    draw_title_block(axis, metadata, sheet_layout, backend="matplotlib", style=style)

    for view in view_specs:
        draw_edges(axis, view, backend="matplotlib", style=style)
        draw_view_dimensions(axis, view, backend="matplotlib", style=style)
        draw_view_title(axis, view, backend="matplotlib", style=style)

    figure.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.98)
    figure.savefig(png_path, dpi=300, facecolor="white", bbox_inches="tight", pad_inches=0.08)
    figure.savefig(pdf_path, dpi=300, facecolor="white", bbox_inches="tight", pad_inches=0.08)
    plt.close(figure)


def configure_dimension_style(document: ezdxf.EzDxfDocument, style: DrawingStyle) -> None:
    """Create a reusable millimeter dimension style."""
    if "ENG_DIM" in document.dimstyles:
        return

    dimstyle = document.dimstyles.duplicate_entry("EZDXF", "ENG_DIM")
    dimstyle.dxf.dimtxt = style.text_height_mm
    dimstyle.dxf.dimasz = max(10.0, style.text_height_mm * 0.75)
    dimstyle.dxf.dimexo = style.extension_gap_mm
    dimstyle.dxf.dimexe = style.extension_overrun_mm
    dimstyle.dxf.dimclrd = 8
    dimstyle.dxf.dimclre = 8
    dimstyle.dxf.dimclrt = 8
    dimstyle.dxf.dimdec = 3
    dimstyle.dxf.dimzin = 8
    dimstyle.dxf.dimtfill = 1
    dimstyle.dxf.dimtfillclr = 7


def generate_dxf(
    metadata: DrawingMetadata,
    view_specs: list[ViewSpec],
    sheet_layout: SheetLayout,
    style: DrawingStyle,
    dxf_path: Path,
) -> None:
    """Generate an AutoCAD-compatible DXF sheet."""

    document = ezdxf.new("R2010", setup=True)
    document.units = ezdxf_units.MM
    document.header["$INSUNITS"] = ezdxf_units.MM

    for layer_name, color in (("geometry", 7), ("dimensions", 8), ("text", 3)):
        if layer_name not in document.layers:
            document.layers.add(layer_name, color=color)

    configure_dimension_style(document, style)

    modelspace = document.modelspace()
    draw_sheet_border(modelspace, sheet_layout, backend="dxf", style=style)
    draw_title_block(modelspace, metadata, sheet_layout, backend="dxf", style=style)

    for view in view_specs:
        draw_edges(modelspace, view, backend="dxf", style=style)
        draw_view_dimensions(modelspace, view, backend="dxf", style=style)
        draw_view_title(modelspace, view, backend="dxf", style=style)

    auditor = document.audit()
    if auditor.has_errors:
        messages = "; ".join(str(error) for error in auditor.errors[:5])
        raise DrawingGenerationError(f"DXF audit reported errors: {messages}")
    document.saveas(str(dxf_path))


def generate_outputs(json_path: Path) -> dict[str, Path]:
    """Generate PNG, PDF, and DXF outputs from an analysis JSON file."""
    payload = load_analysis_json(json_path)
    metadata = extract_metadata(payload, json_path)
    raw_view_specs = extract_views(payload)
    style = build_drawing_style(raw_view_specs)
    view_specs = layout_views(raw_view_specs, style)
    sheet_layout = build_sheet_layout(view_specs, style)
    paths = output_paths(json_path)

    generate_matplotlib_drawing(metadata, view_specs, sheet_layout, style, paths["png"], paths["pdf"])
    generate_dxf(metadata, view_specs, sheet_layout, style, paths["dxf"])
    return paths


def normalize_json_path_argument(path_parts: list[str]) -> Path:
    """Join CLI path tokens so unquoted paths with spaces still work."""
    return Path(" ".join(path_parts)).expanduser()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Generate PNG, PDF, and DXF orthographic drawings from an analysis JSON file."
    )
    parser.add_argument("json_path", nargs="+", help="Path to the analysis JSON file.")
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint for drawing generation."""
    args = parse_args()
    json_path = normalize_json_path_argument(args.json_path)

    try:
        paths = generate_outputs(json_path)
    except DrawingGenerationError as exc:
        print(f"Drawing generation failed: {exc}")
        return 1
    except Exception as exc:  # pragma: no cover - unexpected runtime protection for CLI usage.
        print(f"Drawing generation failed: Unexpected error: {exc}")
        return 1

    print(f"Saved PNG drawing to {paths['png']}")
    print(f"Saved PDF drawing to {paths['pdf']}")
    print(f"Saved DXF drawing to {paths['dxf']}")
    return 0
