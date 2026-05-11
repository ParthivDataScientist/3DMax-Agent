"""Title block drawing utilities for exhibition-style sheets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TitleBlockData:
    company_name: str
    project_name: str
    event: str
    venue: str
    hall_stand: str
    date_str: str
    job_id: str
    drafted_by: str
    scale: str
    sheet_title: str
    sheet_number: str


def default_title_block(input_path: str | Path, *, sheet_title: str, sheet_number: str, date_str: str) -> TitleBlockData:
    path = Path(input_path)
    project_name = path.stem.replace("_", " ").replace("-", " ").strip().upper() or "EXHIBITION BOOTH"
    return TitleBlockData(
        company_name="INSTA EXHIBITIONS PVT. LTD.",
        project_name=project_name,
        event="-",
        venue="-",
        hall_stand="-",
        date_str=date_str,
        job_id=path.stem.upper().replace(" ", "_"),
        drafted_by="AUTO GENERATED",
        scale="NTS",
        sheet_title=sheet_title,
        sheet_number=sheet_number,
    )


def draw_title_block(ax, data: TitleBlockData, *, page_width: float = 420.0, y: float = 8.0, height: float = 28.0) -> None:
    x = 8.0
    width = page_width - 16.0
    ax.plot([x, x + width, x + width, x, x], [y, y, y + height, y + height, y], color="black", lw=0.9)

    columns = [
        x + 72.0,
        x + 150.0,
        x + 225.0,
        x + 285.0,
        x + 335.0,
    ]
    for column in columns:
        ax.plot([column, column], [y, y + height], color="black", lw=0.7)

    row = y + (height / 2.0)
    ax.plot([x, x + width], [row, row], color="black", lw=0.7)

    def write_block(label: str, value: str, left: float, top: float, block_width: float) -> None:
        ax.text(left + 2.0, top - 3.0, label, fontsize=5.5, fontweight="bold", ha="left", va="top")
        ax.text(left + 2.0, top - 10.5, value, fontsize=6.8, ha="left", va="top")

    spans = [x, *columns, x + width]
    upper_pairs = [
        ("COMPANY NAME", data.company_name),
        ("PROJECT NAME", data.project_name),
        ("EVENT", data.event),
        ("VENUE", data.venue),
        ("HALL - STAND", data.hall_stand),
        ("DATE", data.date_str),
    ]
    lower_pairs = [
        ("JOB ID", data.job_id),
        ("DRAFTED BY", data.drafted_by),
        ("SCALE", data.scale),
        ("SHEET TITLE", data.sheet_title),
        ("SHEET NUMBER", data.sheet_number),
        ("PROJECTION", "THIRD ANGLE"),
    ]

    for index, (label, value) in enumerate(upper_pairs):
        write_block(label, value, spans[index], y + height, spans[index + 1] - spans[index])
    for index, (label, value) in enumerate(lower_pairs):
        write_block(label, value, spans[index], row, spans[index + 1] - spans[index])
