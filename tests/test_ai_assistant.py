"""Tests for the backend AI assistant parameter workflow."""

import json

from footing_prelim.ai_assistant import (
    AIParameterChanges,
    AIParameterConstraints,
    AISuggestion,
    apply_changes,
    get_ai_suggestions,
    parse_ai_suggestion_json,
)
from footing_prelim.calculations import design_rectangular_footing
from footing_prelim.models import FootingDesignInput


class FakeResponse:
    """Small fake response object matching the SDK attribute used in tests."""

    def __init__(self, output_text: str):
        self.output_text = output_text


class FakeResponsesAPI:
    """Fake nested responses API used for prompt tests."""

    def __init__(self, output_text: str):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.output_text)


class FakeClient:
    """Fake OpenAI client for deterministic tests."""

    def __init__(self, output_text: str):
        self.responses = FakeResponsesAPI(output_text)


def make_design_input() -> FootingDesignInput:
    """Return a reusable baseline project snapshot."""

    return FootingDesignInput(
        service_axial_kips=200.0,
        service_mx_kip_ft=20.0,
        service_my_kip_ft=10.0,
        allowable_bearing_ksf=4.0,
        column_width_ft=1.5,
        column_length_ft=1.5,
        footing_thickness_ft=1.5,
    )


def test_reduce_bearing_pressure_changes_lower_qmax() -> None:
    """Larger AI-suggested plan dimensions should reduce bearing pressure."""

    design_input = make_design_input()
    before = design_rectangular_footing(design_input)
    suggestion = AISuggestion(
        intent="modify_parameters",
        changes=AIParameterChanges(footing_width_ft=10.0, footing_length_ft=10.0),
        constraints=AIParameterConstraints(reduce_bearing_pressure=True),
        reasoning_summary="Increase footing area to reduce bearing pressure.",
        warnings=[],
        confidence="high",
    )

    result = apply_changes(design_input, suggestion, current_result=before)

    assert result.updated_input.trial_footing_width_ft == 10.0
    assert result.updated_input.trial_footing_length_ft == 10.0
    assert result.updated_result.qmax_ksf < before.qmax_ksf
    assert [change.field_label for change in result.applied_changes] == ["Width", "Length"]


def test_keep_square_constraint_forces_matching_dimensions() -> None:
    """The keep-square constraint should make width and length equal."""

    design_input = FootingDesignInput(
        service_axial_kips=180.0,
        service_mx_kip_ft=15.0,
        service_my_kip_ft=5.0,
        allowable_bearing_ksf=4.0,
        column_width_ft=1.5,
        column_length_ft=2.5,
        footing_thickness_ft=1.5,
    )
    before = design_rectangular_footing(design_input)
    suggestion = AISuggestion(
        intent="modify_parameters",
        changes=AIParameterChanges(footing_length_ft=10.0),
        constraints=AIParameterConstraints(keep_square=True),
        reasoning_summary="Use a square footing for a cleaner trial layout.",
        warnings=[],
        confidence="medium",
    )

    result = apply_changes(design_input, suggestion, current_result=before)

    assert result.updated_input.trial_footing_width_ft == 10.0
    assert result.updated_input.trial_footing_length_ft == 10.0
    assert result.updated_result.recommended_width_ft == result.updated_result.recommended_length_ft


def test_invalid_request_values_are_rejected() -> None:
    """Negative or unrealistic AI changes should be rejected before application."""

    design_input = make_design_input()
    suggestion = AISuggestion(
        intent="modify_parameters",
        changes=AIParameterChanges(footing_width_ft=-5.0, footing_length_ft=120.0, fc_psi=-1.0),
        constraints=AIParameterConstraints(),
        reasoning_summary="Bad request.",
        warnings=[],
        confidence="low",
    )

    result = apply_changes(design_input, suggestion)

    assert result.updated_input.trial_footing_width_ft is None
    assert result.updated_input.trial_footing_length_ft is None
    assert result.updated_input.concrete_strength_ksi == design_input.concrete_strength_ksi
    assert result.applied_changes == []
    assert any("Rejected footing width change" in warning for warning in result.warnings)
    assert any("Rejected footing length change" in warning for warning in result.warnings)


def test_no_op_request_leaves_project_unchanged() -> None:
    """Null AI changes should result in a no-op apply result."""

    design_input = make_design_input()
    before = design_rectangular_footing(design_input)
    suggestion = AISuggestion(
        intent="modify_parameters",
        changes=AIParameterChanges(),
        constraints=AIParameterConstraints(),
        reasoning_summary="No project changes requested.",
        warnings=[],
        confidence="medium",
    )

    result = apply_changes(design_input, suggestion, current_result=before)

    assert result.applied_changes == []
    assert result.updated_result.recommended_width_ft == before.recommended_width_ft
    assert result.updated_result.recommended_length_ft == before.recommended_length_ft
    assert any("did not produce any applied parameter changes" in warning for warning in result.warnings)


def test_get_ai_suggestions_parses_strict_json_from_client() -> None:
    """The AI client wrapper should parse structured JSON and keep the prompt payload strict."""

    payload = {
        "intent": "modify_parameters",
        "changes": {
            "footing_width_ft": 9.0,
            "footing_length_ft": 9.0,
            "thickness_in": None,
            "fc_psi": None,
            "fy_psi": None,
        },
        "constraints": {
            "keep_square": True,
            "minimize_size": False,
            "reduce_bearing_pressure": True,
        },
        "reasoning_summary": "Increase width and length together to reduce pressure while keeping the footing square.",
        "warnings": [],
        "confidence": "high",
    }
    client = FakeClient(json.dumps(payload))

    suggestion = get_ai_suggestions(make_design_input(), "reduce bearing pressure", client=client)

    assert suggestion.changes.footing_width_ft == 9.0
    assert suggestion.constraints.keep_square is True
    assert client.responses.calls[0]["model"] == "gpt-5.4"
    assert client.responses.calls[0]["text"]["format"]["strict"] is True
    assert "reduce bearing pressure" in client.responses.calls[0]["input"][1]["content"]


def test_invalid_schema_text_is_rejected() -> None:
    """Strict parsing should reject payloads outside the declared schema."""

    bad_payload = json.dumps({"intent": "wrong", "changes": {}})

    try:
        parse_ai_suggestion_json(bad_payload)
    except ValueError as exc:
        assert "exact top-level schema" in str(exc) or "intent" in str(exc)
    else:  # pragma: no cover - defensive assertion style
        raise AssertionError("Expected parse_ai_suggestion_json to reject invalid payloads.")
