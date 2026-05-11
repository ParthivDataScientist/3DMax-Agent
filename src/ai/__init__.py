"""Gemini AI enrichment helpers."""

__all__ = [
    "GeminiVisionClient",
    "apply_manifest_to_components",
    "build_component_analysis_prompt",
    "merge_ai_analysis",
]


def __getattr__(name: str):
    if name == "GeminiVisionClient":
        from .gemini_client import GeminiVisionClient

        return GeminiVisionClient
    if name == "build_component_analysis_prompt":
        from .gemini_prompts import build_component_analysis_prompt

        return build_component_analysis_prompt
    if name in {"apply_manifest_to_components", "merge_ai_analysis"}:
        from .fusion import apply_manifest_to_components, merge_ai_analysis

        return {
            "apply_manifest_to_components": apply_manifest_to_components,
            "merge_ai_analysis": merge_ai_analysis,
        }[name]
    raise AttributeError(name)
