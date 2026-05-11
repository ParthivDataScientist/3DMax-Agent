"""Generate CAD-style selected-component PDF and preview images."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str((Path(__file__).resolve().parents[2] / ".cache" / "matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from src.drawing.dimension_renderer import draw_callout, draw_notes_box, draw_view
from src.drawing.view_generator import (
    generate_booth_context_view,
    generate_booth_overall_views,
    generate_component_views,
    generate_overview_footprint_view,
)
from src.extraction.dimensions import format_size
from src.extraction.models import ComponentInstance, ExtractedComponent

from .title_block import default_title_block, draw_title_block


PAGE_WIDTH_MM = 420.0
PAGE_HEIGHT_MM = 297.0
MM_PER_INCH = 25.4


def _new_figure():
    figure = plt.figure(figsize=(PAGE_WIDTH_MM / MM_PER_INCH, PAGE_HEIGHT_MM / MM_PER_INCH))
    axis = figure.add_axes([0, 0, 1, 1])
    axis.set_xlim(0.0, PAGE_WIDTH_MM)
    axis.set_ylim(0.0, PAGE_HEIGHT_MM)
    axis.set_aspect("equal", adjustable="box")
    axis.axis("off")
    return figure, axis


def _sheet_border(ax) -> None:
    ax.plot(
        [6.0, PAGE_WIDTH_MM - 6.0, PAGE_WIDTH_MM - 6.0, 6.0, 6.0],
        [6.0, 6.0, PAGE_HEIGHT_MM - 6.0, PAGE_HEIGHT_MM - 6.0, 6.0],
        color="black",
        lw=1.0,
    )


def _render_overview_sheet(
    *,
    all_components: list[ExtractedComponent],
    selected_components: list[ExtractedComponent],
    input_path: str,
    date_str: str,
) -> plt.Figure:
    figure, axis = _new_figure()
    _sheet_border(axis)

    sheet_number = "SHT-01"
    sheet_title = "SELECTED COMPONENTS OVERVIEW"
    title_block = default_title_block(input_path, sheet_title=sheet_title, sheet_number=sheet_number, date_str=date_str)
    draw_title_block(axis, title_block)

    axis.text(14.0, 284.0, f"{sheet_number} {sheet_title}", fontsize=14.0, fontweight="bold", ha="left", va="top")
    axis.text(14.0, 272.0, f"INPUT FILE: {Path(input_path).name}", fontsize=8.0, ha="left", va="top")
    axis.text(14.0, 265.0, "UNIT: mm", fontsize=8.0, ha="left", va="top")
    axis.text(14.0, 258.0, f"TOTAL DETECTED COMPONENTS: {len(all_components)}", fontsize=8.0, ha="left", va="top")
    axis.text(14.0, 251.0, f"SELECTED COMPONENTS: {len(selected_components)}", fontsize=8.0, ha="left", va="top")

    list_lines = [
        f"[{component.index}] {component.name} | {component.category} | QTY {component.quantity} | {format_size(component)}"
        for component in selected_components
    ]
    draw_notes_box(axis, (14.0, 78.0, 220.0, 160.0), list_lines, title="SELECTED COMPONENT LIST")

    footprint_view = generate_overview_footprint_view(selected_components)
    footprint_meta = draw_view(axis, footprint_view, (250.0, 108.0, 145.0, 120.0), show_dimensions=True)
    callout_anchor = footprint_meta["transform"](tuple(footprint_view["callout_anchor"]))
    draw_callout(axis, footprint_view["callout_text"], callout_anchor, (294.0, 132.0))
    axis.text(250.0, 94.0, "OUTPUT PDF: drawings/selected_components.pdf", fontsize=7.0, ha="left", va="top")
    axis.text(250.0, 88.0, f"PROJECT NAME: {title_block.project_name}", fontsize=7.0, ha="left", va="top")
    return figure


def _render_detail_sheet(
    component: ExtractedComponent,
    *,
    all_instances: list[ComponentInstance],
    sheet_index: int,
    input_path: str,
    date_str: str,
) -> plt.Figure:
    figure, axis = _new_figure()
    _sheet_border(axis)

    sheet_number = f"SHT-{sheet_index:02d}"
    sheet_title = f"{component.name.upper()} DETAILS"
    title_block = default_title_block(input_path, sheet_title=sheet_title, sheet_number=sheet_number, date_str=date_str)
    draw_title_block(axis, title_block)

    axis.text(14.0, 284.0, f"{sheet_number} {sheet_title}", fontsize=13.5, fontweight="bold", ha="left", va="top")
    axis.text(14.0, 272.0, f"CATEGORY: {component.category.upper()}", fontsize=8.0, ha="left", va="top")
    axis.text(120.0, 272.0, f"QTY - {component.quantity:02d} NOS.", fontsize=8.0, ha="left", va="top")
    axis.text(205.0, 272.0, f"SIZE: {format_size(component)}", fontsize=8.0, ha="left", va="top")
    material_finish = component.material or "-"
    if component.finish:
        material_finish = f"{material_finish}, {component.finish}"
    axis.text(14.0, 264.0, f"MATERIAL / FINISH: {material_finish}", fontsize=8.0, ha="left", va="top")
    axis.text(205.0, 264.0, f"CONFIDENCE: {int(round(component.confidence * 100.0))}%", fontsize=8.0, ha="left", va="top")
    if component.representative_instance_id:
        axis.text(14.0, 256.0, f"REPRESENTATIVE INSTANCE: {component.representative_instance_id}", fontsize=7.4, ha="left", va="top")
    if component.ai:
        axis.text(205.0, 256.0, f"AI SUGGESTED NAME: {component.ai.get('suggested_name', component.name)}", fontsize=7.4, ha="left", va="top")

    if component.luminy_validation:
        validation = component.luminy_validation
        solution = validation.get("recommended_solution") or {}
        
        # Check if it's the new fabrication solver format
        if "assembly_type" in validation:
            validation_lines = []
            
            # Print frames and blocking panels
            frames = solution.get("luminy_frames", [])
            for frame in frames:
                size = frame["size"].split(" x ")
                qty = frame.get("quantity", 1)
                for _ in range(qty):
                    validation_lines.append(f"LUMINY FRAME W{size[0]} X H{size[1]}")
                    # Usually, attach a blocking panel
                    bps = solution.get("blocking_panels", [])
                    if bps:
                        # Grab the first one, or maybe distribute them. We'll just list the primary bp for the first frame for now.
                        # Wait, the prompt shows blocking panels under the frame. We can group them if needed.
                        bp = bps[0]
                        bp_size = bp["size"].split(" x ")
                        bp_qty = bp.get("quantity", 1)
                        # We only list it once, or distribute? "W580 X H2750 X 2 NOS."
                        validation_lines.append(f"  (BLOCKING PANEL: W{bp_size[0]} X H{bp_size[1]} X {bp_qty} NOS.)")
                        # Remove it so we don't duplicate
                        bps.pop(0)

            # Print remaining blocking panels if any
            for bp in solution.get("blocking_panels", []):
                bp_size = bp["size"].split(" x ")
                bp_qty = bp.get("quantity", 1)
                validation_lines.append(f"  (BLOCKING PANEL: W{bp_size[0]} X H{bp_size[1]} X {bp_qty} NOS.)")

            for filler in solution.get("custom_fillers", []):
                validation_lines.append(f"CUSTOM WOODEN FRAME W{int(filler['width_mm'])} X H{int(filler.get('height_mm', 2820))}")

            for post in solution.get("posts", []):
                size = post["size"].split(" x ")
                validation_lines.append(f"STANDARD WOODEN POST W{size[0]} X H{size[1]}")

            title = "FABRICATION PLANNER"

        else:
            # Fallback to old format if any old data remains
            validation_lines = [
                f"Detected Size: W {int(round(validation.get('detected_width_mm', component.dimensions.width)))} x H {int(round(validation.get('detected_height_mm', component.dimensions.height)))} mm",
                f"Status: {str(validation.get('status', '-')).replace('_', ' ')}",
            ]
            if solution.get("frame_name"):
                validation_lines.append(f"Recommended: {solution['frame_name']}")
            if solution.get("type") == "cut_from_standard":
                validation_lines.append(
                    f"Cut Required: W {round(float(solution.get('cut_width_mm', 0.0)), 3)} mm | H {round(float(solution.get('cut_height_mm', 0.0)), 3)} mm"
                )
            alternatives = validation.get("alternative_solutions", [])
            if alternatives:
                alt_texts: list[str] = []
                for item in alternatives[:2]:
                    if item.get("type") == "modular_combination":
                        alt_texts.append(
                            " + ".join(
                                f"{module['quantity']}x{module['name'].replace('Luminy Frame W', '')}"
                                for module in item.get("modules", [])
                            )
                        )
                if alt_texts:
                    validation_lines.append(f"Alternatives: {' | '.join(alt_texts)}")
            title = "LUMINY FRAME VALIDATION"
            
        draw_notes_box(axis, (14.0, 198.0, 220.0, 50.0), validation_lines, title=title)

    booth_context_view = generate_booth_context_view(all_instances, component.instance_ids)
    rendered_context = draw_view(axis, booth_context_view, (245.0, 198.0, 159.0, 50.0), show_dimensions=False)
    context_anchor = rendered_context["transform"](tuple(booth_context_view["callout_anchor"]))
    draw_callout(axis, list(booth_context_view["callout_text"]), context_anchor, (252.0, 210.0), with_arrow=False)

    views = generate_component_views(component)
    cells = {
        "front": (14.0, 118.0, 185.0, 82.0),
        "top": (220.0, 118.0, 184.0, 82.0),
        "side": (14.0, 38.0, 185.0, 76.0),
        "iso": (220.0, 38.0, 184.0, 76.0),
    }

    for view_name, bounds in cells.items():
        rendered = draw_view(axis, views[view_name], bounds, show_dimensions=view_name != "iso")
        anchor = rendered["transform"](tuple(views[view_name]["callout_anchor"]))
        target = (bounds[0] + bounds[2] * 0.64, bounds[1] + bounds[3] * 0.30)
        draw_callout(axis, list(views[view_name]["callout_text"]), anchor, target)

    return figure


def _render_booth_overall_sheet(
    *,
    all_instances: list[ComponentInstance],
    input_path: str,
    date_str: str,
) -> plt.Figure:
    figure, axis = _new_figure()
    _sheet_border(axis)

    sheet_number = "SHT-02"
    sheet_title = "BOOTH OVERALL VIEWS"
    title_block = default_title_block(input_path, sheet_title=sheet_title, sheet_number=sheet_number, date_str=date_str)
    draw_title_block(axis, title_block)

    axis.text(14.0, 284.0, f"{sheet_number} {sheet_title}", fontsize=13.5, fontweight="bold", ha="left", va="top")
    axis.text(14.0, 272.0, "FULL BOOTH REFERENCE VIEWS FOR OVERALL UNDERSTANDING", fontsize=8.0, ha="left", va="top")
    axis.text(14.0, 264.0, "DIMENSIONS ON THIS SHEET ARE FROM OBJ GEOMETRY.", fontsize=8.0, ha="left", va="top")

    views = generate_booth_overall_views(all_instances)
    cells = {
        "top": (14.0, 128.0, 185.0, 88.0),
        "front": (220.0, 128.0, 184.0, 88.0),
        "side": (14.0, 40.0, 185.0, 84.0),
        "iso": (220.0, 40.0, 184.0, 84.0),
    }
    for view_name, bounds in cells.items():
        rendered = draw_view(axis, views[view_name], bounds, show_dimensions=view_name != "iso")
        anchor = rendered["transform"](tuple(views[view_name]["callout_anchor"]))
        target = (bounds[0] + bounds[2] * 0.60, bounds[1] + bounds[3] * 0.28)
        draw_callout(axis, list(views[view_name]["callout_text"]), anchor, target)

    return figure


def _save_preview(preview_path: Path, component: ExtractedComponent, view_name: str) -> None:
    figure = plt.figure(figsize=(6.0, 4.6))
    axis = figure.add_axes([0, 0, 1, 1])
    axis.set_xlim(0.0, 160.0)
    axis.set_ylim(0.0, 120.0)
    axis.set_aspect("equal", adjustable="box")
    axis.axis("off")
    view = generate_component_views(component)[view_name]
    draw_view(axis, view, (8.0, 8.0, 144.0, 104.0), show_dimensions=view_name != "iso")
    figure.savefig(preview_path, dpi=220, facecolor="white")
    plt.close(figure)


def generate_component_preview_images(
    components: list[ExtractedComponent],
    previews_dir: Path,
    *,
    view_names: tuple[str, ...] = ("front", "top", "side", "iso"),
) -> list[Path]:
    preview_paths: list[Path] = []
    previews_dir.mkdir(parents=True, exist_ok=True)
    for component in components:
        for view_name in view_names:
            preview_path = previews_dir / f"{component.id}_{view_name}.png"
            _save_preview(preview_path, component, view_name)
            preview_paths.append(preview_path)
    return preview_paths


def generate_selected_components_pdf(
    *,
    all_components: list[ExtractedComponent],
    all_instances: list[ComponentInstance],
    selected_components: list[ExtractedComponent],
    input_path: str,
    drawings_dir: Path,
    previews_dir: Path,
    generated_at: str,
) -> tuple[Path, list[Path]]:
    pdf_path = drawings_dir / "selected_components.pdf"
    preview_paths: list[Path] = []

    with PdfPages(pdf_path) as pdf:
        overview_figure = _render_overview_sheet(
            all_components=all_components,
            selected_components=selected_components,
            input_path=input_path,
            date_str=generated_at,
        )
        pdf.savefig(overview_figure, facecolor="white")
        plt.close(overview_figure)

        overall_booth_figure = _render_booth_overall_sheet(
            all_instances=all_instances,
            input_path=input_path,
            date_str=generated_at,
        )
        pdf.savefig(overall_booth_figure, facecolor="white")
        plt.close(overall_booth_figure)

        for sheet_index, component in enumerate(selected_components, start=3):
            detail_figure = _render_detail_sheet(
                component,
                all_instances=all_instances,
                sheet_index=sheet_index,
                input_path=input_path,
                date_str=generated_at,
            )
            pdf.savefig(detail_figure, facecolor="white")
            plt.close(detail_figure)

            preview_paths.extend(
                generate_component_preview_images([component], previews_dir, view_names=("front", "top", "side", "iso"))
            )

    return pdf_path, preview_paths
