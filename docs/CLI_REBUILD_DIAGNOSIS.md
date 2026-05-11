# CLI Rebuild Diagnosis

## What The Current Code Does
- `pipeline/FabricationPackage.py` is the current end-to-end workflow controller.
- It calls `geometry_pipeline.extract_measurements()` to read an OBJ, split geometry, compute measurements, and produce a detailed analysis payload.
- It then eagerly enriches every component with classification, materials, grouped BOM rows, assembly sheets, elevation sheets, subassembly sheets, and part-detail sheets.
- Existing drawing code in `pipeline/fabrication_drawings.py` and `pipeline/drawing_generator.py` already has useful CAD-style visual primitives, page sizing, title-block concepts, and dimension rendering patterns.

## Why It Does Not Match The New Product
- The current product path is `OBJ -> automatic full fabrication package`.
- The new product path must be `OBJ -> detect components -> ask user -> selected-component-only PDF`.
- The legacy pipeline decides too much too early: it classifies, groups, and generates all fabrication output before the user can choose which booth component matters.
- Legacy output is package-oriented and multi-folder, while the new product needs one strong terminal-first flow with a selected-components PDF and focused manifests.

## What Can Be Reused
- `pipeline/geometry_pipeline.py`
  - mesh cleanup
  - unit normalization to mm
  - connected-component splitting
  - mesh measurement helpers
  - shape/orientation heuristics from `build_component_record()`
- `pipeline/materials.py`
  - material fallback logic for categories that map well to older fabrication types
- `pipeline/drawing_generator.py` and `pipeline/fabrication_drawings.py`
  - line-based CAD rendering ideas
  - A3 landscape sizing patterns
  - title block and dimension styling ideas

## What Needs Refactoring
- A brand new CLI entrypoint is needed at `src/main.py`.
- OBJ parsing needs its own parser layer that preserves `o`, `g`, and `usemtl` identity and returns component candidates plus warnings.
- Component extraction must become a standalone step that stops before any PDF is generated.
- Selection must move into a dedicated terminal interaction module with both interactive and non-interactive flows.
- Drawing generation must be rebuilt around selected components only, using per-component bounding boxes and clean CAD-style sheets instead of the legacy full-package orchestration.
- Manifest writing must be separated from legacy fabrication package output so the new flow always writes:
  - `component_manifest.json`
  - `selected_components.json`

## Rebuild Approach
1. Create a new `src/` package that becomes the primary CLI path.
2. Reuse legacy geometry analysis only as a helper layer, not as the product workflow controller.
3. Parse the OBJ and preserve object/group/material identity.
4. Extract component instances, classify them with booth-aware rules, and group repeated components into selectable component rows.
5. Print the detected components in the terminal and resolve user selection.
6. Write manifests and generate one selected-components CAD-style PDF plus per-view preview PNGs.
7. Leave `pipeline/` intact as legacy functionality for reference and selective reuse.
