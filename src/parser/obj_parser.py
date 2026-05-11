"""OBJ parser that preserves object, group, and material identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Optional

import numpy as np
import trimesh


from src.pipeline.geometry_pipeline import clean_mesh_geometry, scale_mesh_to_mm

@dataclass
class ParsedMeshCandidate:
    mesh_id: str
    mesh: trimesh.Trimesh
    source_label: str
    object_name: Optional[str]
    group_name: Optional[str]
    material_name: Optional[str]
    notes: list[str] = field(default_factory=list)


@dataclass
class ParsedOBJResult:
    input_path: Path
    unit: str
    candidates: list[ParsedMeshCandidate]
    warnings: list[str] = field(default_factory=list)


@dataclass
class _FaceBlock:
    object_name: Optional[str]
    group_name: Optional[str]
    material_name: Optional[str]
    faces: list[list[int]] = field(default_factory=list)


def _clean_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_vertex_index(token: str, vertex_count: int) -> int:
    raw_index = int(token.split("/")[0])
    index = raw_index - 1 if raw_index > 0 else vertex_count + raw_index
    if index < 0 or index >= vertex_count:
        raise IndexError(f"Face index {raw_index} is out of range for {vertex_count} vertices.")
    return index


def _triangulate(indices: list[int]) -> list[list[int]]:
    if len(indices) < 3:
        return []
    if len(indices) == 3:
        return [indices]
    return [[indices[0], indices[offset], indices[offset + 1]] for offset in range(1, len(indices) - 1)]


def _candidate_label(block: _FaceBlock, mesh_id: str) -> str:
    for value in (block.object_name, block.group_name, block.material_name, mesh_id):
        if value:
            return value
    return mesh_id


def _build_candidate(
    mesh_id: str,
    block: _FaceBlock,
    vertices: list[tuple[float, float, float]],
    unit: str,
) -> Optional[ParsedMeshCandidate]:
    if not block.faces:
        return None

    used_indices = sorted({index for face in block.faces for index in face})
    if not used_indices:
        return None

    remap = {old_index: new_index for new_index, old_index in enumerate(used_indices)}
    local_faces = [[remap[index] for index in face] for face in block.faces]
    vertex_array = np.asarray(vertices, dtype=float)
    mesh = trimesh.Trimesh(
        vertices=vertex_array[used_indices],
        faces=np.asarray(local_faces, dtype=int),
        process=False,
    )
    mesh = clean_mesh_geometry(mesh)
    if mesh.vertices.size == 0 or mesh.faces.size == 0:
        return None

    mesh = scale_mesh_to_mm(mesh, unit)
    return ParsedMeshCandidate(
        mesh_id=mesh_id,
        mesh=mesh,
        source_label=_candidate_label(block, mesh_id),
        object_name=block.object_name,
        group_name=block.group_name,
        material_name=block.material_name,
    )


def _fallback_scene_parse(obj_path: Path, unit: str) -> tuple[list[ParsedMeshCandidate], list[str]]:
    warnings = [
        "Warning: manual OBJ block parsing produced no usable face blocks. Falling back to trimesh scene loading."
    ]
    candidates: list[ParsedMeshCandidate] = []
    loaded = trimesh.load(obj_path, force="scene", skip_materials=False)
    if isinstance(loaded, trimesh.Trimesh):
        loaded = trimesh.Scene([loaded])

    for index, (name, geometry) in enumerate(loaded.geometry.items(), start=1):
        if not isinstance(geometry, trimesh.Trimesh) or geometry.is_empty:
            continue
        mesh = clean_mesh_geometry(geometry.copy())
        if mesh.vertices.size == 0 or mesh.faces.size == 0:
            continue
        candidates.append(
            ParsedMeshCandidate(
                mesh_id=f"mesh_{index:03d}",
                mesh=scale_mesh_to_mm(mesh, unit),
                source_label=name or f"mesh_{index:03d}",
                object_name=name or None,
                group_name=None,
                material_name=None,
                notes=["Loaded from trimesh scene fallback."],
            )
        )

    return candidates, warnings


def parse_obj_file(obj_path: str | Path, unit: str = "mm") -> ParsedOBJResult:
    path = Path(obj_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"input file does not exist: {path}")
    if path.suffix.lower() != ".obj":
        raise ValueError(f"input file must be an .obj: {path}")

    vertices: list[tuple[float, float, float]] = []
    warnings: list[str] = []
    blocks: list[_FaceBlock] = []
    current = _FaceBlock(object_name=None, group_name=None, material_name=None)
    saw_named_object = False
    saw_named_group = False

    def flush_current() -> None:
        nonlocal current
        if current.faces:
            blocks.append(current)
            current = _FaceBlock(
                object_name=current.object_name,
                group_name=current.group_name,
                material_name=current.material_name,
            )

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            fields = line.split()
            record_type = fields[0].lower()
            try:
                if record_type == "v":
                    if len(fields) < 4:
                        warnings.append(f"Warning: malformed vertex skipped at line {line_number}.")
                        continue
                    vertices.append((float(fields[1]), float(fields[2]), float(fields[3])))
                elif record_type == "o":
                    if current.faces:
                        flush_current()
                    current.object_name = _clean_name(" ".join(fields[1:])) if len(fields) > 1 else None
                    saw_named_object = saw_named_object or bool(current.object_name)
                elif record_type == "g":
                    if current.faces:
                        flush_current()
                    current.group_name = _clean_name(" ".join(fields[1:])) if len(fields) > 1 else None
                    saw_named_group = saw_named_group or bool(current.group_name)
                elif record_type == "usemtl":
                    if current.faces:
                        flush_current()
                    current.material_name = _clean_name(" ".join(fields[1:])) if len(fields) > 1 else None
                elif record_type == "f":
                    if len(fields) < 4:
                        warnings.append(f"Warning: malformed face skipped at line {line_number}.")
                        continue
                    try:
                        indices = [_parse_vertex_index(token, len(vertices)) for token in fields[1:]]
                    except (ValueError, IndexError) as exc:
                        warnings.append(f"Warning: face skipped at line {line_number}: {exc}")
                        continue
                    current.faces.extend(_triangulate(indices))
            except ValueError as exc:
                warnings.append(f"Warning: OBJ line {line_number} skipped: {exc}")

    if current.faces:
        blocks.append(current)

    candidates: list[ParsedMeshCandidate] = []
    for index, block in enumerate(blocks, start=1):
        candidate = _build_candidate(f"mesh_{index:03d}", block, vertices, unit)
        if candidate is None:
            warnings.append(f"Warning: mesh block {index} did not contain measurable geometry and was skipped.")
            continue
        candidates.append(candidate)

    if not candidates:
        fallback_candidates, fallback_warnings = _fallback_scene_parse(path, unit)
        candidates.extend(fallback_candidates)
        warnings.extend(fallback_warnings)

    if not candidates:
        raise ValueError("OBJ has no valid mesh geometry.")

    if not saw_named_object and not saw_named_group:
        warnings.append("Warning: OBJ has no named objects or groups. Using geometry-based grouping.")

    return ParsedOBJResult(
        input_path=path.resolve(),
        unit="mm",
        candidates=candidates,
        warnings=warnings,
    )
