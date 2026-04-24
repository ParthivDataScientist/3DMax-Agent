"""Mesh edge classification helpers for orthographic drawing generation."""

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


def round_number(value: float | None, precision: int = 6) -> float | None:
    """Round finite numbers to a stable JSON-friendly precision."""
    if value is None:
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return round(numeric, precision)


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    """Return a unit vector or zero vector for degenerate input."""
    norm = np.linalg.norm(vector)
    if norm <= EPSILON:
        return np.zeros_like(vector, dtype=float)
    return np.asarray(vector, dtype=float) / norm


def edge_key(first: int, second: int) -> tuple[int, int]:
    """Create a stable undirected edge key."""
    return tuple(sorted((int(first), int(second))))


def build_edge_to_faces(mesh: trimesh.Trimesh) -> dict[tuple[int, int], list[int]]:
    """Map each unique triangle edge to its adjacent faces."""
    edge_to_faces: dict[tuple[int, int], list[int]] = defaultdict(list)
    for face_index, face in enumerate(np.asarray(mesh.faces, dtype=int)):
        for start_index in range(len(face)):
            first = int(face[start_index])
            second = int(face[(start_index + 1) % len(face)])
            edge_to_faces[edge_key(first, second)].append(int(face_index))
    return edge_to_faces


def extract_candidate_edges(
    mesh: trimesh.Trimesh,
    feature_angle_degrees: float,
    *,
    precision: int = 6,
) -> list[dict[str, Any]]:
    """Classify mesh unique edges as boundary or sharp candidates."""
    unique_edges = np.asarray(mesh.edges_unique, dtype=int)
    if len(unique_edges) == 0:
        return []

    face_normals = np.asarray(mesh.face_normals, dtype=float)
    edge_faces = build_edge_to_faces(mesh)
    records: list[dict[str, Any]] = []

    for index, edge in enumerate(unique_edges):
        first = int(edge[0])
        second = int(edge[1])
        key = edge_key(first, second)
        adjacent_faces = sorted(edge_faces.get(key, []))
        adjacent_face_count = len(adjacent_faces)
        adjacent_face_angle_degrees: float | None = None
        is_boundary = adjacent_face_count == 1
        is_sharp = False

        if adjacent_face_count >= 2:
            first_normal = normalize_vector(face_normals[adjacent_faces[0]])
            second_normal = normalize_vector(face_normals[adjacent_faces[1]])
            dot_product = float(np.clip(np.dot(first_normal, second_normal), -1.0, 1.0))
            adjacent_face_angle_degrees = math.degrees(math.acos(dot_product))
            is_sharp = adjacent_face_angle_degrees > feature_angle_degrees

        records.append(
            {
                "index": index,
                "vertex_indices": [first, second],
                "adjacent_face_count": adjacent_face_count,
                "adjacent_face_indices": adjacent_faces,
                "adjacent_face_angle_degrees": round_number(adjacent_face_angle_degrees, precision),
                "is_boundary": is_boundary,
                "is_sharp": is_sharp,
            }
        )

    return records


def extract_silhouette_edges(
    mesh: trimesh.Trimesh,
    view_direction: np.ndarray | tuple[float, float, float],
    *,
    epsilon: float = EPSILON,
) -> set[tuple[int, int]]:
    """Find view-dependent silhouette edges from opposing adjacent face normals."""
    face_adjacency = np.asarray(mesh.face_adjacency, dtype=int)
    adjacency_edges = np.asarray(mesh.face_adjacency_edges, dtype=int)
    face_normals = np.asarray(mesh.face_normals, dtype=float)
    normalized_view_direction = normalize_vector(np.asarray(view_direction, dtype=float))

    silhouettes: set[tuple[int, int]] = set()
    for (first_face, second_face), edge in zip(face_adjacency, adjacency_edges):
        first_dot = float(np.dot(face_normals[int(first_face)], normalized_view_direction))
        second_dot = float(np.dot(face_normals[int(second_face)], normalized_view_direction))
        if first_dot * second_dot < -(epsilon * epsilon):
            silhouettes.add(edge_key(int(edge[0]), int(edge[1])))

    return silhouettes


def select_visible_edges(
    candidate_edges: list[dict[str, Any]],
    silhouette_edges: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Combine boundary, sharp, and silhouette classifications per view."""
    visible: dict[tuple[int, int], dict[str, Any]] = {}

    for record in candidate_edges:
        key = edge_key(*record["vertex_indices"])
        classification: str | None = None
        if record["is_boundary"]:
            classification = "boundary"
        elif record["is_sharp"]:
            classification = "sharp"

        if classification is None:
            continue

        visible[key] = {
            "vertex_indices": [key[0], key[1]],
            "classification": classification,
        }

    for key in silhouette_edges:
        existing = visible.get(key)
        if existing is None or CLASSIFICATION_PRIORITY["silhouette"] > CLASSIFICATION_PRIORITY[existing["classification"]]:
            visible[key] = {
                "vertex_indices": [key[0], key[1]],
                "classification": "silhouette",
            }

    return [
        visible[key]
        for key in sorted(visible)
    ]
