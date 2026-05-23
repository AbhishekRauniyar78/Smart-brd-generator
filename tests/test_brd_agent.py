"""Integration tests for BRD agent in offline mode."""

from src.agents.brd_agent import BRDGenerationAgent
from src.models.schemas import BRDRequest, InputFragment, ModalityType


def test_generate_brd_offline(offline_settings):
    agent = BRDGenerationAgent(offline_settings)
    request = BRDRequest(
        project_name="Customer Portal",
        business_context="Modernize B2B portal",
        fragments=[
            InputFragment(
                modality=ModalityType.TEXT,
                content="Users need SSO and dashboards",
            ),
            InputFragment(
                modality=ModalityType.TEXT,
                content="Support team handles 200 password reset tickets weekly",
            ),
        ],
        constraints=["SOC 2", "Q3 launch"],
    )

    response = agent.generate(request)

    assert response.request_id
    assert response.project_name == "Customer Portal"
    assert response.executive_summary
    assert response.markdown_content
    assert "# Business Requirements Document" in response.markdown_content
    assert response.processing_metadata.get("offline_mode") is True
    assert len(response.decision_rationales) >= 1
    assert response.gcs_output_uri
