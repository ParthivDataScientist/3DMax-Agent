"""Database bootstrap helpers for the component library."""

from __future__ import annotations

import sqlite3
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_DB_PATH = DATA_DIR / "component_library.sqlite"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS luminy_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    width_mm REAL NOT NULL,
    height_mm REAL NOT NULL,
    can_cut_width INTEGER DEFAULT 1,
    can_cut_height INTEGER DEFAULT 1,
    is_standard INTEGER DEFAULT 1,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS blocking_panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    width_mm REAL NOT NULL,
    height_mm REAL NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS standard_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    width_mm REAL NOT NULL,
    height_mm REAL NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS custom_fillers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    width_mm REAL NOT NULL,
    height_mm REAL,
    notes TEXT
);
"""


def connect_database(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_database(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    connection = connect_database(db_path)
    connection.executescript(SCHEMA_SQL)
    connection.commit()
    return connection
