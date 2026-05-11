"""Gemini multimodal client for booth understanding."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv


class GeminiVisionClient:
    """Thin wrapper around the official Gemini Python SDK."""

    def __init__(self) -> None:
        load_dotenv()
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY missing. Add it to .env")

        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on optional install path.
            raise RuntimeError(
                "google-genai is not installed. Add it to requirements and install dependencies."
            ) from exc

        self._genai = genai
        self.client = genai.Client(api_key=self.api_key)

    @staticmethod
    def _clean_json_response(raw_text: str) -> str:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        return cleaned

    def _load_images(self, image_paths: list[str]) -> tuple[list[object], list[str]]:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - depends on optional install path.
            raise RuntimeError("Pillow is not installed. Add it to requirements and install dependencies.") from exc

        images: list[object] = []
        warnings: list[str] = []
        for image_path in image_paths:
            path = Path(image_path).expanduser()
            if not path.exists():
                warnings.append(f"Warning: Gemini image path does not exist and was skipped: {path}")
                continue
            try:
                with Image.open(path) as image:
                    images.append(image.copy())
            except Exception as exc:
                warnings.append(f"Warning: Gemini image could not be opened and was skipped: {path} ({exc})")
        return images, warnings

    def analyze_components(self, prompt: str, image_paths: list[str]) -> tuple[dict, list[str]]:
        contents: list[object] = [prompt]
        images, warnings = self._load_images(image_paths)
        contents.extend(images)

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
            )
        except Exception as exc:  # pragma: no cover - network/runtime dependent.
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc

        raw_text = (getattr(response, "text", "") or "").strip()
        if not raw_text:
            raise RuntimeError("Gemini returned an empty response.")

        cleaned = self._clean_json_response(raw_text)
        try:
            return json.loads(cleaned), warnings
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Gemini returned non-JSON output: {exc}") from exc
