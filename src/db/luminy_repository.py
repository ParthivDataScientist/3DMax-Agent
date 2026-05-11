"""Repository helpers for Luminy frame lookup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .database import DEFAULT_DB_PATH, ensure_database


@dataclass
class LuminyFrameRecord:
    id: int
    name: str
    width_mm: float
    height_mm: float
    can_cut_width: bool
    can_cut_height: bool
    is_standard: bool
    notes: str | None = None


class LuminyRepository:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path).expanduser()

    def _connection(self):
        return ensure_database(self.db_path)

    @staticmethod
    def _row_to_record(row) -> LuminyFrameRecord:
        return LuminyFrameRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            width_mm=float(row["width_mm"]),
            height_mm=float(row["height_mm"]),
            can_cut_width=bool(row["can_cut_width"]),
            can_cut_height=bool(row["can_cut_height"]),
            is_standard=bool(row["is_standard"]),
            notes=str(row["notes"]) if row["notes"] is not None else None,
        )

    def list_all_frames(self) -> list[LuminyFrameRecord]:
        connection = self._connection()
        try:
            rows = connection.execute(
                "SELECT * FROM luminy_frames ORDER BY height_mm, width_mm"
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            connection.close()

    def frames_for_height(self, height_mm: float, tolerance_mm: float = 5.0) -> list[LuminyFrameRecord]:
        connection = self._connection()
        try:
            rows = connection.execute(
                """
                SELECT * FROM luminy_frames
                WHERE ABS(height_mm - ?) <= ?
                ORDER BY width_mm
                """,
                (float(height_mm), float(tolerance_mm)),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            connection.close()

    def exact_frame(self, width_mm: float, height_mm: float, tolerance_mm: float = 5.0) -> LuminyFrameRecord | None:
        connection = self._connection()
        try:
            row = connection.execute(
                """
                SELECT * FROM luminy_frames
                WHERE ABS(width_mm - ?) <= ? AND ABS(height_mm - ?) <= ?
                ORDER BY ABS(width_mm - ?) + ABS(height_mm - ?)
                LIMIT 1
                """,
                (float(width_mm), float(tolerance_mm), float(height_mm), float(tolerance_mm), float(width_mm), float(height_mm)),
            ).fetchone()
            return self._row_to_record(row) if row else None
        finally:
            connection.close()

    def cuttable_frames(self, width_mm: float, height_mm: float, tolerance_mm: float = 5.0) -> list[LuminyFrameRecord]:
        connection = self._connection()
        try:
            rows = connection.execute(
                """
                SELECT * FROM luminy_frames
                WHERE width_mm >= ? AND height_mm >= ?
                ORDER BY (width_mm - ?) + (height_mm - ?), width_mm, height_mm
                """,
                (
                    float(width_mm) - float(tolerance_mm),
                    float(height_mm) - float(tolerance_mm),
                    float(width_mm),
                    float(height_mm),
                ),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            connection.close()
