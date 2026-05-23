"""In-memory mock GCP clients for offline/local development."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from config.settings import Settings
from src.cloud.vertex_client import VertexGeminiClient
from src.models.schemas import BRDResponse, DecisionRationale, InputFragment, ProcessingResult

logger = structlog.get_logger(__name__)

MOCK_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "mock_gcs"


class MockGCSClient:
    """Local filesystem-backed GCS substitute."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._root = MOCK_DATA_DIR
        self._root.mkdir(parents=True, exist_ok=True)

    def upload_bytes(
        self,
        data: bytes,
        filename: str,
        prefix: str | None = None,
        content_type: str | None = None,
    ) -> str:
        prefix = prefix or self.settings.gcs_input_prefix
        blob_dir = self._root / prefix.replace("/", "_")
        blob_dir.mkdir(parents=True, exist_ok=True)
        path = blob_dir / f"{uuid4().hex}_{filename}"
        path.write_bytes(data)
        uri = f"mock://local/{path.relative_to(self._root).as_posix()}"
        logger.info("mock_gcs_upload", uri=uri)
        return uri

    def upload_file(self, local_path: str | Path, prefix: str | None = None) -> str:
        path = Path(local_path)
        return self.upload_bytes(path.read_bytes(), path.name, prefix=prefix)

    def download_bytes(self, gcs_uri: str) -> bytes:
        if gcs_uri.startswith("mock://local/"):
            rel = gcs_uri.replace("mock://local/", "")
            return (self._root / rel).read_bytes()
        if gcs_uri.startswith("gs://"):
            # Fallback: try local mirror path
            parts = gcs_uri.replace("gs://", "").split("/", 1)
            if len(parts) == 2:
                return (self._root / parts[1]).read_bytes()
        raise FileNotFoundError(f"Mock GCS object not found: {gcs_uri}")

    def upload_text(self, content: str, filename: str, prefix: str | None = None) -> str:
        return self.upload_bytes(
            content.encode("utf-8"), filename, prefix=prefix, content_type="text/markdown"
        )


class MockBigQueryClient:
    """In-memory BigQuery substitute."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._context_rows: list[dict[str, Any]] = []
        self._decision_rows: list[dict[str, Any]] = []

    def ensure_tables(self) -> None:
        logger.info("mock_bq_tables_ready")

    def log_context_fragments(
        self,
        request_id: str,
        fragments: list[InputFragment] | list[ProcessingResult],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for frag in fragments:
            if isinstance(frag, ProcessingResult):
                self._context_rows.append({
                    "fragment_id": frag.fragment_id,
                    "request_id": request_id,
                    "modality": frag.modality.value,
                    "extracted_text": frag.extracted_text[:100_000],
                    "gcs_uri": frag.gcs_uri,
                    "metadata": frag.metadata,
                    "ingested_at": now,
                })
            else:
                self._context_rows.append({
                    "fragment_id": frag.id,
                    "request_id": request_id,
                    "modality": frag.modality.value,
                    "extracted_text": (frag.content or "")[:100_000],
                    "gcs_uri": frag.gcs_uri,
                    "metadata": frag.metadata,
                    "ingested_at": now,
                })

    def log_decisions(
        self,
        request_id: str,
        project_name: str,
        rationales: list[DecisionRationale],
        model_used: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for r in rationales:
            self._decision_rows.append({
                "decision_id": str(uuid4()),
                "request_id": request_id,
                "project_name": project_name,
                "section": r.section,
                "reasoning": r.reasoning,
                "confidence": r.confidence,
                "source_fragment_ids": r.source_fragment_ids,
                "supporting_evidence": r.supporting_evidence,
                "model_used": model_used,
                "created_at": now,
            })

    def log_brd_response(self, response: BRDResponse) -> None:
        self.log_decisions(
            request_id=response.request_id,
            project_name=response.project_name,
            rationales=response.decision_rationales,
            model_used=response.model_used,
        )

    def query_context(
        self,
        project_keyword: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = self._context_rows
        if project_keyword:
            kw = project_keyword.lower()
            rows = [
                r for r in rows
                if kw in (r.get("extracted_text") or "").lower()
            ]
        return list(reversed(rows[-limit:]))


class MockVertexGeminiClient:
    """Deterministic BRD generator — no Vertex AI calls."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = f"mock/{settings.gemini_model}"

    def generate(
        self,
        system_instruction: str,
        user_content: str | list[Any],
        temperature: float = 0.3,
        response_mime_type: str | None = "application/json",
    ) -> tuple[str, dict[str, Any]]:
        prompt = user_content if isinstance(user_content, str) else str(user_content)
        return json.dumps(self._build_brd_json(prompt)), {
            "prompt_token_count": len(prompt) // 4,
            "candidates_token_count": 800,
            "total_token_count": len(prompt) // 4 + 800,
            "mock": True,
        }

    def generate_multimodal(
        self,
        system_instruction: str,
        parts: list[Any],
        temperature: float = 0.3,
    ) -> tuple[str, dict[str, Any]]:
        return self.generate(system_instruction, str(parts), temperature)

    @staticmethod
    def parse_json_response(text: str) -> dict[str, Any]:
        return VertexGeminiClient.parse_json_response(text)

    def _build_brd_json(self, prompt: str) -> dict[str, Any]:
        """Synthesize a plausible BRD JSON from prompt content."""
        project = "Untitled Project"
        match = re.search(r"Project:\s*(.+)", prompt)
        if match:
            project = match.group(1).strip()

        fragments = re.findall(
            r"\[Fragment ([^\]|]+)[^\]]*\]\n(.*?)(?=\n\[Fragment |\Z)",
            prompt,
            re.DOTALL,
        )
        fragment_ids = [f[0].strip() for f in fragments]
        evidence = [f[1].strip()[:200] for f in fragments[:3]] or ["Business context provided"]

        def rationale(section: str, reasoning: str, confidence: float = 0.75) -> dict:
            return {
                "section": section,
                "reasoning": reasoning,
                "confidence": confidence,
                "source_fragment_ids": fragment_ids[:2],
                "supporting_evidence": evidence,
            }

        objectives = (
            f"Deliver {project} aligned with stakeholder needs and measurable outcomes."
        )
        func_reqs = "\n".join(
            f"{i + 1}. Requirement derived from input fragment {fid}"
            for i, fid in enumerate(fragment_ids[:5])
        ) or "1. Core functionality per business context\n2. Integration with existing systems"

        return {
            "executive_summary": (
                f"This BRD for **{project}** was generated in **offline mock mode**. "
                f"It synthesizes {len(fragment_ids)} input fragment(s) into structured "
                "business requirements. Connect Vertex AI for production-quality output."
            ),
            "sections": [
                {
                    "title": "Business Objectives",
                    "content": objectives,
                    "rationale": rationale(
                        "Business Objectives",
                        "Derived from project name and input fragments.",
                        0.82,
                    ),
                },
                {
                    "title": "Functional Requirements",
                    "content": func_reqs,
                    "rationale": rationale(
                        "Functional Requirements",
                        "Mapped from processed text and document fragments.",
                        0.78,
                    ),
                },
            ],
            "business_objectives": objectives,
            "in_scope": "- Core features described in input fragments\n- MVP delivery per constraints",
            "out_of_scope": "- Features not mentioned in source materials\n- Future-phase enhancements",
            "stakeholders": "Product Owner, Engineering Lead, Business Sponsor (inferred from context)",
            "functional_requirements": func_reqs,
            "non_functional_requirements": (
                "- Availability: 99.5% uptime\n"
                "- Security: Role-based access, audit logging\n"
                "- Performance: Sub-2s page loads for primary workflows"
            ),
            "assumptions_constraints": (
                "Assumptions: Source fragments are accurate and complete.\n"
                f"Constraints mentioned in request: extracted from prompt."
            ),
            "risks": (
                "- Incomplete requirements from fragmented inputs\n"
                "- Integration complexity with legacy systems\n"
                "- Timeline pressure on delivery milestones"
            ),
            "success_metrics": (
                "- User adoption rate > 60% within 90 days\n"
                "- Reduction in support tickets by 25%\n"
                "- On-time delivery per project timeline"
            ),
            "timeline": "Phase 1 (Discovery): 4 weeks | Phase 2 (Build): 12 weeks | Phase 3 (Launch): 4 weeks",
        }
