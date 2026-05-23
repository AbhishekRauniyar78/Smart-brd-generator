"""Provision GCP resources for the BRD Generation Agent."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from src.cloud.bigquery_client import BigQueryClient


def run(cmd: list[str], check: bool = True) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=check)


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup GCP for BRD Agent")
    parser.add_argument("--project", required=True, help="GCP project ID")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--bucket", default="brd-agent-artifacts")
    parser.add_argument("--skip-apis", action="store_true")
    args = parser.parse_args()

    project = args.project
    region = args.region

    if not args.skip_apis:
        apis = [
            "aiplatform.googleapis.com",
            "storage.googleapis.com",
            "bigquery.googleapis.com",
            "run.googleapis.com",
        ]
        run(["gcloud", "config", "set", "project", project])
        run([
            "gcloud", "services", "enable",
            *apis,
            f"--project={project}",
        ])

    # Create GCS bucket
    try:
        run([
            "gcloud", "storage", "buckets", "create",
            f"gs://{args.bucket}",
            f"--project={project}",
            f"--location={region}",
            "--uniform-bucket-level-access",
        ])
    except subprocess.CalledProcessError:
        print(f"Bucket gs://{args.bucket} may already exist.")

    # Create BigQuery tables
    import os
    os.environ["GCP_PROJECT_ID"] = project
    settings = get_settings()
    settings.gcp_project_id = project
    bq = BigQueryClient(settings)
    bq.ensure_tables()
    print("\nSetup complete.")
    print(f"  Project:  {project}")
    print(f"  Bucket:   gs://{args.bucket}")
    print(f"  Dataset:  {settings.bq_dataset}")
    print("\nCopy .env.example to .env and set GCP_PROJECT_ID.")


if __name__ == "__main__":
    main()
