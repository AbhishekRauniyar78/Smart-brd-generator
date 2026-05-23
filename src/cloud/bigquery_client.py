"""BigQuery client for context storage and explainable decision logging."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog
from google.cloud import bigquery

from config.settings import Settings
from src.models.schemas import BRDResponse, DecisionRationale, InputFragment, ProcessingResult

logger = structlog.get_logger(__name__)

DECISIONS_SCHEMA = [
    bigquery.SchemaField("decision_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("request_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("project_name", "STRING"),
    bigquery.SchemaField("section", "STRING"),
    bigquery.SchemaField("reasoning", "STRING"),
    bigquery.SchemaField("confidence", "FLOAT"),
    bigquery.SchemaField("source_fragment_ids", "STRING", mode="REPEATED"),
    bigquery.SchemaField("supporting_evidence", "STRING", mode="REPEATED"),
    bigquery.SchemaField("model_used", "STRING"),
    bigquery.SchemaField("created_at", "TIMESTAMP"),
]

CONTEXT_SCHEMA = [
    bigquery.SchemaField("fragment_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("request_id", "STRING"),
    bigquery.SchemaField("modality", "STRING"),
    bigquery.SchemaField("extracted_text", "STRING"),
    bigquery.SchemaField("gcs_uri", "STRING"),
    bigquery.SchemaField("metadata", "JSON"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP"),
]


class BigQueryClient:
    """Persist fragmented context and decision rationales for auditability."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: bigquery.Client | None = None
        self._dataset_id = f"{settings.gcp_project_id}.{settings.bq_dataset}"

    @property
    def client(self) -> bigquery.Client:
        if self._client is None:
            self._client = bigquery.Client(project=self.settings.gcp_project_id or None)
        return self._client

    def ensure_tables(self) -> None:
        """Create dataset and tables if they do not exist."""
        dataset = bigquery.Dataset(self._dataset_id)
        dataset.location = self.settings.gcp_region
        self.client.create_dataset(dataset, exists_ok=True)

        for table_id, schema in [
            (self.settings.decisions_table_id, DECISIONS_SCHEMA),
            (self.settings.context_table_id, CONTEXT_SCHEMA),
        ]:
            table = bigquery.Table(table_id, schema=schema)
            self.client.create_table(table, exists_ok=True)
            logger.info("bq_table_ready", table=table_id)

    def log_context_fragments(
        self,
        request_id: str,
        fragments: list[InputFragment] | list[ProcessingResult],
    ) -> None:
        """Store processed context fragments for retrieval and analytics."""
        rows: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()

        for frag in fragments:
            if isinstance(frag, ProcessingResult):
                rows.append({
                    "fragment_id": frag.fragment_id,
                    "request_id": request_id,
                    "modality": frag.modality.value,
                    "extracted_text": frag.extracted_text[:100_000],
                    "gcs_uri": frag.gcs_uri,
                    "metadata": frag.metadata,
                    "ingested_at": now,
                })
            else:
                rows.append({
                    "fragment_id": frag.id,
                    "request_id": request_id,
                    "modality": frag.modality.value,
                    "extracted_text": (frag.content or "")[:100_000],
                    "gcs_uri": frag.gcs_uri,
                    "metadata": frag.metadata,
                    "ingested_at": now,
                })

        if rows:
            errors = self.client.insert_rows_json(
                self.settings.context_table_id, rows
            )
            if errors:
                logger.warning("bq_context_insert_errors", errors=errors)

    def log_decisions(
        self,
        request_id: str,
        project_name: str,
        rationales: list[DecisionRationale],
        model_used: str,
    ) -> None:
        """Log explainable decision rationales."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            {
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
            }
            for r in rationales
        ]
        if rows:
            errors = self.client.insert_rows_json(
                self.settings.decisions_table_id, rows
            )
            if errors:
                logger.warning("bq_decision_insert_errors", errors=errors)

    def log_brd_response(self, response: BRDResponse) -> None:
        """Convenience method to log full BRD response rationales."""
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
        """Retrieve recent context fragments (for RAG-style enrichment)."""
        query = f"""
            SELECT fragment_id, modality, extracted_text, gcs_uri, ingested_at
            FROM `{self.settings.context_table_id}`
            ORDER BY ingested_at DESC
            LIMIT {limit}
        """
        if project_keyword:
            query = f"""
                SELECT fragment_id, modality, extracted_text, gcs_uri, ingested_at
                FROM `{self.settings.context_table_id}`
                WHERE LOWER(extracted_text) LIKE LOWER('%{project_keyword}%')
                ORDER BY ingested_at DESC
                LIMIT {limit}
            """
        return [dict(row) for row in self.client.query(query).result()]
