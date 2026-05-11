"""Low-level CAD-style drawing helpers for matplotlib output."""

from __future__ import annotations

from typing import Callable

import matplotlib.pyplot as plt


GEOMETRY_COLOR = "#111111"
DIMENSION_COLOR = "#1E5BD7"
CALLOUT_COLOR = "#BA2D0B"


def _view_bounds(view: dict[str, object]) -> tuple[float, float, float, float]:
    points: list[tuple[float, float]] = []
    for segment in view.get("geometry", []):
        points.append(tuple(segment["start"]))
        points.append(tuple(segment["end"]))
    if not points:
        return (0.0, 0.0, 1.0, 1.0)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x = min(xs)
    min_y = min(ys)
    max_x = max(xs)
    max_y = max(ys)
    return (min_x, min_y, max(max_x - min_x, 1.0), max(max_y - min_y, 1.0))


def draw_callout(
    ax,
    text_lines: list[str],
    anchor: tuple[float, float],
    target: tuple[float, float],
    *,
    color: str = CALLOUT_COLOR,
    with_arrow: bool = True,
) -> None:
    text = "\n".join(text_lines)
    arrowprops = {"arrowstyle": "->", "lw": 0.8, "color": color} if with_arrow else None
    ax.annotate(
        text,
        xy=anchor,
        xytext=target,
        ha="left",
        va="center",
        fontsize=7.0,
        color=color,
        arrowprops=arrowprops,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": color, "lw": 0.8},
    )


def draw_notes_box(ax, bounds: tuple[float, float, float, float], lines: list[str], title: str | None = None) -> None:
    x, y, width, height = bounds
    ax.plot([x, x + width, x + width, x, x], [y, y, y + height, y + height, y], color=GEOMETRY_COLOR, lw=0.8)
    cursor_y = y + height - 6.0
    if title:
        ax.text(x + 3.0, cursor_y, title, fontsize=7.5, fontweight="bold", ha="left", va="top")
        cursor_y -= 6.0

    for line in lines[:9]:
        ax.text(x + 3.0, cursor_y, line, fontsize=6.5, ha="left", va="top", color=GEOMETRY_COLOR)
        cursor_y -= 5.0


def draw_view(ax, view: dict[str, object], bounds: tuple[float, float, float, float], *, show_dimensions: bool = True) -> dict[str, Callable[[tuple[float, float]], tuple[float, float]]]:
    x, y, width, height = bounds
    min_x, min_y, geom_width, geom_height = _view_bounds(view)
    padding_x = width * 0.15
    padding_y = height * 0.18
    usable_width = max(width - (padding_x * 2.0), 1.0)
    usable_height = max(height - (padding_y * 2.0), 1.0)
    scale = min(usable_width / geom_width, usable_height / geom_height)
    offset_x = x + (width - (geom_width * scale)) / 2.0
    offset_y = y + (height - (geom_height * scale)) / 2.0

    def transform(point: tuple[float, float]) -> tuple[float, float]:
        return (
            offset_x + ((point[0] - min_x) * scale),
            offset_y + ((point[1] - min_y) * scale),
        )

    ax.plot(
        [x, x + width, x + width, x, x],
        [y, y, y + height, y + height, y],
        color="#B9C0CA",
        lw=0.3,
    )
    ax.text(x + width / 2.0, y + height - 3.0, str(view.get("title", "")).upper(), fontsize=7.5, fontweight="bold", ha="center", va="top")

    for fill in view.get("fills", []):
        fill_points = [transform(tuple(point)) for point in fill.get("points", [])]
        if len(fill_points) < 3:
            continue
        polygon = plt.Polygon(
            fill_points,
            closed=True,
            facecolor=str(fill.get("facecolor", "#BA2D0B")),
            edgecolor=str(fill.get("edgecolor", "#BA2D0B")),
            alpha=float(fill.get("alpha", 0.18)),
            linewidth=float(fill.get("linewidth", 0.8)),
        )
        ax.add_patch(polygon)

    for segment in view.get("geometry", []):
        start = transform(tuple(segment["start"]))
        end = transform(tuple(segment["end"]))
        ax.plot(
            [start[0], end[0]],
            [start[1], end[1]],
            color=str(segment.get("color", GEOMETRY_COLOR)),
            lw=float(segment.get("linewidth", 1.0)),
        )

    if show_dimensions:
        for dimension in view.get("dimensions", []):
            point_a = transform(tuple(dimension["points"][0]))
            point_b = transform(tuple(dimension["points"][1]))
            text = str(dimension["text"])

            if dimension["orientation"] == "horizontal":
                dim_y = min(point_a[1], point_b[1]) - 7.0
                ax.plot([point_a[0], point_a[0]], [point_a[1], dim_y], color=DIMENSION_COLOR, lw=0.8)
                ax.plot([point_b[0], point_b[0]], [point_b[1], dim_y], color=DIMENSION_COLOR, lw=0.8)
                ax.plot([point_a[0], point_b[0]], [dim_y, dim_y], color=DIMENSION_COLOR, lw=0.8)
                ax.text((point_a[0] + point_b[0]) / 2.0, dim_y - 2.0, text, fontsize=6.8, color=DIMENSION_COLOR, ha="center", va="top")
            else:
                dim_x = max(point_a[0], point_b[0]) + 7.0
                ax.plot([point_a[0], dim_x], [point_a[1], point_a[1]], color=DIMENSION_COLOR, lw=0.8)
                ax.plot([point_b[0], dim_x], [point_b[1], point_b[1]], color=DIMENSION_COLOR, lw=0.8)
                ax.plot([dim_x, dim_x], [point_a[1], point_b[1]], color=DIMENSION_COLOR, lw=0.8)
                ax.text(dim_x + 2.0, (point_a[1] + point_b[1]) / 2.0, text, fontsize=6.8, color=DIMENSION_COLOR, ha="left", va="center", rotation=90)

    return {"transform": transform}
