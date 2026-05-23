"""Orchestrates modality-specific processors for fragmented inputs."""

from __future__ import annotations

import structlog

from src.cloud.storage_client import GCSClient
from src.cloud.vertex_client import VertexGeminiClient
from src.models.schemas import InputFragment, ModalityType, ProcessingResult
from src.processors.document_processor import DocumentProcessor
from src.processors.image_processor import ImageProcessor
from src.processors.text_processor import TextProcessor

logger = structlog.get_logger(__name__)


class MultimodalPipeline:
    """Route each fragment to the correct processor and normalize output."""

    def __init__(
        self,
        gcs: GCSClient | None = None,
        gemini: VertexGeminiClient | None = None,
    ) -> None:
        self._processors = {
            ModalityType.TEXT: TextProcessor(),
            ModalityType.IMAGE: ImageProcessor(gcs=gcs, gemini=gemini),
            ModalityType.DOCUMENT: DocumentProcessor(gcs=gcs),
        }

    def process_all(self, fragments: list[InputFragment]) -> list[ProcessingResult]:
        results: list[ProcessingResult] = []
        for fragment in fragments:
            processor = self._processors.get(fragment.modality)
            if not processor:
                logger.warning("unknown_modality", modality=fragment.modality)
                continue
            try:
                result = processor.process(fragment)
                results.append(result)
                logger.info(
                    "fragment_processed",
                    fragment_id=fragment.id,
                    modality=fragment.modality.value,
                    chars=len(result.extracted_text),
                )
            except Exception as exc:
                logger.error(
                    "fragment_processing_failed",
                    fragment_id=fragment.id,
                    error=str(exc),
                )
                results.append(
                    ProcessingResult(
                        fragment_id=fragment.id,
                        modality=fragment.modality,
                        extracted_text=f"[Processing failed: {exc}]",
                        gcs_uri=fragment.gcs_uri,
                        metadata={"error": str(exc)},
                    )
                )
        return results
