"""Tests for modality processors."""

from src.models.schemas import InputFragment, ModalityType
from src.processors.document_processor import DocumentProcessor
from src.processors.multimodal_pipeline import MultimodalPipeline
from src.processors.text_processor import TextProcessor


def test_text_processor():
    frag = InputFragment(modality=ModalityType.TEXT, content="Requirement A")
    result = TextProcessor().process(frag)
    assert result.extracted_text == "Requirement A"
    assert result.modality == ModalityType.TEXT


def test_document_processor_inline():
    frag = InputFragment(
        modality=ModalityType.DOCUMENT,
        content="Section 1\n\nSection 2",
    )
    result = DocumentProcessor().process(frag)
    assert "Section 1" in result.extracted_text


def test_multimodal_pipeline_offline(offline_settings):
    from src.cloud.mock_clients import MockGCSClient, MockVertexGeminiClient

    pipeline = MultimodalPipeline(
        gcs=MockGCSClient(offline_settings),
        gemini=MockVertexGeminiClient(offline_settings),
    )
    fragments = [
        InputFragment(modality=ModalityType.TEXT, content="Line 1"),
        InputFragment(modality=ModalityType.TEXT, content="Line 2"),
    ]
    results = pipeline.process_all(fragments)
    assert len(results) == 2
