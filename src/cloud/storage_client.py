"""Google Cloud Storage client for artifact persistence."""

from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import structlog
from google.cloud import storage

from config.settings import Settings

logger = structlog.get_logger(__name__)


class GCSClient:
    """Upload and retrieve multi-modal inputs and generated BRDs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: storage.Client | None = None
        self._bucket_name = settings.gcs_bucket_name

    @property
    def client(self) -> storage.Client:
        if self._client is None:
            self._client = storage.Client(project=self.settings.gcp_project_id or None)
        return self._client

    @property
    def bucket(self) -> storage.Bucket:
        return self.client.bucket(self._bucket_name)

    def upload_bytes(
        self,
        data: bytes,
        filename: str,
        prefix: str | None = None,
        content_type: str | None = None,
    ) -> str:
        """Upload bytes and return gs:// URI."""
        prefix = prefix or self.settings.gcs_input_prefix
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        blob_name = f"{prefix}{timestamp}/{uuid4().hex}_{filename}"
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(
            data,
            content_type=content_type or mimetypes.guess_type(filename)[0],
        )
        uri = f"gs://{self._bucket_name}/{blob_name}"
        logger.info("gcs_upload_complete", uri=uri)
        return uri

    def upload_file(
        self,
        local_path: str | Path,
        prefix: str | None = None,
    ) -> str:
        """Upload a local file and return gs:// URI."""
        path = Path(local_path)
        prefix = prefix or self.settings.gcs_input_prefix
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        blob_name = f"{prefix}{timestamp}/{uuid4().hex}_{path.name}"
        blob = self.bucket.blob(blob_name)
        blob.upload_from_filename(str(path))
        uri = f"gs://{self._bucket_name}/{blob_name}"
        logger.info("gcs_file_upload_complete", uri=uri)
        return uri

    def download_bytes(self, gcs_uri: str) -> bytes:
        """Download object bytes from a gs:// URI."""
        if not gcs_uri.startswith("gs://"):
            raise ValueError(f"Invalid GCS URI: {gcs_uri}")
        path = gcs_uri[5:]
        bucket_name, _, blob_name = path.partition("/")
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.download_as_bytes()

    def upload_text(
        self,
        content: str,
        filename: str,
        prefix: str | None = None,
    ) -> str:
        """Upload text content (e.g. generated BRD markdown)."""
        prefix = prefix or self.settings.gcs_output_prefix
        return self.upload_bytes(
            content.encode("utf-8"),
            filename,
            prefix=prefix,
            content_type="text/markdown",
        )
