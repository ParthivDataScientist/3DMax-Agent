"""Orthographic projection helpers for mesh-based drawing generation."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np
import trimesh


EPSILON = 1e-9
CLASSIFICATION_PRIORITY = {
    "silhouette": 0,
    "sharp": 1,
    "boundary": 2,
}
VIEW_DEFINITIONS: dict[str, dict[str, Any]] = {
    "front": {
        "plane": "XZ",
        "horizontal_axis": "x",
        "vertical_axis": "z",
        "depth_axis": "y",
        "coordinate_indices": (0, 2),
        "view_direction": np.array([0.0, 1.0, 0.0], dtype=float),
    },
    "top": {
        "plane": "XY",
        "horizontal_axis": "x",
        "vertical_axis": "y",
        "depth_axis": "z",
        "coordinate_indices": (0, 1),
        "view_direction": np.array([0.0, 0.0, 1.0], dtype=float),
    },
    "side": {
        "plane": "YZ",
        "horizontal_axis": "y",
        "vertical_axis": "z",
        "depth_axis": "x",
        "coordinate_indices": (1, 2),
        "view_direction": np.array([1.0, 0.0, 0.0], dtype=float),
    },
}


def round_number(value: float | None, precision: int = 6) -> float | None:
    """Round finite numbers to a stable JSON-friendly precision."""
    if value is None:
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return round(numeric, precision)


def round_vector(values: np.ndarray, precision: int = 6) -> list[float | None]:
    """Convert a numeric vector to a rounded Python list."""
    return [round_number(float(value), precision) for value in np.asarray(values, dtype=float)]


def project_points(points: np.ndarray, view_name: str) -> np.ndarray:
    """Project 3D points into the 2D plane of a standard orthographic view."""
    definition = VIEW_DEFINITIONS[view_name]
    return np.asarray(points, dtype=float)[:, definition["coordinate_indices"]]


def normalize_projected_points(points_2d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Shift a set of 2D points into the positive quadrant."""
    points = np.asarray(points_2d, dtype=float)
    if len(points) == 0:
        return np.zeros((0, 2), dtype=float), np.zeros(2, dtype=float)

    minimum = points.min(axis=0)
    return points - minimum, minimum


def segment_key(first: np.ndarray, second: np.ndarray, precision: int) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    """Create a stable undirected 2D segment key."""
    first_key = tuple(round_vector(first, precision))
    second_key = tuple(round_vector(second, precision))
    return tuple(sorted((first_key, second_key)))


def group_segments_into_entities(edges: list[dict[str, Any]], precision: int, epsilon: float) -> list[dict[str, Any]]:
    adj = defaultdict(list)
    for i, edge in enumerate(edges):
        s = tuple(edge["start"])
        e = tuple(edge["end"])
        adj[s].append((e, i))
        adj[e].append((s, i))

    visited_edges = set()
    entities = []

    for i, edge in enumerate(edges):
        if i in visited_edges:
            continue

        path_points = [tuple(edge["start"]), tuple(edge["end"])]
        visited_edges.add(i)

        while True:
            cur = path_points[-1]
            candidates = [nxt for nxt in adj[cur] if nxt[1] not in visited_edges]
            if len(candidates) != 1:
                break
            nxt_pt, nxt_edge_idx = candidates[0]
            visited_edges.add(nxt_edge_idx)
            path_points.append(nxt_pt)
            if nxt_pt == path_points[0]:
                break

        if path_points[0] != path_points[-1]:
            while True:
                cur = path_points[0]
                candidates = [nxt for nxt in adj[cur] if nxt[1] not in visited_edges]
                if len(candidates) != 1:
                    break
                nxt_pt, nxt_edge_idx = candidates[0]
                visited_edges.add(nxt_edge_idx)
                path_points.insert(0, nxt_pt)
                if nxt_pt == path_points[-1]:
                    break

        is_closed = (path_points[0] == path_points[-1])
        points_np = np.array(path_points)
        is_circle = False

        if is_closed and len(path_points) > 8:
            centroid = points_np[:-1].mean(axis=0)
            radii = np.linalg.norm(points_np[:-1] - centroid, axis=1)
            mean_r = float(radii.mean())
            if mean_r > epsilon and (radii.std() / mean_r) < 0.05:
                is_circle = True
                entities.append({
                    "type": "CIRCLE",
                    "center": round_vector(centroid, precision),
                    "radius": round_number(mean_r, precision),
                })

        if not is_circle:
             if len(path_points) == 2:
                 entities.append({
                     "type": "LINE",
                     "start": round_vector(path_points[0], precision),
                     "end": round_vector(path_points[1], precision),
                 })
             else:
                 entities.append({
                     "type": "LWPOLYLINE",
                     "points": [round_vector(pt, precision) for pt in (path_points[:-1] if is_closed else path_points)],
                     "closed": is_closed,
                 })

    return entities


def build_projected_view(
    mesh: trimesh.Trimesh,
    edge_records: list[dict[str, Any]],
    view_name: str,
    *,
    precision: int = 6,
    epsilon: float = EPSILON,
) -> dict[str, Any]:
    """Project vertices and visible edges for one orthographic view."""
    if view_name not in VIEW_DEFINITIONS:
        raise KeyError(f"Unsupported orthographic view: {view_name}")

    definition = VIEW_DEFINITIONS[view_name]
    vertices_3d = np.asarray(mesh.vertices, dtype=float)
    projected_vertices = project_points(vertices_3d, view_name)
    normalized_vertices, _ = normalize_projected_points(projected_vertices)

    if len(normalized_vertices) == 0:
        max_corner = np.zeros(2, dtype=float)
    else:
        max_corner = normalized_vertices.max(axis=0)

    deduplicated_edges: dict[
        tuple[tuple[float | None, float | None], tuple[float | None, float | None]],
        dict[str, Any],
    ] = {}

    for record in edge_records:
        first_index, second_index = [int(value) for value in record["vertex_indices"]]
        first_point = normalized_vertices[first_index]
        second_point = normalized_vertices[second_index]

        if np.linalg.norm(second_point - first_point) <= epsilon:
            continue

        key = segment_key(first_point, second_point, precision)
        segment_record = {
            "start": round_vector(first_point, precision),
            "end": round_vector(second_point, precision),
            "vertex_indices": [first_index, second_index],
            "classification": record["classification"],
        }

        existing = deduplicated_edges.get(key)
        if existing is None or CLASSIFICATION_PRIORITY[segment_record["classification"]] > CLASSIFICATION_PRIORITY[existing["classification"]]:
            deduplicated_edges[key] = segment_record

    return {
        "plane": definition["plane"],
        "horizontal_axis": definition["horizontal_axis"],
        "vertical_axis": definition["vertical_axis"],
        "depth_axis": definition["depth_axis"],
        "projected_vertices": [
            {
                "index": int(index),
                "coordinates": round_vector(point, precision),
            }
            for index, point in enumerate(normalized_vertices)
        ],
        "edges": [
            deduplicated_edges[key]
            for key in sorted(deduplicated_edges)
        ],
        "entities": group_segments_into_entities(
            [deduplicated_edges[key] for key in sorted(deduplicated_edges)],
            precision,
            epsilon
        ),
        "bounds_2d": {
            "min": [0.0, 0.0],
            "max": round_vector(max_corner, precision),
            "size": round_vector(max_corner, precision),
        },
    }
