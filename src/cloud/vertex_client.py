"""Vertex AI / Gemini client for multi-modal generation."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from google import genai
from google.genai import types

from config.settings import Settings

logger = structlog.get_logger(__name__)


class VertexGeminiClient:
    """Wraps Gemini via the google-genai SDK on Vertex AI."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.gemini_model
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(
                vertexai=True,
                project=self.settings.gcp_project_id,
                location=self.settings.vertex_ai_location,
            )
        return self._client

    def generate(
        self,
        system_instruction: str,
        user_content: str | list[Any],
        temperature: float = 0.3,
        response_mime_type: str | None = "application/json",
    ) -> tuple[str, dict[str, Any]]:
        """Generate content and return (text, usage_metadata)."""
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )
        if response_mime_type:
            config.response_mime_type = response_mime_type

        response = self.client.models.generate_content(
            model=self.model,
            contents=user_content,
            config=config,
        )

        text = response.text or ""
        usage: dict[str, Any] = {}
        if response.usage_metadata:
            usage = {
                "prompt_token_count": response.usage_metadata.prompt_token_count,
                "candidates_token_count": response.usage_metadata.candidates_token_count,
                "total_token_count": response.usage_metadata.total_token_count,
            }

        logger.info("gemini_generation_complete", model=self.model, usage=usage)
        return text, usage

    def generate_multimodal(
        self,
        system_instruction: str,
        parts: list[Any],
        temperature: float = 0.3,
    ) -> tuple[str, dict[str, Any]]:
        """Generate from mixed text + image/document parts."""
        return self.generate(
            system_instruction=system_instruction,
            user_content=parts,
            temperature=temperature,
            response_mime_type="application/json",
        )

    @staticmethod
    def parse_json_response(text: str) -> dict[str, Any]:
        """Extract JSON from model response, tolerating markdown fences."""
        cleaned = text.strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if fence_match:
            cleaned = fence_match.group(1)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Attempt to find first JSON object
            obj_match = re.search(r"\{[\s\S]*\}", cleaned)
            if obj_match:
                return json.loads(obj_match.group(0))
            raise
