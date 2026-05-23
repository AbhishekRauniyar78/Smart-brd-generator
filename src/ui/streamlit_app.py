"""Streamlit UI for the BRD Generation Agent."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings
from src.agents.brd_agent import BRDGenerationAgent
from src.cloud.gcp_auth import check_online_mode
from src.models.schemas import BRDRequest, InputFragment, ModalityType

st.set_page_config(
    page_title="BRD Generation Agent",
    page_icon="📋",
    layout="wide",
)

st.title("📋 BRD Generation Agent")
st.caption(
    "Multi-modal Business Requirements Document generator — "
    "Google Gemini + Vertex AI, Cloud Storage, BigQuery"
)


@st.cache_resource
def get_agent(offline: bool, _mode_key: str, _settings_version: str) -> BRDGenerationAgent:
    """Cache busted via _mode_key and _settings_version when config changes."""
    settings = Settings(offline_mode=offline)
    return BRDGenerationAgent(settings)


def _settings_version() -> str:
    """Changes when settings.py is modified so Streamlit cache refreshes."""
    settings_path = ROOT / "config" / "settings.py"
    try:
        return str(settings_path.stat().st_mtime_ns)
    except OSError:
        return "default"


with st.sidebar:
    st.header("Settings")
    want_offline = st.toggle(
        "Offline / Mock mode",
        value=True,
        help="Run without GCP credentials. Uses local mock clients.",
    )
    st.divider()
    st.markdown("**Online mode options**")
    st.markdown("1. **Vertex AI**: `GCP_PROJECT_ID` + `gcloud auth application-default login`")
    st.markdown("2. **AI Studio**: set `GEMINI_API_KEY` in `.env`")
    st.divider()

    effective_offline = want_offline
    online_status = None
    mode_key = "offline"

    if not want_offline:
        probe = Settings(offline_mode=False)
        online_status = check_online_mode(probe)
        if online_status.ready:
            effective_offline = False
            mode_key = online_status.mode
            if online_status.mode == "api_key":
                st.success("Online: Google AI Studio")
            else:
                st.success("Online: Vertex AI + GCP")
        else:
            st.error("Online mode unavailable")
            st.markdown(online_status.message)
            effective_offline = True
            mode_key = "offline-fallback"
    else:
        st.success("Mock mode active")

agent = get_agent(effective_offline, mode_key, _settings_version())

tab_generate, tab_history, tab_about = st.tabs(["Generate BRD", "Context History", "About"])

with tab_generate:
    col1, col2 = st.columns([1, 1])

    with col1:
        project_name = st.text_input("Project name *", placeholder="Customer Portal Redesign")
        business_context = st.text_area(
            "Business context",
            placeholder="Describe the initiative, goals, and background...",
            height=120,
        )
        stakeholder_notes = st.text_area(
            "Stakeholder notes",
            placeholder="VP Sales wants faster quotes; IT requires SSO...",
            height=80,
        )
        constraints_raw = st.text_input(
            "Constraints (comma-separated)",
            placeholder="SOC 2, Q3 launch, Salesforce integration",
        )

    with col2:
        text_fragments = st.text_area(
            "Text fragments (one per line)",
            placeholder="Users need SSO and role-based dashboards\nSupport handles 200+ password reset tickets/week",
            height=200,
        )
        uploaded_docs = st.file_uploader(
            "Documents (PDF, DOCX, TXT)",
            type=["pdf", "docx", "txt"],
            accept_multiple_files=True,
        )
        uploaded_images = st.file_uploader(
            "Images (PNG, JPG, WebP)",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
        )

    if st.button("Generate BRD", type="primary", use_container_width=True):
        if not project_name.strip():
            st.error("Project name is required.")
        else:
            fragments: list[InputFragment] = []

            for line in text_fragments.strip().splitlines():
                line = line.strip()
                if line:
                    fragments.append(InputFragment(modality=ModalityType.TEXT, content=line))

            for doc in uploaded_docs or []:
                data = doc.read()
                fragments.append(
                    agent.ingest_fragment(
                        modality="document",
                        file_bytes=data,
                        filename=doc.name,
                        mime_type=doc.type,
                    )
                )

            for img in uploaded_images or []:
                data = img.read()
                fragments.append(
                    agent.ingest_fragment(
                        modality="image",
                        content=base64.b64encode(data).decode(),
                        file_bytes=data,
                        filename=img.name,
                        mime_type=img.type,
                    )
                )

            constraints = [c.strip() for c in constraints_raw.split(",") if c.strip()]
            request = BRDRequest(
                project_name=project_name.strip(),
                business_context=business_context,
                stakeholder_notes=stakeholder_notes,
                constraints=constraints,
                fragments=fragments,
            )

            with st.spinner("Processing fragments and generating BRD..."):
                try:
                    response = agent.generate(request)
                    st.session_state["last_response"] = response
                except Exception as exc:
                    st.error(f"Generation failed: {exc}")
                    st.stop()

    if "last_response" in st.session_state:
        resp = st.session_state["last_response"]
        st.success(f"BRD generated — Request ID: `{resp.request_id}`")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Sections", len(resp.sections))
        m2.metric("Rationales", len(resp.decision_rationales))
        m3.metric("Fragments", resp.processing_metadata.get("fragments_processed", 0))
        m4.metric("Model", resp.model_used.split("/")[-1][:20])

        st.download_button(
            "Download Markdown",
            data=resp.markdown_content,
            file_name=f"BRD_{resp.project_name.replace(' ', '_')}.md",
            mime="text/markdown",
        )

        if resp.gcs_output_uri:
            st.caption(f"Artifact: `{resp.gcs_output_uri}`")

        st.subheader("Executive Summary")
        st.markdown(resp.executive_summary)

        doc_tab, rationale_tab, json_tab = st.tabs(["Full BRD", "Decision Rationales", "JSON"])

        with doc_tab:
            st.markdown(resp.markdown_content)

        with rationale_tab:
            for r in resp.decision_rationales:
                with st.expander(f"{r.section} — {r.confidence:.0%} confidence"):
                    st.write(r.reasoning)
                    if r.source_fragment_ids:
                        st.caption(f"Sources: {', '.join(r.source_fragment_ids)}")
                    if r.supporting_evidence:
                        st.markdown("**Evidence:**")
                        for ev in r.supporting_evidence:
                            st.markdown(f"- {ev}")

        with json_tab:
            st.json(json.loads(resp.model_dump_json()))

with tab_history:
    keyword = st.text_input("Search context by keyword", placeholder="portal, SSO, inventory")
    limit = st.slider("Max results", 5, 50, 20)

    if st.button("Query BigQuery / Mock store"):
        try:
            rows = agent.bq.query_context(project_keyword=keyword or None, limit=limit)
            if not rows:
                st.info("No context fragments found. Generate a BRD first.")
            else:
                for row in rows:
                    with st.expander(
                        f"[{row.get('modality', '?')}] {row.get('fragment_id', '')[:8]}…"
                    ):
                        st.text(row.get("extracted_text", "")[:2000])
                        st.caption(f"Ingested: {row.get('ingested_at', 'N/A')}")
        except Exception as exc:
            st.error(str(exc))

with tab_about:
    st.markdown("""
    ### Architecture
    1. **Ingest** text, images, and documents
    2. **Process** via modality-specific processors
    3. **Persist** context to BigQuery (or mock store)
    4. **Generate** BRD with Gemini (or mock engine)
    5. **Store** artifact in Cloud Storage (or local mock dir)
    6. **Log** explainable decisions

    ### CLI
    ```bash
    python -m src.main generate --project "My Project" --text "requirement" --output brd.md
    set OFFLINE_MODE=true
    ```

    ### API
    ```bash
    python -m src.main serve
    ```
    """)
