"""High-level geometry understanding pipeline for Wavefront OBJ meshes."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from edge_detection import extract_candidate_edges, extract_silhouette_edges, select_visible_edges
from projection import VIEW_DEFINITIONS, build_projected_view


PRECISION = 6
UNIT = "mm"
SOURCE_UNIT_SCALES = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
}
EPSILON = 1e-9
FEATURE_EDGE_ANGLE_DEGREES = 30.0
PLANAR_CLUSTER_NORMAL_DEGREES = 7.5
PLANAR_DISTANCE_RATIO = 0.01
MAJOR_PLANAR_REGION_RATIO = 0.05
FLAT_PANEL_THICKNESS_RATIO = 0.08
SPHERE_EXTENT_RATIO = 0.85
SPHERE_RADIUS_CV = 0.08
CYLINDER_RADIUS_CV = 0.12
CYLINDER_SECONDARY_RATIO = 0.12
BOX_NORMAL_ALIGNMENT = 0.94
VERTICAL_ALIGNMENT = 0.85
HORIZONTAL_ALIGNMENT = 0.25
SEMANTIC_ELONGATION_RATIO = 2.5


class ExtractionError(Exception):
    """Raised when the mesh cannot be converted into measurement data."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def round_number(value: Any, precision: int = PRECISION) -> float | None:
    """Convert numpy-friendly numeric values into rounded Python floats."""
    if value is None:
        return None

    numeric = float(value)
    if not math.isfinite(numeric):
        return None

    return round(numeric, precision)


def round_vector(values: np.ndarray | list[float]) -> list[float | None]:
    return [round_number(value) for value in values]


def safe_ratio(numerator: float, denominator: float) -> float:
    if abs(denominator) <= EPSILON:
        return 0.0
    return float(numerator / denominator)


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm <= EPSILON:
        return np.zeros(3, dtype=float)
    return vector / norm


def clean_mesh_geometry(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Drop unreferenced vertices and zero-area faces before analysis."""
    mesh.remove_unreferenced_vertices()
    if len(mesh.faces):
        nondegenerate = mesh.nondegenerate_faces(height=EPSILON)
        if not bool(np.all(nondegenerate)):
            mesh.update_faces(nondegenerate)
            mesh.remove_unreferenced_vertices()
    return mesh


def safe_average_vectors(vectors: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    values = np.asarray(vectors, dtype=float)
    if values.ndim != 2 or values.shape[0] == 0:
        return np.zeros(3, dtype=float)

    finite_rows = np.isfinite(values).all(axis=1)
    values = values[finite_rows]
    if values.shape[0] == 0:
        return np.zeros(vectors.shape[1] if np.ndim(vectors) == 2 else 3, dtype=float)

    if weights is not None:
        cleaned_weights = np.asarray(weights, dtype=float)[finite_rows]
        cleaned_weights = np.where(np.isfinite(cleaned_weights) & (cleaned_weights > EPSILON), cleaned_weights, 0.0)
        if float(cleaned_weights.sum()) > EPSILON:
            return np.average(values, axis=0, weights=cleaned_weights)

    return values.mean(axis=0)


def safe_mesh_centroid(mesh: trimesh.Trimesh) -> np.ndarray:
    try:
        centroid = np.asarray(mesh.centroid, dtype=float)
        if centroid.shape == (3,) and np.isfinite(centroid).all():
            return centroid
    except ValueError:
        pass

    vertices = np.asarray(mesh.vertices, dtype=float)
    finite_vertices = vertices[np.isfinite(vertices).all(axis=1)]
    if len(finite_vertices):
        return finite_vertices.mean(axis=0)

    return np.zeros(3, dtype=float)


def safe_mesh_center_of_mass(mesh: trimesh.Trimesh) -> np.ndarray:
    if mesh.is_volume:
        try:
            center_mass = np.asarray(mesh.center_mass, dtype=float)
            if center_mass.shape == (3,) and np.isfinite(center_mass).all():
                return center_mass
        except ValueError:
            pass
    return safe_mesh_centroid(mesh)


def angle_between_vectors(first: np.ndarray, second: np.ndarray) -> float:
    first_normalized = normalize_vector(first)
    second_normalized = normalize_vector(second)
    dot_product = float(np.clip(np.dot(first_normalized, second_normalized), -1.0, 1.0))
    return math.degrees(math.acos(dot_product))


def classify_axis_tilt(axis_vector: np.ndarray) -> tuple[str, float]:
    alignment_to_vertical = abs(float(np.dot(normalize_vector(axis_vector), np.array([0.0, 0.0, 1.0]))))
    tilt_degrees = round_number(math.degrees(math.acos(np.clip(alignment_to_vertical, 0.0, 1.0)))) or 0.0

    if alignment_to_vertical >= VERTICAL_ALIGNMENT:
        return "vertical", tilt_degrees
    if alignment_to_vertical <= HORIZONTAL_ALIGNMENT:
        return "horizontal", tilt_degrees
    return "angled", tilt_degrees


def classify_surface_orientation(surface_normal: np.ndarray) -> tuple[str, float]:
    normal_alignment = abs(float(np.dot(normalize_vector(surface_normal), np.array([0.0, 0.0, 1.0]))))
    tilt_degrees = round_number(math.degrees(math.acos(np.clip(normal_alignment, 0.0, 1.0)))) or 0.0

    if normal_alignment >= VERTICAL_ALIGNMENT:
        return "horizontal", tilt_degrees
    if normal_alignment <= HORIZONTAL_ALIGNMENT:
        return "vertical", tilt_degrees
    return "angled", tilt_degrees


def resolve_unit_scale(source_unit: str) -> float:
    normalized_unit = source_unit.strip().lower()
    if normalized_unit not in SOURCE_UNIT_SCALES:
        raise ExtractionError(
            "unsupported_unit",
            f"Unsupported source unit '{source_unit}'. Expected one of: {', '.join(SOURCE_UNIT_SCALES)}.",
        )
    return SOURCE_UNIT_SCALES[normalized_unit]


def scale_mesh_to_mm(mesh: trimesh.Trimesh, source_unit: str) -> trimesh.Trimesh:
    """Return a mesh scaled into millimeters."""
    scale_factor = resolve_unit_scale(source_unit)
    if abs(scale_factor - 1.0) <= EPSILON:
        return mesh

    scaled_mesh = mesh.copy()
    scaled_mesh.apply_scale(scale_factor)
    return scaled_mesh


def build_error_payload(
    obj_path: Path | None,
    code: str,
    message: str,
    *,
    source_unit: str = UNIT,
) -> dict[str, Any]:
    return {
        "input": {
            "source_path": str(obj_path.resolve()) if obj_path else None,
            "unit": UNIT,
            "source_unit": source_unit,
            "normalized_unit": UNIT,
            "unit_scale_to_mm": SOURCE_UNIT_SCALES.get(source_unit, 1.0),
        },
        "error": {
            "code": code,
            "message": message,
        },
    }


def build_output_path(obj_path: Path, suffix: str = "_analysis.json") -> Path:
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    return output_dir / f"{obj_path.stem}{suffix}"


def write_payload_to_file(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_mesh(obj_path: Path) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Load an OBJ file and normalize it into a single Trimesh instance."""
    if not obj_path.exists():
        raise ExtractionError("file_not_found", f"OBJ file not found: {obj_path}")

    if obj_path.suffix.lower() != ".obj":
        raise ExtractionError("unsupported_file_type", "This pipeline currently supports only .obj files.")

    try:
        loaded = trimesh.load(obj_path, force="scene", skip_materials=True)
    except Exception as exc:  # pragma: no cover - trimesh surfaces parser-specific errors.
        raise ExtractionError("load_failed", f"Unable to read OBJ file: {exc}") from exc

    if isinstance(loaded, trimesh.Scene):
        geometries = [
            geometry.copy()
            for geometry in loaded.geometry.values()
            if isinstance(geometry, trimesh.Trimesh) and not geometry.is_empty
        ]
        geometry_names = list(loaded.geometry.keys())

        if not geometries:
            raise ExtractionError("empty_mesh", "OBJ file does not contain any readable mesh geometry.")

        mesh = geometries[0] if len(geometries) == 1 else trimesh.util.concatenate(geometries)
        named_meshes = []
        for name, geom in loaded.geometry.items():
            if isinstance(geom, trimesh.Trimesh) and not geom.is_empty:
                named_meshes.append((name, geom))
        source_type = "scene"
    elif isinstance(loaded, trimesh.Trimesh):
        if loaded.is_empty:
            raise ExtractionError("empty_mesh", "OBJ file contains an empty mesh.")

        mesh = loaded.copy()
        geometry_names = [obj_path.stem]
        named_meshes = [(obj_path.stem, loaded.copy())]
        source_type = "mesh"
    else:
        raise ExtractionError(
            "unsupported_geometry",
            f"Unsupported geometry type returned by trimesh: {type(loaded).__name__}",
        )

    mesh = clean_mesh_geometry(mesh)
    cleaned_named_meshes = []
    for name, geom in named_meshes:
        cleaned = clean_mesh_geometry(geom.copy())
        if cleaned.vertices.size == 0 or cleaned.faces.size == 0:
            continue
        cleaned_named_meshes.append((name, cleaned))
    named_meshes = cleaned_named_meshes

    if mesh.vertices.size == 0 or mesh.faces.size == 0:
        raise ExtractionError("empty_mesh", "OBJ file does not contain measurable non-degenerate mesh faces.")
    if not named_meshes:
        raise ExtractionError("empty_mesh", "OBJ file does not contain measurable non-degenerate mesh components.")

    metadata = {
        "source_type": source_type,
        "geometry_count": len(geometry_names),
        "geometry_names": geometry_names,
    }
    return mesh, metadata, named_meshes


def split_components(named_meshes: list[tuple[str, trimesh.Trimesh]]) -> list[tuple[str, trimesh.Trimesh]]:
    components = []

    for source_name, mesh in named_meshes:
        try:
            submeshes = mesh.split(only_watertight=False)
        except ImportError:
            face_groups = connected_face_groups(mesh.faces)
            submeshes = mesh.submesh(face_groups, append=False, repair=False)

        for component in submeshes:
            cleaned = component.copy()
            cleaned = clean_mesh_geometry(cleaned)
            if cleaned.vertices.size == 0 or cleaned.faces.size == 0:
                continue
            components.append((source_name, cleaned))

    return components


def connected_face_groups(faces: np.ndarray) -> list[list[int]]:
    if len(faces) == 0:
        return []

    parent = list(range(len(faces)))
    rank = [0] * len(faces)
    vertex_to_face: dict[int, int] = {}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return

        if rank[first_root] < rank[second_root]:
            parent[first_root] = second_root
        elif rank[first_root] > rank[second_root]:
            parent[second_root] = first_root
        else:
            parent[second_root] = first_root
            rank[first_root] += 1

    for face_index, face in enumerate(np.asarray(faces, dtype=int)):
        for vertex_index in face:
            if vertex_index in vertex_to_face:
                union(face_index, vertex_to_face[vertex_index])
            else:
                vertex_to_face[vertex_index] = face_index

    groups: dict[int, list[int]] = defaultdict(list)
    for face_index in range(len(faces)):
        groups[find(face_index)].append(face_index)

    return list(groups.values())


def build_vertices(mesh: trimesh.Trimesh) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "coordinates": round_vector(vertex),
        }
        for index, vertex in enumerate(mesh.vertices)
    ]


def build_edges(mesh: trimesh.Trimesh) -> list[dict[str, Any]]:
    candidate_edges = extract_candidate_edges(mesh, FEATURE_EDGE_ANGLE_DEGREES, precision=PRECISION)
    vertices = np.asarray(mesh.vertices, dtype=float)

    return [
        {
            "index": int(record["index"]),
            "vertex_indices": [int(record["vertex_indices"][0]), int(record["vertex_indices"][1])],
            "length": round_number(
                np.linalg.norm(
                    vertices[record["vertex_indices"][1]] - vertices[record["vertex_indices"][0]]
                )
            ),
            "adjacent_face_count": int(record["adjacent_face_count"]),
            "adjacent_face_indices": [int(face_index) for face_index in record["adjacent_face_indices"]],
            "is_boundary": bool(record["is_boundary"]),
            "adjacent_face_angle_degrees": record["adjacent_face_angle_degrees"],
            "is_feature_edge": bool(record["is_boundary"] or record["is_sharp"]),
        }
        for record in candidate_edges
    ]


def build_faces(mesh: trimesh.Trimesh) -> list[dict[str, Any]]:
    face_centers = mesh.triangles_center
    return [
        {
            "index": index,
            "vertex_indices": [int(vertex_index) for vertex_index in face],
            "normal": round_vector(mesh.face_normals[index]),
            "centroid": round_vector(face_centers[index]),
            "area": round_number(mesh.area_faces[index]),
        }
        for index, face in enumerate(mesh.faces)
    ]


def build_view_dimensions(size: np.ndarray) -> dict[str, dict[str, float | None]]:
    return {
        "front": {
            "width": round_number(size[0]),
            "height": round_number(size[2]),
            "depth": round_number(size[1]),
        },
        "top": {
            "width": round_number(size[0]),
            "height": round_number(size[1]),
            "depth": round_number(size[2]),
        },
        "side": {
            "width": round_number(size[1]),
            "height": round_number(size[2]),
            "depth": round_number(size[0]),
        },
    }


def generate_orthographic_projections(mesh: trimesh.Trimesh) -> dict[str, Any]:
    bounds = np.asarray(mesh.bounds, dtype=float)
    size = bounds[1] - bounds[0]
    dimensions_by_view = build_view_dimensions(size)
    candidate_edges = extract_candidate_edges(mesh, FEATURE_EDGE_ANGLE_DEGREES, precision=PRECISION)
    projected_views: dict[str, Any] = {}

    for view_name, definition in VIEW_DEFINITIONS.items():
        silhouette_edges = extract_silhouette_edges(
            mesh,
            definition["view_direction"],
            epsilon=EPSILON,
        )
        visible_edges = select_visible_edges(candidate_edges, silhouette_edges)
        view_payload = build_projected_view(
            mesh,
            visible_edges,
            view_name,
            precision=PRECISION,
            epsilon=EPSILON,
        )
        view_payload["dimensions"] = dimensions_by_view[view_name]
        projected_views[view_name] = view_payload

    return projected_views


def compute_principal_frame(mesh: trimesh.Trimesh) -> dict[str, Any]:
    vertices = np.asarray(mesh.vertices, dtype=float)
    centroid = vertices.mean(axis=0)
    centered = vertices - centroid

    if len(vertices) < 3 or np.allclose(centered, 0.0):
        axes = np.eye(3)
    else:
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
        axes = np.array([normalize_vector(axis) for axis in vh[:3]])

    local_coordinates = centered @ axes.T
    local_minimum = local_coordinates.min(axis=0)
    local_maximum = local_coordinates.max(axis=0)
    extents = local_maximum - local_minimum

    order = np.argsort(extents)[::-1]
    axes = axes[order]
    extents = extents[order]
    local_minimum = local_minimum[order]
    local_maximum = local_maximum[order]

    if np.linalg.det(axes) < 0:
        axes[2] *= -1.0

    return {
        "centroid": centroid,
        "axes": axes,
        "extents": extents,
        "local_minimum": local_minimum,
        "local_maximum": local_maximum,
    }


def compute_semantic_dimensions(principal_frame: dict[str, Any]) -> dict[str, Any]:
    axes = np.asarray(principal_frame["axes"], dtype=float)
    extents = np.asarray(principal_frame["extents"], dtype=float)
    vertical_axis = np.array([0.0, 0.0, 1.0], dtype=float)

    vertical_alignments = [abs(float(np.dot(normalize_vector(axis), vertical_axis))) for axis in axes]
    height_axis_index = int(np.argmax(vertical_alignments))
    height_axis = axes[height_axis_index]
    height = float(extents[height_axis_index])

    base_indices = [index for index in range(len(extents)) if index != height_axis_index]
    base_indices.sort(key=lambda index: float(extents[index]), reverse=True)

    length_axis_index = base_indices[0] if base_indices else height_axis_index
    width_axis_index = base_indices[1] if len(base_indices) > 1 else height_axis_index

    length = float(extents[length_axis_index])
    width = float(extents[width_axis_index])

    return {
        "length": length,
        "width": width,
        "height": height,
        "height_axis_index": height_axis_index,
        "height_axis": height_axis,
        "height_axis_alignment": vertical_alignments[height_axis_index],
        "length_axis_index": length_axis_index,
        "length_axis": axes[length_axis_index],
        "width_axis_index": width_axis_index,
        "width_axis": axes[width_axis_index],
    }


def summarize_planar_region(
    face_indices: list[int],
    face_centers: np.ndarray,
    face_normals: np.ndarray,
    face_areas: np.ndarray,
    total_area: float,
) -> dict[str, Any]:
    region_centers = face_centers[face_indices]
    region_normals = face_normals[face_indices]
    region_areas = face_areas[face_indices]
    region_area = float(region_areas.sum())

    centroid = safe_average_vectors(region_centers, region_areas)
    average_normal = normalize_vector(safe_average_vectors(region_normals, region_areas))

    if len(face_indices) >= 3:
        centered_points = region_centers - centroid
        _, _, vh = np.linalg.svd(centered_points, full_matrices=False)
        plane_normal = normalize_vector(vh[-1])
        if np.dot(plane_normal, average_normal) < 0.0:
            plane_normal *= -1.0
    else:
        plane_normal = average_normal

    plane_distances = np.abs((region_centers - centroid) @ plane_normal)
    surface_orientation, tilt_degrees = classify_surface_orientation(plane_normal)

    return {
        "face_indices": sorted(int(index) for index in face_indices),
        "face_count": len(face_indices),
        "area": round_number(region_area),
        "area_ratio": round_number(safe_ratio(region_area, total_area)),
        "average_normal": round_vector(average_normal),
        "plane_normal": round_vector(plane_normal),
        "centroid": round_vector(centroid),
        "max_plane_distance": round_number(float(plane_distances.max()) if len(plane_distances) else 0.0),
        "orientation": surface_orientation,
        "tilt_from_vertical_degrees": tilt_degrees,
    }


def build_planar_regions(mesh: trimesh.Trimesh) -> list[dict[str, Any]]:
    face_count = len(mesh.faces)
    if face_count == 0:
        return []

    face_normals = np.asarray(mesh.face_normals, dtype=float)
    face_centers = np.asarray(mesh.triangles_center, dtype=float)
    face_areas = np.asarray(mesh.area_faces, dtype=float)
    valid_face_mask = np.isfinite(face_areas) & (face_areas > EPSILON)
    if not bool(valid_face_mask.any()):
        return []
    total_area = float(mesh.area) if mesh.area > EPSILON else float(face_areas[valid_face_mask].sum())

    adjacency_map: dict[int, list[int]] = defaultdict(list)
    for first_face, second_face in np.asarray(mesh.face_adjacency, dtype=int):
        adjacency_map[int(first_face)].append(int(second_face))
        adjacency_map[int(second_face)].append(int(first_face))

    distance_tolerance = max(float(np.max(mesh.extents)) * PLANAR_DISTANCE_RATIO, EPSILON)
    visited = np.logical_not(valid_face_mask)
    clusters: list[dict[str, Any]] = []

    for start_face in range(face_count):
        if visited[start_face]:
            continue

        reference_normal = normalize_vector(face_normals[start_face])
        reference_point = face_centers[start_face]
        stack = [start_face]
        visited[start_face] = True
        members: list[int] = []

        while stack:
            current_face = stack.pop()
            members.append(current_face)

            for neighbor_face in adjacency_map.get(current_face, []):
                if visited[neighbor_face]:
                    continue
                if not valid_face_mask[neighbor_face]:
                    visited[neighbor_face] = True
                    continue

                normal_angle = angle_between_vectors(face_normals[neighbor_face], reference_normal)
                if normal_angle > PLANAR_CLUSTER_NORMAL_DEGREES:
                    continue

                plane_offset = abs(float(np.dot(reference_normal, face_centers[neighbor_face] - reference_point)))
                if plane_offset > distance_tolerance:
                    continue

                visited[neighbor_face] = True
                stack.append(neighbor_face)

        clusters.append(
            summarize_planar_region(
                face_indices=members,
                face_centers=face_centers,
                face_normals=face_normals,
                face_areas=face_areas,
                total_area=total_area,
            )
        )

    clusters.sort(key=lambda region: region["area"] or 0.0, reverse=True)
    for index, cluster in enumerate(clusters, start=1):
        cluster["id"] = index

    return clusters


def major_planar_regions(planar_regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        region
        for region in planar_regions
        if (region.get("area_ratio") or 0.0) >= MAJOR_PLANAR_REGION_RATIO
    ]


def box_like_normals(planar_regions: list[dict[str, Any]], principal_axes: np.ndarray) -> bool:
    represented_axes: set[int] = set()

    for region in planar_regions:
        normal = np.asarray(region["plane_normal"], dtype=float)
        alignments = [abs(float(np.dot(normalize_vector(normal), axis))) for axis in principal_axes]
        best_axis = int(np.argmax(alignments))
        if alignments[best_axis] < BOX_NORMAL_ALIGNMENT:
            return False
        represented_axes.add(best_axis)

    return len(represented_axes) >= 3


def compute_shape_features(
    mesh: trimesh.Trimesh,
    principal_frame: dict[str, Any],
    planar_regions: list[dict[str, Any]],
) -> dict[str, Any]:
    extents = np.asarray(principal_frame["extents"], dtype=float)
    centroid = np.asarray(principal_frame["centroid"], dtype=float)
    dominant_axis = np.asarray(principal_frame["axes"][0], dtype=float)

    length = float(extents[0])
    width = float(extents[1])
    height = float(extents[2])

    vertices = np.asarray(mesh.vertices, dtype=float)
    centered_vertices = vertices - centroid
    radial_distances = np.linalg.norm(centered_vertices, axis=1)

    axis_projection = np.outer(centered_vertices @ dominant_axis, dominant_axis)
    axis_radial_vectors = centered_vertices - axis_projection
    axis_radial_distances = np.linalg.norm(axis_radial_vectors, axis=1)

    adjacency_angles = np.degrees(mesh.face_adjacency_angles)
    curvature_mean = float(adjacency_angles.mean()) if len(adjacency_angles) else 0.0
    curvature_std = float(adjacency_angles.std()) if len(adjacency_angles) else 0.0

    major_regions = major_planar_regions(planar_regions)
    major_region_coverage = sum(region["area_ratio"] or 0.0 for region in major_regions)

    return {
        "length": length,
        "width": width,
        "height": height,
        "thickness": min(length, width, height),
        "aspect_ratio": safe_ratio(length, max(height, EPSILON)),
        "flatness_ratio": safe_ratio(height, max(length, EPSILON)),
        "secondary_axis_similarity": safe_ratio(abs(width - height), max(width, EPSILON)),
        "spherical_extent_ratio": safe_ratio(height, max(length, EPSILON)),
        "centroid_radius_cv": safe_ratio(float(radial_distances.std()), max(float(radial_distances.mean()), EPSILON)),
        "axis_radius_cv": safe_ratio(
            float(axis_radial_distances.std()),
            max(float(axis_radial_distances.mean()), EPSILON),
        ),
        "major_planar_region_count": len(major_regions),
        "major_planar_area_ratio": major_region_coverage,
        "mean_face_adjacency_angle_degrees": curvature_mean,
        "std_face_adjacency_angle_degrees": curvature_std,
    }


def detect_shape(
    mesh: trimesh.Trimesh,
    principal_frame: dict[str, Any],
    planar_regions: list[dict[str, Any]],
    shape_features: dict[str, Any],
) -> str:
    if (
        shape_features["flatness_ratio"] <= FLAT_PANEL_THICKNESS_RATIO
        and shape_features["major_planar_region_count"] >= 2
        and shape_features["major_planar_area_ratio"] >= 0.6
    ):
        return "flat panel"

    if (
        mesh.is_volume
        and shape_features["spherical_extent_ratio"] >= SPHERE_EXTENT_RATIO
        and shape_features["centroid_radius_cv"] <= SPHERE_RADIUS_CV
    ):
        return "sphere"

    if (
        mesh.is_volume
        and shape_features["secondary_axis_similarity"] <= CYLINDER_SECONDARY_RATIO
        and shape_features["centroid_radius_cv"] <= CYLINDER_RADIUS_CV
        and shape_features["spherical_extent_ratio"] < SPHERE_EXTENT_RATIO
        and shape_features["major_planar_region_count"] <= 4
    ):
        if shape_features["major_planar_area_ratio"] < 0.2:
            return "capsule"
        return "cylinder"

    major_regions = major_planar_regions(planar_regions)
    if (
        len(major_regions) >= 4
        and shape_features["major_planar_area_ratio"] >= 0.75
        and box_like_normals(major_regions, np.asarray(principal_frame["axes"], dtype=float))
    ):
        return "box"

    return "irregular"


def detect_orientation(
    shape: str,
    principal_frame: dict[str, Any],
    semantic_dimensions: dict[str, Any],
) -> dict[str, Any]:
    axes = np.asarray(principal_frame["axes"], dtype=float)

    if shape == "flat panel":
        reference_axis = axes[2]
        orientation, tilt_degrees = classify_surface_orientation(reference_axis)
        reference_name = "panel_normal"
    elif shape == "box":
        reference_axis = np.asarray(semantic_dimensions["height_axis"], dtype=float)
        tilt_degrees = round_number(
            math.degrees(
                math.acos(
                    np.clip(float(abs(np.dot(normalize_vector(reference_axis), np.array([0.0, 0.0, 1.0])))), 0.0, 1.0)
                )
            )
        ) or 0.0
        if semantic_dimensions["height"] > max(semantic_dimensions["length"], semantic_dimensions["width"]):
            orientation = "vertical"
        else:
            orientation = "horizontal"
        reference_name = "height_axis"
    else:
        reference_axis = axes[0]
        orientation, tilt_degrees = classify_axis_tilt(reference_axis)
        reference_name = "dominant_axis"

    return {
        "classification": orientation,
        "reference_axis_name": reference_name,
        "reference_axis_vector": round_vector(reference_axis),
        "tilt_from_vertical_degrees": tilt_degrees,
    }


def assign_semantics(
    shape: str,
    orientation: str,
    shape_features: dict[str, Any],
    semantic_dimensions: dict[str, Any],
) -> tuple[str, str]:
    length = semantic_dimensions["length"]
    width = semantic_dimensions["width"]
    height = semantic_dimensions["height"]

    if shape == "flat panel":
        if orientation == "horizontal":
            return "platform", "platform"
        if orientation == "vertical":
            return "panel", "display_surface"
        return "panel", "unknown"

    if shape == "cylinder":
        if orientation == "vertical":
            return "pillar", "pillar"
        if orientation == "horizontal":
            return "beam", "beam"
        return "unknown", "unknown"

    if shape == "box":
        if height < min(length, width) * 0.2:
            return "platform", "platform"

        if height > max(length, width) * 1.5:
            return "pillar", "pillar"

        if length > width * 2.0 and length > height * 2.0:
            return "beam", "beam"

        return "block", "structure"

    return "unknown", "unknown"


def build_mesh_measurements(mesh: trimesh.Trimesh) -> dict[str, Any]:
    bounds = mesh.bounds
    minimum = bounds[0]
    maximum = bounds[1]
    size = maximum - minimum
    volume = round_number(mesh.volume) if mesh.is_volume else None
    edges = build_edges(mesh)
    views = generate_orthographic_projections(mesh)

    return {
        "validation": {
            "is_valid_mesh": True,
            "is_watertight": bool(mesh.is_watertight),
            "is_winding_consistent": bool(mesh.is_winding_consistent),
            "is_volume": bool(mesh.is_volume),
            "vertex_count": int(len(mesh.vertices)),
            "edge_count": int(len(edges)),
            "feature_edge_count": int(sum(1 for edge in edges if edge["is_feature_edge"])),
            "face_count": int(len(mesh.faces)),
        },
        "overall_dimensions": {
            "x": round_number(size[0]),
            "y": round_number(size[1]),
            "z": round_number(size[2]),
            "length": round_number(size[0]),
            "width": round_number(size[1]),
            "height": round_number(size[2]),
        },
        "bounding_box": {
            "min": round_vector(minimum),
            "max": round_vector(maximum),
            "size": round_vector(size),
            "centroid": round_vector(mesh.bounding_box.centroid),
            "extents_diagonal": round_number(np.linalg.norm(size)),
        },
        "mesh_metrics": {
            "surface_area": round_number(mesh.area),
            "volume": volume,
            "center_of_mass": round_vector(safe_mesh_center_of_mass(mesh)),
            "mesh_centroid": round_vector(safe_mesh_centroid(mesh)),
        },
        "vertices": build_vertices(mesh),
        "edges": edges,
        "faces": build_faces(mesh),
        "views": views,
    }


def build_component_record(component_id: int, mesh: trimesh.Trimesh, source_name: str) -> dict[str, Any]:
    principal_frame = compute_principal_frame(mesh)
    semantic_dimensions = compute_semantic_dimensions(principal_frame)
    planar_regions = build_planar_regions(mesh)
    shape_features = compute_shape_features(mesh, principal_frame, planar_regions)
    shape = detect_shape(mesh, principal_frame, planar_regions, shape_features)
    orientation = detect_orientation(shape, principal_frame, semantic_dimensions)
    component_type, semantic_role = assign_semantics(
        shape=shape,
        orientation=orientation["classification"],
        shape_features=shape_features,
        semantic_dimensions=semantic_dimensions,
    )

    measurements = build_mesh_measurements(mesh)
    oriented_extents = np.asarray(principal_frame["extents"], dtype=float)
    dominant_axis = np.asarray(principal_frame["axes"][0], dtype=float)
    _, dominant_axis_tilt = classify_axis_tilt(dominant_axis)
    semantic_length = semantic_dimensions["length"]
    semantic_width = semantic_dimensions["width"]
    semantic_height = semantic_dimensions["height"]
    semantic_aspect_ratio = safe_ratio(semantic_length, max(semantic_width, EPSILON))
    height_to_length_ratio = safe_ratio(semantic_height, max(semantic_length, EPSILON))

    fabrication_flags = []
    geometry_primitives = []
    component_orientation = orientation["classification"]

    if shape in ("cylinder", "capsule"):
        geometry_primitives.extend(["CIRCLE", "ARC", "LINE"])
        if component_orientation == "angled":
            if shape == "cylinder":
                fabrication_flags.append("manual_review_required")
            fabrication_flags.append("non_standard_orientation")
    elif shape == "flat panel":
        geometry_primitives.extend(["POLYLINE", "LINE"])
        # A flat panel that is angled (not plumb vertical or flat horizontal) needs review.
        # threshold logic:
        #   alignment >= 0.95  => within ~18° of horizontal  (truly flat)
        #   alignment <= 0.10  => within ~6°  of vertical    (truly plumb wall)
        #   anything between   => angled, flag for review
        panel_normal = np.asarray(principal_frame["axes"][2], dtype=float)
        vertical = np.array([0.0, 0.0, 1.0], dtype=float)
        alignment = abs(float(np.dot(normalize_vector(panel_normal), vertical)))
        tilt_deg = round(math.degrees(math.acos(min(alignment, 1.0))), 1)
        if not (alignment >= 0.95 or alignment <= 0.10):
            fabrication_flags.append("angled_panel")
            fabrication_flags.append(f"tilt_{tilt_deg}deg")
            fabrication_flags.append("approximate_profile")
    elif shape == "box":
        geometry_primitives.extend(["RECTANGLE", "LINE"])
    elif shape in ("sphere", "irregular"):
        geometry_primitives.extend(["POLYLINE"])
        fabrication_flags.append("manual_review_required")
        fabrication_flags.append("approximate_profile")

    if shape == "irregular" and not bool(mesh.is_watertight):
        fabrication_flags.append("non_planar_part")

    # Expose straight constraints for cylindrical/capsule parts
    diameter = None
    radius = None
    straight_length = None
    if shape in ("cylinder", "capsule"):
        diameter = round_number(min(semantic_length, semantic_width))
        radius = round_number(diameter / 2.0) if diameter is not None else None
        straight_length = semantic_length
        if shape == "capsule" and radius is not None:
            # Total length = straight_length + 2 * radius
            straight_length = max(0.0, semantic_length - 2.0 * radius)

    return {
        "id": component_id,
        "source_name": source_name,
        "type": component_type,
        "shape": shape,
        "shape_family": shape,
        "orientation": orientation["classification"],
        "semantic_role": semantic_role,
        "geometry_primitives": geometry_primitives,
        "fabrication": {
            "flags": fabrication_flags,
            "manual_review_required": "manual_review_required" in fabrication_flags
        },
        "dimensions": {
            "length": round_number(semantic_length),
            "width": round_number(semantic_width),
            "height": round_number(semantic_height),
            "thickness": round_number(min(semantic_length, semantic_width, semantic_height)),
            "diameter": diameter,
            "radius": radius,
            "straight_length": round_number(straight_length) if straight_length is not None else None,
            "aspect_ratio": round_number(semantic_aspect_ratio),
            "height_to_length_ratio": round_number(height_to_length_ratio),
            "axis_aligned_size": measurements["bounding_box"]["size"],
        },
        "dominant_axis": {
            "vector": round_vector(dominant_axis),
            "tilt_from_vertical_degrees": dominant_axis_tilt,
        },
        "orientation_reference": {
            "axis_name": orientation["reference_axis_name"],
            "axis_vector": orientation["reference_axis_vector"],
            "tilt_from_vertical_degrees": orientation["tilt_from_vertical_degrees"],
        },
        "oriented_frame": {
            "centroid": round_vector(principal_frame["centroid"]),
            "axes": {
                "length_axis": round_vector(semantic_dimensions["length_axis"]),
                "width_axis": round_vector(semantic_dimensions["width_axis"]),
                "height_axis": round_vector(semantic_dimensions["height_axis"]),
            },
            "extents": {
                "length": round_number(semantic_length),
                "width": round_number(semantic_width),
                "height": round_number(semantic_height),
            },
            "principal_extents_sorted": round_vector(oriented_extents),
        },
        "analysis": {
            "major_planar_region_count": int(shape_features["major_planar_region_count"]),
            "major_planar_area_ratio": round_number(shape_features["major_planar_area_ratio"]),
            "flatness_ratio": round_number(shape_features["flatness_ratio"]),
            "secondary_axis_similarity": round_number(shape_features["secondary_axis_similarity"]),
            "spherical_extent_ratio": round_number(shape_features["spherical_extent_ratio"]),
            "centroid_radius_cv": round_number(shape_features["centroid_radius_cv"]),
            "axis_radius_cv": round_number(shape_features["axis_radius_cv"]),
            "mean_face_adjacency_angle_degrees": round_number(
                shape_features["mean_face_adjacency_angle_degrees"]
            ),
            "std_face_adjacency_angle_degrees": round_number(
                shape_features["std_face_adjacency_angle_degrees"]
            ),
            "semantic_height_axis_alignment": round_number(semantic_dimensions["height_axis_alignment"]),
        },
        "vertices": measurements["vertices"],
        "edges": measurements["edges"],
        "planar_regions": planar_regions,
        "faces": measurements["faces"],
        "geometry": {
            "validation": measurements["validation"],
            "bounding_box": measurements["bounding_box"],
            "mesh_metrics": measurements["mesh_metrics"],
            "views": measurements["views"],
        },
    }


def summarize_components(components: list[dict[str, Any]]) -> dict[str, Any]:
    shape_counts = Counter(component["shape"] for component in components)
    type_counts = Counter(component["type"] for component in components)
    orientation_counts = Counter(component["orientation"] for component in components)

    return {
        "component_count": len(components),
        "shape_counts": dict(shape_counts),
        "type_counts": dict(type_counts),
        "orientation_counts": dict(orientation_counts),
    }


def extract_measurements(obj_path: str, source_unit: str = UNIT) -> dict[str, Any]:
    path = Path(obj_path).expanduser()
    mesh, mesh_source, named_meshes = load_mesh(path)
    source_unit_normalized = source_unit.strip().lower()
    mesh = scale_mesh_to_mm(mesh, source_unit_normalized)
    
    scaled_named_meshes = [
        (name, scale_mesh_to_mm(comp_mesh, source_unit_normalized))
        for name, comp_mesh in named_meshes
    ]
    unit_scale_to_mm = resolve_unit_scale(source_unit_normalized)

    payload = {
        "input": {
            "source_path": str(path.resolve()),
            "file_name": path.name,
            "mesh_name": path.stem,
            "file_type": path.suffix.lower().lstrip("."),
            "unit": UNIT,
            "source_unit": source_unit_normalized,
            "normalized_unit": UNIT,
            "unit_scale_to_mm": unit_scale_to_mm,
            "source_geometry": mesh_source,
        },
    }
    payload.update(build_mesh_measurements(mesh))

    components = [
        build_component_record(component_id=index, mesh=component_mesh, source_name=source_name)
        for index, (source_name, component_mesh) in enumerate(split_components(scaled_named_meshes), start=1)
    ]
    payload["component_summary"] = summarize_components(components)
    payload["components"] = components
    return payload


def normalize_obj_path_argument(path_parts: list[str]) -> Path:
    """Join CLI path tokens so unquoted OBJ paths with spaces still work."""
    return Path(" ".join(path_parts)).expanduser()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract measurement-ready geometric and semantic data from an OBJ mesh."
    )
    parser.add_argument("obj_path", nargs="+", help="Path to the Wavefront OBJ file to analyze.")
    parser.add_argument(
        "--source-unit",
        default=UNIT,
        choices=sorted(SOURCE_UNIT_SCALES.keys()),
        help="Source unit used in the OBJ file. Geometry is normalized to millimeters.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    obj_path = normalize_obj_path_argument(args.obj_path)

    try:
        payload = extract_measurements(str(obj_path), source_unit=args.source_unit)
        output_path = build_output_path(obj_path)
        write_payload_to_file(output_path, payload)
    except ExtractionError as exc:
        output_path = build_output_path(obj_path, suffix="_error.json")
        write_payload_to_file(
            output_path,
            build_error_payload(obj_path, exc.code, exc.message, source_unit=args.source_unit),
        )
        print(f"Saved error output to {output_path}")
        return 1
    except Exception as exc:  # pragma: no cover - unexpected runtime protection for CLI usage.
        output_path = build_output_path(obj_path, suffix="_error.json")
        write_payload_to_file(
            output_path,
            build_error_payload(
                obj_path,
                "unexpected_error",
                f"Unexpected error: {exc}",
                source_unit=args.source_unit,
            ),
        )
        print(f"Saved error output to {output_path}")
        return 1

    print(f"Saved analysis output to {output_path}")
    return 0
