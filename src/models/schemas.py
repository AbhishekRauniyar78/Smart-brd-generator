"""Pydantic models for inputs, outputs, and explainability."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ModalityType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"


class InputFragment(BaseModel):
    """A single piece of fragmented real-time input."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    modality: ModalityType
    content: str | None = None  # raw text or extracted text
    gcs_uri: str | None = None  # gs://bucket/path for binary assets
    mime_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DecisionRationale(BaseModel):
    """Explainability record for a generated decision or section."""

    section: str
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_fragment_ids: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)


class BRDSection(BaseModel):
    title: str
    content: str
    rationale: DecisionRationale | None = None


class BRDRequest(BaseModel):
    project_name: str
    business_context: str = ""
    fragments: list[InputFragment] = Field(default_factory=list)
    stakeholder_notes: str = ""
    constraints: list[str] = Field(default_factory=list)


class BRDResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    sections: list[BRDSection]
    executive_summary: str
    decision_rationales: list[DecisionRationale]
    gcs_output_uri: str | None = None
    markdown_content: str = ""
    model_used: str = ""
    processing_metadata: dict[str, Any] = Field(default_factory=dict)


class ProcessingResult(BaseModel):
    """Normalized output from a modality processor."""

    fragment_id: str
    modality: ModalityType
    extracted_text: str
    gcs_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
