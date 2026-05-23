"""Tests for Pydantic schemas."""

from src.models.schemas import (
    BRDRequest,
    DecisionRationale,
    InputFragment,
    ModalityType,
)


def test_input_fragment_defaults():
    frag = InputFragment(modality=ModalityType.TEXT, content="Hello")
    assert frag.id
    assert frag.modality == ModalityType.TEXT
    assert frag.content == "Hello"


def test_brd_request():
    req = BRDRequest(
        project_name="Test Project",
        fragments=[InputFragment(modality=ModalityType.TEXT, content="Req 1")],
        constraints=["SOC 2"],
    )
    assert req.project_name == "Test Project"
    assert len(req.fragments) == 1
    assert req.constraints == ["SOC 2"]


def test_decision_rationale_bounds():
    r = DecisionRationale(
        section="Scope",
        reasoning="Based on input",
        confidence=0.9,
        source_fragment_ids=["abc"],
    )
    assert r.confidence == 0.9
