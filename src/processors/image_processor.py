"""Image fragment processor — extracts visual context via Gemini vision."""

from __future__ import annotations

import base64
import mimetypes

import structlog
from google.genai import types

from src.cloud.storage_client import GCSClient
from src.cloud.vertex_client import VertexGeminiClient
from src.models.schemas import InputFragment, ModalityType, ProcessingResult
from src.processors.base import BaseProcessor

logger = structlog.get_logger(__name__)

VISION_PROMPT = """Analyze this image in a business context.
Extract: visible text, diagrams, UI elements, charts, whiteboard notes,
process flows, and any requirements or constraints implied.
Return JSON:
{
  "summary": "...",
  "extracted_text": "...",
  "business_signals": ["..."],
  "confidence": 0.0-1.0
}
"""


class ImageProcessor(BaseProcessor):
    def __init__(
        self,
        gcs: GCSClient | None = None,
        gemini: VertexGeminiClient | None = None,
    ) -> None:
        self.gcs = gcs
        self.gemini = gemini

    def process(self, fragment: InputFragment) -> ProcessingResult:
        image_bytes, mime_type = self._load_image(fragment)
        extracted = self._describe_with_vision(image_bytes, mime_type)

        return ProcessingResult(
            fragment_id=fragment.id,
            modality=ModalityType.IMAGE,
            extracted_text=extracted,
            gcs_uri=fragment.gcs_uri,
            metadata={
                **fragment.metadata,
                "mime_type": mime_type,
                "vision_enriched": bool(self.gemini),
            },
        )

    def _load_image(self, fragment: InputFragment) -> tuple[bytes, str]:
        if fragment.gcs_uri and self.gcs:
            data = self.gcs.download_bytes(fragment.gcs_uri)
            mime = fragment.mime_type or mimetypes.guess_type(fragment.gcs_uri)[0]
            return data, mime or "image/png"

        if fragment.content:
            # Base64-encoded inline image
            if fragment.content.startswith("data:"):
                header, _, encoded = fragment.content.partition(",")
                mime = header.split(";")[0].replace("data:", "")
                return base64.b64decode(encoded), mime
            return base64.b64decode(fragment.content), fragment.mime_type or "image/png"

        raise ValueError(f"Image fragment {fragment.id} has no content or gcs_uri")

    def _describe_with_vision(self, image_bytes: bytes, mime_type: str) -> str:
        if not self.gemini:
            return f"[Image asset: {len(image_bytes)} bytes, type={mime_type}]"

        parts = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            VISION_PROMPT,
        ]
        try:
            text, _ = self.gemini.generate_multimodal(
                system_instruction="You are a business analyst extracting requirements from visuals.",
                parts=parts,
                temperature=0.2,
            )
            parsed = self.gemini.parse_json_response(text)
            summary = parsed.get("summary", "")
            extracted = parsed.get("extracted_text", "")
            signals = parsed.get("business_signals", [])
            return f"{summary}\n\nExtracted text:\n{extracted}\n\nSignals: {', '.join(signals)}"
        except Exception as exc:
            logger.warning("vision_extraction_failed", error=str(exc))
            return f"[Image: vision extraction unavailable, {len(image_bytes)} bytes]"
