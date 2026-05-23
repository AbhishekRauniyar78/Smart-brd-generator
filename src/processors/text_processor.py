"""Text fragment processor."""

from src.models.schemas import InputFragment, ModalityType, ProcessingResult
from src.processors.base import BaseProcessor


class TextProcessor(BaseProcessor):
    def process(self, fragment: InputFragment) -> ProcessingResult:
        return ProcessingResult(
            fragment_id=fragment.id,
            modality=ModalityType.TEXT,
            extracted_text=fragment.content or "",
            gcs_uri=fragment.gcs_uri,
            metadata=fragment.metadata,
        )
