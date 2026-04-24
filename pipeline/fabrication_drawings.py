"""Fabrication drawing package generation for assembly, elevations, and part sheets."""

from __future__ import annotations

import re
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
SCALE_DENOMINATORS = [1, 2, 5, 10, 20]


@dataclass(frozen=True)
class PageSpec:
    """Selected paper size and drawing scale for one sheet."""

    sheet_name: str
    orientation: str
    width_mm: float
    height_mm: float
    scale_denominator: int

    @property
    def scale_label(self) -> str:
        return f"1:{self.scale_denominator}"

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


def scale_view_spec(view_spec: ViewSpec, scale_denominator: int) -> ViewSpec:
    """Convert model-space view geometry into paper-space using the chosen scale."""
    scaled_edges = tuple(
        (
            (start[0] / scale_denominator, start[1] / scale_denominator),
            (end[0] / scale_denominator, end[1] / scale_denominator),
        )
        for start, end in view_spec.projected_edges
    )
    return replace(
        view_spec,
        width_mm=view_spec.width_mm / scale_denominator,
        height_mm=view_spec.height_mm / scale_denominator,
        projected_edges=scaled_edges,
    )


def layout_three_views(view_specs: list[ViewSpec], style: DrawingStyle) -> list[ViewSpec]:
    """Place front/top/side views onto one orthographic sheet."""
    view_map = {view.name: view for view in view_specs}
    left_reserve = style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    right_reserve = style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    top_reserve = style.border_margin_mm + style.dimension_offset_mm + style.title_offset_mm + style.sheet_padding_mm
    bottom_reserve = style.border_margin_mm + style.title_block_height_mm + style.dimension_offset_mm + style.sheet_padding_mm

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


def layout_single_view(view_spec: ViewSpec, style: DrawingStyle) -> list[ViewSpec]:
    """Place a single elevation view on one sheet."""
    origin_x = style.border_margin_mm + style.dimension_offset_mm + style.sheet_padding_mm
    origin_y = style.border_margin_mm + style.title_block_height_mm + style.dimension_offset_mm + style.sheet_padding_mm
    return [replace(view_spec, origin_x=origin_x, origin_y=origin_y)]


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


def select_sheet_plan(raw_views: list[ViewSpec], *, layout_kind: str) -> SheetPlan:
    """Select the smallest ISO sheet that fits at the largest readable scale."""
    if layout_kind not in {"orthographic", "single"}:
        raise ValueError(f"Unsupported layout kind: {layout_kind}")

    candidates: list[tuple[int, int, float, PageSpec, DrawingStyle, list[ViewSpec]]] = []
    fallback: tuple[float, int, DrawingStyle, list[ViewSpec]] | None = None

    for scale_denominator in SCALE_DENOMINATORS:
        scaled_views = [scale_view_spec(view, scale_denominator) for view in raw_views]
        style = build_page_style(scaled_views)
        laid_out_views = (
            layout_three_views(scaled_views, style)
            if layout_kind == "orthographic"
            else layout_single_view(scaled_views[0], style)
        )
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
        sheet_rank, _, _, page_spec, style, laid_out_views = sorted(
            candidates,
            key=lambda item: (item[0], item[1], item[2]),
        )[0]
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


def scale_labels(labels: list[LabelSpec], scale_denominator: int) -> list[LabelSpec]:
    """Convert model-space label anchors into paper-space coordinates."""
    return [
        LabelSpec(
            text=label.text,
            x_mm=label.x_mm / scale_denominator,
            y_mm=label.y_mm / scale_denominator,
        )
        for label in labels
    ]


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


def build_component_labels(payload: dict[str, Any], view_name: str) -> list[LabelSpec]:
    """Create instance-ID callouts for assembly/elevation drawings."""
    assembly_min = [float(value) for value in payload["bounding_box"]["min"]]
    return [
        component_label_for_view(component, assembly_min, view_name)
        for component in payload.get("components", [])
    ]


def draw_labels(target: Any, labels: list[LabelSpec], *, backend: str, view_offset: tuple[float, float], text_height_mm: float) -> None:
    """Render component callouts on a drawing sheet."""
    for label in labels:
        insert = (view_offset[0] + label.x_mm, view_offset[1] + label.y_mm)
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
        add_left_text(
            target,
            note,
            (note_x, note_y + (index * (style.text_height_mm + 1.4))),
            backend=backend,
            height_mm=style.text_height_mm,
            bold=index == 0,
        )


def render_sheet_matplotlib(
    output_base: Path,
    metadata: DrawingMetadata,
    sheet_plan: SheetPlan,
    *,
    notes: list[str],
    labels_by_view: dict[str, list[LabelSpec]] | None = None,
) -> None:
    """Render one fabrication sheet to PNG and PDF using matplotlib."""
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
        draw_view_dimensions(axis, view, backend="matplotlib", style=sheet_plan.style)
        draw_view_title(axis, view, backend="matplotlib", style=sheet_plan.style)
        labels = labels_by_view.get(view.name, [])
        draw_labels(
            axis,
            labels,
            backend="matplotlib",
            view_offset=(view.origin_x, view.origin_y),
            text_height_mm=max(3.0, sheet_plan.style.text_height_mm),
        )

    figure.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.99)
    # figure.savefig(output_base.with_suffix(".png"), dpi=300, facecolor="white")
    figure.savefig(output_base.with_suffix(".pdf"), dpi=300, facecolor="white")
    plt.close(figure)


def render_sheet_dxf(
    output_base: Path,
    metadata: DrawingMetadata,
    sheet_plan: SheetPlan,
    *,
    notes: list[str],
    labels_by_view: dict[str, list[LabelSpec]] | None = None,
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
        draw_view_dimensions(modelspace, view, backend="dxf", style=sheet_plan.style)
        draw_view_title(modelspace, view, backend="dxf", style=sheet_plan.style)
        labels = labels_by_view.get(view.name, [])
        draw_labels(
            modelspace,
            labels,
            backend="dxf",
            view_offset=(view.origin_x, view.origin_y),
            text_height_mm=max(3.0, sheet_plan.style.text_height_mm),
        )

    # auditor = document.audit()
    # if auditor.has_errors:
    #     messages = "; ".join(str(error) for error in auditor.errors[:5])
    #     raise RuntimeError(f"DXF audit reported errors: {messages}")
    # document.saveas(output_base.with_suffix(".dxf"))


def orthographic_view_specs_from_payload(payload_views: dict[str, Any]) -> list[ViewSpec]:
    """Build the standard front/top/side view specs from a views payload."""
    return [view_spec_from_view_payload(view_name, payload_views[view_name]) for view_name in ("front", "top", "side")]


def write_sheet(
    output_base: Path,
    metadata: DrawingMetadata,
    raw_view_specs: list[ViewSpec],
    *,
    layout_kind: str,
    notes: list[str],
    labels_by_view: dict[str, list[LabelSpec]] | None = None,
) -> PageSpec:
    """Select page/scale, then export PNG, PDF, and DXF for one sheet."""
    output_base.parent.mkdir(parents=True, exist_ok=True)
    sheet_plan = select_sheet_plan(raw_view_specs, layout_kind=layout_kind)
    metadata = replace(
        metadata,
        scale_label=sheet_plan.page_spec.scale_label,
        sheet_label=sheet_plan.page_spec.sheet_label,
    )
    scaled_labels = {
        view_name: scale_labels(labels, sheet_plan.page_spec.scale_denominator)
        for view_name, labels in (labels_by_view or {}).items()
    }
    render_sheet_matplotlib(output_base, metadata, sheet_plan, notes=notes, labels_by_view=scaled_labels)
    # render_sheet_dxf(output_base, metadata, sheet_plan, notes=notes, labels_by_view=scaled_labels)
    return sheet_plan.page_spec


def generate_assembly_and_elevation_drawings(payload: dict[str, Any], output_root: Path) -> dict[str, list[str]]:
    """Export assembly and per-view elevation sheets from the full analysis payload."""
    output_root.mkdir(parents=True, exist_ok=True)
    assembly_dir = output_root / "assembly"
    elevations_dir = output_root / "elevations"
    assembly_dir.mkdir(parents=True, exist_ok=True)
    elevations_dir.mkdir(parents=True, exist_ok=True)

    source_name = str(payload["input"]["file_name"])
    model_name = str(payload["input"]["mesh_name"]).upper()
    raw_views = orthographic_view_specs_from_payload(payload["views"])

    import datetime
    assembly_metadata = DrawingMetadata(
        drawing_name=f"{model_name.upper()} ASSEMBLY DRAWING",
        source_name=source_name.upper(),
        units="mm",
        material="MIXED (SEE BOM)",
        revision="A",
        date_str=datetime.date.today().isoformat(),
        drafter="AI DRAFTING",
    )
    assembly_notes = [
        "ASSEMBLY NOTES",
        f"COMPONENT COUNT: {len(payload.get('components', []))}",
    ]
    assembly_labels = {
        view_name: build_component_labels(payload, view_name)
        for view_name in ("front", "top", "side")
    }
    assembly_page = write_sheet(
        assembly_dir / "assembly",
        assembly_metadata,
        raw_views,
        layout_kind="orthographic",
        notes=assembly_notes,
        labels_by_view=assembly_labels,
    )

    elevation_paths: list[str] = []
    for view_name in ("front", "top", "side"):
        view_metadata = DrawingMetadata(
            drawing_name=f"{model_name.upper()} {VIEW_TITLES[view_name]}",
            source_name=source_name.upper(),
            units="mm",
            material="MIXED",
            revision="A",
            date_str=datetime.date.today().isoformat(),
            drafter="AI DRAFTING",
        )
        output_base = elevations_dir / f"elevation_{view_name}"
        write_sheet(
            output_base,
            view_metadata,
            [view_spec_from_view_payload(view_name, payload["views"][view_name])],
            layout_kind="single",
            notes=[f"ELEVATION: {VIEW_TITLES[view_name]}"],
            labels_by_view={view_name: build_component_labels(payload, view_name)},
        )
        elevation_paths.extend([str(output_base.with_suffix(".pdf"))])

    return {
        "assembly": [
            str((assembly_dir / "assembly").with_suffix(ext))
            for ext in (".pdf",)
        ],
        "elevations": elevation_paths,
        "assembly_sheet": [assembly_page.sheet_label, assembly_page.scale_label],
    }


def generate_part_detail_drawings(part_groups: list[dict[str, Any]], output_root: Path) -> list[dict[str, Any]]:
    """Export one part-detail sheet per unique grouped part."""
    parts_dir = output_root / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    drawing_records: list[dict[str, Any]] = []
    for group in part_groups:
        component = group["representative_component"]
        raw_views = orthographic_view_specs_from_payload(component["geometry"]["views"])
        output_base = parts_dir / slugify(group["file_basename"])
        notes = [
            "PART NOTES",
            f"PART ID: {group['part_group_id']}",
            f"MATERIAL: {group['material']}",
            f"THICKNESS: {group['nominal_thickness_mm']} mm",
            f"QTY: {group['quantity']}",
        ]
        
        shape = component.get("shape", "")
        dims = component.get("dimensions", {})
        fabrication_flags = component.get("fabrication", {}).get("flags", [])
        source = component.get("source_name", "")
        if source:
            notes.append(f"SOURCE: {source}")

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
                "files": [str(output_base.with_suffix(".pdf"))],
                "sheet": page_spec.sheet_label,
                "scale": page_spec.scale_label,
            }
        )

    return drawing_records
