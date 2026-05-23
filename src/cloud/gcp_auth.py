"""GCP credential and configuration validation for online mode."""

from __future__ import annotations

import os
from dataclasses import dataclass

from config.settings import Settings

PLACEHOLDER_PROJECT = "your-gcp-project-id"


class GCPConfigurationError(Exception):
    """Raised when online mode is requested but GCP is not properly configured."""


@dataclass
class OnlineModeStatus:
    ready: bool
    mode: str  # "vertex", "api_key", or "unavailable"
    message: str = ""


def has_gcp_credentials() -> bool:
    """Return True if Application Default Credentials or a service account key exist."""
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    try:
        import google.auth

        google.auth.default()
        return True
    except Exception:
        return False


def validate_gcp_project(settings: Settings) -> list[str]:
    """Return list of configuration errors (empty if valid)."""
    errors: list[str] = []
    project = (settings.gcp_project_id or "").strip()
    if not project or project == PLACEHOLDER_PROJECT:
        errors.append(
            "Set `GCP_PROJECT_ID` in your `.env` file to your real Google Cloud project ID."
        )
    return errors


def check_online_mode(settings: Settings) -> OnlineModeStatus:
    """
    Determine whether online mode can run and which backend to use.

    Priority:
    1. GEMINI_API_KEY → Google AI Studio (no Vertex/GCS credentials required for generation)
    2. GCP credentials + project → full Vertex AI + GCS + BigQuery
    """
    if settings.offline_mode:
        return OnlineModeStatus(ready=True, mode="offline")

    api_key = settings.resolved_gemini_api_key()
    if api_key:
        return OnlineModeStatus(
            ready=True,
            mode="api_key",
            message="Using Google AI Studio (GEMINI_API_KEY). GCS/BigQuery use local mocks.",
        )

    project_errors = validate_gcp_project(settings)
    if project_errors:
        return OnlineModeStatus(
            ready=False,
            mode="unavailable",
            message=_format_setup_help(project_errors),
        )

    if not has_gcp_credentials():
        return OnlineModeStatus(
            ready=False,
            mode="unavailable",
            message=_format_setup_help([
                "Google Cloud credentials were not found.",
                "Run: `gcloud auth application-default login`",
                "Or set `GOOGLE_APPLICATION_CREDENTIALS` to a service account JSON key.",
                "Alternatively, set `GEMINI_API_KEY` in `.env` for Google AI Studio (simpler).",
            ]),
        )

    return OnlineModeStatus(
        ready=True,
        mode="vertex",
        message="Using Vertex AI with Cloud Storage and BigQuery.",
    )


def require_online_mode(settings: Settings) -> OnlineModeStatus:
    """Validate online mode; raise GCPConfigurationError if not ready."""
    status = check_online_mode(settings)
    if not status.ready:
        raise GCPConfigurationError(status.message)
    return status


def _format_setup_help(errors: list[str]) -> str:
    lines = ["**Online mode is not configured:**", ""]
    lines.extend(f"- {e}" for e in errors)
    return "\n".join(lines)


def use_mock_storage(settings: Settings, online_status: OnlineModeStatus | None = None) -> bool:
    """Use mock GCS when offline or when only API key is set (no full GCP)."""
    if settings.offline_mode:
        return True
    status = online_status or check_online_mode(settings)
    return status.mode == "api_key"
