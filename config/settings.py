"""Application configuration loaded from environment variables."""

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Google Cloud
    gcp_project_id: str = ""
    gcp_region: str = "us-central1"
    vertex_ai_location: str = "us-central1"
    gemini_model: str = "gemini-2.0-flash-001"
    gemini_api_key: str = Field(
        default="",
        description="Google AI Studio API key (env: GEMINI_API_KEY or GOOGLE_API_KEY)",
    )

    def resolved_gemini_api_key(self) -> str:
        """Return API key from model field or environment (safe if field missing on stale instances)."""
        key = getattr(self, "gemini_api_key", "") or ""
        if not str(key).strip():
            key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get(
                "GOOGLE_API_KEY", ""
            )
        return str(key).strip()

    # Cloud Storage
    gcs_bucket_name: str = "brd-agent-artifacts"
    gcs_input_prefix: str = "inputs/"
    gcs_output_prefix: str = "outputs/"

    # BigQuery
    bq_dataset: str = "brd_agent"
    bq_decisions_table: str = "decision_log"
    bq_context_table: str = "context_fragments"

    # Application
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    offline_mode: bool = False  # Use mock GCP/Gemini (no credentials needed)

    @property
    def decisions_table_id(self) -> str:
        return f"{self.gcp_project_id}.{self.bq_dataset}.{self.bq_decisions_table}"

    @property
    def context_table_id(self) -> str:
        return f"{self.gcp_project_id}.{self.bq_dataset}.{self.bq_context_table}"


def get_settings() -> Settings:
    """Return fresh settings (no cache — avoids stale instances during hot reload)."""
    return Settings()
