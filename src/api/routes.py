"""FastAPI routes for real-time multi-modal BRD generation."""

from __future__ import annotations

import base64

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from config.settings import get_settings
from src.agents.brd_agent import BRDGenerationAgent
from src.models.schemas import BRDRequest, BRDResponse, InputFragment, ModalityType

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["BRD"])

_agent: BRDGenerationAgent | None = None


def get_agent() -> BRDGenerationAgent:
    global _agent
    if _agent is None:
        _agent = BRDGenerationAgent(get_settings())
    return _agent


class TextFragmentInput(BaseModel):
    content: str
    metadata: dict = Field(default_factory=dict)


class GenerateBRDRequest(BaseModel):
    project_name: str
    business_context: str = ""
    stakeholder_notes: str = ""
    constraints: list[str] = Field(default_factory=list)
    text_fragments: list[TextFragmentInput] = Field(default_factory=list)


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "healthy",
        "service": "brd-generation-agent",
        "model": settings.gemini_model,
        "project": settings.gcp_project_id or "not-configured",
        "offline_mode": settings.offline_mode,
    }


@router.post("/brd/generate", response_model=BRDResponse)
async def generate_brd(payload: GenerateBRDRequest) -> BRDResponse:
    """Generate a BRD from text fragments (JSON body)."""
    agent = get_agent()
    fragments = [
        InputFragment(modality=ModalityType.TEXT, content=t.content, metadata=t.metadata)
        for t in payload.text_fragments
    ]
    request = BRDRequest(
        project_name=payload.project_name,
        business_context=payload.business_context,
        stakeholder_notes=payload.stakeholder_notes,
        constraints=payload.constraints,
        fragments=fragments,
    )
    try:
        return agent.generate(request)
    except Exception as exc:
        logger.error("brd_generation_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/brd/generate-multimodal", response_model=BRDResponse)
async def generate_brd_multimodal(
    project_name: str = Form(...),
    business_context: str = Form(""),
    stakeholder_notes: str = Form(""),
    constraints: str = Form(""),
    text_notes: str = Form(""),
    documents: list[UploadFile] = File(default=[]),
    images: list[UploadFile] = File(default=[]),
) -> BRDResponse:
    """
    Real-time multi-modal BRD generation.

    Accepts form fields plus file uploads for documents (PDF/DOCX/TXT)
    and images (PNG/JPG/WebP).
    """
    agent = get_agent()
    fragments: list[InputFragment] = []

    if text_notes.strip():
        fragments.append(
            InputFragment(modality=ModalityType.TEXT, content=text_notes)
        )

    for doc in documents:
        data = await doc.read()
        fragment = agent.ingest_fragment(
            modality="document",
            file_bytes=data,
            filename=doc.filename or "document",
            mime_type=doc.content_type,
        )
        fragments.append(fragment)

    for img in images:
        data = await img.read()
        fragment = agent.ingest_fragment(
            modality="image",
            content=base64.b64encode(data).decode(),
            file_bytes=data,
            filename=img.filename or "image",
            mime_type=img.content_type,
        )
        fragments.append(fragment)

    constraint_list = [c.strip() for c in constraints.split(",") if c.strip()]
    request = BRDRequest(
        project_name=project_name,
        business_context=business_context,
        stakeholder_notes=stakeholder_notes,
        constraints=constraint_list,
        fragments=fragments,
    )

    try:
        return agent.generate(request)
    except Exception as exc:
        logger.error("multimodal_brd_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/brd/context")
async def query_context(keyword: str | None = None, limit: int = 20) -> dict:
    """Query historical context fragments from BigQuery."""
    agent = get_agent()
    try:
        rows = agent.bq.query_context(project_keyword=keyword, limit=limit)
        return {"count": len(rows), "fragments": rows}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
