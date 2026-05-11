"""Data models for extracted booth components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


def _round_mm(value: float) -> float:
    return round(float(value), 3)


@dataclass
class ComponentDimensions:
    width: float
    height: float
    depth: float
    unit: str = "mm"

    def as_dict(self) -> dict[str, float | str]:
        return {
            "width": _round_mm(self.width),
            "height": _round_mm(self.height),
            "depth": _round_mm(self.depth),
            "unit": self.unit,
        }


@dataclass
class BoundingBox3D:
    minimum: list[float]
    maximum: list[float]

    def as_dict(self) -> dict[str, list[float]]:
        return {
            "min": [_round_mm(value) for value in self.minimum],
            "max": [_round_mm(value) for value in self.maximum],
        }


@dataclass
class ComponentInstance:
    id: str
    mesh_id: str
    source_label: str
    original_name: Optional[str]
    object_name: Optional[str]
    group_name: Optional[str]
    material_name: Optional[str]
    name: str
    category: str
    confidence: float
    quantity: int
    dimensions: ComponentDimensions
    bounding_box: BoundingBox3D
    mesh_ids: list[str]
    material: Optional[str] = None
    finish: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    manual_review_required: bool = False
    shape: str = "unknown"
    orientation: str = "unknown"
    classification_key: str = "unknown"
    ai: dict[str, Any] = field(default_factory=dict)
    luminy_validation: dict[str, Any] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mesh_id": self.mesh_id,
            "source_label": self.source_label,
            "original_name": self.original_name,
            "object_name": self.object_name,
            "group_name": self.group_name,
            "material_name": self.material_name,
            "name": self.name,
            "category": self.category,
            "confidence": round(float(self.confidence), 4),
            "quantity": self.quantity,
            "dimensions": self.dimensions.as_dict(),
            "bounding_box": self.bounding_box.as_dict(),
            "mesh_ids": list(self.mesh_ids),
            "material": self.material,
            "finish": self.finish,
            "notes": list(self.notes),
            "manual_review_required": self.manual_review_required,
            "shape": self.shape,
            "orientation": self.orientation,
            "classification_key": self.classification_key,
            "ai": dict(self.ai),
            "luminy_validation": dict(self.luminy_validation),
        }


@dataclass
class ExtractedComponent:
    id: str
    index: int
    name: str
    original_name: Optional[str]
    category: str
    confidence: float
    quantity: int
    dimensions: ComponentDimensions
    bounding_box: BoundingBox3D
    mesh_ids: list[str]
    instance_ids: list[str]
    source_object_names: list[str]
    source_group_names: list[str]
    material: Optional[str] = None
    finish: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    manual_review_required: bool = False
    shape: str = "unknown"
    orientation: str = "unknown"
    classification_key: str = "unknown"
    representative_instance_id: Optional[str] = None
    ai: dict[str, Any] = field(default_factory=dict)
    luminy_validation: dict[str, Any] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index,
            "name": self.name,
            "original_name": self.original_name,
            "category": self.category,
            "confidence": round(float(self.confidence), 4),
            "quantity": self.quantity,
            "dimensions": self.dimensions.as_dict(),
            "bounding_box": self.bounding_box.as_dict(),
            "mesh_ids": list(self.mesh_ids),
            "instance_ids": list(self.instance_ids),
            "source_object_names": list(self.source_object_names),
            "source_group_names": list(self.source_group_names),
            "material": self.material,
            "finish": self.finish,
            "notes": list(self.notes),
            "manual_review_required": self.manual_review_required,
            "shape": self.shape,
            "orientation": self.orientation,
            "classification_key": self.classification_key,
            "representative_instance_id": self.representative_instance_id,
            "ai": dict(self.ai),
            "luminy_validation": dict(self.luminy_validation),
        }
