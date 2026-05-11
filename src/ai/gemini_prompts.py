"""Prompt templates for Gemini booth component enrichment."""

from __future__ import annotations

import json


def build_component_analysis_prompt(component_manifest: dict) -> str:
    manifest_json = json.dumps(component_manifest, indent=2)
    return f"""You are analyzing an exhibition booth from OBJ geometry data and booth reference images.
The OBJ geometry engine has already extracted components and measurements.
Do not calculate exact measurements from images.
Do not invent dimensions.

Your job is to improve object understanding only:
- identify what each component likely is
- suggest better component names
- classify component category
- identify likely material or finish from photos
- identify visible notes such as edge-lit, laminate, fabric, wooden frame, logo panel
- mark uncertain components for manual review

Return strict JSON only.
Do not include markdown.
Do not include explanation outside JSON.

Input component manifest:
{manifest_json}

Return JSON in this exact structure:
{{
  "ai_analysis": {{
    "source": "gemini",
    "model": "gemini-2.5-flash",
    "summary": "short booth understanding summary",
    "components": [
      {{
        "component_id": "component_001",
        "suggested_name": "Luminy Frame",
        "category": "Frame",
        "likely_material": "Wood / Aluminum / Acrylic / Fabric / Laminate / Unknown",
        "finish": "White laminate / Fabric finish / Edge-lit / Painted / Unknown",
        "visual_description": "short description",
        "confidence": 0.0,
        "manual_review_required": true,
        "notes": [
          "Do not use image for exact measurement"
        ]
      }}
    ]
  }}
}}

Allowed categories:
- Luminy Frame
- Wooden Frame
- Wooden Arc Fascia
- Logo Panel
- Switch Board Panel
- Product Display
- Standard Wooden Post
- Blocking Panel
- Wall Panel
- Counter
- Table
- Fixture
- Unknown Component

Rules:
1. Measurements must come from OBJ geometry only.
2. If unsure, use "Unknown Component".
3. If confidence is below 0.6, manual_review_required must be true.
4. Do not rename components aggressively unless visual evidence is strong.
5. If a photo shows material/finish, add it.
6. For curved objects, add note: "Curved component detected visually. Verify radius from geometry."
"""
