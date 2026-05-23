"""Gemini client via Google AI Studio API key (non-Vertex)."""

from __future__ import annotations

from typing import Any

import structlog
from google import genai
from google.genai import types

from config.settings import Settings
from src.cloud.vertex_client import VertexGeminiClient

logger = structlog.get_logger(__name__)

# Vertex model IDs → AI Studio model names
_MODEL_MAP = {
    "gemini-2.0-flash-001": "gemini-2.0-flash",
    "gemini-2.0-flash": "gemini-2.0-flash",
    "gemini-1.5-flash-001": "gemini-1.5-flash",
    "gemini-1.5-pro-001": "gemini-1.5-pro",
}


class GeminiApiKeyClient:
    """Gemini via GOOGLE_API_KEY / GEMINI_API_KEY — no Vertex AI project required."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = _MODEL_MAP.get(settings.gemini_model, settings.gemini_model)
        api_key = settings.resolved_gemini_api_key()
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) is required for Google AI Studio mode."
            )
        self._client = genai.Client(api_key=api_key)
        logger.info("gemini_api_key_client_ready", model=self.model)

    def generate(
        self,
        system_instruction: str,
        user_content: str | list[Any],
        temperature: float = 0.3,
        response_mime_type: str | None = "application/json",
    ) -> tuple[str, dict[str, Any]]:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )
        if response_mime_type:
            config.response_mime_type = response_mime_type

        response = self._client.models.generate_content(
            model=self.model,
            contents=user_content,
            config=config,
        )

        text = response.text or ""
        usage: dict[str, Any] = {"backend": "google_ai_studio"}
        if response.usage_metadata:
            usage.update({
                "prompt_token_count": response.usage_metadata.prompt_token_count,
                "candidates_token_count": response.usage_metadata.candidates_token_count,
                "total_token_count": response.usage_metadata.total_token_count,
            })

        logger.info("gemini_api_generation_complete", model=self.model, usage=usage)
        return text, usage

    def generate_multimodal(
        self,
        system_instruction: str,
        parts: list[Any],
        temperature: float = 0.3,
    ) -> tuple[str, dict[str, Any]]:
        return self.generate(
            system_instruction=system_instruction,
            user_content=parts,
            temperature=temperature,
            response_mime_type="application/json",
        )

    parse_json_response = staticmethod(VertexGeminiClient.parse_json_response)
