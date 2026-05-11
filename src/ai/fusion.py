"""Merge Gemini understanding into geometry-based component manifests."""

from __future__ import annotations

from src.extraction.models import ExtractedComponent


def merge_ai_analysis(component_manifest: dict, ai_result: dict) -> dict:
    ai_components = {
        item.get("component_id"): item
        for item in ai_result.get("ai_analysis", {}).get("components", [])
        if item.get("component_id")
    }

    merged = dict(component_manifest)
    merged_components = list(merged.get("components", []))
    for component in merged_components:
        component_id = component.get("id")
        ai_item = ai_components.get(component_id)
        if not ai_item:
            continue

        component["ai"] = ai_item
        if ai_item.get("confidence") is not None:
            component["confidence"] = ai_item.get("confidence")
        if ai_item.get("confidence", 0.0) >= 0.6:
            component["name"] = ai_item.get("suggested_name") or component.get("name")
            component["category"] = ai_item.get("category") or component.get("category")
            component["material"] = ai_item.get("likely_material") or component.get("material")
            component["finish"] = ai_item.get("finish") or component.get("finish")

        component.setdefault("notes", [])
        existing_notes = list(component["notes"])
        for note in ai_item.get("notes", []):
            if note not in existing_notes:
                existing_notes.append(note)
        component["notes"] = existing_notes
        component["manual_review_required"] = bool(ai_item.get("manual_review_required", False))

    merged["components"] = merged_components
    merged["ai_enriched"] = True
    merged["ai_summary"] = ai_result.get("ai_analysis", {}).get("summary")
    return merged


def apply_manifest_to_components(components: list[ExtractedComponent], component_manifest: dict) -> list[ExtractedComponent]:
    by_id = {component.id: component for component in components}
    for item in component_manifest.get("components", []):
        component = by_id.get(item.get("id"))
        if component is None:
            continue

        component.name = item.get("name", component.name)
        component.category = item.get("category", component.category)
        component.material = item.get("material", component.material)
        component.finish = item.get("finish", component.finish)
        component.notes = list(item.get("notes", component.notes))
        component.manual_review_required = bool(item.get("manual_review_required", component.manual_review_required))
        component.ai = dict(item.get("ai", component.ai))

        confidence = item.get("confidence")
        if confidence is not None:
            try:
                component.confidence = float(confidence)
            except (TypeError, ValueError):
                pass

    return components
