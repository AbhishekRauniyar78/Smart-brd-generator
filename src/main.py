"""Entry point: FastAPI server and CLI for BRD generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from src.api.routes import router
from src.agents.brd_agent import BRDGenerationAgent
from src.models.schemas import BRDRequest, InputFragment, ModalityType

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

app = FastAPI(
    title="BRD Generation Agent",
    description=(
        "Multi-modal AI system using Google Gemini and GCP "
        "(Vertex AI, Cloud Storage, BigQuery) for explainable BRD generation."
    ),
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="BRD Generation Agent CLI")
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate", help="Generate a BRD from inputs")
    gen.add_argument("--project", required=True, help="Project name")
    gen.add_argument("--context", default="", help="Business context")
    gen.add_argument("--text", action="append", default=[], help="Text fragment(s)")
    gen.add_argument("--document", action="append", default=[], help="Document path(s)")
    gen.add_argument("--image", action="append", default=[], help="Image path(s)")
    gen.add_argument("--output", default="", help="Save markdown to file")
    gen.add_argument("--json", action="store_true", help="Print full JSON response")

    sub.add_parser("serve", help="Start FastAPI server")
    sub.add_parser("ui", help="Start Streamlit UI")
    sub.add_parser("setup", help="Create BigQuery tables")

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "serve":
        uvicorn.run(
            "src.main:app",
            host=settings.api_host,
            port=settings.api_port,
            reload=False,
        )
        return

    if args.command == "ui":
        import subprocess
        app_path = ROOT / "src" / "ui" / "streamlit_app.py"
        subprocess.run([
            sys.executable, "-m", "streamlit", "run",
            str(app_path),
            "--server.port", "8501",
        ], check=True)
        return

    if args.command == "setup":
        from src.cloud.bigquery_client import BigQueryClient
        BigQueryClient(settings).ensure_tables()
        print("BigQuery dataset and tables ready.")
        return

    if args.command == "generate":
        agent = BRDGenerationAgent(settings)
        fragments: list[InputFragment] = []

        for t in args.text:
            fragments.append(InputFragment(modality=ModalityType.TEXT, content=t))

        for doc_path in args.document:
            path = Path(doc_path)
            data = path.read_bytes()
            fragments.append(
                agent.ingest_fragment(
                    modality="document",
                    file_bytes=data,
                    filename=path.name,
                )
            )

        for img_path in args.image:
            path = Path(img_path)
            data = path.read_bytes()
            fragments.append(
                agent.ingest_fragment(
                    modality="image",
                    content=__import__("base64").b64encode(data).decode(),
                    file_bytes=data,
                    filename=path.name,
                )
            )

        request = BRDRequest(
            project_name=args.project,
            business_context=args.context,
            fragments=fragments,
        )
        response = agent.generate(request)

        if args.json:
            print(response.model_dump_json(indent=2))
        else:
            print(response.markdown_content)

        if args.output:
            Path(args.output).write_text(response.markdown_content, encoding="utf-8")
            print(f"\nSaved to {args.output}", file=sys.stderr)

        if response.gcs_output_uri:
            print(f"GCS artifact: {response.gcs_output_uri}", file=sys.stderr)
        return

    parser.print_help()


if __name__ == "__main__":
    run_cli()
