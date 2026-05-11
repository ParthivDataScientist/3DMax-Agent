"""Seed the Luminy frame library with standard reference sizes."""

from __future__ import annotations

from pathlib import Path

from .database import DEFAULT_DB_PATH, ensure_database


LUMINY_FRAME_ROWS: list[dict[str, object]] = [
    {"width_mm": 470, "height_mm": 470},
    {"width_mm": 940, "height_mm": 470},
    {"width_mm": 1880, "height_mm": 470},
    {"width_mm": 3760, "height_mm": 470},
    {"width_mm": 470, "height_mm": 940},
    {"width_mm": 940, "height_mm": 940},
    {"width_mm": 1410, "height_mm": 940},
    {"width_mm": 1880, "height_mm": 940},
    {"width_mm": 2350, "height_mm": 940},
    {"width_mm": 470, "height_mm": 1880},
    {"width_mm": 940, "height_mm": 1880},
    {"width_mm": 1410, "height_mm": 1880},
    {"width_mm": 1880, "height_mm": 1880},
    {"width_mm": 2350, "height_mm": 1880},
    {"width_mm": 470, "height_mm": 2426},
    {"width_mm": 940, "height_mm": 2426},
    {"width_mm": 1410, "height_mm": 2426},
    {"width_mm": 1880, "height_mm": 2426},
    {"width_mm": 2350, "height_mm": 2426},
    {"width_mm": 2426, "height_mm": 2426},
    {"width_mm": 470, "height_mm": 2820},
    {"width_mm": 940, "height_mm": 2820},
    {"width_mm": 1410, "height_mm": 2820},
    {"width_mm": 1880, "height_mm": 2820},
    {"width_mm": 2350, "height_mm": 2820},
    {"width_mm": 470, "height_mm": 3366},
    {"width_mm": 940, "height_mm": 3366},
    {"width_mm": 1410, "height_mm": 3366},
    {"width_mm": 1880, "height_mm": 3366},
    {"width_mm": 2350, "height_mm": 3366},
]

BLOCKING_PANEL_ROWS = [
    {"width_mm": 280, "height_mm": 2750},
    {"width_mm": 580, "height_mm": 2750},
]

STANDARD_POST_ROWS = [
    {"width_mm": 120, "height_mm": 2820},
]

CUSTOM_FILLER_ROWS = [
    {"width_mm": 39},
    {"width_mm": 153},
    {"width_mm": 159},
    {"width_mm": 350},
]

def seed_luminy_library(db_path: str | Path = DEFAULT_DB_PATH) -> int:
    connection = ensure_database(db_path)
    total_inserted = 0
    try:
        # Seed luminy_frames
        connection.execute("DELETE FROM luminy_frames")
        insert_sql = """
        INSERT INTO luminy_frames (
            name, width_mm, height_mm, can_cut_width, can_cut_height, is_standard, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        for row in LUMINY_FRAME_ROWS:
            w, h = float(row["width_mm"]), float(row["height_mm"])
            connection.execute(insert_sql, (f"Luminy Frame W{int(w)} x H{int(h)}", w, h, 1, 1, 1, "Seeded"))
            total_inserted += 1

        # Seed blocking_panels
        connection.execute("DELETE FROM blocking_panels")
        insert_bp_sql = "INSERT INTO blocking_panels (name, width_mm, height_mm, notes) VALUES (?, ?, ?, ?)"
        for row in BLOCKING_PANEL_ROWS:
            w, h = float(row["width_mm"]), float(row["height_mm"])
            connection.execute(insert_bp_sql, (f"Blocking Panel W{int(w)} x H{int(h)}", w, h, "Standard"))
            total_inserted += 1
            
        # Seed standard_posts
        connection.execute("DELETE FROM standard_posts")
        insert_sp_sql = "INSERT INTO standard_posts (name, width_mm, height_mm, notes) VALUES (?, ?, ?, ?)"
        for row in STANDARD_POST_ROWS:
            w, h = float(row["width_mm"]), float(row["height_mm"])
            connection.execute(insert_sp_sql, (f"Standard Wooden Post W{int(w)} x H{int(h)}", w, h, "Standard"))
            total_inserted += 1
            
        # Seed custom_fillers
        connection.execute("DELETE FROM custom_fillers")
        insert_cf_sql = "INSERT INTO custom_fillers (name, width_mm, height_mm, notes) VALUES (?, ?, ?, ?)"
        for row in CUSTOM_FILLER_ROWS:
            w = float(row["width_mm"])
            # Height can be dynamic, storing NULL or 2820 as default? The requirements say:
            # Custom Wooden Fillers: W39, W153, W159, W350
            # Let's leave height_mm as NULL or 2820
            h = 2820.0
            connection.execute(insert_cf_sql, (f"Custom Wooden Filler W{int(w)}", w, h, "Custom"))
            total_inserted += 1

        connection.commit()
        return total_inserted
    finally:
        connection.close()
