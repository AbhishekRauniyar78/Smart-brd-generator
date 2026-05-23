"""Tests for mock/offline GCP clients."""

import json

from src.cloud.mock_clients import MockBigQueryClient, MockGCSClient, MockVertexGeminiClient
from src.models.schemas import DecisionRationale, ModalityType, ProcessingResult


def test_mock_gcs_roundtrip(offline_settings):
    gcs = MockGCSClient(offline_settings)
    uri = gcs.upload_bytes(b"hello world", "test.txt")
    assert uri.startswith("mock://")
    data = gcs.download_bytes(uri)
    assert data == b"hello world"


def test_mock_bq_context_and_decisions(offline_settings):
    bq = MockBigQueryClient(offline_settings)
    bq.ensure_tables()

    processed = [
        ProcessingResult(
            fragment_id="frag-1",
            modality=ModalityType.TEXT,
            extracted_text="Users need SSO",
        )
    ]
    bq.log_context_fragments("req-1", processed)

    bq.log_decisions(
        "req-1",
        "Portal",
        [
            DecisionRationale(
                section="Auth",
                reasoning="SSO mentioned",
                confidence=0.85,
                source_fragment_ids=["frag-1"],
            )
        ],
        "mock/gemini",
    )

    rows = bq.query_context(project_keyword="SSO", limit=10)
    assert len(rows) == 1
    assert "SSO" in rows[0]["extracted_text"]


def test_mock_gemini_generates_valid_json(offline_settings):
    gemini = MockVertexGeminiClient(offline_settings)
    prompt = "Project: Inventory System\n[Fragment abc | text]\nWarehouse scanners"
    text, usage = gemini.generate("system", prompt)
    data = gemini.parse_json_response(text)

    assert "executive_summary" in data
    assert "functional_requirements" in data
    assert usage.get("mock") is True
    assert "Inventory System" in data["executive_summary"]
