"""Fabrication drawing package generation for assembly, elevations, and part sheets."""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import units as ezdxf_units
import matplotlib.pyplot as plt

from drawing_generator import (
    DrawingMetadata,
    DrawingStyle,
    SheetLayout,
    ViewSpec,
    add_centered_text,
    add_left_text,
    configure_dimension_style,
    draw_edges,
    draw_entities,
    draw_sheet_border,
    draw_title_block,
    draw_view_dimensions,
    draw_view_title,
)


MM_PER_INCH = 25.4
VIEW_TITLES = {
    "front": "FRONT VIEW",
    "top": "TOP VIEW",
    "side": "RIGHT SIDE VIEW",
}
VIEW_AXIS_INDEX = {
    "front": (0, 2),
    "top": (0, 1),
    "side": (1, 2),
}
ISO_SHEETS = [
    ("A4", 210.0, 297.0),
    ("A3", 297.0, 420.0),
    ("A2", 420.0, 594.0),
    ("A1", 594.0, 841.0),
    ("A0", 841.0, 1189.0),
]
# Denominators < 1 = magnification (e.g. 0.2 → 5:1). Denominators > 1 = reduction (e.g. 10 → 1:10).
SCALE_DENOMINATORS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100]
SUPPORTED_OUTPUT_EXTENSIONS = (".pdf", ".png", ".dxf")


def configured_output_extensions() -> tuple[str, ...]:
    """Return requested drawing output formats; default to PDF only for speed."""
    raw_formats = os.getenv("DRAWING_OUTPUT_FORMATS", "pdf")
    extensions: list[str] = []
    for item in raw_formats.split(","):
        normalized = item.strip().lower()
        if not normalized:
            continue
        extension = normalized if normalized.startswith(".") else f".{normalized}"
        if extension in SUPPORTED_OUTPUT_EXTENSIONS and extension not in extensions:
            extensions.append(extension)
    return tuple(extensions) or (".pdf",)


OUTPUT_EXTENSIONS = configured_output_extensions()
NOTE_LINE_GAP_MM = 1.2
NOTE_PANEL_PAD_MM = 8.0
MIN_LABEL_SPACING_MM = 5.0
OBJECT_LABELS = {
    "wall_panel": "WALL",
    "partition": "PARTITION",
    "back_panel": "BACK PANEL",
    "floor_panel": "FLOOR",
    "table_top": "TABLE TOP",
    "counter": "COUNTER",
    "shelf": "SHELF",
    "acrylic_logo": "LOGO",
    "frame": "FRAME",
    "pole": "POLE",
}
BOOTH_PRIORITY = {
    "wall_panel": 0,
    "partition": 1,
    "back_panel": 2,
    "floor_panel": 3,
    "counter": 4,
    "table_top": 5,
    "shelf": 6,
    "frame": 7,
    "pole": 8,
}


@dataclass(frozen=True)
class PageSpec:
    """Selected paper size and drawing scale for one sheet."""

    sheet_name: str
    orientation: str
    width_mm: float
    height_mm: float
    scale_denominator: float

    @property
    def scale_label(self) -> str:
        d = self.scale_denominator
        if d < 1:
            mag = round(1.0 / d)
            return f"{mag}:1"
        n = int(d) if d == int(d) else d
        return f"1:{n}"

    @property
    def sheet_label(self) -> str:
        return f"{self.sheet_name} {self.orientation.upper()}"


@dataclass(frozen=True)
class LabelSpec:
    """Annotation callout to place on a sheet."""

    text: str
    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class SheetPlan:
    """All drawing inputs required to render one fabrication sheet."""

    page_spec: PageSpec
    style: DrawingStyle
    view_specs: list[ViewSpec]
    sheet_layout: SheetLayout


def slugify(value: str) -> str:
    """Convert a display label into a filesystem-friendly slug."""
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return normalized.strip("_") or "drawing"


def view_spec_from_view_payload(view_name: str, view_payload: dict[str, Any]) -> ViewSpec:
    """Convert a projection payload into a draw-ready ViewSpec."""
    bounds_size = [float(value) for value in view_payload["bounds_2d"]["size"]]
    edges = tuple(
        (
            (float(edge["start"][0]), float(edge["start"][1])),
            (float(edge["end"][0]), float(edge["end"][1])),
        )
        for edge in view_payload.get("edges", [])
    )
    return ViewSpec(
        name=view_name,
        title=VIEW_TITLES[view_name],
        width_mm=bounds_size[0],
        height_mm=bounds_size[1],
        dimension_width_mm=float(view_payload["dimensions"]["width"]),
        dimension_height_mm=float(view_payload["dimensions"]["height"]),
        depth_mm=float(view_payload["dimensions"]["depth"]),
        plane=str(view_payload["plane"]),
        horizontal_axis=str(view_payload["horizontal_axis"]),
        vertical_axis=str(view_payload["vertical_axis"]),
        depth_axis=str(view_payload["depth_axis"]),
        projected_edges=edges,
        projected_entities=tuple(view_payload.get("entities", [])),
    )


def build_page_style(view_specs: list[ViewSpec]) -> DrawingStyle:
    """Use paper-space styling suitable for ISO fabrication sheets."""
    max_dimension_mm = max((max(view.width_mm, view.height_mm) for view in view_specs), default=100.0)
    return DrawingStyle(
        max_dimension_mm=max_dimension_mm,
        view_gap_mm=18.0,
        border_margin_mm=10.0,
        dimension_offset_mm=12.0,
        extension_gap_mm=2.5,
        extension_overrun_mm=4.0,
        title_offset_mm=8.0,
        geometry_linewidth_pt=1.2,
        dimension_linewidth_pt=0.65,
        arrow_mutation_scale_pt=8.0,
        text_height_mm=3.5,
        title_text_height_mm=5.0,
        header_text_height_mm=2.5,
        title_block_width_mm=92.0,
        title_block_height_mm=38.0,
        sheet_padding_mm=12.0,
    )


def scale_point(point: list[float] | tuple[float, float], scale_denominator: float) -> list[float]:
    """Scale a two-dimensional model-space point into paper-space."""
    return [float(point[0]) / scale_denominator, float(point[1]) / scale_denominator]


def scale_projected_entity(entity: dict[str, Any], scale_denominator: float) -> dict[str, Any]:
    """Scale projected DXF-style entities without mutating the analysis payload."""
    scaled = dict(entity)
    entity_type = str(entity.get("type", "LINE")).upper()

    if entity_type == "LINE":
        scaled["start"] = scale_point(entity["start"], scale_denominator)
        scaled["end"] = scale_point(entity["end"], scale_denominator)
    elif entity_type == "LWPOLYLINE":
        scaled["points"] = [scale_point(point, scale_denominator) for point in entity.get("points", [])]
    elif entity_type == "CIRCLE":
        scaled["center"] = scale_point(entity["center"], scale_denominator)
        scaled["radius"] = float(entity["radius"]) / scale_denominator

    return scaled


def scale_view_spec(view_spec: ViewSpec, scale_denominator: float) -> ViewSpec:
    """Convert model-space view geometry into paper-space using the chosen scale."""
    scaled_edges = tuple(
        (
            (start[0] / scale_denominator, start[1] / scale_denominator),
            (end[0] / scale_denominator, end[1] / scale_denominator),
        )
        for start, end in view_spec.projected_edges
    )
    scaled_entities = tuple(
        scale_projected_entity(entity, scale_denominator)
        for entity in view_spec.projected_entities
    )
    return replace(
        view_spec,
        width_mm=view_spec.width_mm / scale_denominator,
        height_mm=view_spec.height_mm / scale_denominator,
        projected_edges=scaled_edges,
        projected_entities=scaled_entities,
    )


def note_panel_height(notes: list[str], style: DrawingStyle) -> float:
    if not notes:
        return 0.0
    return NOTE_PANEL_PAD_MM + (len(notes) * (style.text_height_mm + NOTE_LINE_GAP_MM))


def bottom_reserved_height(style: DrawingStyle, notes: list[str]) -> float:
    lower_panel_height = max(style.title_block_height_mm, note_panel_height(notes, style))
    return style.border_margin_mm + style.sheet_padding_mm + lower_panel_height + style.dimension_offset_mm


def layout_three_views(view_specs: list[ViewSpec], style: DrawingStyle, bottom_reserve: float) -> list[ViewSpec]:
    """Place front/top/side views onto one orthographic sheet."""
    view_map = {view.name: view for view in view_specs}
    left_reserve = style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    right_reserve = style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    top_reserve = style.border_margin_mm + style.dimension_offset_mm + style.title_offset_mm + style.sheet_padding_mm

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
    return [front, top, side]


def layout_single_view(view_spec: ViewSpec, style: DrawingStyle, bottom_reserve: float) -> list[ViewSpec]:
    """Place a single elevation view on one sheet."""
    origin_x = style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    origin_y = bottom_reserve
    return [replace(view_spec, origin_x=origin_x, origin_y=origin_y)]


def layout_view_row(view_specs: list[ViewSpec], style: DrawingStyle, bottom_reserve: float) -> list[ViewSpec]:
    """Place one or more views left-to-right, useful for plan/elevation sheets."""
    origin_x = style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    origin_y = bottom_reserve
    max_height = max((view.height_mm for view in view_specs), default=0.0)
    laid_out: list[ViewSpec] = []
    cursor_x = origin_x

    for view in view_specs:
        view_y = origin_y + ((max_height - view.height_mm) / 2.0)
        laid_out.append(replace(view, origin_x=cursor_x, origin_y=view_y))
        cursor_x += view.width_mm + style.view_gap_mm

    return laid_out


def required_sheet_size(view_specs: list[ViewSpec], style: DrawingStyle) -> tuple[float, float]:
    """Compute the minimum paper-space size required for the placed content."""
    max_x = max((view.origin_x + view.width_mm for view in view_specs), default=0.0)
    max_y = max((view.origin_y + view.height_mm for view in view_specs), default=0.0)
    required_width = max_x + style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    required_height = max_y + style.border_margin_mm + style.dimension_offset_mm + style.title_offset_mm + style.sheet_padding_mm
    return required_width, required_height


def fixed_sheet_layout(page_spec: PageSpec, style: DrawingStyle) -> SheetLayout:
    """Build a sheet layout anchored to a selected ISO page."""
    return SheetLayout(
        sheet_width_mm=page_spec.width_mm,
        sheet_height_mm=page_spec.height_mm,
        title_block_origin_x=page_spec.width_mm - style.border_margin_mm - style.title_block_width_mm,
        title_block_origin_y=style.border_margin_mm,
        title_block_width_mm=style.title_block_width_mm,
        title_block_height_mm=style.title_block_height_mm,
    )


def select_sheet_plan(raw_views: list[ViewSpec], *, layout_kind: str, notes: list[str] | None = None) -> SheetPlan:
    """Select the smallest ISO sheet that fits at the largest readable scale."""
    if layout_kind not in {"orthographic", "single", "row"}:
        raise ValueError(f"Unsupported layout kind: {layout_kind}")

    notes = notes or []
    candidates: list[tuple[int, float, float, PageSpec, DrawingStyle, list[ViewSpec]]] = []
    fallback: tuple[float, float, DrawingStyle, list[ViewSpec]] | None = None

    for scale_denominator in SCALE_DENOMINATORS:
        scaled_views = [scale_view_spec(view, scale_denominator) for view in raw_views]
        style = build_page_style(scaled_views)
        reserve_bottom = bottom_reserved_height(style, notes)
        if layout_kind == "orthographic":
            laid_out_views = layout_three_views(scaled_views, style, reserve_bottom)
        elif layout_kind == "row":
            laid_out_views = layout_view_row(scaled_views, style, reserve_bottom)
        else:
            laid_out_views = layout_single_view(scaled_views[0], style, reserve_bottom)
        required_width, required_height = required_sheet_size(laid_out_views, style)
        required_area = required_width * required_height

        if fallback is None or required_area < fallback[0] or (
            abs(required_area - fallback[0]) <= 1e-6 and scale_denominator < fallback[1]
        ):
            fallback = (required_area, scale_denominator, style, laid_out_views)

        for sheet_rank, (sheet_name, first, second) in enumerate(ISO_SHEETS):
            for orientation, width_mm, height_mm in (
                ("portrait", first, second),
                ("landscape", second, first),
            ):
                if required_width <= width_mm and required_height <= height_mm:
                    slack_area = (width_mm * height_mm) - required_area
                    candidates.append(
                        (
                            sheet_rank,
                            scale_denominator,
                            slack_area,
                            PageSpec(sheet_name, orientation, width_mm, height_mm, scale_denominator),
                            style,
                            laid_out_views,
                        )
                    )

    if candidates:
        def _fill_key(item):
            # Maximise fill ratio; break ties by preferring smaller paper then larger scale
            page_area = item[3].width_mm * item[3].height_mm
            fill = (page_area - item[2]) / page_area
            return (-fill, item[0], item[1])
        sheet_rank, _, _, page_spec, style, laid_out_views = sorted(candidates, key=_fill_key)[0]
        _ = sheet_rank
        return SheetPlan(
            page_spec=page_spec,
            style=style,
            view_specs=laid_out_views,
            sheet_layout=fixed_sheet_layout(page_spec, style),
        )

    if fallback is None:
        raise ValueError("Unable to compute a sheet plan for empty input views.")

    _, scale_denominator, style, laid_out_views = fallback
    required_width, required_height = required_sheet_size(laid_out_views, style)
    page_spec = PageSpec("CUSTOM", "landscape", required_width, required_height, scale_denominator)
    return SheetPlan(
        page_spec=page_spec,
        style=style,
        view_specs=laid_out_views,
        sheet_layout=fixed_sheet_layout(page_spec, style),
    )


def scale_labels(labels: list[LabelSpec], scale_denominator: float) -> list[LabelSpec]:
    """Convert model-space label anchors into paper-space coordinates."""
    return [
        LabelSpec(
            text=label.text,
            x_mm=label.x_mm / scale_denominator,
            y_mm=label.y_mm / scale_denominator,
        )
        for label in labels
    ]


def label_collides(label: LabelSpec, placed: list[LabelSpec], min_spacing: float) -> bool:
    return any(
        abs(label.x_mm - other.x_mm) < min_spacing and abs(label.y_mm - other.y_mm) < min_spacing
        for other in placed
    )


def spread_labels(labels: list[LabelSpec], min_spacing: float = MIN_LABEL_SPACING_MM) -> list[LabelSpec]:
    """Nudge dense component labels so repeated callouts do not sit on top of each other."""
    offsets = [
        (0.0, 0.0),
        (min_spacing, 0.0),
        (-min_spacing, 0.0),
        (0.0, min_spacing),
        (0.0, -min_spacing),
        (min_spacing, min_spacing),
        (-min_spacing, min_spacing),
        (min_spacing, -min_spacing),
        (-min_spacing, -min_spacing),
        (min_spacing * 1.6, 0.0),
        (-min_spacing * 1.6, 0.0),
        (0.0, min_spacing * 1.6),
        (0.0, -min_spacing * 1.6),
    ]
    placed: list[LabelSpec] = []
    for label in sorted(labels, key=lambda item: (round(item.y_mm, 3), round(item.x_mm, 3), item.text)):
        candidate = label
        for dx, dy in offsets:
            nudged = LabelSpec(label.text, label.x_mm + dx, label.y_mm + dy)
            if not label_collides(nudged, placed, min_spacing):
                candidate = nudged
                break
        placed.append(candidate)
    return placed


def component_label_for_view(
    component: dict[str, Any],
    assembly_min: list[float],
    view_name: str,
) -> LabelSpec:
    """Project a component center into one orthographic assembly view."""
    minimum = [float(value) for value in component["geometry"]["bounding_box"]["min"]]
    maximum = [float(value) for value in component["geometry"]["bounding_box"]["max"]]
    center = [(minimum[index] + maximum[index]) / 2.0 for index in range(3)]
    axis_u, axis_v = VIEW_AXIS_INDEX[view_name]
    return LabelSpec(
        text=component["instance_id"],
        x_mm=center[axis_u] - assembly_min[axis_u],
        y_mm=center[axis_v] - assembly_min[axis_v],
    )


def component_plan_label_for_view(
    component: dict[str, Any],
    assembly_min: list[float],
    view_name: str,
) -> LabelSpec:
    """Create a descriptive top-plan label inspired by exhibition CAD sheets."""
    label = str(component.get("parent_assembly") or component.get("part_name") or component.get("object_type") or "")
    labeled_component = {**component, "instance_id": f"{component['instance_id']} {label}".strip()}
    return component_label_for_view(labeled_component, assembly_min, view_name)


def build_component_labels(payload: dict[str, Any], view_name: str) -> list[LabelSpec]:
    """Create instance-ID callouts for assembly/elevation drawings."""
    assembly_min = [float(value) for value in payload["bounding_box"]["min"]]
    return [
        component_label_for_view(component, assembly_min, view_name)
        for component in payload.get("components", [])
    ]


def build_component_plan_labels(payload: dict[str, Any], view_name: str) -> list[LabelSpec]:
    """Create descriptive labels for overall plan sheets."""
    assembly_min = [float(value) for value in payload["bounding_box"]["min"]]
    return [
        component_plan_label_for_view(component, assembly_min, view_name)
        for component in payload.get("components", [])
    ]


def format_mm(value: Any) -> str:
    """Format a measurement compactly for drawing notes."""
    if value is None:
        return "-"
    numeric = float(value)
    if abs(numeric - round(numeric)) <= 0.05:
        return str(int(round(numeric)))
    return f"{numeric:.1f}"


def object_label(component: dict[str, Any]) -> str:
    object_type = str(component.get("object_type") or component.get("type") or "part")
    return OBJECT_LABELS.get(object_type, object_type.replace("_", " ").upper())


def short_component_name(component: dict[str, Any]) -> str:
    name = str(component.get("component_name") or object_label(component)).upper()
    parent = str(component.get("parent_assembly") or "").upper()
    if parent and name.startswith(parent):
        shortened = name[len(parent):].strip()
        return shortened or parent
    return name


def component_sort_key(component: dict[str, Any]) -> tuple[int, str]:
    object_type = str(component.get("object_type") or "")
    return (
        BOOTH_PRIORITY.get(object_type, 99),
        str(component.get("parent_assembly") or ""),
        str(component.get("instance_id") or ""),
    )


def projected_size_for_view(component: dict[str, Any], view_name: str) -> tuple[float | None, float | None]:
    bbox_size = component.get("geometry", {}).get("bounding_box", {}).get("size", [])
    axis_u, axis_v = VIEW_AXIS_INDEX[view_name]
    if len(bbox_size) <= max(axis_u, axis_v):
        return None, None
    return float(bbox_size[axis_u]), float(bbox_size[axis_v])


def component_schedule_line(component: dict[str, Any], view_name: str | None = None) -> str:
    dims = component.get("dimensions", {})
    part_group_id = component.get("part_group_id", "-")
    parent = str(component.get("parent_assembly") or "UNASSIGNED")
    component_name = short_component_name(component)
    if view_name:
        size_u, size_v = projected_size_for_view(component, view_name)
        size_text = f"{format_mm(size_u)} x {format_mm(size_v)} mm"
    else:
        size_text = (
            f"LxWxH {format_mm(dims.get('length'))} x "
            f"{format_mm(dims.get('width'))} x {format_mm(dims.get('height'))} mm"
        )
    return f"{component.get('instance_id')} {parent} / {component_name} {part_group_id}: {size_text}"


def component_schedule_notes(
    components: list[dict[str, Any]],
    *,
    title: str,
    view_name: str | None = None,
    max_items: int = 8,
) -> list[str]:
    sorted_components = sorted(components, key=component_sort_key)
    notes = [title]
    notes.extend(component_schedule_line(component, view_name) for component in sorted_components[:max_items])
    if len(sorted_components) > max_items:
        notes.append(f"+ {len(sorted_components) - max_items} MORE - SEE analysis/component_schedule.csv")
    return notes


def type_summary_notes(components: list[dict[str, Any]], *, max_items: int = 5) -> list[str]:
    counts = Counter(str(component.get("object_type") or "unknown") for component in components)
    if not counts:
        return []
    ordered = sorted(counts.items(), key=lambda item: (BOOTH_PRIORITY.get(item[0], 99), item[0]))
    summary = [
        f"{OBJECT_LABELS.get(object_type, object_type.replace('_', ' ').upper())}: {count}"
        for object_type, count in ordered[:max_items]
    ]
    return ["COMPONENT TYPE SUMMARY", *summary]


def format_instance_list(instance_ids: list[str], *, max_items: int = 8) -> str:
    if len(instance_ids) <= max_items:
        return ", ".join(instance_ids)
    return f"{', '.join(instance_ids[:max_items])}, +{len(instance_ids) - max_items} more"


def sheet_files(output_base: Path) -> list[str]:
    """Return the generated paths for a sheet in package order."""
    return [str(output_base.with_suffix(extension)) for extension in OUTPUT_EXTENSIONS]


def sheet_record(
    sheet_no: str,
    title: str,
    category: str,
    output_base: Path,
    page_spec: PageSpec,
) -> dict[str, Any]:
    """Build manifest metadata for one generated shop-style sheet."""
    return {
        "sheet_no": sheet_no,
        "title": title,
        "category": category,
        "files": sheet_files(output_base),
        "sheet": page_spec.sheet_label,
        "scale": page_spec.scale_label,
    }


def draw_labels(target: Any, labels: list[LabelSpec], *, backend: str, view_offset: tuple[float, float], text_height_mm: float) -> None:
    """Render component callouts on a drawing sheet."""
    for label in labels:
        insert = (view_offset[0] + label.x_mm, view_offset[1] + label.y_mm)
        if backend == "matplotlib":
            target.text(
                insert[0],
                insert[1],
                label.text,
                ha="center",
                va="center",
                fontsize=max(4.8, text_height_mm * 0.32),
                fontweight="bold",
                color="black",
                bbox={
                    "facecolor": "white",
                    "edgecolor": "none",
                    "boxstyle": "round,pad=0.10",
                    "alpha": 0.82,
                },
            )
            continue
        add_centered_text(
            target,
            label.text,
            insert,
            backend=backend,
            height_mm=text_height_mm,
            bold=True,
        )


def draw_note_panel(
    target: Any,
    notes: list[str],
    *,
    backend: str,
    sheet_layout: SheetLayout,
    style: DrawingStyle,
) -> None:
    """Render a simple notes block above the title block."""
    if not notes:
        return

    note_x = style.border_margin_mm + style.sheet_padding_mm
    note_y = style.border_margin_mm + style.sheet_padding_mm + 6.0
    for index, note in enumerate(notes):
        insert = (note_x, note_y + (index * (style.text_height_mm + NOTE_LINE_GAP_MM)))
        if backend == "matplotlib":
            target.text(
                insert[0],
                insert[1],
                note,
                ha="left",
                va="center",
                fontsize=max(4.8, style.text_height_mm * 0.28),
                fontweight="bold" if index == 0 else "normal",
                color="black",
            )
        else:
            add_left_text(
                target,
                note,
                insert,
                backend=backend,
                height_mm=max(2.4, style.text_height_mm * 0.82),
                bold=index == 0,
            )


def render_sheet_matplotlib(
    output_base: Path,
    metadata: DrawingMetadata,
    sheet_plan: SheetPlan,
    *,
    notes: list[str],
    labels_by_view: dict[str, list[LabelSpec]] | None = None,
    show_dimensions: bool = True,
) -> None:
    """Render one fabrication sheet to configured matplotlib-backed formats."""
    labels_by_view = labels_by_view or {}
    figure = plt.figure(
        figsize=(
            sheet_plan.page_spec.width_mm / MM_PER_INCH,
            sheet_plan.page_spec.height_mm / MM_PER_INCH,
        )
    )
    axis = figure.add_subplot(111)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlim(0.0, sheet_plan.sheet_layout.sheet_width_mm)
    axis.set_ylim(0.0, sheet_plan.sheet_layout.sheet_height_mm)
    axis.axis("off")

    draw_sheet_border(axis, sheet_plan.sheet_layout, backend="matplotlib", style=sheet_plan.style)
    draw_title_block(axis, metadata, sheet_plan.sheet_layout, backend="matplotlib", style=sheet_plan.style)
    draw_note_panel(axis, notes, backend="matplotlib", sheet_layout=sheet_plan.sheet_layout, style=sheet_plan.style)

    for view in sheet_plan.view_specs:
        draw_entities(axis, view, backend="matplotlib", style=sheet_plan.style)
        if show_dimensions:
            draw_view_dimensions(axis, view, backend="matplotlib", style=sheet_plan.style)
        draw_view_title(axis, view, backend="matplotlib", style=sheet_plan.style)
        labels = labels_by_view.get(view.name, [])
        label_height = 2.6 if sum(len(items) for items in labels_by_view.values()) > 20 else max(2.8, sheet_plan.style.text_height_mm * 0.85)
        draw_labels(
            axis,
            labels,
            backend="matplotlib",
            view_offset=(view.origin_x, view.origin_y),
            text_height_mm=label_height,
        )

    figure.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.99)
    if ".png" in OUTPUT_EXTENSIONS:
        figure.savefig(output_base.with_suffix(".png"), dpi=300, facecolor="white")
    if ".pdf" in OUTPUT_EXTENSIONS:
        figure.savefig(output_base.with_suffix(".pdf"), dpi=300, facecolor="white")
    plt.close(figure)


def render_sheet_dxf(
    output_base: Path,
    metadata: DrawingMetadata,
    sheet_plan: SheetPlan,
    *,
    notes: list[str],
    labels_by_view: dict[str, list[LabelSpec]] | None = None,
    show_dimensions: bool = True,
) -> None:
    """Render one fabrication sheet to DXF."""
    labels_by_view = labels_by_view or {}
    document = ezdxf.new("R2010", setup=True)
    document.units = ezdxf_units.MM
    document.header["$INSUNITS"] = ezdxf_units.MM

    for layer_name, color in (
        ("OUTLINE", 7),
        ("HIDDEN", 8),
        ("CENTER", 3),
        ("DIM", 2),
        ("TEXT", 4),
        ("COMPONENT_ID", 6),
        ("CUTOUT", 1),
        ("geometry", 7),
        ("dimensions", 8),
        ("text", 3)
    ):
        if layer_name not in document.layers:
            document.layers.add(layer_name, color=color)

    configure_dimension_style(document, sheet_plan.style)
    modelspace = document.modelspace()

    draw_sheet_border(modelspace, sheet_plan.sheet_layout, backend="dxf", style=sheet_plan.style)
    draw_title_block(modelspace, metadata, sheet_plan.sheet_layout, backend="dxf", style=sheet_plan.style)
    draw_note_panel(modelspace, notes, backend="dxf", sheet_layout=sheet_plan.sheet_layout, style=sheet_plan.style)

    for view in sheet_plan.view_specs:
        draw_entities(modelspace, view, backend="dxf", style=sheet_plan.style, layer="OUTLINE")
        if show_dimensions:
            draw_view_dimensions(modelspace, view, backend="dxf", style=sheet_plan.style)
        draw_view_title(modelspace, view, backend="dxf", style=sheet_plan.style)
        labels = labels_by_view.get(view.name, [])
        label_height = 2.6 if sum(len(items) for items in labels_by_view.values()) > 20 else max(2.8, sheet_plan.style.text_height_mm * 0.85)
        draw_labels(
            modelspace,
            labels,
            backend="dxf",
            view_offset=(view.origin_x, view.origin_y),
            text_height_mm=label_height,
        )

    document.saveas(output_base.with_suffix(".dxf"))


def orthographic_view_specs_from_payload(payload_views: dict[str, Any]) -> list[ViewSpec]:
    """Build the standard front/top/side view specs from a views payload."""
    return [view_spec_from_view_payload(view_name, payload_views[view_name]) for view_name in ("front", "top", "side")]


def axis_index_for_name(axis_name: str) -> int:
    return {"x": 0, "y": 1, "z": 2}[axis_name.lower()]


def shifted_point(point: list[float] | tuple[float, float], dx: float, dy: float) -> tuple[float, float]:
    return (float(point[0]) + dx, float(point[1]) + dy)


def shift_projected_entity(entity: dict[str, Any], dx: float, dy: float) -> dict[str, Any]:
    shifted = dict(entity)
    entity_type = str(entity.get("type", "LINE")).upper()
    if entity_type == "LINE":
        shifted["start"] = list(shifted_point(entity["start"], dx, dy))
        shifted["end"] = list(shifted_point(entity["end"], dx, dy))
    elif entity_type == "LWPOLYLINE":
        shifted["points"] = [list(shifted_point(point, dx, dy)) for point in entity.get("points", [])]
    elif entity_type == "CIRCLE":
        shifted["center"] = list(shifted_point(entity["center"], dx, dy))
    return shifted


def component_bounds(components: list[dict[str, Any]]) -> tuple[list[float], list[float], list[float]]:
    mins = [[float(value) for value in component["geometry"]["bounding_box"]["min"]] for component in components]
    maxs = [[float(value) for value in component["geometry"]["bounding_box"]["max"]] for component in components]
    minimum = [min(values[index] for values in mins) for index in range(3)]
    maximum = [max(values[index] for values in maxs) for index in range(3)]
    size = [maximum[index] - minimum[index] for index in range(3)]
    return minimum, maximum, size


def combined_view_spec_from_components(components: list[dict[str, Any]], view_name: str) -> ViewSpec:
    """Create one projected view that shows a full parent subassembly."""
    if not components:
        raise ValueError("Cannot create a subassembly drawing with no components.")

    group_min, _, group_size = component_bounds(components)
    reference_view = components[0]["geometry"]["views"][view_name]
    horizontal_axis = str(reference_view["horizontal_axis"])
    vertical_axis = str(reference_view["vertical_axis"])
    depth_axis = str(reference_view["depth_axis"])
    axis_u = axis_index_for_name(horizontal_axis)
    axis_v = axis_index_for_name(vertical_axis)
    axis_depth = axis_index_for_name(depth_axis)
    projected_edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    projected_entities: list[dict[str, Any]] = []

    for component in components:
        bbox_min = [float(value) for value in component["geometry"]["bounding_box"]["min"]]
        dx = bbox_min[axis_u] - group_min[axis_u]
        dy = bbox_min[axis_v] - group_min[axis_v]
        component_view = component["geometry"]["views"][view_name]
        for edge in component_view.get("edges", []):
            projected_edges.append(
                (
                    shifted_point(edge["start"], dx, dy),
                    shifted_point(edge["end"], dx, dy),
                )
            )
        projected_entities.extend(
            shift_projected_entity(entity, dx, dy)
            for entity in component_view.get("entities", [])
        )

    return ViewSpec(
        name=view_name,
        title=VIEW_TITLES[view_name],
        width_mm=max(group_size[axis_u], 1.0),
        height_mm=max(group_size[axis_v], 1.0),
        dimension_width_mm=max(group_size[axis_u], 1.0),
        dimension_height_mm=max(group_size[axis_v], 1.0),
        depth_mm=max(group_size[axis_depth], 1.0),
        plane=str(reference_view["plane"]),
        horizontal_axis=horizontal_axis,
        vertical_axis=vertical_axis,
        depth_axis=depth_axis,
        projected_edges=tuple(projected_edges),
        projected_entities=tuple(projected_entities),
    )


def subassembly_labels(components: list[dict[str, Any]], view_name: str) -> list[LabelSpec]:
    group_min, _, _ = component_bounds(components)
    axis_u, axis_v = VIEW_AXIS_INDEX[view_name]
    labels: list[LabelSpec] = []
    for component in components:
        bbox = component["geometry"]["bounding_box"]
        minimum = [float(value) for value in bbox["min"]]
        maximum = [float(value) for value in bbox["max"]]
        center = [(minimum[index] + maximum[index]) / 2.0 for index in range(3)]
        labels.append(
            LabelSpec(
                text=f"{component['instance_id']} {short_component_name(component)}",
                x_mm=center[axis_u] - group_min[axis_u],
                y_mm=center[axis_v] - group_min[axis_v],
            )
        )
    return labels


def write_sheet(
    output_base: Path,
    metadata: DrawingMetadata,
    raw_view_specs: list[ViewSpec],
    *,
    layout_kind: str,
    notes: list[str],
    labels_by_view: dict[str, list[LabelSpec]] | None = None,
    show_dimensions: bool = True,
) -> PageSpec:
    """Select page/scale, then export configured drawing formats for one sheet."""
    output_base.parent.mkdir(parents=True, exist_ok=True)
    sheet_plan = select_sheet_plan(raw_view_specs, layout_kind=layout_kind, notes=notes)
    metadata = replace(
        metadata,
        scale_label=sheet_plan.page_spec.scale_label,
        sheet_label=sheet_plan.page_spec.sheet_label,
    )
    scaled_labels = {
        view_name: spread_labels(scale_labels(labels, sheet_plan.page_spec.scale_denominator))
        for view_name, labels in (labels_by_view or {}).items()
    }
    if ".pdf" in OUTPUT_EXTENSIONS or ".png" in OUTPUT_EXTENSIONS:
        render_sheet_matplotlib(
            output_base,
            metadata,
            sheet_plan,
            notes=notes,
            labels_by_view=scaled_labels,
            show_dimensions=show_dimensions,
        )
    if ".dxf" in OUTPUT_EXTENSIONS:
        render_sheet_dxf(
            output_base,
            metadata,
            sheet_plan,
            notes=notes,
            labels_by_view=scaled_labels,
            show_dimensions=show_dimensions,
        )
    return sheet_plan.page_spec


def generate_assembly_and_elevation_drawings(payload: dict[str, Any], output_root: Path) -> dict[str, Any]:
    """Export assembly and per-view elevation sheets from the full analysis payload."""
    output_root.mkdir(parents=True, exist_ok=True)
    assembly_dir = output_root / "assembly"
    elevations_dir = output_root / "elevations"
    assembly_dir.mkdir(parents=True, exist_ok=True)
    elevations_dir.mkdir(parents=True, exist_ok=True)

    source_name = str(payload["input"]["file_name"])
    model_name = str(payload["input"]["mesh_name"]).upper()
    raw_views = orthographic_view_specs_from_payload(payload["views"])
    view_by_name = {view.name: view for view in raw_views}
    components = payload.get("components", [])
    unique_part_count = len({component.get("part_group_id") for component in components if component.get("part_group_id")})

    import datetime
    today = datetime.date.today().isoformat()
    assembly_metadata = DrawingMetadata(
        drawing_name=f"{model_name.upper()} ASSEMBLY DRAWING",
        source_name=source_name.upper(),
        units="mm",
        material="MIXED (SEE BOM)",
        revision="A",
        date_str=today,
        drafter="AI DRAFTING",
    )
    assembly_notes = [
        "ASSEMBLY NOTES",
        f"COMPONENT COUNT: {len(components)}",
        f"UNIQUE PARTS: {unique_part_count}",
        "ANALYSIS INCLUDED: analysis/component_schedule.csv",
    ]
    assembly_notes.extend(type_summary_notes(components, max_items=4))
    assembly_labels = {
        view_name: build_component_labels(payload, view_name)
        for view_name in ("front", "top", "side")
    }
    assembly_base = assembly_dir / "assembly"
    assembly_page = write_sheet(
        assembly_base,
        assembly_metadata,
        raw_views,
        layout_kind="orthographic",
        notes=assembly_notes,
        labels_by_view=assembly_labels,
    )

    generated_sheets: list[dict[str, Any]] = [
        sheet_record("ASM", "ASSEMBLY DRAWING", "assembly", assembly_base, assembly_page)
    ]

    overall_plan_base = assembly_dir / "SHT - 01 OVERALL PLAN"
    overall_plan_page = write_sheet(
        overall_plan_base,
        replace(assembly_metadata, drawing_name=f"{model_name.upper()} OVERALL PLAN"),
        [view_by_name["top"]],
        layout_kind="single",
        notes=[
            "OVERALL PLAN",
            f"COMPONENT COUNT: {len(components)}",
            "LABELS SHOW COMPONENT ID + BOOTH PART TYPE",
            "SEE analysis/component_schedule.csv FOR FULL MEASUREMENTS",
        ],
        labels_by_view={"top": build_component_plan_labels(payload, "top")},
        show_dimensions=False,
    )
    generated_sheets.append(
        sheet_record("SHT - 01", "OVERALL PLAN", "plan", overall_plan_base, overall_plan_page)
    )

    dimensioned_plan_base = assembly_dir / "SHT - 02 PLAN WITH DIMENSIONS"
    dimensioned_plan_page = write_sheet(
        dimensioned_plan_base,
        replace(assembly_metadata, drawing_name=f"{model_name.upper()} PLAN WITH DIMENSIONS"),
        [view_by_name["top"]],
        layout_kind="single",
        notes=["PLAN WITH DIMENSIONS"],
        labels_by_view={"top": build_component_labels(payload, "top")},
    )
    generated_sheets.append(
        sheet_record("SHT - 02", "PLAN WITH DIMENSIONS", "plan", dimensioned_plan_base, dimensioned_plan_page)
    )

    combined_elevation_base = elevations_dir / "SHT - 03 ELEVATION"
    combined_elevation_page = write_sheet(
        combined_elevation_base,
        DrawingMetadata(
            drawing_name=f"{model_name.upper()} ELEVATION",
            source_name=source_name.upper(),
            units="mm",
            material="MIXED",
            revision="A",
            date_str=today,
            drafter="AI DRAFTING",
        ),
        [view_by_name["front"], view_by_name["side"]],
        layout_kind="row",
        notes=[
            "ELEVATION KEY",
            "FRONT VIEW / SIDE VIEW",
            f"COMPONENTS: {len(components)}",
            f"UNIQUE PARTS: {unique_part_count}",
            "SEE INDIVIDUAL ELEVATIONS FOR PROJECTED SIZES",
        ],
        labels_by_view={
            "front": build_component_labels(payload, "front"),
            "side": build_component_labels(payload, "side"),
        },
    )
    generated_sheets.append(
        sheet_record("SHT - 03", "ELEVATION", "elevation", combined_elevation_base, combined_elevation_page)
    )

    elevation_paths: list[str] = sheet_files(combined_elevation_base)
    for view_name in ("front", "top", "side"):
        view_metadata = DrawingMetadata(
            drawing_name=f"{model_name.upper()} {VIEW_TITLES[view_name]}",
            source_name=source_name.upper(),
            units="mm",
            material="MIXED",
            revision="A",
            date_str=today,
            drafter="AI DRAFTING",
        )
        output_base = elevations_dir / f"elevation_{view_name}"
        view_page = write_sheet(
            output_base,
            view_metadata,
            [view_spec_from_view_payload(view_name, payload["views"][view_name])],
            layout_kind="single",
            notes=component_schedule_notes(
                components,
                title=f"ELEVATION KEY: {VIEW_TITLES[view_name]}",
                view_name=view_name,
                max_items=10,
            ),
            labels_by_view={view_name: build_component_labels(payload, view_name)},
        )
        elevation_paths.extend(sheet_files(output_base))
        generated_sheets.append(
            sheet_record(
                f"ELEVATION-{view_name.upper()}",
                VIEW_TITLES[view_name],
                "elevation",
                output_base,
                view_page,
            )
        )

    return {
        "assembly": sheet_files(assembly_base) + sheet_files(overall_plan_base) + sheet_files(dimensioned_plan_base),
        "elevations": elevation_paths,
        "sheets": generated_sheets,
        "assembly_sheet": [assembly_page.sheet_label, assembly_page.scale_label],
    }


def generate_subassembly_drawings(payload: dict[str, Any], output_root: Path) -> list[dict[str, Any]]:
    """Export one grouped PDF per parent object/subassembly."""
    subassemblies_dir = output_root / "subassemblies"
    subassemblies_dir.mkdir(parents=True, exist_ok=True)

    components = payload.get("components", [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for component in components:
        grouped.setdefault(str(component.get("parent_assembly") or "UNASSIGNED"), []).append(component)

    import datetime
    today = datetime.date.today().isoformat()
    records: list[dict[str, Any]] = []
    for assembly_name in sorted(grouped):
        group_components = sorted(grouped[assembly_name], key=component_sort_key)
        subassembly_id = str(group_components[0].get("subassembly_id") or f"A{len(records) + 1:03d}")
        raw_views = [
            combined_view_spec_from_components(group_components, view_name)
            for view_name in ("front", "top", "side")
        ]
        output_base = subassemblies_dir / f"{subassembly_id} {slugify(assembly_name)} ASSEMBLY"
        notes = [
            f"SUBASSEMBLY: {assembly_name}",
            f"SUBASSEMBLY ID: {subassembly_id}",
            f"COMPONENTS: {len(group_components)}",
        ]
        notes.extend(
            f"{component['instance_id']} {short_component_name(component)} {component.get('part_group_id', '-')}"
            for component in group_components[:8]
        )
        if len(group_components) > 8:
            notes.append(f"+ {len(group_components) - 8} MORE - SEE analysis/component_schedule.csv")

        page_spec = write_sheet(
            output_base,
            DrawingMetadata(
                drawing_name=f"{assembly_name} ASSEMBLY",
                source_name=str(payload["input"]["file_name"]).upper(),
                units="mm",
                material="MIXED (SEE BOM)",
                revision="A",
                date_str=today,
                drafter="AI DRAFTING",
            ),
            raw_views,
            layout_kind="orthographic",
            notes=notes,
            labels_by_view={
                view_name: subassembly_labels(group_components, view_name)
                for view_name in ("front", "top", "side")
            },
        )
        records.append(
            {
                "subassembly_id": subassembly_id,
                "name": assembly_name,
                "component_count": len(group_components),
                "instance_ids": [component["instance_id"] for component in group_components],
                "component_names": [component.get("component_name") for component in group_components],
                "files": sheet_files(output_base),
                "sheet": page_spec.sheet_label,
                "scale": page_spec.scale_label,
            }
        )

    return records


def generate_part_detail_drawings(part_groups: list[dict[str, Any]], output_root: Path) -> list[dict[str, Any]]:
    """Export one part-detail sheet per unique grouped part."""
    parts_dir = output_root / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    drawing_records: list[dict[str, Any]] = []
    for sheet_number, group in enumerate(part_groups, start=4):
        component = group["representative_component"]
        raw_views = orthographic_view_specs_from_payload(component["geometry"]["views"])
        output_base = parts_dir / f"SHT - {sheet_number:02d} {group['part_name']} DETAILS"
        notes = [
            "PART NOTES",
            f"PART ID: {group['part_group_id']}",
            f"SUBASSEMBLY: {group.get('parent_assembly', 'UNASSIGNED')}",
            f"COMPONENT NAME: {group.get('component_name', group.get('source_name', 'UNKNOWN'))}",
            f"OBJECT TYPE: {object_label(component)}",
            f"MATERIAL: {group['material']}",
            f"THICKNESS: {group['nominal_thickness_mm']} mm",
            f"QTY: {group['quantity']}",
            f"INSTANCES: {format_instance_list(list(group['instance_ids']))}",
        ]
        
        shape = component.get("shape", "")
        dims = component.get("dimensions", {})
        placement = component.get("placement", {})
        fabrication_flags = component.get("fabrication", {}).get("flags", [])
        source = component.get("source_name", "")
        if source:
            notes.append(f"SOURCE: {source}")
        notes.append(
            "SIZE LxWxH: "
            f"{format_mm(dims.get('length'))} x {format_mm(dims.get('width'))} x {format_mm(dims.get('height'))} mm"
        )
        if placement:
            notes.append(
                "PLACEMENT Z: "
                f"BOTTOM {format_mm(placement.get('bottom_z'))} / TOP {format_mm(placement.get('top_z'))} mm"
            )

        if group["object_type"] in {"wall_panel", "partition", "back_panel"}:
            notes.append(
                "PANEL ELEVATION: "
                f"{format_mm(dims.get('length'))} W x {format_mm(dims.get('height'))} H x "
                f"{format_mm(dims.get('thickness'))} THK"
            )
        elif group["object_type"] == "floor_panel":
            notes.append(
                "PLAN SIZE: "
                f"{format_mm(dims.get('length'))} L x {format_mm(dims.get('width'))} W x "
                f"{format_mm(dims.get('thickness'))} THK"
            )

        if shape in ("cylinder", "capsule"):
            diameter = dims.get("diameter")
            radius = dims.get("radius")
            straight = dims.get("straight_length")
            if diameter is not None:
                notes.append(f"DIAMETER (o): {diameter:.1f} mm")
                notes.append(f"RADIUS: {radius:.1f} mm")
                if shape == "capsule" and straight is not None:
                    notes.append(f"STRAIGHT LENGTH: {straight:.1f} mm")
                    notes.append(f"O.A.L.: {dims.get('length'):.1f} mm")
            else:
                # Fallback calculation
                r = min(dims.get("length", 0.0), dims.get("width", 0.0)) / 2.0
                notes.append(f"DIAMETER (o): {r * 2.0:.1f} mm")
                notes.append(f"RADIUS: {r:.1f} mm")
                
        # If we successfully parsed a capsule, we don't need manual review purely for being an odd shape
        if shape == "capsule" and "manual_review_required" in fabrication_flags:
            fabrication_flags = [f for f in fabrication_flags if f != "manual_review_required"]

        if "angled_panel" in fabrication_flags:
            # Extract tilt degrees from the dynamic flag e.g. "tilt_30.0deg"
            tilt_str = next((f for f in fabrication_flags if f.startswith("tilt_") and f.endswith("deg")), None)
            tilt_label = tilt_str.replace("tilt_", "").replace("deg", "") + " deg" if tilt_str else "?"
            notes.append(f"NOTE: ANGLED PANEL - TILT {tilt_label} FROM HORIZONTAL")
            notes.append("NOTE: APPROXIMATE PROFILE (MANUAL REVIEW)")
        elif "approximate_profile" in fabrication_flags:
            notes.append("NOTE: APPROXIMATE PROFILE (MANUAL REVIEW)")
        elif "manual_review_required" in fabrication_flags:
            notes.append("NOTE: MANUAL REVIEW REQUIRED")
        if "non_standard_orientation" in fabrication_flags:
            notes.append("NOTE: NON-STANDARD ORIENTATION - VERIFY INSTALLATION ANGLE")

        import datetime
        metadata = DrawingMetadata(
            drawing_name=f"PART: {component['part_name'].upper()}",
            source_name=str(component["instance_id"]).upper(),
            units="mm",
            material=group["material"].upper(),
            revision="A",
            date_str=datetime.date.today().isoformat(),
            drafter="AI DRAFTING",
        )
        page_spec = write_sheet(
            output_base,
            metadata,
            raw_views,
            layout_kind="orthographic",
            notes=notes,
        )
        drawing_records.append(
            {
                "part_group_id": group["part_group_id"],
                "object_type": group["object_type"],
                "parent_assembly": group.get("parent_assembly", "UNASSIGNED"),
                "subassembly_id": group.get("subassembly_id", "A000"),
                "component_name": group.get("component_name", group.get("source_name", "unknown")),
                "sheet_no": f"SHT - {sheet_number:02d}",
                "title": f"{group['part_name']} DETAILS",
                "quantity": group["quantity"],
                "instance_ids": list(group["instance_ids"]),
                "files": sheet_files(output_base),
                "sheet": page_spec.sheet_label,
                "scale": page_spec.scale_label,
            }
        )

    return drawing_records
