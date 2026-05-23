"""Document processor for PDF, DOCX, and plain text files."""

from __future__ import annotations

import io
import mimetypes

import structlog
from pypdf import PdfReader

from src.cloud.storage_client import GCSClient
from src.models.schemas import InputFragment, ModalityType, ProcessingResult
from src.processors.base import BaseProcessor

logger = structlog.get_logger(__name__)

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None  # type: ignore[misc, assignment]


class DocumentProcessor(BaseProcessor):
    def __init__(self, gcs: GCSClient | None = None) -> None:
        self.gcs = gcs

    def process(self, fragment: InputFragment) -> ProcessingResult:
        text, doc_meta = self._extract_text(fragment)
        return ProcessingResult(
            fragment_id=fragment.id,
            modality=ModalityType.DOCUMENT,
            extracted_text=text,
            gcs_uri=fragment.gcs_uri,
            metadata={**fragment.metadata, **doc_meta},
        )

    def _extract_text(self, fragment: InputFragment) -> tuple[str, dict]:
        if fragment.content:
            return fragment.content, {"source": "inline"}

        if not fragment.gcs_uri or not self.gcs:
            raise ValueError(f"Document fragment {fragment.id} needs content or gcs_uri")

        data = self.gcs.download_bytes(fragment.gcs_uri)
        mime = fragment.mime_type or mimetypes.guess_type(fragment.gcs_uri)[0] or ""
        filename = fragment.gcs_uri.rsplit("/", 1)[-1].lower()

        if "pdf" in mime or filename.endswith(".pdf"):
            return self._extract_pdf(data), {"format": "pdf", "pages": "auto"}
        if "word" in mime or filename.endswith(".docx"):
            return self._extract_docx(data), {"format": "docx"}
        if filename.endswith(".txt") or "text" in mime:
            return data.decode("utf-8", errors="replace"), {"format": "txt"}

        return data.decode("utf-8", errors="replace"), {"format": "unknown"}

    @staticmethod
    def _extract_pdf(data: bytes) -> str:
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"--- Page {i + 1} ---\n{text}")
        return "\n\n".join(pages) if pages else "[PDF: no extractable text]"

    @staticmethod
    def _extract_docx(data: bytes) -> str:
        if DocxDocument is None:
            return "[DOCX: python-docx not installed]"
        doc = DocxDocument(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs) if paragraphs else "[DOCX: empty]"
