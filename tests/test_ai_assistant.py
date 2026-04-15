"""Tests for the deterministic natural-language footing command layer."""

from __future__ import annotations

import json
import math

import pytest

from footing_prelim.ai_assistant import (
    AISuggestion,
    apply_changes,
    get_ai_suggestions,
    parse_ai_suggestion_json,
    run_ai_design_assistant_workflow,
)
from footing_prelim.calculations import design_rectangular_footing, round_up_to_increment
from footing_prelim.models import FootingDesignInput


def make_design_input(**overrides: float | None) -> FootingDesignInput:
    """Return a predictable baseline project state for command tests."""

    payload = {
        "service_axial_kips": 120.0,
        "service_mx_kip_ft": 0.0,
        "service_my_kip_ft": 0.0,
        "allowable_bearing_ksf": 4.0,
        "column_width_ft": 1.5,
        "column_length_ft": 2.0,
        "footing_thickness_ft": 1.0,
        "trial_footing_width_ft": 10.0,
        "trial_footing_length_ft": 12.0,
        "concrete_strength_ksi": 4.0,
        "steel_yield_ksi": 60.0,
        "dimension_increment_ft": 0.5,
        "min_footing_width_ft": 2.0,
        "min_footing_length_ft": 2.0,
        "max_footing_width_ft": 30.0,
        "max_footing_length_ft": 30.0,
    }
    payload.update(overrides)
    return FootingDesignInput(**payload)


def visible_footing_dimensions(design_input: FootingDesignInput) -> tuple[float, float]:
    """Return the live footing size shown by the current result state."""

    result = design_rectangular_footing(design_input)
    width_ft = result.recommended_width_ft or design_input.trial_footing_width_ft or design_input.min_footing_width_ft
    length_ft = result.recommended_length_ft or design_input.trial_footing_length_ft or design_input.min_footing_length_ft
    return width_ft, length_ft


def assert_actions_match(actual_actions, expected_actions) -> None:
    """Compare action tuples with tolerant numeric assertions."""

    assert len(actual_actions) == len(expected_actions)
    for actual, expected in zip(actual_actions, expected_actions):
        expected_field, expected_operation, expected_value, expected_source = expected
        assert actual.field == expected_field
        assert actual.operation == expected_operation
        assert actual.source_field == expected_source
        if expected_value is None:
            assert actual.value is None
        else:
            assert actual.value == pytest.approx(expected_value)


PARSE_CASES = [
    {
        "prompt": "decrease footing size in half",
        "expected": [
            ("trial_footing_width_ft", "multiply", 0.5, None),
            ("trial_footing_length_ft", "multiply", 0.5, None),
        ],
    },
    {
        "prompt": "decrese footing size in haf",
        "expected": [
            ("trial_footing_width_ft", "multiply", 0.5, None),
            ("trial_footing_length_ft", "multiply", 0.5, None),
        ],
        "corrections": 2,
    },
    {
        "prompt": "make the footing 2 feet wider",
        "expected": [("trial_footing_width_ft", "add", 2.0, None)],
    },
    {
        "prompt": "make footing 1 foot longer",
        "expected": [("trial_footing_length_ft", "add", 1.0, None)],
    },
    {
        "prompt": "make footing 25% wider",
        "expected": [("trial_footing_width_ft", "multiply", 1.25, None)],
    },
    {
        "prompt": "decrease footing width by 25 percent",
        "expected": [("trial_footing_width_ft", "multiply", 0.75, None)],
    },
    {
        "prompt": "decrese footing widht by 25 persent",
        "expected": [("trial_footing_width_ft", "multiply", 0.75, None)],
        "corrections": 3,
    },
    {
        "prompt": "increase thickness by 2 inches",
        "expected": [("footing_thickness_ft", "add", 2.0 / 12.0, None)],
    },
    {
        "prompt": "increase thickness to 18 inches",
        "expected": [("footing_thickness_ft", "set", 1.5, None)],
    },
    {
        "prompt": "switch to 5 ksi concrete",
        "expected": [("concrete_strength_ksi", "set", 5.0, None)],
    },
    {
        "prompt": "change concret strenght to 5 ksi",
        "expected": [("concrete_strength_ksi", "set", 5.0, None)],
        "corrections": 2,
    },
    {
        "prompt": "switch to 3500 psf bearing",
        "expected": [("allowable_bearing_ksf", "set", 3.5, None)],
    },
    {
        "prompt": "change soil bearing to 3000 psf",
        "expected": [("allowable_bearing_ksf", "set", 3.0, None)],
    },
    {
        "prompt": "decrease soil berring by 10 percent",
        "expected": [("allowable_bearing_ksf", "multiply", 0.9, None)],
        "corrections": 1,
    },
    {
        "prompt": "reduce service axial load by 15 percent",
        "expected": [("service_axial_kips", "multiply", 0.85, None)],
    },
    {
        "prompt": "reduce column load by 10 percent",
        "expected": [("service_axial_kips", "multiply", 0.9, None)],
    },
    {
        "prompt": "reduce service moment mx by 20 percent",
        "expected": [("service_mx_kip_ft", "multiply", 0.8, None)],
        "overrides": {"service_mx_kip_ft": 20.0},
    },
    {
        "prompt": "reset eccentricity inputs",
        "expected": [
            ("service_mx_kip_ft", "reset", None, None),
            ("service_my_kip_ft", "reset", None, None),
        ],
        "overrides": {"service_mx_kip_ft": 20.0, "service_my_kip_ft": 10.0},
    },
    {
        "prompt": "use a 16 inch column",
        "expected": [
            ("column_width_ft", "set", 16.0 / 12.0, None),
            ("column_length_ft", "set", 16.0 / 12.0, None),
        ],
    },
    {
        "prompt": "double the column size",
        "expected": [
            ("column_width_ft", "multiply", 2.0, None),
            ("column_length_ft", "multiply", 2.0, None),
        ],
    },
    {
        "prompt": "make the footing 8 ft by 8 ft",
        "expected": [
            ("trial_footing_width_ft", "set", 8.0, None),
            ("trial_footing_length_ft", "set", 8.0, None),
        ],
    },
    {
        "prompt": "use 12 inch thick footing and 4 ksi concrete",
        "expected": [
            ("footing_thickness_ft", "set", 1.0, None),
            ("concrete_strength_ksi", "set", 4.0, None),
        ],
    },
    {
        "prompt": "make everything match a lighter load case",
        "expected": [
            ("service_axial_kips", "multiply", 0.9, None),
            ("service_mx_kip_ft", "multiply", 0.9, None),
            ("service_my_kip_ft", "multiply", 0.9, None),
        ],
        "overrides": {"service_mx_kip_ft": 20.0, "service_my_kip_ft": 10.0},
    },
    {
        "prompt": "make everything match a heavier load case",
        "expected": [
            ("service_axial_kips", "multiply", 1.1, None),
            ("service_mx_kip_ft", "multiply", 1.1, None),
            ("service_my_kip_ft", "multiply", 1.1, None),
        ],
        "overrides": {"service_mx_kip_ft": 20.0, "service_my_kip_ft": 10.0},
    },
    {
        "prompt": "reset footing dimensions",
        "expected": [
            ("trial_footing_width_ft", "reset", None, None),
            ("trial_footing_length_ft", "reset", None, None),
        ],
    },
    {
        "prompt": "make it smaller",
        "expected": [
            ("trial_footing_width_ft", "subtract", 0.5, None),
            ("trial_footing_length_ft", "subtract", 0.5, None),
        ],
    },
    {
        "prompt": "reduce loads",
        "expected": [
            ("service_axial_kips", "multiply", 0.9, None),
            ("service_mx_kip_ft", "multiply", 0.9, None),
            ("service_my_kip_ft", "multiply", 0.9, None),
        ],
        "overrides": {"service_mx_kip_ft": 20.0, "service_my_kip_ft": 10.0},
    },
    {
        "prompt": "make the footing square",
        "expected": [("trial_footing_width_ft", "copy_from", None, "trial_footing_length_ft")],
    },
    {
        "prompt": "change the long side to 14 feet",
        "expected": [("trial_footing_length_ft", "set", 14.0, None)],
    },
    {
        "prompt": "change the short side to 6 feet",
        "expected": [("trial_footing_width_ft", "set", 6.0, None)],
    },
    {
        "prompt": "make it much wider than the column",
        "expected": [("trial_footing_width_ft", "set", 12.0, None)],
        "overrides": {"column_width_ft": 6.0, "trial_footing_width_ft": 7.0},
    },
]


@pytest.mark.parametrize("case", PARSE_CASES, ids=[case["prompt"] for case in PARSE_CASES])
def test_parser_builds_expected_structured_actions(case) -> None:
    """Natural-language prompts should resolve to validated field actions."""

    design_input = make_design_input(**case.get("overrides", {}))
    suggestion = get_ai_suggestions(design_input, case["prompt"])

    assert suggestion.intent == "update_parameters"
    assert_actions_match(suggestion.changes, case["expected"])
    assert len(suggestion.fuzzy_corrections) == case.get("corrections", 0)
    assert not any(warning.startswith("Could not apply") for warning in suggestion.warnings)


APPLY_CASES = [
    {
        "prompt": "decrease footing size in half",
        "expected_input": {"trial_footing_width_ft": 5.0, "trial_footing_length_ft": 6.0},
    },
    {
        "prompt": "make the footing 2 feet wider",
        "expected_input": {"trial_footing_width_ft": 12.0},
    },
    {
        "prompt": "make footing 25% wider",
        "expected_input": {"trial_footing_width_ft": 12.5},
    },
    {
        "prompt": "make it smaller",
        "expected_input": {"trial_footing_width_ft": 9.5, "trial_footing_length_ft": 11.5},
    },
    {
        "prompt": "make the footing square",
        "expected_input": {"trial_footing_width_ft": 12.0, "trial_footing_length_ft": 12.0},
    },
    {
        "prompt": "change the long side to 14 feet",
        "expected_input": {"trial_footing_length_ft": 14.0},
    },
    {
        "prompt": "change the short side to 6 feet",
        "expected_input": {"trial_footing_width_ft": 6.0},
    },
    {
        "prompt": "make the footing 8 ft by 8 ft",
        "expected_input": {"trial_footing_width_ft": 8.0, "trial_footing_length_ft": 8.0},
    },
    {
        "prompt": "reset footing dimensions",
        "expected_input": {"trial_footing_width_ft": None, "trial_footing_length_ft": None},
    },
    {
        "prompt": "use a 16 inch column",
        "expected_input": {"column_width_ft": 16.0 / 12.0, "column_length_ft": 16.0 / 12.0},
    },
    {
        "prompt": "double the column size",
        "expected_input": {"column_width_ft": 3.0, "column_length_ft": 4.0},
    },
    {
        "prompt": "switch to 5 ksi concrete",
        "expected_input": {"concrete_strength_ksi": 5.0},
    },
    {
        "prompt": "change concret strenght to 5 ksi",
        "expected_input": {"concrete_strength_ksi": 5.0},
        "corrections": 2,
    },
    {
        "prompt": "switch to 3500 psf bearing",
        "expected_input": {"allowable_bearing_ksf": 3.5},
    },
    {
        "prompt": "decrease soil berring by 10 percent",
        "expected_input": {"allowable_bearing_ksf": 3.6},
        "corrections": 1,
    },
    {
        "prompt": "increase thickness by 2 inches",
        "expected_input": {"footing_thickness_ft": 14.0 / 12.0},
    },
    {
        "prompt": "increase thickness to 18 inches",
        "expected_input": {"footing_thickness_ft": 1.5},
    },
    {
        "prompt": "use 12 inch thick footing and 5 ksi concrete",
        "expected_input": {"footing_thickness_ft": 1.0, "concrete_strength_ksi": 5.0},
    },
    {
        "prompt": "reduce column load by 10 percent",
        "expected_input": {"service_axial_kips": 108.0},
    },
    {
        "prompt": "make everything match a lighter load case",
        "expected_input": {"service_axial_kips": 108.0, "service_mx_kip_ft": 18.0, "service_my_kip_ft": 9.0},
        "overrides": {"service_mx_kip_ft": 20.0, "service_my_kip_ft": 10.0},
    },
    {
        "prompt": "make everything match a heavier load case",
        "expected_input": {"service_axial_kips": 132.0, "service_mx_kip_ft": 22.0, "service_my_kip_ft": 11.0},
        "overrides": {"service_mx_kip_ft": 20.0, "service_my_kip_ft": 10.0},
    },
    {
        "prompt": "reset eccentricity inputs",
        "expected_input": {"service_mx_kip_ft": 0.0, "service_my_kip_ft": 0.0},
        "overrides": {"service_mx_kip_ft": 20.0, "service_my_kip_ft": 10.0},
    },
    {
        "prompt": "make it much wider than the column",
        "expected_input": {"trial_footing_width_ft": 12.0},
        "overrides": {"column_width_ft": 6.0, "trial_footing_width_ft": 7.0},
    },
]


@pytest.mark.parametrize("case", APPLY_CASES, ids=[case["prompt"] for case in APPLY_CASES])
def test_workflow_updates_real_model_inputs(case) -> None:
    """Structured command actions should update the real footing input model."""

    design_input = make_design_input(**case.get("overrides", {}))
    result = run_ai_design_assistant_workflow(design_input, case["prompt"])

    for field_name, expected_value in case["expected_input"].items():
        actual_value = getattr(result.updated_input, field_name)
        if expected_value is None:
            assert actual_value is None
        else:
            assert actual_value == pytest.approx(expected_value)

    assert result.updated_result.input_data == result.updated_input
    assert len(result.suggestion.fuzzy_corrections) == case.get("corrections", 0)


@pytest.mark.parametrize(
    ("prompt", "warning_fragment"),
    [
        ("make it safer", "no single editable parameter clearly maps"),
        ("improve the design", "no single editable parameter clearly maps"),
        ("fix the bad value", "no single editable parameter clearly maps"),
        ("make it stronger", "no single editable parameter clearly maps"),
    ],
)
def test_parser_requests_clarification_only_for_truly_ambiguous_commands(prompt: str, warning_fragment: str) -> None:
    """Vague commands should not mutate the model without a defensible interpretation."""

    suggestion = get_ai_suggestions(make_design_input(), prompt)

    assert suggestion.intent == "clarification_required"
    assert suggestion.changes == []
    assert any(warning_fragment in warning for warning in suggestion.warnings)


@pytest.mark.parametrize(
    "case",
    [
        {
            "prompt": "change footing width to 0 ft",
            "warning_fragment": "must remain positive",
        },
        {
            "prompt": "increase thickness to 2 inches",
            "warning_fragment": "at least 6.00 in",
        },
        {
            "prompt": "switch to 50 psf bearing",
            "warning_fragment": "at least 0.10 ksf",
        },
        {
            "prompt": "switch to 1 ksi concrete",
            "warning_fragment": "at least 2.50 ksi",
        },
        {
            "prompt": "reset service axial load",
            "warning_fragment": "not resettable",
        },
    ],
    ids=lambda case: case["prompt"],
)
def test_invalid_or_unsupported_commands_are_rejected_with_clear_warnings(case) -> None:
    """Invalid edits should fail safely without mutating unrelated input values."""

    design_input = make_design_input()
    result = run_ai_design_assistant_workflow(design_input, case["prompt"])

    assert any(case["warning_fragment"] in warning for warning in result.warnings)
    assert result.updated_input == design_input
    assert result.applied_changes == []


@pytest.mark.parametrize(
    "case",
    [
        {
            "prompt": "make it much wider than the column",
            "overrides": {"trial_footing_width_ft": 12.0, "column_width_ft": 5.0},
        },
        {
            "prompt": "make the footing square",
            "overrides": {"trial_footing_width_ft": 12.0, "trial_footing_length_ft": 12.0},
        },
    ],
    ids=lambda case: case["prompt"],
)
def test_no_op_commands_return_update_intent_and_no_change_warning(case) -> None:
    """Already-satisfied requests should not be misclassified as unclear commands."""

    suggestion = get_ai_suggestions(make_design_input(**case["overrides"]), case["prompt"])
    result = apply_changes(make_design_input(**case["overrides"]), suggestion)

    assert suggestion.intent == "update_parameters"
    assert suggestion.changes == []
    assert any(warning.startswith("No changes were needed") for warning in suggestion.warnings)
    assert result.applied_changes == []


def test_relative_footing_edits_use_live_current_dimensions_when_trial_values_are_empty() -> None:
    """Relative footing edits should use the current visible footing size, not raw None fields."""

    design_input = make_design_input(
        service_axial_kips=80.0,
        trial_footing_width_ft=None,
        trial_footing_length_ft=None,
        service_mx_kip_ft=0.0,
        service_my_kip_ft=0.0,
    )
    before_width_ft, before_length_ft = visible_footing_dimensions(design_input)

    result = run_ai_design_assistant_workflow(design_input, "decrease footing size in half")

    assert result.updated_input.trial_footing_width_ft == pytest.approx(
        round_up_to_increment(before_width_ft * 0.5, design_input.dimension_increment_ft)
    )
    assert result.updated_input.trial_footing_length_ft == pytest.approx(
        round_up_to_increment(before_length_ft * 0.5, design_input.dimension_increment_ft)
    )


def test_round_trip_json_payload_rebuilds_typed_suggestion() -> None:
    """Stored structured command payloads should deserialize back into typed suggestions."""

    suggestion = get_ai_suggestions(make_design_input(), "decrese footing widht by 25 persent")
    payload = {
        "intent": suggestion.intent,
        "normalized_text": suggestion.normalized_text,
        "fuzzy_corrections": [
            {
                "from_text": item.from_text,
                "to_text": item.to_text,
                "confidence": item.confidence,
            }
            for item in suggestion.fuzzy_corrections
        ],
        "changes": [
            {
                "field": item.field,
                "operation": item.operation,
                "value": item.value,
                "source_field": item.source_field,
                "unit": item.unit,
                "clause": item.clause,
            }
            for item in suggestion.changes
        ],
        "reasoning_summary": suggestion.reasoning_summary,
        "warnings": suggestion.warnings,
        "confidence": suggestion.confidence,
    }

    rebuilt = parse_ai_suggestion_json(json.dumps(payload))

    assert isinstance(rebuilt, AISuggestion)
    assert rebuilt.normalized_text == "decrease footing width by 25 percent"
    assert_actions_match(rebuilt.changes, [("trial_footing_width_ft", "multiply", 0.75, None)])


def test_invalid_json_schema_is_rejected() -> None:
    """Stored payloads must match the strict structured command schema."""

    with pytest.raises(ValueError):
        parse_ai_suggestion_json({"intent": "wrong", "changes": []})


def test_workflow_surfaces_parameter_change_warnings_when_result_still_recommends_larger_footing() -> None:
    """The user should be told when a trial size edit does not control the final live recommendation."""

    design_input = make_design_input(service_axial_kips=200.0, trial_footing_width_ft=None, trial_footing_length_ft=None)
    result = run_ai_design_assistant_workflow(design_input, "decrease footing size in half")

    assert any("current calculation still recommends" in warning for warning in result.warnings)
    assert "Reduced footing width" in result.explanation
    assert result.applied_changes


def test_multi_edit_command_preserves_deterministic_action_order() -> None:
    """Multi-clause commands should apply edits in the same order they were written."""

    suggestion = get_ai_suggestions(make_design_input(), "make footing 2 feet wider and 1 foot longer")

    assert_actions_match(
        suggestion.changes,
        [
            ("trial_footing_width_ft", "add", 2.0, None),
            ("trial_footing_length_ft", "add", 1.0, None),
        ],
    )


def test_fuzzy_correction_summary_is_included_in_user_response() -> None:
    """User-facing explanations should acknowledge safe typo corrections when applied."""

    result = run_ai_design_assistant_workflow(make_design_input(), "change concret strenght to 5 ksi")

    assert "Corrected 'concret' to 'concrete' and 'strenght' to 'strength'." in result.explanation
    assert result.updated_input.concrete_strength_ksi == pytest.approx(5.0)


def test_apply_changes_accepts_serialized_suggestion_payloads() -> None:
    """The apply API should accept serialized structured suggestions, not only typed objects."""

    suggestion = get_ai_suggestions(make_design_input(), "switch to 5 ksi concrete")
    payload = json.dumps(
        {
            "intent": suggestion.intent,
            "normalized_text": suggestion.normalized_text,
            "fuzzy_corrections": [],
            "changes": [
                {
                    "field": "concrete_strength_ksi",
                    "operation": "set",
                    "value": 5.0,
                    "source_field": None,
                    "unit": "ksi",
                    "clause": "switch to 5 ksi concrete",
                }
            ],
            "reasoning_summary": suggestion.reasoning_summary,
            "warnings": [],
            "confidence": suggestion.confidence,
        }
    )

    result = apply_changes(make_design_input(), payload)

    assert result.updated_input.concrete_strength_ksi == pytest.approx(5.0)
    assert result.applied_changes[0].field_label == "Concrete Strength"
