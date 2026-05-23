"""Pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings


@pytest.fixture
def offline_settings() -> Settings:
    return Settings(
        offline_mode=True,
        gcp_project_id="test-project",
        gcs_bucket_name="test-bucket",
    )
