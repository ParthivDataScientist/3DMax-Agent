"""
3DMax Agent — FastAPI Server
Serves the static frontend and exposes a /api/process endpoint
that runs the Python fabrication pipeline in-process.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Make pipeline imports available ──────────────────────────────────────────
PIPELINE_DIR = Path(__file__).parent / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from FabricationPackage import build_fabrication_package  # noqa: E402
from geometry_pipeline import ExtractionError              # noqa: E402

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="3DMax Agent", version="1.0.0")

ALLOWED_UNITS = {"mm", "cm", "m", "in"}


# ── Request schema ─────────────────────────────────────────────────────────────
class ProcessRequest(BaseModel):
    filename: str
    content: str
    sourceUnit: str = "mm"


# ── /api/process ──────────────────────────────────────────────────────────────
@app.post("/api/process")
async def process_obj(req: ProcessRequest) -> JSONResponse:
    # Validate inputs
    if not req.filename.lower().endswith(".obj"):
        raise HTTPException(status_code=400, detail="Only Wavefront .obj files are supported.")
    if req.sourceUnit not in ALLOWED_UNITS:
        raise HTTPException(status_code=400, detail=f"sourceUnit must be one of: {', '.join(sorted(ALLOWED_UNITS))}")
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="File content is empty.")

    work_dir = tempfile.mkdtemp(prefix="obj-agent-")
    try:
        # Write OBJ to temp dir
        obj_path = os.path.join(work_dir, req.filename)
        with open(obj_path, "w", encoding="utf-8") as fh:
            fh.write(req.content)

        output_root = os.path.join(work_dir, "output")

        # Run pipeline directly (no subprocess)
        try:
            results = build_fabrication_package(
                obj_path=obj_path,
                source_unit=req.sourceUnit,
                output_root=output_root,
            )
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")

        # Zip fabrication outputs — exclude analysis/ (internal app data)
        import zipfile
        EXCLUDE = {"analysis"}
        package_root: Path = results["package_root"]
        zip_base = os.path.join(work_dir, f"{package_root.name}_package")
        zip_path = zip_base + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in package_root.rglob("*"):
                if item.is_file() and item.relative_to(package_root).parts[0] not in EXCLUDE:
                    zf.write(item, item.relative_to(package_root))

        # Read zip as base64
        import base64
        with open(zip_path, "rb") as fh:
            zip_b64 = base64.b64encode(fh.read()).decode()

        # Read summary metadata from analysis JSON
        component_count: int | str = "—"
        part_group_count: int | str = "—"
        object_types: list[str] = []
        try:
            analysis_path: Path = results["analysis_json"]
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            component_count = len(analysis.get("components", []))
            part_groups = analysis.get("fabrication", {}).get("part_groups", [])
            part_group_count = len(part_groups)
            object_types = list({g["object_type"] for g in part_groups if g.get("object_type")})
        except Exception:
            pass  # non-critical

        return JSONResponse({
            "filename": f"{package_root.name}_package.zip",
            "zipBase64": zip_b64,
            "componentCount": component_count,
            "partGroupCount": part_group_count,
            "objectTypes": object_types,
        })

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── /api/health ───────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Static frontend (must be mounted last) ───────────────────────────────────
PUBLIC_DIR = Path(__file__).parent / "public"
if PUBLIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")
