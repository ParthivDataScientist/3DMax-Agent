# OBJ Measurement Extractor

Phase 1 prototype for reading a Wavefront `.obj` mesh and returning structured JSON that a later AutoCAD measurement step can consume.

The current pipeline also performs higher-level geometry understanding on top of the mesh extraction:

- disconnected component segmentation
- shape classification for `box`, `cylinder`, `sphere`, `flat panel`, and `irregular`
- planar face clustering
- orientation detection
- semantic labeling for booth-style structures such as panels, beams, pillars, and platforms

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe .\Extract.py .\path\to\model.obj
```

The command writes the JSON result into the `output` folder and prints only the saved file path in the terminal.

## Generate Drawings

After the analysis JSON is created, generate orthographic drawing outputs from it:

```powershell
.\.venv\Scripts\python.exe .\GenerateDrawing.py .\output\box_analysis.json
```

This creates these files in the `output` folder:

- `*_drawing.png`
- `*_drawing.pdf`
- `*_drawing.dxf`

The drawing generator reads the top-level `views` block from the JSON and builds:

- a matplotlib technical drawing sheet
- an AutoCAD-compatible DXF using `ezdxf`

## Output

The script returns JSON with these top-level sections:

- `input`
- `validation`
- `overall_dimensions`
- `bounding_box`
- `mesh_metrics`
- `vertices`
- `edges`
- `faces`
- `views`
- `component_summary`
- `components`

Each item in `components` contains its own geometry, planar regions, dimensions, shape classification, orientation, and semantic role.

If the file cannot be processed, the script writes an error JSON file into `output` and exits with a non-zero status code.
