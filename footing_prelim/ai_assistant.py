"""AI parameter suggestion backend for the preliminary footing assistant."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Literal, Optional

from footing_prelim.calculations import design_rectangular_footing
from footing_prelim.models import FootingDesignInput, FootingDesignResult

MODEL_NAME = "gpt-5.4"
ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT_DIR / "ai_assistant.log"
LOGGER = logging.getLogger("footing_prelim.ai_assistant")

MIN_FOOTING_DIMENSION_FT = 1.0
MAX_FOOTING_DIMENSION_FT = 100.0
MIN_THICKNESS_IN = 6.0
MAX_THICKNESS_IN = 120.0
MIN_FC_PSI = 2_500.0
MAX_FC_PSI = 15_000.0
MIN_FY_PSI = 40_000.0
MAX_FY_PSI = 100_000.0

AI_SUGGESTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "ai_design_assistant_suggestion",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {"type": "string", "enum": ["modify_parameters"]},
            "changes": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "footing_width_ft": {"type": ["number", "null"]},
                    "footing_length_ft": {"type": ["number", "null"]},
                    "thickness_in": {"type": ["number", "null"]},
                    "fc_psi": {"type": ["number", "null"]},
                    "fy_psi": {"type": ["number", "null"]},
                },
                "required": [
                    "footing_width_ft",
                    "footing_length_ft",
                    "thickness_in",
                    "fc_psi",
                    "fy_psi",
                ],
            },
            "constraints": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "keep_square": {"type": "boolean"},
                    "minimize_size": {"type": "boolean"},
                    "reduce_bearing_pressure": {"type": "boolean"},
                },
                "required": [
                    "keep_square",
                    "minimize_size",
                    "reduce_bearing_pressure",
                ],
            },
            "reasoning_summary": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": [
            "intent",
            "changes",
            "constraints",
            "reasoning_summary",
            "warnings",
            "confidence",
        ],
    },
}


@dataclass
class AIParameterChanges:
    """Structured AI change suggestions."""

    footing_width_ft: Optional[float] = None
    footing_length_ft: Optional[float] = None
    thickness_in: Optional[float] = None
    fc_psi: Optional[float] = None
    fy_psi: Optional[float] = None


@dataclass
class AIParameterConstraints:
    """Non-numeric design intent flags returned by the AI."""

    keep_square: bool = False
    minimize_size: bool = False
    reduce_bearing_pressure: bool = False


@dataclass
class AISuggestion:
    """Validated AI suggestion payload."""

    intent: Literal["modify_parameters"]
    changes: AIParameterChanges
    constraints: AIParameterConstraints
    reasoning_summary: str
    warnings: list[str]
    confidence: Literal["low", "medium", "high"]


@dataclass
class AppliedParameterChange:
    """A single before/after change entry for UI diff rendering."""

    field_label: str
    before_value: float
    after_value: float
    units: str


@dataclass
class AIApplyResult:
    """Result of safely applying AI parameter suggestions."""

    suggestion: AISuggestion
    before_result: FootingDesignResult
    updated_input: FootingDesignInput
    updated_result: FootingDesignResult
    applied_changes: list[AppliedParameterChange]
    explanation: str
    warnings: list[str]


def build_ai_prompt_messages(
    project_data: FootingDesignInput | dict[str, Any],
    user_prompt: str,
    current_result: FootingDesignResult | None = None,
) -> list[dict[str, str]]:
    """Build the prompt payload sent to the AI model."""

    design_input = normalize_project_data(project_data)
    current_width_ft, current_length_ft = current_footing_dimensions_ft(design_input, current_result)
    thickness_in = design_input.footing_thickness_ft * 12.0

    return [
        {
            "role": "system",
            "content": (
                "You are a structural engineering assistant. "
                "You DO NOT perform calculations. "
                "You ONLY suggest parameter adjustments. "
                "Return ONLY valid JSON matching the schema."
            ),
        },
        {
            "role": "user",
            "content": (
                "Current footing parameters:\n"
                f"- Width: {format_value(current_width_ft, 'ft')}\n"
                f"- Length: {format_value(current_length_ft, 'ft')}\n"
                f"- Thickness: {format_value(thickness_in, 'in')}\n"
                f"- Load P: {format_value(design_input.service_axial_kips, 'kips')}\n"
                f"- Moments: {format_value(design_input.service_mx_kip_ft, 'kip-ft')}, "
                f"{format_value(design_input.service_my_kip_ft, 'kip-ft')}\n"
                f"- Soil bearing: {format_value(design_input.allowable_bearing_ksf, 'ksf')}\n\n"
                "User request:\n"
                f'"{user_prompt.strip()}"\n\n'
                "Return structured parameter changes."
            ),
        },
    ]


def get_ai_suggestions(
    project_data: FootingDesignInput | dict[str, Any],
    user_prompt: str,
    client: Any | None = None,
    model: str = MODEL_NAME,
    current_result: FootingDesignResult | None = None,
) -> AISuggestion:
    """Send the project snapshot and user request to the AI model."""

    if not user_prompt or not user_prompt.strip():
        raise ValueError("User prompt cannot be empty.")

    design_input = normalize_project_data(project_data)
    messages = build_ai_prompt_messages(design_input, user_prompt, current_result=current_result)

    if client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on optional runtime dependency
            raise RuntimeError(
                "OpenAI Python SDK is not installed. Install `openai` and configure OPENAI_API_KEY."
            ) from exc
        client = OpenAI()

    response = client.responses.create(
        model=model,
        input=messages,
        text={"format": AI_SUGGESTION_RESPONSE_FORMAT},
    )
    raw_output = getattr(response, "output_text", "")
    if not raw_output:
        raise RuntimeError("AI response did not include structured JSON output.")

    suggestion = parse_ai_suggestion_json(raw_output)
    log_ai_interaction(
        event="ai_suggestion_generated",
        payload={
            "model": model,
            "user_prompt": user_prompt,
            "messages": messages,
            "raw_output": raw_output,
            "validated_suggestion": asdict(suggestion),
        },
    )
    return suggestion


def parse_ai_suggestion_json(raw_json: str | dict[str, Any]) -> AISuggestion:
    """Validate and parse strict JSON into a typed AI suggestion object."""

    if isinstance(raw_json, str):
        payload = json.loads(raw_json)
    else:
        payload = raw_json

    expected_top_level = {
        "intent",
        "changes",
        "constraints",
        "reasoning_summary",
        "warnings",
        "confidence",
    }
    if set(payload.keys()) != expected_top_level:
        raise ValueError("AI response must match the exact top-level schema.")

    if payload["intent"] != "modify_parameters":
        raise ValueError("AI response intent must be 'modify_parameters'.")

    changes_payload = payload["changes"]
    constraints_payload = payload["constraints"]

    expected_changes = {
        "footing_width_ft",
        "footing_length_ft",
        "thickness_in",
        "fc_psi",
        "fy_psi",
    }
    if set(changes_payload.keys()) != expected_changes:
        raise ValueError("AI response changes object must match the exact schema.")

    expected_constraints = {"keep_square", "minimize_size", "reduce_bearing_pressure"}
    if set(constraints_payload.keys()) != expected_constraints:
        raise ValueError("AI response constraints object must match the exact schema.")

    warnings = payload["warnings"]
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ValueError("AI response warnings must be a list of strings.")

    confidence = payload["confidence"]
    if confidence not in {"low", "medium", "high"}:
        raise ValueError("AI response confidence must be low, medium, or high.")

    reasoning_summary = payload["reasoning_summary"]
    if not isinstance(reasoning_summary, str):
        raise ValueError("AI response reasoning_summary must be a string.")

    changes = AIParameterChanges(
        footing_width_ft=validate_optional_number(changes_payload["footing_width_ft"], "footing_width_ft"),
        footing_length_ft=validate_optional_number(changes_payload["footing_length_ft"], "footing_length_ft"),
        thickness_in=validate_optional_number(changes_payload["thickness_in"], "thickness_in"),
        fc_psi=validate_optional_number(changes_payload["fc_psi"], "fc_psi"),
        fy_psi=validate_optional_number(changes_payload["fy_psi"], "fy_psi"),
    )

    constraints = AIParameterConstraints(
        keep_square=validate_boolean(constraints_payload["keep_square"], "keep_square"),
        minimize_size=validate_boolean(constraints_payload["minimize_size"], "minimize_size"),
        reduce_bearing_pressure=validate_boolean(
            constraints_payload["reduce_bearing_pressure"],
            "reduce_bearing_pressure",
        ),
    )

    return AISuggestion(
        intent="modify_parameters",
        changes=changes,
        constraints=constraints,
        reasoning_summary=reasoning_summary,
        warnings=warnings,
        confidence=confidence,
    )


def apply_changes(
    project_data: FootingDesignInput | dict[str, Any],
    suggestion: AISuggestion | dict[str, Any] | str,
    current_result: FootingDesignResult | None = None,
) -> AIApplyResult:
    """Safely apply validated AI parameter changes and rerun the engine."""

    design_input = normalize_project_data(project_data)
    validated_suggestion = ensure_suggestion(suggestion)
    before_result = current_result or design_rectangular_footing(design_input)

    updated_input = replace(design_input)
    warnings = list(validated_suggestion.warnings)
    applied_changes: list[AppliedParameterChange] = []

    current_width_ft, current_length_ft = current_footing_dimensions_ft(design_input, before_result)
    target_width_ft = validate_dimension_change(
        validated_suggestion.changes.footing_width_ft,
        "footing width",
        warnings,
    )
    target_length_ft = validate_dimension_change(
        validated_suggestion.changes.footing_length_ft,
        "footing length",
        warnings,
    )

    if validated_suggestion.constraints.keep_square:
        square_dimension_ft = max(
            value
            for value in [
                target_width_ft,
                target_length_ft,
                current_width_ft,
                current_length_ft,
            ]
            if value is not None
        )
        target_width_ft = square_dimension_ft
        target_length_ft = square_dimension_ft

    if target_width_ft is not None:
        updated_input.trial_footing_width_ft = target_width_ft
        updated_input.min_footing_width_ft = min(updated_input.min_footing_width_ft, target_width_ft)
        updated_input.max_footing_width_ft = max(updated_input.max_footing_width_ft, target_width_ft)
        record_change(applied_changes, "Width", current_width_ft, target_width_ft, "ft")

    if target_length_ft is not None:
        updated_input.trial_footing_length_ft = target_length_ft
        updated_input.min_footing_length_ft = min(updated_input.min_footing_length_ft, target_length_ft)
        updated_input.max_footing_length_ft = max(updated_input.max_footing_length_ft, target_length_ft)
        record_change(applied_changes, "Length", current_length_ft, target_length_ft, "ft")

    current_thickness_in = design_input.footing_thickness_ft * 12.0
    thickness_in = validated_suggestion.changes.thickness_in
    if thickness_in is not None:
        if thickness_in < 0.0:
            warnings.append("Rejected thickness change because negative thickness is not allowed.")
        else:
            clamped_thickness_in = clamp(thickness_in, MIN_THICKNESS_IN, MAX_THICKNESS_IN)
            if clamped_thickness_in != thickness_in:
                warnings.append(
                    f"Clamped thickness from {thickness_in:.2f} in to {clamped_thickness_in:.2f} in."
                )
            updated_input.footing_thickness_ft = clamped_thickness_in / 12.0
            record_change(applied_changes, "Thickness", current_thickness_in, clamped_thickness_in, "in")

    current_fc_psi = design_input.concrete_strength_ksi * 1000.0
    fc_psi = validate_material_change(
        validated_suggestion.changes.fc_psi,
        "fc",
        MIN_FC_PSI,
        MAX_FC_PSI,
        warnings,
    )
    if fc_psi is not None:
        updated_input.concrete_strength_ksi = fc_psi / 1000.0
        record_change(applied_changes, "Concrete Strength", current_fc_psi, fc_psi, "psi")

    current_fy_psi = design_input.steel_yield_ksi * 1000.0
    fy_psi = validate_material_change(
        validated_suggestion.changes.fy_psi,
        "fy",
        MIN_FY_PSI,
        MAX_FY_PSI,
        warnings,
    )
    if fy_psi is not None:
        updated_input.steel_yield_ksi = fy_psi / 1000.0
        record_change(applied_changes, "Steel Yield", current_fy_psi, fy_psi, "psi")

    if validated_suggestion.constraints.reduce_bearing_pressure and not any(
        change.field_label in {"Width", "Length"} for change in applied_changes
    ):
        warnings.append(
            "Constraint 'reduce_bearing_pressure' was noted, but no explicit width or length change was returned."
        )
    if validated_suggestion.constraints.minimize_size and not applied_changes:
        warnings.append(
            "Constraint 'minimize_size' was noted, but no direct parameter change was returned to apply in v1."
        )
    if not applied_changes:
        warnings.append("AI suggestion did not produce any applied parameter changes.")

    updated_result = design_rectangular_footing(updated_input)
    apply_result = AIApplyResult(
        suggestion=validated_suggestion,
        before_result=before_result,
        updated_input=updated_input,
        updated_result=updated_result,
        applied_changes=applied_changes,
        explanation=validated_suggestion.reasoning_summary,
        warnings=warnings,
    )
    log_ai_interaction(
        event="ai_changes_applied",
        payload={
            "suggestion": asdict(validated_suggestion),
            "applied_changes": [asdict(change) for change in applied_changes],
            "warnings": warnings,
            "updated_input": asdict(updated_input),
            "updated_result_summary": asdict(updated_result.summary),
        },
    )
    return apply_result


def run_ai_design_assistant_workflow(
    project_data: FootingDesignInput | dict[str, Any],
    user_prompt: str,
    client: Any | None = None,
    model: str = MODEL_NAME,
) -> AIApplyResult:
    """Get AI suggestions, apply them safely, and rerun the calculation engine."""

    design_input = normalize_project_data(project_data)
    current_result = design_rectangular_footing(design_input)
    suggestion = get_ai_suggestions(
        project_data=design_input,
        user_prompt=user_prompt,
        client=client,
        model=model,
        current_result=current_result,
    )
    return apply_changes(design_input, suggestion, current_result=current_result)


def normalize_project_data(project_data: FootingDesignInput | dict[str, Any]) -> FootingDesignInput:
    """Accept typed input or a dict payload and return a typed project snapshot."""

    if isinstance(project_data, FootingDesignInput):
        return project_data
    if not isinstance(project_data, dict):
        raise TypeError("Project data must be a FootingDesignInput or a dict.")

    allowed_fields = {field.name for field in fields(FootingDesignInput)}
    cleaned_payload: dict[str, Any] = {}
    for key, value in project_data.items():
        if key not in allowed_fields:
            continue
        cleaned_payload[key] = None if value is None else float(value)
    return FootingDesignInput(**cleaned_payload)


def current_footing_dimensions_ft(
    design_input: FootingDesignInput,
    current_result: FootingDesignResult | None,
) -> tuple[float, float]:
    """Return the footing dimensions currently visible to the engineer."""

    if current_result is None:
        current_result = design_rectangular_footing(design_input)

    width_ft = (
        current_result.recommended_width_ft
        or design_input.trial_footing_width_ft
        or design_input.min_footing_width_ft
    )
    length_ft = (
        current_result.recommended_length_ft
        or design_input.trial_footing_length_ft
        or design_input.min_footing_length_ft
    )
    return width_ft, length_ft


def validate_optional_number(value: Any, field_name: str) -> Optional[float]:
    """Validate nullable numeric AI fields."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"AI response field '{field_name}' must be a number or null.")
    return float(value)


def validate_boolean(value: Any, field_name: str) -> bool:
    """Validate boolean AI fields."""

    if not isinstance(value, bool):
        raise ValueError(f"AI response field '{field_name}' must be a boolean.")
    return value


def ensure_suggestion(suggestion: AISuggestion | dict[str, Any] | str) -> AISuggestion:
    """Accept a typed suggestion or parse raw JSON/dict payload."""

    if isinstance(suggestion, AISuggestion):
        return suggestion
    return parse_ai_suggestion_json(suggestion)


def validate_dimension_change(value: Optional[float], label: str, warnings: list[str]) -> Optional[float]:
    """Reject negative or unrealistic footing dimensions."""

    if value is None:
        return None
    if value < 0.0:
        warnings.append(f"Rejected {label} change because negative values are not allowed.")
        return None
    if value < MIN_FOOTING_DIMENSION_FT or value > MAX_FOOTING_DIMENSION_FT:
        warnings.append(
            f"Rejected {label} change because it must stay between "
            f"{MIN_FOOTING_DIMENSION_FT:.0f} ft and {MAX_FOOTING_DIMENSION_FT:.0f} ft."
        )
        return None
    return float(value)


def validate_material_change(
    value: Optional[float],
    label: str,
    minimum: float,
    maximum: float,
    warnings: list[str],
) -> Optional[float]:
    """Reject nonpositive or unrealistic material properties."""

    if value is None:
        return None
    if value <= 0.0:
        warnings.append(f"Rejected {label} change because nonpositive values are not allowed.")
        return None
    if value < minimum or value > maximum:
        warnings.append(
            f"Rejected {label} change because it must stay between {minimum:.0f} and {maximum:.0f} psi."
        )
        return None
    return float(value)


def record_change(
    changes: list[AppliedParameterChange],
    field_label: str,
    before_value: float,
    after_value: float,
    units: str,
) -> None:
    """Record a before/after change entry when a value actually changed."""

    if abs(before_value - after_value) < 1e-9:
        return
    changes.append(
        AppliedParameterChange(
            field_label=field_label,
            before_value=before_value,
            after_value=after_value,
            units=units,
        )
    )


def format_value(value: float, units: str) -> str:
    """Format values in a readable, prompt-friendly style."""

    return f"{value:.2f} {units}"


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a number to a fixed range."""

    return min(max(value, minimum), maximum)


def log_ai_interaction(event: str, payload: dict[str, Any]) -> None:
    """Write structured AI interaction logs for later audit."""

    ensure_logger_configured()
    LOGGER.info(json.dumps({"event": event, **payload}, default=str))


def ensure_logger_configured() -> None:
    """Attach a JSON log file handler on first use."""

    if LOGGER.handlers:
        return
    try:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
