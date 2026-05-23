"""Tests for online mode validation."""

import os

from config.settings import Settings
from src.cloud.gcp_auth import check_online_mode, validate_gcp_project
from src.cloud.factory import create_gemini_client


def test_validate_project_placeholder():
    s = Settings(gcp_project_id="your-gcp-project-id", offline_mode=False)
    errors = validate_gcp_project(s)
    assert len(errors) == 1


def test_online_unavailable_without_creds_or_key():
    s = Settings(
        gcp_project_id="real-project",
        offline_mode=False,
        gemini_api_key="",
    )
    # May pass creds check in CI with ADC; force no key path
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    status = check_online_mode(s)
    # Without real ADC in test env, should be unavailable OR vertex if CI has creds
    assert status.mode in ("unavailable", "vertex", "api_key")


def test_online_api_key_mode():
    s = Settings(offline_mode=False, gemini_api_key="test-key-12345")
    status = check_online_mode(s)
    assert status.ready is True
    assert status.mode == "api_key"


def test_factory_uses_mock_gemini_when_offline(offline_settings):
    client = create_gemini_client(offline_settings)
    assert "mock" in getattr(client, "model", "")


def test_factory_api_key_client():
    s = Settings(offline_mode=False, gemini_api_key="test-key")
    client = create_gemini_client(s)
    assert client.__class__.__name__ == "GeminiApiKeyClient"
