"""CLI entrypoint for the OBJ geometry understanding pipeline."""

from __future__ import annotations

import sys

from geometry_pipeline import ExtractionError, extract_measurements, main


__all__ = ["ExtractionError", "extract_measurements", "main"]


if __name__ == "__main__":
    sys.exit(main())
