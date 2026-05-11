import sqlite3
from pathlib import Path
from typing import List, Dict, Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_DB_PATH = DATA_DIR / "component_library.sqlite"

class ComponentOptimizer:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_luminy_frames(self, target_height: float) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            # allow some tolerance for height, e.g. 2820
            rows = conn.execute("SELECT * FROM luminy_frames WHERE ABS(height_mm - ?) <= 5 ORDER BY width_mm DESC", (target_height,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_standard_posts(self, target_height: float) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM standard_posts WHERE ABS(height_mm - ?) <= 5 ORDER BY width_mm DESC", (target_height,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_custom_fillers(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM custom_fillers ORDER BY width_mm").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_blocking_panels(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM blocking_panels ORDER BY width_mm DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
