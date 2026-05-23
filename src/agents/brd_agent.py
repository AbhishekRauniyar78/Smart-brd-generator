"""BRD Generation Agent — context-aware, explainable BRD synthesis."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any

import structlog

from config.settings import Settings
from src.cloud.factory import create_bq_client, create_gcs_client, create_gemini_client
from src.cloud.gcp_auth import check_online_mode
from src.models.schemas import (
    BRDRequest,
    BRDResponse,
    BRDSection,
    DecisionRationale,
    InputFragment,
    ProcessingResult,
)
from src.processors.multimodal_pipeline import MultimodalPipeline

logger = structlog.get_logger(__name__)

BRD_SYSTEM_PROMPT = """You are an expert Business Analyst and BRD author.
Given fragmented, multi-modal business inputs, synthesize a comprehensive,
accurate Business Requirements Document.

Rules:
1. Ground every section in the provided evidence — do not invent facts.
2. Flag gaps explicitly when source data is insufficient.
3. Provide confidence scores (0.0–1.0) and reasoning for each major section.
4. Cite source fragment IDs that support each decision.
5. Output valid JSON matching the required schema exactly.
"""

BRD_USER_SCHEMA = """{
  "executive_summary": "string",
  "sections": [
    {
      "title": "Business Objectives | Scope | Stakeholders | Functional Requirements | ...",
      "content": "markdown content for this section",
      "rationale": {
        "section": "section name",
        "reasoning": "why this content was written",
        "confidence": 0.85,
        "source_fragment_ids": ["id1", "id2"],
        "supporting_evidence": ["quote or paraphrase from source"]
      }
    }
  ],
  "business_objectives": "string",
  "in_scope": "bullet list as string",
  "out_of_scope": "bullet list as string",
  "stakeholders": "string",
  "functional_requirements": "numbered list as string",
  "non_functional_requirements": "string",
  "assumptions_constraints": "string",
  "risks": "string",
  "success_metrics": "string",
  "timeline": "string"
}"""


class BRDGenerationAgent:
    """
    Multi-modal BRD generation agent.

    Pipeline:
    1. Ingest fragmented inputs (text, images, documents)
    2. Normalize via modality processors
    3. Persist context to BigQuery
    4. Generate BRD with Gemini (explainable rationales)
    5. Store artifact in GCS
    6. Log decisions to BigQuery
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.gemini = create_gemini_client(self.settings)
        self.gcs = create_gcs_client(self.settings)
        self.bq = create_bq_client(self.settings)
        self.pipeline = MultimodalPipeline(gcs=self.gcs, gemini=self.gemini)
        self._template_path = Path(__file__).resolve().parents[2] / "templates" / "brd_template.md"
        self._online_status = check_online_mode(self.settings)
        logger.info(
            "brd_agent_ready",
            offline=self.settings.offline_mode,
            mode=self._online_status.mode,
            model=self.settings.gemini_model,
        )

    def generate(self, request: BRDRequest) -> BRDResponse:
        """Full BRD generation pipeline."""
        from uuid import uuid4

        request_id = str(uuid4())
        logger.info(
            "brd_generation_started",
            project=request.project_name,
            request_id=request_id,
        )

        # Step 1: Process multi-modal fragments
        processed = self.pipeline.process_all(request.fragments)

        # Step 2: Enrich with historical context from BigQuery (optional)
        historical = self._fetch_historical_context(request.project_name)
        if historical:
            from src.models.schemas import ModalityType

            processed.append(
                ProcessingResult(
                    fragment_id="historical-context",
                    modality=(
                        processed[0].modality
                        if processed
                        else (
                            request.fragments[0].modality
                            if request.fragments
                            else ModalityType.TEXT
                        )
                    ),
                    extracted_text=self._format_historical(historical),
                    metadata={"source": "bigquery"},
                )
            )

        # Step 3: Log context fragments
        try:
            self.bq.ensure_tables()
            self.bq.log_context_fragments(request_id, processed)
        except Exception as exc:
            logger.warning("bq_context_log_skipped", error=str(exc))

        # Step 4: Generate BRD via Gemini
        brd_data, usage = self._generate_brd_content(request, processed)

        # Step 5: Build response with explainability
        sections, rationales = self._parse_sections(brd_data)
        markdown = self._render_markdown(request, brd_data, rationales, request_id)

        response = BRDResponse(
            request_id=request_id,
            project_name=request.project_name,
            sections=sections,
            executive_summary=brd_data.get("executive_summary", ""),
            decision_rationales=rationales,
            markdown_content=markdown,
            model_used=getattr(self.gemini, "model", self.settings.gemini_model),
            processing_metadata={
                "fragments_processed": len(processed),
                "usage": usage,
                "constraints": request.constraints,
                "offline_mode": self.settings.offline_mode,
                "online_mode": self._online_status.mode,
            },
        )

        # Step 6: Persist to GCS
        try:
            response.gcs_output_uri = self.gcs.upload_text(
                markdown,
                filename=f"BRD_{request.project_name.replace(' ', '_')}.md",
            )
        except Exception as exc:
            logger.warning("gcs_upload_skipped", error=str(exc))

        # Step 7: Log explainable decisions
        try:
            self.bq.log_brd_response(response)
        except Exception as exc:
            logger.warning("bq_decision_log_skipped", error=str(exc))

        logger.info("brd_generation_complete", request_id=response.request_id)
        return response

    def _generate_brd_content(
        self,
        request: BRDRequest,
        processed: list[ProcessingResult],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        context_block = self._build_context_block(request, processed)
        user_prompt = f"""Generate a Business Requirements Document.

Project: {request.project_name}
Business Context: {request.business_context}
Stakeholder Notes: {request.stakeholder_notes}
Constraints: {', '.join(request.constraints) or 'None specified'}

--- PROCESSED INPUT FRAGMENTS ---
{context_block}

--- REQUIRED JSON SCHEMA ---
{BRD_USER_SCHEMA}
"""

        text, usage = self.gemini.generate(
            system_instruction=BRD_SYSTEM_PROMPT,
            user_content=user_prompt,
            temperature=0.3,
        )
        return self.gemini.parse_json_response(text), usage

    @staticmethod
    def _build_context_block(
        request: BRDRequest,
        processed: list[ProcessingResult],
    ) -> str:
        parts = []
        for p in processed:
            parts.append(
                f"[Fragment {p.fragment_id} | {p.modality.value}]\n{p.extracted_text}\n"
            )
        if not parts and request.business_context:
            parts.append(f"[Context only]\n{request.business_context}")
        return "\n".join(parts)

    def _fetch_historical_context(self, keyword: str) -> list[dict]:
        try:
            return self.bq.query_context(project_keyword=keyword, limit=10)
        except Exception:
            return []

    @staticmethod
    def _format_historical(rows: list[dict]) -> str:
        lines = ["Historical context from prior sessions:"]
        for row in rows:
            lines.append(
                f"- [{row.get('modality')}] {row.get('extracted_text', '')[:500]}"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_sections(
        data: dict[str, Any],
    ) -> tuple[list[BRDSection], list[DecisionRationale]]:
        sections: list[BRDSection] = []
        rationales: list[DecisionRationale] = []

        for item in data.get("sections", []):
            rationale_data = item.get("rationale")
            rationale = None
            if rationale_data:
                rationale = DecisionRationale(**rationale_data)
                rationales.append(rationale)
            sections.append(
                BRDSection(
                    title=item.get("title", "Untitled"),
                    content=item.get("content", ""),
                    rationale=rationale,
                )
            )

        # Ensure rationales exist for template sections even if nested differently
        if not rationales and data.get("executive_summary"):
            rationales.append(
                DecisionRationale(
                    section="Executive Summary",
                    reasoning="Synthesized from all input fragments",
                    confidence=0.8,
                    source_fragment_ids=[],
                    supporting_evidence=[data["executive_summary"][:200]],
                )
            )

        return sections, rationales

    def _render_markdown(
        self,
        request: BRDRequest,
        data: dict[str, Any],
        rationales: list[DecisionRationale],
        request_id: str,
    ) -> str:
        template_content = self._template_path.read_text(encoding="utf-8")
        rationale_text = "\n".join(
            f"### {r.section} (confidence: {r.confidence:.0%})\n"
            f"**Reasoning:** {r.reasoning}\n"
            f"**Sources:** {', '.join(r.source_fragment_ids) or 'N/A'}\n"
            f"**Evidence:** {'; '.join(r.supporting_evidence[:3])}\n"
            for r in rationales
        )

        mapping = {
            "project_name": request.project_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "executive_summary": data.get("executive_summary", ""),
            "business_objectives": data.get("business_objectives", ""),
            "in_scope": data.get("in_scope", ""),
            "out_of_scope": data.get("out_of_scope", ""),
            "stakeholders": data.get("stakeholders", ""),
            "functional_requirements": data.get("functional_requirements", ""),
            "non_functional_requirements": data.get("non_functional_requirements", ""),
            "assumptions_constraints": data.get("assumptions_constraints", ""),
            "risks": data.get("risks", ""),
            "success_metrics": data.get("success_metrics", ""),
            "timeline": data.get("timeline", ""),
            "decision_rationale": rationale_text or "No rationales recorded.",
        }
        return Template(template_content).safe_substitute(mapping)

    def ingest_fragment(
        self,
        modality: str,
        content: str | None = None,
        file_bytes: bytes | None = None,
        filename: str = "upload",
        mime_type: str | None = None,
    ) -> InputFragment:
        """Helper to create and optionally upload a fragment to GCS."""
        from src.models.schemas import ModalityType

        gcs_uri = None
        if file_bytes:
            gcs_uri = self.gcs.upload_bytes(file_bytes, filename, content_type=mime_type)

        return InputFragment(
            modality=ModalityType(modality),
            content=content,
            gcs_uri=gcs_uri,
            mime_type=mime_type,
        )
