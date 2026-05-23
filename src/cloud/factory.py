"""Factory for real vs mock GCP clients."""

from __future__ import annotations

from typing import Any

from config.settings import Settings
from src.cloud.gcp_auth import (
    check_online_mode,
    require_online_mode,
    use_mock_storage,
)


def create_gemini_client(settings: Settings) -> Any:
    if settings.offline_mode:
        from src.cloud.mock_clients import MockVertexGeminiClient
        return MockVertexGeminiClient(settings)

    status = require_online_mode(settings)

    if status.mode == "api_key":
        from src.cloud.gemini_api_client import GeminiApiKeyClient
        return GeminiApiKeyClient(settings)

    from src.cloud.vertex_client import VertexGeminiClient
    return VertexGeminiClient(settings)


def create_gcs_client(settings: Settings) -> Any:
    status = check_online_mode(settings)
    if use_mock_storage(settings, status):
        from src.cloud.mock_clients import MockGCSClient
        return MockGCSClient(settings)

    require_online_mode(settings)
    from src.cloud.storage_client import GCSClient
    return GCSClient(settings)


def create_bq_client(settings: Settings) -> Any:
    status = check_online_mode(settings)
    if use_mock_storage(settings, status):
        from src.cloud.mock_clients import MockBigQueryClient
        return MockBigQueryClient(settings)

    require_online_mode(settings)
    from src.cloud.bigquery_client import BigQueryClient
    return BigQueryClient(settings)
