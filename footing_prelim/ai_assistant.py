"""Deterministic natural-language command layer for the footing assistant."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field, fields, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, Optional

from footing_prelim.calculations import design_rectangular_footing, round_up_to_increment
from footing_prelim.models import FootingDesignInput, FootingDesignResult

MODEL_NAME = "deterministic-command-layer-v1"
ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT_DIR / "ai_assistant.log"
LOGGER = logging.getLogger("footing_prelim.ai_assistant")

MIN_FOOTING_DIMENSION_FT = 1.0
MAX_FOOTING_DIMENSION_FT = 100.0
MIN_THICKNESS_IN = 6.0
MAX_THICKNESS_IN = 120.0
MIN_FC_KSI = 2.5
MAX_FC_KSI = 15.0
MIN_FY_KSI = 40.0
MAX_FY_KSI = 100.0
DEFAULT_COLUMN_STEP_FT = 2.0 / 12.0
DEFAULT_THICKNESS_STEP_FT = 2.0 / 12.0
DEFAULT_LOAD_SCALE = 0.9
EPSILON = 1e-9

Operation = Literal[
    "set",
    "add",
    "subtract",
    "multiply",
    "divide",
    "reset",
    "select",
    "copy_from",
    "set_if_exists",
]
Confidence = Literal["low", "medium", "high"]

UNIT_ALIASES = {
    "ft": "ft",
    "foot": "ft",
    "feet": "ft",
    "in": "in",
    "inch": "in",
    "inches": "in",
    "ksi": "ksi",
    "psi": "psi",
    "ksf": "ksf",
    "psf": "psf",
    "kip": "kip",
    "kips": "kip",
    "lb": "lb",
    "lbs": "lb",
    "lb-ft": "lb-ft",
    "kip-ft": "kip-ft",
    "kipft": "kip-ft",
    "kip-fts": "kip-ft",
    "kip-in": "kip-in",
    "kipin": "kip-in",
    "percent": "percent",
}

EXPLICIT_TOKEN_CORRECTIONS = {
    "decrese": "decrease",
    "decreaase": "decrease",
    "widht": "width",
    "widtth": "width",
    "foting": "footing",
    "footng": "footing",
    "haf": "half",
    "halv": "halve",
    "persent": "percent",
    "percet": "percent",
    "concret": "concrete",
    "strenght": "strength",
    "strenth": "strength",
    "berring": "bearing",
    "berringg": "bearing",
    "thikness": "thickness",
    "thicness": "thickness",
    "colum": "column",
    "axail": "axial",
    "eccentrcity": "eccentricity",
}

PHRASE_NORMALIZATIONS = (
    ("footing width and length", "footing dimensions"),
    ("footing length and width", "footing dimensions"),
    ("column width and length", "column dimensions"),
    ("column length and width", "column dimensions"),
    ("width and length", "dimensions"),
    ("length and width", "dimensions"),
    ("mx and my", "moments"),
    ("my and mx", "moments"),
    ("load case", "loadcase"),
)


@dataclass(frozen=True)
class FuzzyCorrection:
    """A high-confidence token correction applied before command resolution."""

    from_text: str
    to_text: str
    confidence: float


@dataclass(frozen=True)
class AICommandAction:
    """A validated structured action produced from plain-English input."""

    field: str
    operation: Operation
    value: Optional[float | str] = None
    source_field: Optional[str] = None
    unit: Optional[str] = None
    clause: str = ""


@dataclass
class AISuggestion:
    """Structured command intent produced by the deterministic parser."""

    intent: Literal["update_parameters", "clarification_required"]
    normalized_text: str
    fuzzy_corrections: list[FuzzyCorrection]
    changes: list[AICommandAction]
    reasoning_summary: str
    warnings: list[str]
    confidence: Confidence


@dataclass
class AppliedParameterChange:
    """A single before/after change entry for UI diff rendering."""

    field_name: str
    field_label: str
    before_value: float
    after_value: float
    units: str
    operation: Operation


@dataclass
class AIApplyResult:
    """Result of applying validated natural-language edit actions."""

    suggestion: AISuggestion
    before_result: FootingDesignResult
    updated_input: FootingDesignInput
    updated_result: FootingDesignResult
    applied_changes: list[AppliedParameterChange]
    explanation: str
    warnings: list[str]


@dataclass(frozen=True)
class FieldSpec:
    """Metadata for an editable real input field."""

    field_name: str
    label: str
    canonical_unit: str
    display_unit: str
    min_value: Optional[float]
    max_value: Optional[float]
    allow_negative: bool = False
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetSpec:
    """Metadata for a real field or a virtual group target."""

    target_id: str
    label: str
    field_names: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass
class NormalizedCommand:
    """Normalized user text with tracked fuzzy corrections."""

    original_text: str
    normalized_text: str
    fuzzy_corrections: list[FuzzyCorrection]


@dataclass(frozen=True)
class ParsedQuantity:
    """A numeric quantity parsed from user text."""

    value: float
    unit: Optional[str]


FIELD_SPECS: dict[str, FieldSpec] = {
    "trial_footing_width_ft": FieldSpec(
        field_name="trial_footing_width_ft",
        label="Footing Width",
        canonical_unit="ft",
        display_unit="ft",
        min_value=MIN_FOOTING_DIMENSION_FT,
        max_value=MAX_FOOTING_DIMENSION_FT,
        aliases=("footing width", "width"),
    ),
    "trial_footing_length_ft": FieldSpec(
        field_name="trial_footing_length_ft",
        label="Footing Length",
        canonical_unit="ft",
        display_unit="ft",
        min_value=MIN_FOOTING_DIMENSION_FT,
        max_value=MAX_FOOTING_DIMENSION_FT,
        aliases=("footing length", "length"),
    ),
    "footing_thickness_ft": FieldSpec(
        field_name="footing_thickness_ft",
        label="Footing Thickness",
        canonical_unit="ft",
        display_unit="in",
        min_value=MIN_THICKNESS_IN / 12.0,
        max_value=MAX_THICKNESS_IN / 12.0,
        aliases=("footing thickness", "thickness", "thick footing"),
    ),
    "column_width_ft": FieldSpec(
        field_name="column_width_ft",
        label="Column Width",
        canonical_unit="ft",
        display_unit="ft",
        min_value=0.25,
        max_value=20.0,
        aliases=("column width",),
    ),
    "column_length_ft": FieldSpec(
        field_name="column_length_ft",
        label="Column Length",
        canonical_unit="ft",
        display_unit="ft",
        min_value=0.25,
        max_value=20.0,
        aliases=("column length",),
    ),
    "service_axial_kips": FieldSpec(
        field_name="service_axial_kips",
        label="Service Axial Load",
        canonical_unit="kip",
        display_unit="kip",
        min_value=0.01,
        max_value=1_000_000.0,
        aliases=("service axial load", "axial load", "column load", "load"),
    ),
    "service_mx_kip_ft": FieldSpec(
        field_name="service_mx_kip_ft",
        label="Service Moment Mx",
        canonical_unit="kip-ft",
        display_unit="kip-ft",
        min_value=-1_000_000.0,
        max_value=1_000_000.0,
        allow_negative=True,
        aliases=("service moment mx", "mx", "moment x", "moment about x"),
    ),
    "service_my_kip_ft": FieldSpec(
        field_name="service_my_kip_ft",
        label="Service Moment My",
        canonical_unit="kip-ft",
        display_unit="kip-ft",
        min_value=-1_000_000.0,
        max_value=1_000_000.0,
        allow_negative=True,
        aliases=("service moment my", "my", "moment y", "moment about y"),
    ),
    "allowable_bearing_ksf": FieldSpec(
        field_name="allowable_bearing_ksf",
        label="Allowable Soil Bearing",
        canonical_unit="ksf",
        display_unit="ksf",
        min_value=0.1,
        max_value=100.0,
        aliases=("allowable soil bearing", "soil bearing", "bearing pressure", "bearing"),
    ),
    "concrete_strength_ksi": FieldSpec(
        field_name="concrete_strength_ksi",
        label="Concrete Strength",
        canonical_unit="ksi",
        display_unit="ksi",
        min_value=MIN_FC_KSI,
        max_value=MAX_FC_KSI,
        aliases=("concrete strength", "concrete", "fc"),
    ),
    "steel_yield_ksi": FieldSpec(
        field_name="steel_yield_ksi",
        label="Steel Yield Strength",
        canonical_unit="ksi",
        display_unit="ksi",
        min_value=MIN_FY_KSI,
        max_value=MAX_FY_KSI,
        aliases=("steel strength", "steel yield", "steel", "fy"),
    ),
    "dimension_increment_ft": FieldSpec(
        field_name="dimension_increment_ft",
        label="Footing Size Increment",
        canonical_unit="ft",
        display_unit="ft",
        min_value=0.01,
        max_value=10.0,
        aliases=("size increment", "dimension increment", "increment"),
    ),
    "min_footing_width_ft": FieldSpec(
        field_name="min_footing_width_ft",
        label="Minimum Footing Width",
        canonical_unit="ft",
        display_unit="ft",
        min_value=0.01,
        max_value=MAX_FOOTING_DIMENSION_FT,
        aliases=("minimum width", "min width", "minimum footing width"),
    ),
    "min_footing_length_ft": FieldSpec(
        field_name="min_footing_length_ft",
        label="Minimum Footing Length",
        canonical_unit="ft",
        display_unit="ft",
        min_value=0.01,
        max_value=MAX_FOOTING_DIMENSION_FT,
        aliases=("minimum length", "min length", "minimum footing length"),
    ),
    "max_footing_width_ft": FieldSpec(
        field_name="max_footing_width_ft",
        label="Maximum Footing Width",
        canonical_unit="ft",
        display_unit="ft",
        min_value=0.01,
        max_value=MAX_FOOTING_DIMENSION_FT,
        aliases=("maximum width", "max width", "maximum footing width"),
    ),
    "max_footing_length_ft": FieldSpec(
        field_name="max_footing_length_ft",
        label="Maximum Footing Length",
        canonical_unit="ft",
        display_unit="ft",
        min_value=0.01,
        max_value=MAX_FOOTING_DIMENSION_FT,
        aliases=("maximum length", "max length", "maximum footing length"),
    ),
}

TARGET_SPECS: dict[str, TargetSpec] = {
    target.target_id: target
    for target in (
        TargetSpec(
            target_id="footing_plan_dimensions",
            label="Footing Plan Dimensions",
            field_names=("trial_footing_width_ft", "trial_footing_length_ft"),
            aliases=("footing dimensions", "footing dimension", "footing size", "footing", "dimensions"),
        ),
        TargetSpec(
            target_id="column_plan_dimensions",
            label="Column Plan Dimensions",
            field_names=("column_width_ft", "column_length_ft"),
            aliases=("column dimensions", "column dimension", "column size", "column"),
        ),
        TargetSpec(
            target_id="service_loads",
            label="Service Loads",
            field_names=("service_axial_kips", "service_mx_kip_ft", "service_my_kip_ft"),
            aliases=("service loads", "loads", "loadcase", "load case"),
        ),
        TargetSpec(
            target_id="service_moments",
            label="Service Moments",
            field_names=("service_mx_kip_ft", "service_my_kip_ft"),
            aliases=("service moments", "moments", "eccentricity inputs"),
        ),
    )
}

TARGET_ALIAS_INDEX: list[tuple[str, str]] = sorted(
    [
        *((alias, field_name) for field_name, spec in FIELD_SPECS.items() for alias in spec.aliases),
        *((alias, target_id) for target_id, spec in TARGET_SPECS.items() for alias in spec.aliases),
    ],
    key=lambda item: len(item[0]),
    reverse=True,
)


def build_vocabulary_tokens() -> list[str]:
    """Build the parser vocabulary from known fields, targets, units, and command words."""

    vocabulary: set[str] = set(EXPLICIT_TOKEN_CORRECTIONS.values())
    vocabulary.update(UNIT_ALIASES.keys())
    vocabulary.update(UNIT_ALIASES.values())
    for alias, target_id in TARGET_ALIAS_INDEX:
        vocabulary.update(part for part in alias.replace("-", " ").split() if part)
        vocabulary.update(part for part in target_id.replace("_", " ").split() if part)
    vocabulary.update(
        {
            "add",
            "all",
            "axial",
            "bearing",
            "bigger",
            "by",
            "case",
            "change",
            "clear",
            "column",
            "concrete",
            "copy",
            "cut",
            "decrease",
            "deeper",
            "dimension",
            "dimensions",
            "double",
            "everything",
            "footing",
            "half",
            "halve",
            "heavier",
            "increase",
            "lighter",
            "load",
            "loadcase",
            "long",
            "longer",
            "make",
            "match",
            "moment",
            "percent",
            "pressure",
            "reduce",
            "reset",
            "set",
            "shallower",
            "short",
            "shorter",
            "side",
            "size",
            "smaller",
            "square",
            "steel",
            "switch",
            "thick",
            "thicker",
            "thin",
            "thinner",
            "to",
            "use",
            "wider",
            "width",
        }
    )
    return sorted(vocabulary)


VOCABULARY_TOKENS = build_vocabulary_tokens()


def get_ai_suggestions(
    project_data: FootingDesignInput | dict[str, Any],
    user_prompt: str,
    client: Any | None = None,
    model: str = MODEL_NAME,
    current_result: FootingDesignResult | None = None,
) -> AISuggestion:
    """Parse a plain-English engineering command into validated structured actions."""

    del client, model  # Deterministic local parser; the command layer no longer calls an external model.

    if not user_prompt or not user_prompt.strip():
        raise ValueError("User prompt cannot be empty.")

    design_input = normalize_project_data(project_data)
    active_result = current_result or design_rectangular_footing(design_input)
    normalized = normalize_user_text(user_prompt)
    suggestion = build_structured_actions(design_input, normalized, active_result)
    log_ai_interaction(
        event="ai_command_parsed",
        payload={
            "model": MODEL_NAME,
            "user_prompt": user_prompt,
            "normalized_text": suggestion.normalized_text,
            "fuzzy_corrections": [asdict(item) for item in suggestion.fuzzy_corrections],
            "actions": [asdict(item) for item in suggestion.changes],
            "confidence": suggestion.confidence,
            "warnings": suggestion.warnings,
        },
    )
    return suggestion


def parse_ai_suggestion_json(raw_json: str | dict[str, Any]) -> AISuggestion:
    """Accept stored JSON payloads and rebuild a typed parsed-command object."""

    if isinstance(raw_json, str):
        payload = json.loads(raw_json)
    else:
        payload = raw_json

    required_keys = {
        "intent",
        "normalized_text",
        "fuzzy_corrections",
        "changes",
        "reasoning_summary",
        "warnings",
        "confidence",
    }
    if set(payload.keys()) != required_keys:
        raise ValueError("AI suggestion payload must match the structured command schema exactly.")

    fuzzy_corrections = [
        FuzzyCorrection(
            from_text=str(item["from_text"]),
            to_text=str(item["to_text"]),
            confidence=float(item["confidence"]),
        )
        for item in payload["fuzzy_corrections"]
    ]
    allowed_operations = {"set", "add", "subtract", "multiply", "divide", "reset", "select", "copy_from", "set_if_exists"}
    changes: list[AICommandAction] = []
    for item in payload["changes"]:
        field_name = str(item["field"])
        operation = str(item["operation"])
        if field_name not in FIELD_SPECS:
            raise ValueError(f"Unknown AI action field '{field_name}'.")
        if operation not in allowed_operations:
            raise ValueError(f"Unknown AI action operation '{operation}'.")
        changes.append(
            AICommandAction(
                field=field_name,
                operation=operation,
                value=item.get("value"),
                source_field=item.get("source_field"),
                unit=item.get("unit"),
                clause=str(item.get("clause", "")),
            )
        )
    confidence = payload["confidence"]
    if confidence not in {"low", "medium", "high"}:
        raise ValueError("AI suggestion confidence must be low, medium, or high.")

    intent = payload["intent"]
    if intent not in {"update_parameters", "clarification_required"}:
        raise ValueError("AI suggestion intent must be update_parameters or clarification_required.")

    warnings = payload["warnings"]
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ValueError("AI suggestion warnings must be a list of strings.")

    return AISuggestion(
        intent=intent,
        normalized_text=str(payload["normalized_text"]),
        fuzzy_corrections=fuzzy_corrections,
        changes=changes,
        reasoning_summary=str(payload["reasoning_summary"]),
        warnings=warnings,
        confidence=confidence,
    )


def apply_changes(
    project_data: FootingDesignInput | dict[str, Any],
    suggestion: AISuggestion | dict[str, Any] | str,
    current_result: FootingDesignResult | None = None,
) -> AIApplyResult:
    """Safely apply validated natural-language edit actions and rerun the engine."""

    design_input = normalize_project_data(project_data)
    validated_suggestion = ensure_suggestion(suggestion)
    before_result = current_result or design_rectangular_footing(design_input)

    updated_input, updated_result, applied_changes, warnings = execute_actions(
        design_input=design_input,
        actions=validated_suggestion.changes,
        current_result=before_result,
        initial_warnings=list(validated_suggestion.warnings),
        record_changes=True,
    )
    explanation = format_user_response(validated_suggestion, applied_changes, warnings)

    apply_result = AIApplyResult(
        suggestion=validated_suggestion,
        before_result=before_result,
        updated_input=updated_input,
        updated_result=updated_result,
        applied_changes=applied_changes,
        explanation=explanation,
        warnings=warnings,
    )
    log_ai_interaction(
        event="ai_command_applied",
        payload={
            "normalized_text": validated_suggestion.normalized_text,
            "fuzzy_corrections": [asdict(item) for item in validated_suggestion.fuzzy_corrections],
            "actions": [asdict(item) for item in validated_suggestion.changes],
            "applied_changes": [asdict(item) for item in applied_changes],
            "warnings": warnings,
            "updated_input": asdict(updated_input),
            "updated_result_summary": asdict(updated_result.summary),
            "explanation": explanation,
        },
    )
    return apply_result


def run_ai_design_assistant_workflow(
    project_data: FootingDesignInput | dict[str, Any],
    user_prompt: str,
    client: Any | None = None,
    model: str = MODEL_NAME,
) -> AIApplyResult:
    """Parse a natural-language command, apply it safely, and rerun the calculation engine."""

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
        if value in ("", None):
            cleaned_payload[key] = None
        else:
            cleaned_payload[key] = float(value)
    return FootingDesignInput(**cleaned_payload)


def normalize_user_text(user_prompt: str) -> NormalizedCommand:
    """Lowercase, normalize punctuation, and apply high-confidence fuzzy corrections."""

    original_text = " ".join(user_prompt.strip().split())
    normalized = original_text.lower()
    normalized = normalized.replace("×", " x ")
    normalized = normalized.replace("%", " percent ")
    normalized = re.sub(r"(?<=\d)(?=[a-zA-Z])", " ", normalized)
    normalized = re.sub(r"(?<=[a-zA-Z])(?=\d)", " ", normalized)
    normalized = re.sub(r"[^a-z0-9./+\-\s]", " ", normalized)

    tokens = re.findall(r"\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?|[a-z]+(?:-[a-z]+)?", normalized)
    corrections: list[FuzzyCorrection] = []
    corrected_tokens: list[str] = []

    for token in tokens:
        if re.fullmatch(r"\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?", token):
            corrected_tokens.append(token)
            continue

        corrected, confidence = normalize_token(token)
        corrected_tokens.append(corrected)
        if corrected != token:
            corrections.append(FuzzyCorrection(from_text=token, to_text=corrected, confidence=confidence))

    corrected_text = " ".join(corrected_tokens)
    for source, replacement in PHRASE_NORMALIZATIONS:
        corrected_text = corrected_text.replace(source, replacement)
    corrected_text = re.sub(r"\s+", " ", corrected_text).strip()

    return NormalizedCommand(
        original_text=original_text,
        normalized_text=corrected_text,
        fuzzy_corrections=corrections,
    )


def normalize_token(token: str) -> tuple[str, float]:
    """Return a canonical token when the match is safe enough to auto-correct."""

    if token in EXPLICIT_TOKEN_CORRECTIONS:
        return EXPLICIT_TOKEN_CORRECTIONS[token], 0.99
    if token in VOCABULARY_TOKENS:
        return token, 1.0
    if len(token) <= 3:
        return token, 0.0

    best_match = token
    best_ratio = 0.0
    for candidate in VOCABULARY_TOKENS:
        ratio = SequenceMatcher(None, token, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = candidate
    if best_ratio >= 0.86:
        return best_match, round(best_ratio, 3)
    return token, 0.0


def build_structured_actions(
    design_input: FootingDesignInput,
    normalized: NormalizedCommand,
    current_result: FootingDesignResult,
) -> AISuggestion:
    """Resolve normalized text into a deterministic list of validated field actions."""

    preview_input = replace(design_input)
    preview_result = current_result
    actions: list[AICommandAction] = []
    warnings: list[str] = []
    clause_summaries: list[str] = []
    last_target: Optional[str] = None

    clauses = split_command_clauses(normalized.normalized_text)
    for clause in clauses:
        clause_actions, clause_summary, clause_warnings, resolved_target = parse_clause(
            clause=clause,
            design_input=preview_input,
            current_result=preview_result,
            last_target=last_target,
        )
        if clause_actions:
            preview_input, preview_result, _, preview_warnings = execute_actions(
                design_input=preview_input,
                actions=clause_actions,
                current_result=preview_result,
                initial_warnings=[],
                record_changes=False,
            )
            warnings.extend(preview_warnings)
            actions.extend(clause_actions)
            last_target = resolved_target or last_target
        elif resolved_target:
            last_target = resolved_target

        warnings.extend(clause_warnings)
        if clause_summary:
            clause_summaries.append(clause_summary)

    if not actions and not warnings:
        warnings.append(
            f"Could not apply '{normalized.original_text}' because no single editable parameter clearly maps to that request."
        )

    no_op_only = bool(warnings) and all(warning.startswith("No changes were needed") for warning in warnings)
    intent: Literal["update_parameters", "clarification_required"] = (
        "update_parameters" if actions or no_op_only else "clarification_required"
    )
    reasoning_summary = (
        "; ".join(clause_summaries)
        if clause_summaries
        else f"Interpreted command as: {normalized.normalized_text}."
    )
    confidence = infer_confidence(actions, warnings, normalized.fuzzy_corrections)

    return AISuggestion(
        intent=intent,
        normalized_text=normalized.normalized_text,
        fuzzy_corrections=normalized.fuzzy_corrections,
        changes=actions,
        reasoning_summary=reasoning_summary,
        warnings=dedupe_preserve_order(warnings),
        confidence=confidence,
    )


def split_command_clauses(normalized_text: str) -> list[str]:
    """Split a normalized command into manageable clauses."""

    parts = re.split(r"\s*(?:,|;|\bthen\b|\balso\b|\band\b)\s*", normalized_text)
    return [part.strip() for part in parts if part.strip()]


def parse_clause(
    clause: str,
    design_input: FootingDesignInput,
    current_result: FootingDesignResult,
    last_target: Optional[str],
) -> tuple[list[AICommandAction], str, list[str], Optional[str]]:
    """Resolve a single normalized clause into real field actions."""

    warnings: list[str] = []

    comparison_actions = parse_comparison_clause(clause, design_input, current_result)
    if comparison_actions is not None:
        actions, summary, resolved_target = comparison_actions
        if not actions:
            warnings.append(f"No changes were needed for '{clause}' because the current model already satisfies that request.")
        return actions, summary, warnings, resolved_target

    target_id = resolve_target_id(clause, last_target)
    if "square" in clause:
        if target_id in {None, "footing_plan_dimensions", "trial_footing_width_ft", "trial_footing_length_ft"}:
            actions = build_square_actions("footing_plan_dimensions", design_input, current_result)
            if not actions:
                warnings.append("No changes were needed because the footing plan is already square.")
            return actions, "Interpreted square command as matching the footing plan sides.", warnings, "footing_plan_dimensions"
        if target_id in {"column_plan_dimensions", "column_width_ft", "column_length_ft"}:
            actions = build_square_actions("column_plan_dimensions", design_input, current_result)
            if not actions:
                warnings.append("No changes were needed because the column plan is already square.")
            return actions, "Interpreted square command as matching the column plan sides.", warnings, "column_plan_dimensions"
        warnings.append(f"Could not make '{clause}' square because that target is not a rectangular plan dimension.")
        return [], "", warnings, target_id

    if any(word in clause for word in ("reset", "clear", "revert")):
        actions = build_reset_actions(target_id, clause)
        if actions:
            return actions, f"Interpreted reset command for {describe_target(target_id)}.", warnings, target_id
        warnings.append(f"Could not reset '{clause}' because that field is not resettable in this tool.")
        return [], "", warnings, target_id

    rectangle_actions = parse_rectangle_clause(clause, target_id)
    if rectangle_actions is not None:
        return rectangle_actions, "Interpreted paired dimensions using width-by-length order.", warnings, target_id

    side_actions = parse_long_short_side_clause(clause, design_input, current_result, target_id)
    if side_actions is not None:
        actions, summary = side_actions
        return actions, summary, warnings, target_id

    load_case_actions = parse_load_case_clause(clause, target_id)
    if load_case_actions is not None:
        return load_case_actions, "Interpreted load-case wording as scaling the live service loads.", warnings, "service_loads"

    resolved_target = target_id or infer_default_target_id(clause, last_target)
    if resolved_target is None:
        warnings.append(
            f"Could not apply '{clause}' because no single editable parameter clearly maps to that request."
        )
        return [], "", warnings, None

    quantity = extract_primary_quantity(clause)
    explicit_set = has_absolute_set_language(clause)
    operation = infer_operation(clause, quantity, explicit_set, resolved_target)

    if operation is None:
        warnings.append(
            f"Could not apply '{clause}' because the requested edit amount or direction was not clear enough."
        )
        return [], "", warnings, resolved_target

    try:
        actions = build_actions_for_target(
            target_id=resolved_target,
            clause=clause,
            operation=operation,
            quantity=quantity,
            design_input=design_input,
            current_result=current_result,
        )
    except ValueError as exc:
        warnings.append(str(exc))
        return [], "", warnings, resolved_target

    if not actions:
        warnings.append(
            f"No changes were needed for '{clause}' because the current model already satisfies that request."
        )
        return [], "", warnings, resolved_target

    return actions, f"Resolved '{clause}' to {len(actions)} structured field edit(s).", warnings, resolved_target


def resolve_target_id(clause: str, last_target: Optional[str]) -> Optional[str]:
    """Resolve an explicit or implied target from the clause text."""

    matched_target: Optional[str] = None
    for alias, target_id in TARGET_ALIAS_INDEX:
        if not re.search(rf"\b{re.escape(alias)}\b", clause):
            continue
        if target_id == "dimensions":
            matched_target = "column_plan_dimensions" if "column" in clause else "footing_plan_dimensions"
            break
        matched_target = target_id
        break

    if matched_target is None and re.search(r"\bit\b", clause) and last_target:
        matched_target = last_target

    return refine_target_id(clause, matched_target)


def refine_target_id(clause: str, target_id: Optional[str]) -> Optional[str]:
    """Narrow generic targets to a specific editable field when the wording is directional."""

    if target_id in {"service_loads", "service_axial_kips", "service_moments", "service_mx_kip_ft", "service_my_kip_ft"}:
        if re.search(r"\bmx\b|\bmoment x\b|\bmoment about x\b", clause):
            return "service_mx_kip_ft"
        if re.search(r"\bmy\b|\bmoment y\b|\bmoment about y\b", clause):
            return "service_my_kip_ft"
        if any(token in clause for token in ("axial", "column load", "axial load")):
            return "service_axial_kips"
        return target_id

    if target_id in {
        "footing_plan_dimensions",
        "trial_footing_width_ft",
        "trial_footing_length_ft",
        None,
    } and "footing" in clause:
        if any(token in clause for token in ("wider", "narrower", "width")):
            return "trial_footing_width_ft"
        if any(token in clause for token in ("longer", "shorter", "length", "long side", "short side")):
            return "trial_footing_length_ft"
        if any(token in clause for token in ("thickness", "thick", "thicker", "thinner", "deeper", "shallower")):
            return "footing_thickness_ft"
        return target_id or "footing_plan_dimensions"

    if target_id in {
        "column_plan_dimensions",
        "column_width_ft",
        "column_length_ft",
        None,
    } and "column" in clause:
        if any(token in clause for token in ("wider", "narrower", "width")):
            return "column_width_ft"
        if any(token in clause for token in ("longer", "shorter", "length", "long side", "short side")):
            return "column_length_ft"
        return target_id or "column_plan_dimensions"

    if target_id == "footing_plan_dimensions":
        if any(token in clause for token in ("wider", "narrower", "width")):
            return "trial_footing_width_ft"
        if any(token in clause for token in ("longer", "shorter", "length", "long side", "short side")):
            return "trial_footing_length_ft"
    if target_id == "column_plan_dimensions":
        if any(token in clause for token in ("wider", "narrower", "width")):
            return "column_width_ft"
        if any(token in clause for token in ("longer", "shorter", "length", "long side", "short side")):
            return "column_length_ft"

    return target_id


def is_load_target(target_id: Optional[str]) -> bool:
    """Return True when the target maps to a live service load or moment field."""

    return target_id in {
        "service_loads",
        "service_axial_kips",
        "service_moments",
        "service_mx_kip_ft",
        "service_my_kip_ft",
    }


def is_plan_dimension_target(target_id: Optional[str]) -> bool:
    """Return True when the target maps to a footing or column plan dimension."""

    return target_id in {
        "footing_plan_dimensions",
        "trial_footing_width_ft",
        "trial_footing_length_ft",
        "column_plan_dimensions",
        "column_width_ft",
        "column_length_ft",
    }


def infer_default_target_id(clause: str, last_target: Optional[str]) -> Optional[str]:
    """Choose a safe default target only when the phrasing strongly implies one."""

    if any(word in clause for word in ("lighter", "heavier", "loadcase")):
        return "service_loads"
    if any(word in clause for word in ("wider", "width")):
        return "trial_footing_width_ft"
    if any(word in clause for word in ("longer", "length", "long side", "short side")):
        return "trial_footing_length_ft"
    if any(word in clause for word in ("thick", "thickness", "thicker", "thinner", "deeper", "shallower")):
        return "footing_thickness_ft"
    if any(word in clause for word in ("smaller", "larger", "bigger", "square", "footing size")):
        return "footing_plan_dimensions"
    if "concrete" in clause or "fc" in clause:
        return "concrete_strength_ksi"
    if "steel" in clause or "fy" in clause:
        return "steel_yield_ksi"
    if any(word in clause for word in ("bearing", "soil")):
        return "allowable_bearing_ksf"
    if any(word in clause for word in ("axial", "load")):
        return "service_axial_kips"
    if any(word in clause for word in ("moment", "mx", "my", "eccentricity")):
        return "service_moments"
    return refine_target_id(clause, last_target)


def parse_comparison_clause(
    clause: str,
    design_input: FootingDesignInput,
    current_result: FootingDesignResult,
) -> Optional[tuple[list[AICommandAction], str, str]]:
    """Support comparative phrasing like 'make it much wider than the column'."""

    match = re.search(r"(much\s+)?(wider|longer)\s+than\s+the\s+column", clause)
    if not match:
        return None

    is_much = bool(match.group(1))
    comparative = match.group(2)
    factor = 2.0 if is_much else 1.5
    if comparative == "wider":
        reference_value = current_field_value(design_input, current_result, "column_width_ft")
        current_value = current_field_value(design_input, current_result, "trial_footing_width_ft")
        target_value = max(current_value, round_up_to_increment(reference_value * factor, design_input.dimension_increment_ft))
        if abs(target_value - current_value) < EPSILON:
            return [], "Current footing width already exceeds the requested relation to the column.", "trial_footing_width_ft"
        return (
            [AICommandAction("trial_footing_width_ft", "set", target_value, unit="ft", clause=clause)],
            "Interpreted comparative width wording against the live column width.",
            "trial_footing_width_ft",
        )

    reference_value = current_field_value(design_input, current_result, "column_length_ft")
    current_value = current_field_value(design_input, current_result, "trial_footing_length_ft")
    target_value = max(current_value, round_up_to_increment(reference_value * factor, design_input.dimension_increment_ft))
    if abs(target_value - current_value) < EPSILON:
        return [], "Current footing length already exceeds the requested relation to the column.", "trial_footing_length_ft"
    return (
        [AICommandAction("trial_footing_length_ft", "set", target_value, unit="ft", clause=clause)],
        "Interpreted comparative length wording against the live column length.",
        "trial_footing_length_ft",
    )


def parse_rectangle_clause(clause: str, target_id: Optional[str]) -> Optional[list[AICommandAction]]:
    """Support paired dimension entries such as 'make footing 8 by 10'."""

    if target_id not in {"footing_plan_dimensions", "column_plan_dimensions"}:
        return None

    match = re.search(
        r"(?P<a>\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(?P<unit_a>ft|feet|foot|in|inch|inches)?\s*(?:x|by)\s*"
        r"(?P<b>\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(?P<unit_b>ft|feet|foot|in|inch|inches)?",
        clause,
    )
    if not match:
        return None

    unit_a = UNIT_ALIASES.get((match.group("unit_a") or "").lower()) if match.group("unit_a") else None
    unit_b = UNIT_ALIASES.get((match.group("unit_b") or "").lower()) if match.group("unit_b") else unit_a
    width_field, length_field = TARGET_SPECS[target_id].field_names
    width_value = convert_to_canonical(
        parse_number(match.group("a")),
        unit_a or "ft",
        FIELD_SPECS[width_field].canonical_unit,
    )
    length_value = convert_to_canonical(
        parse_number(match.group("b")),
        unit_b or unit_a or "ft",
        FIELD_SPECS[length_field].canonical_unit,
    )
    return [
        AICommandAction(width_field, "set", width_value, unit=FIELD_SPECS[width_field].canonical_unit, clause=clause),
        AICommandAction(length_field, "set", length_value, unit=FIELD_SPECS[length_field].canonical_unit, clause=clause),
    ]


def parse_long_short_side_clause(
    clause: str,
    design_input: FootingDesignInput,
    current_result: FootingDesignResult,
    target_id: Optional[str],
) -> Optional[tuple[list[AICommandAction], str]]:
    """Support commands such as 'change the long side to 14 feet'."""

    if "long side" not in clause and "short side" not in clause:
        return None

    quantity = extract_primary_quantity(clause)
    if quantity is None:
        raise ValueError(f"Could not apply '{clause}' because no new dimension was provided.")

    target_group = target_id or "footing_plan_dimensions"
    if target_group in {"trial_footing_width_ft", "trial_footing_length_ft"}:
        target_group = "footing_plan_dimensions"
    elif target_group in {"column_width_ft", "column_length_ft"}:
        target_group = "column_plan_dimensions"
    elif target_group not in {"footing_plan_dimensions", "column_plan_dimensions"}:
        target_group = "footing_plan_dimensions"

    width_field, length_field = TARGET_SPECS[target_group].field_names
    width_value = current_field_value(design_input, current_result, width_field)
    length_value = current_field_value(design_input, current_result, length_field)
    unit = infer_unit_for_target(width_field, quantity.value, quantity.unit)
    canonical_value = convert_to_canonical(quantity.value, unit, FIELD_SPECS[width_field].canonical_unit)

    if "long side" in clause:
        target_field = length_field if length_value >= width_value else width_field
        return [AICommandAction(target_field, "set", canonical_value, unit=FIELD_SPECS[target_field].canonical_unit, clause=clause)], (
            "Interpreted long-side wording using the currently larger live plan dimension."
        )

    target_field = width_field if width_value <= length_value else length_field
    return [AICommandAction(target_field, "set", canonical_value, unit=FIELD_SPECS[target_field].canonical_unit, clause=clause)], (
        "Interpreted short-side wording using the currently smaller live plan dimension."
    )


def parse_load_case_clause(clause: str, target_id: Optional[str]) -> Optional[list[AICommandAction]]:
    """Interpret 'lighter/heavier load case' phrasing using a documented default scale."""

    if "lighter loadcase" in clause or "lighter load case" in clause:
        return build_actions_for_target(
            target_id="service_loads",
            clause=clause,
            operation="multiply",
            quantity=ParsedQuantity(DEFAULT_LOAD_SCALE, None),
            design_input=None,
            current_result=None,
        )
    if "heavier loadcase" in clause or "heavier load case" in clause:
        return build_actions_for_target(
            target_id="service_loads",
            clause=clause,
            operation="multiply",
            quantity=ParsedQuantity(1.0 + (1.0 - DEFAULT_LOAD_SCALE), None),
            design_input=None,
            current_result=None,
        )
    if target_id == "service_loads" and any(word in clause for word in ("lighter", "heavier")):
        factor = DEFAULT_LOAD_SCALE if "lighter" in clause else 1.0 + (1.0 - DEFAULT_LOAD_SCALE)
        return build_actions_for_target(
            target_id="service_loads",
            clause=clause,
            operation="multiply",
            quantity=ParsedQuantity(factor, None),
            design_input=None,
            current_result=None,
        )
    return None


def has_absolute_set_language(clause: str) -> bool:
    """Return True for wording that clearly requests an absolute target value."""

    return any(token in clause for token in (" to ", "use ", "switch ", "set ", "change "))


def infer_operation(
    clause: str,
    quantity: Optional[ParsedQuantity],
    explicit_set: bool,
    target_id: str,
) -> Optional[Operation]:
    """Infer the action operation from command wording."""

    if explicit_set and quantity is not None:
        return "set"
    if any(token in clause for token in ("reset", "clear", "revert")):
        return "reset"
    if any(token in clause for token in ("double", "twice", "triple", "half", "halve", "halved")):
        return "multiply"
    if quantity is not None and quantity.unit == "percent":
        return "multiply"
    if quantity is None and is_load_target(target_id) and any(
        token in clause for token in ("lighter", "heavier", "reduce", "lower", "increase", "raise", "smaller", "larger", "bigger")
    ):
        return "multiply"
    if quantity is not None and re.search(r"\b(by|wider|longer|thicker|deeper|shallower|narrower|shorter|thinner)\b", clause):
        if any(token in clause for token in ("decrease", "reduce", "lower", "subtract", "narrower", "shorter", "shallower", "thinner")):
            return "subtract"
        return "add"
    if quantity is not None:
        if any(token in clause for token in ("increase", "raise", "add", "wider", "longer", "thicker", "deeper")):
            return "add"
        if any(token in clause for token in ("decrease", "reduce", "lower", "subtract", "smaller", "narrower", "shorter", "thinner", "shallower")):
            return "subtract"
        if any(token in clause for token in ("use", "switch", "set", "change")):
            return "set"
        if target_id in FIELD_SPECS or target_id in TARGET_SPECS:
            return "set"
    if any(token in clause for token in ("smaller", "narrower", "shorter", "thinner", "shallower", "reduce", "lower")):
        return "subtract"
    if any(token in clause for token in ("larger", "bigger", "wider", "longer", "thicker", "deeper", "increase", "raise", "add")):
        return "add"
    return None


def build_actions_for_target(
    target_id: str,
    clause: str,
    operation: Operation,
    quantity: Optional[ParsedQuantity],
    design_input: FootingDesignInput | None,
    current_result: FootingDesignResult | None,
) -> list[AICommandAction]:
    """Expand a resolved target into one or more real field actions."""

    if target_id == "footing_plan_dimensions":
        return build_group_actions(
            ("trial_footing_width_ft", "trial_footing_length_ft"),
            clause,
            operation,
            quantity,
            design_input,
        )
    if target_id == "column_plan_dimensions":
        return build_group_actions(
            ("column_width_ft", "column_length_ft"),
            clause,
            operation,
            quantity,
            design_input,
        )
    if target_id == "service_loads":
        return build_group_actions(
            ("service_axial_kips", "service_mx_kip_ft", "service_my_kip_ft"),
            clause,
            operation,
            quantity,
            design_input,
        )
    if target_id == "service_moments":
        return build_group_actions(
            ("service_mx_kip_ft", "service_my_kip_ft"),
            clause,
            operation,
            quantity,
            design_input,
        )
    if target_id in FIELD_SPECS:
        return build_field_actions(target_id, clause, operation, quantity, design_input)
    raise ValueError(f"Could not apply '{clause}' because '{target_id}' is not an editable target.")


def build_group_actions(
    field_names: tuple[str, ...],
    clause: str,
    operation: Operation,
    quantity: Optional[ParsedQuantity],
    design_input: FootingDesignInput | None,
) -> list[AICommandAction]:
    """Create concrete field actions for a virtual group target."""

    actions: list[AICommandAction] = []
    for field_name in field_names:
        actions.extend(build_field_actions(field_name, clause, operation, quantity, design_input))
    return actions


def build_field_actions(
    field_name: str,
    clause: str,
    operation: Operation,
    quantity: Optional[ParsedQuantity],
    design_input: FootingDesignInput | None,
) -> list[AICommandAction]:
    """Create a real field action, including qualitative defaults and unit inference."""

    spec = FIELD_SPECS[field_name]

    if operation == "reset":
        return [AICommandAction(field=field_name, operation="reset", clause=clause)]

    if operation == "multiply":
        if quantity is None:
            quantity = infer_default_quantity(clause, field_name, design_input)
        factor = infer_multiplier(clause, quantity)
        return [AICommandAction(field=field_name, operation="multiply", value=factor, clause=clause)]

    if quantity is None:
        quantity = infer_default_quantity(clause, field_name, design_input)
        if quantity is None:
            raise ValueError(
                f"Could not apply '{clause}' because no numeric value or safe default step could be resolved."
            )

    unit = infer_unit_for_target(field_name, quantity.value, quantity.unit)
    canonical_value = convert_to_canonical(quantity.value, unit, spec.canonical_unit)

    if operation in {"set", "set_if_exists"}:
        return [
            AICommandAction(
                field=field_name,
                operation=operation,
                value=canonical_value,
                unit=spec.canonical_unit,
                clause=clause,
            )
        ]
    return [
        AICommandAction(
            field=field_name,
            operation=operation,
            value=canonical_value,
            unit=spec.canonical_unit,
            clause=clause,
        )
    ]


def build_square_actions(
    target_id: str,
    design_input: FootingDesignInput,
    current_result: FootingDesignResult,
) -> list[AICommandAction]:
    """Create a copy action that makes a rectangular plan square."""

    if target_id == "footing_plan_dimensions":
        width_field, length_field = "trial_footing_width_ft", "trial_footing_length_ft"
    else:
        width_field, length_field = "column_width_ft", "column_length_ft"

    width_value = current_field_value(design_input, current_result, width_field)
    length_value = current_field_value(design_input, current_result, length_field)
    if abs(width_value - length_value) < EPSILON:
        return []
    if width_value > length_value:
        return [AICommandAction(field=length_field, operation="copy_from", source_field=width_field, clause="square")]
    return [AICommandAction(field=width_field, operation="copy_from", source_field=length_field, clause="square")]


def build_reset_actions(target_id: Optional[str], clause: str) -> list[AICommandAction]:
    """Create reset actions for resettable targets."""

    reset_map = {
        "footing_plan_dimensions": ("trial_footing_width_ft", "trial_footing_length_ft"),
        "column_plan_dimensions": ("column_width_ft", "column_length_ft"),
        "service_moments": ("service_mx_kip_ft", "service_my_kip_ft"),
        "service_mx_kip_ft": ("service_mx_kip_ft",),
        "service_my_kip_ft": ("service_my_kip_ft",),
        "trial_footing_width_ft": ("trial_footing_width_ft",),
        "trial_footing_length_ft": ("trial_footing_length_ft",),
        "column_width_ft": ("column_width_ft",),
        "column_length_ft": ("column_length_ft",),
        "footing_thickness_ft": ("footing_thickness_ft",),
        "allowable_bearing_ksf": ("allowable_bearing_ksf",),
        "concrete_strength_ksi": ("concrete_strength_ksi",),
        "steel_yield_ksi": ("steel_yield_ksi",),
        "dimension_increment_ft": ("dimension_increment_ft",),
        "min_footing_width_ft": ("min_footing_width_ft",),
        "min_footing_length_ft": ("min_footing_length_ft",),
        "max_footing_width_ft": ("max_footing_width_ft",),
        "max_footing_length_ft": ("max_footing_length_ft",),
    }
    if target_id == "service_loads":
        return []
    if target_id == "service_axial_kips":
        return []
    if target_id == "service_moments" or "eccentricity" in clause:
        return [
            AICommandAction(field="service_mx_kip_ft", operation="reset", clause=clause),
            AICommandAction(field="service_my_kip_ft", operation="reset", clause=clause),
        ]
    if target_id in reset_map:
        return [AICommandAction(field=field_name, operation="reset", clause=clause) for field_name in reset_map[target_id]]
    return []


def infer_multiplier(clause: str, quantity: Optional[ParsedQuantity]) -> float:
    """Resolve multiplicative phrases like halve, double, or percent edits."""

    if "double" in clause or "twice" in clause:
        return 2.0
    if "triple" in clause:
        return 3.0
    if any(token in clause for token in ("half", "halve", "halved")):
        return 0.5
    if quantity is not None and quantity.unit == "percent":
        percentage = quantity.value / 100.0
        if any(token in clause for token in ("decrease", "reduce", "lower", "smaller", "lighter")):
            return 1.0 - percentage
        return 1.0 + percentage
    if quantity is not None and quantity.value:
        return quantity.value
    raise ValueError(f"Could not apply '{clause}' because the requested scale factor was not clear.")


def infer_default_quantity(
    clause: str,
    field_name: str,
    design_input: FootingDesignInput | None,
) -> Optional[ParsedQuantity]:
    """Provide conservative defaults for vague but still resolvable commands."""

    if field_name in {"trial_footing_width_ft", "trial_footing_length_ft"}:
        step = design_input.dimension_increment_ft if design_input is not None else 0.5
        return ParsedQuantity(step, "ft")
    if field_name in {"column_width_ft", "column_length_ft"}:
        return ParsedQuantity(DEFAULT_COLUMN_STEP_FT, "ft")
    if field_name == "footing_thickness_ft":
        return ParsedQuantity(DEFAULT_THICKNESS_STEP_FT, "ft")
    if field_name in {"service_axial_kips", "service_mx_kip_ft", "service_my_kip_ft"} and any(
        token in clause for token in ("lighter", "heavier", "smaller", "larger", "bigger", "reduce", "lower", "increase", "raise")
    ):
        factor = DEFAULT_LOAD_SCALE if any(token in clause for token in ("lighter", "smaller", "reduce", "lower")) else 1.1
        return ParsedQuantity(factor, None)
    return None


def infer_unit_for_target(field_name: str, value: float, explicit_unit: Optional[str]) -> str:
    """Infer omitted units conservatively from the target field and numeric magnitude."""

    if explicit_unit is not None:
        return explicit_unit

    if field_name == "footing_thickness_ft":
        return "in" if value >= 6.0 else "ft"
    if field_name in {"column_width_ft", "column_length_ft"}:
        return "in" if value >= 4.0 else "ft"
    if field_name in {"trial_footing_width_ft", "trial_footing_length_ft", "min_footing_width_ft", "min_footing_length_ft", "max_footing_width_ft", "max_footing_length_ft", "dimension_increment_ft"}:
        return "ft"
    if field_name == "allowable_bearing_ksf":
        return "psf" if value >= 100.0 else "ksf"
    if field_name in {"concrete_strength_ksi", "steel_yield_ksi"}:
        return "psi" if value >= 1000.0 else "ksi"
    if field_name == "service_axial_kips":
        return "kip"
    if field_name in {"service_mx_kip_ft", "service_my_kip_ft"}:
        return "kip-ft"
    return FIELD_SPECS[field_name].canonical_unit


def extract_primary_quantity(clause: str) -> Optional[ParsedQuantity]:
    """Return the first meaningful quantity found in a clause."""

    pattern = re.compile(
        r"(?P<value>\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)"
        r"(?:\s*(?P<unit>kip-ft|kip-in|kipft|kipin|ksi|psi|ksf|psf|kips|kip|lbs|lb|feet|foot|ft|inches|inch|in|percent))?"
    )
    match = pattern.search(clause)
    if not match:
        return None
    unit = match.group("unit")
    canonical_unit = UNIT_ALIASES.get(unit, unit) if unit else None
    return ParsedQuantity(value=parse_number(match.group("value")), unit=canonical_unit)


def parse_number(raw_value: str) -> float:
    """Parse integers, decimals, and simple fractions."""

    if "/" in raw_value:
        numerator, denominator = raw_value.split("/", 1)
        return float(numerator) / float(denominator)
    return float(raw_value)


def convert_to_canonical(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a parsed quantity into the target field's canonical unit."""

    if from_unit == to_unit:
        return float(value)

    conversions = {
        ("in", "ft"): value / 12.0,
        ("ft", "in"): value * 12.0,
        ("psf", "ksf"): value / 1000.0,
        ("ksf", "psf"): value * 1000.0,
        ("psi", "ksi"): value / 1000.0,
        ("ksi", "psi"): value * 1000.0,
        ("lb", "kip"): value / 1000.0,
        ("kip", "lb"): value * 1000.0,
        ("kip-in", "kip-ft"): value / 12.0,
        ("lb-ft", "kip-ft"): value / 1000.0,
    }
    try:
        return float(conversions[(from_unit, to_unit)])
    except KeyError as exc:
        raise ValueError(f"Unsupported unit conversion from {from_unit} to {to_unit}.") from exc


def execute_actions(
    design_input: FootingDesignInput,
    actions: list[AICommandAction],
    current_result: FootingDesignResult,
    initial_warnings: list[str],
    record_changes: bool,
) -> tuple[FootingDesignInput, FootingDesignResult, list[AppliedParameterChange], list[str]]:
    """Apply a validated action sequence to a working project snapshot."""

    updated_input = replace(design_input)
    working_result = current_result
    warnings = list(initial_warnings)
    applied_changes: list[AppliedParameterChange] = []
    defaults = default_reset_snapshot(design_input)

    for action in actions:
        try:
            before_value = current_field_value(updated_input, working_result, action.field)
            before_record_value = recordable_field_value(updated_input, working_result, action.field)
            proposed_value = compute_proposed_value(
                action=action,
                design_input=updated_input,
                current_result=working_result,
                defaults=defaults,
            )
            if proposed_value is None and action.operation != "reset":
                continue
            if proposed_value is not None:
                validate_proposed_value(action.field, proposed_value, updated_input)
            updated_input = set_field_value(updated_input, action.field, proposed_value)
            working_result = design_rectangular_footing(updated_input)
            after_record_value = recordable_field_value(updated_input, working_result, action.field)
            if record_changes and abs(after_record_value - before_record_value) > EPSILON:
                record_change(applied_changes, action.field, action.operation, before_record_value, after_record_value)
        except ValueError as exc:
            warnings.append(str(exc))

    if record_changes:
        for field_name in dedupe_preserve_order([change.field_name for change in applied_changes]):
            record_result_override_warning(
                warnings,
                field_name,
                recordable_field_value(updated_input, working_result, field_name),
                current_field_value(updated_input, working_result, field_name),
            )

    if record_changes and not applied_changes and not warnings:
        warnings.append("No changes were needed because the command already matched the current project state.")

    return updated_input, working_result, applied_changes, dedupe_preserve_order(warnings)


def compute_proposed_value(
    action: AICommandAction,
    design_input: FootingDesignInput,
    current_result: FootingDesignResult,
    defaults: FootingDesignInput,
) -> Optional[float]:
    """Compute the proposed canonical field value for a single action."""

    current_value = current_field_value(design_input, current_result, action.field)

    if action.operation == "reset":
        return reset_value_for_field(action.field, defaults)
    if action.operation == "copy_from":
        if not action.source_field:
            raise ValueError(f"Could not apply '{action.clause}' because the copy source field is missing.")
        return current_field_value(design_input, current_result, action.source_field)
    if action.value is None:
        raise ValueError(f"Could not apply '{action.clause}' because no value was provided.")

    numeric_value = float(action.value)
    if action.operation == "set":
        return numeric_value
    if action.operation == "set_if_exists":
        return numeric_value
    if action.operation == "add":
        return current_value + numeric_value
    if action.operation == "subtract":
        return current_value - numeric_value
    if action.operation == "multiply":
        return current_value * numeric_value
    if action.operation == "divide":
        if abs(numeric_value) < EPSILON:
            raise ValueError(f"Could not apply '{action.clause}' because division by zero is not allowed.")
        return current_value / numeric_value
    raise ValueError(f"Unsupported action operation '{action.operation}'.")


def set_field_value(design_input: FootingDesignInput, field_name: str, value: Optional[float]) -> FootingDesignInput:
    """Return an updated input snapshot with one field changed."""

    updated_input = replace(design_input)

    if field_name == "trial_footing_width_ft":
        if value is None:
            updated_input.trial_footing_width_ft = None
        else:
            rounded_value = round_up_to_increment(value, updated_input.dimension_increment_ft)
            updated_input.trial_footing_width_ft = rounded_value
            updated_input.min_footing_width_ft = min(updated_input.min_footing_width_ft, rounded_value)
            updated_input.max_footing_width_ft = max(updated_input.max_footing_width_ft, rounded_value)
        return updated_input

    if field_name == "trial_footing_length_ft":
        if value is None:
            updated_input.trial_footing_length_ft = None
        else:
            rounded_value = round_up_to_increment(value, updated_input.dimension_increment_ft)
            updated_input.trial_footing_length_ft = rounded_value
            updated_input.min_footing_length_ft = min(updated_input.min_footing_length_ft, rounded_value)
            updated_input.max_footing_length_ft = max(updated_input.max_footing_length_ft, rounded_value)
        return updated_input

    setattr(updated_input, field_name, value)
    return updated_input


def current_field_value(
    design_input: FootingDesignInput,
    current_result: FootingDesignResult,
    field_name: str,
) -> float:
    """Read the live value a user sees for a field, not just the raw input attribute."""

    if field_name == "trial_footing_width_ft":
        width_ft, _ = current_footing_dimensions_ft(design_input, current_result)
        return width_ft
    if field_name == "trial_footing_length_ft":
        _, length_ft = current_footing_dimensions_ft(design_input, current_result)
        return length_ft
    return float(getattr(design_input, field_name))


def recordable_field_value(
    design_input: FootingDesignInput,
    current_result: FootingDesignResult,
    field_name: str,
) -> float:
    """Return the actual parameter value to report in user-facing change summaries."""

    if field_name == "trial_footing_width_ft":
        return (
            float(design_input.trial_footing_width_ft)
            if design_input.trial_footing_width_ft is not None
            else current_field_value(design_input, current_result, field_name)
        )
    if field_name == "trial_footing_length_ft":
        return (
            float(design_input.trial_footing_length_ft)
            if design_input.trial_footing_length_ft is not None
            else current_field_value(design_input, current_result, field_name)
        )
    return current_field_value(design_input, current_result, field_name)


def current_footing_dimensions_ft(
    design_input: FootingDesignInput,
    current_result: FootingDesignResult,
) -> tuple[float, float]:
    """Return the footing dimensions currently visible to the engineer."""

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


def default_reset_snapshot(design_input: FootingDesignInput) -> FootingDesignInput:
    """Build a reset baseline using dataclass defaults while preserving the required axial load."""

    return FootingDesignInput(service_axial_kips=design_input.service_axial_kips)


def reset_value_for_field(field_name: str, defaults: FootingDesignInput) -> Optional[float]:
    """Return the configured reset value for a field."""

    if field_name in {"trial_footing_width_ft", "trial_footing_length_ft"}:
        return None
    if field_name in {"service_mx_kip_ft", "service_my_kip_ft"}:
        return 0.0
    if field_name == "service_axial_kips":
        raise ValueError("Could not reset service axial load because this tool does not store a safe default load case.")
    return float(getattr(defaults, field_name))


def validate_proposed_value(field_name: str, value: float, design_input: FootingDesignInput) -> None:
    """Raise a clear error if a proposed edit would break model assumptions."""

    spec = FIELD_SPECS[field_name]
    if not spec.allow_negative and value <= 0.0:
        raise ValueError(f"Could not apply {spec.label.lower()} because it must remain positive.")
    if spec.min_value is not None and value < spec.min_value - EPSILON:
        raise ValueError(
            f"Could not apply {spec.label.lower()} because it must be at least "
            f"{format_value(convert_for_display(spec.min_value, spec.display_unit), spec.display_unit)}."
        )
    if spec.max_value is not None and value > spec.max_value + EPSILON:
        raise ValueError(
            f"Could not apply {spec.label.lower()} because it must be at most "
            f"{format_value(convert_for_display(spec.max_value, spec.display_unit), spec.display_unit)}."
        )

    if field_name == "min_footing_width_ft" and value > design_input.max_footing_width_ft + EPSILON:
        raise ValueError("Could not apply minimum footing width because it would exceed the current maximum footing width.")
    if field_name == "min_footing_length_ft" and value > design_input.max_footing_length_ft + EPSILON:
        raise ValueError("Could not apply minimum footing length because it would exceed the current maximum footing length.")
    if field_name == "max_footing_width_ft" and value < design_input.min_footing_width_ft - EPSILON:
        raise ValueError("Could not apply maximum footing width because it would fall below the current minimum footing width.")
    if field_name == "max_footing_length_ft" and value < design_input.min_footing_length_ft - EPSILON:
        raise ValueError("Could not apply maximum footing length because it would fall below the current minimum footing length.")


def record_change(
    changes: list[AppliedParameterChange],
    field_name: str,
    operation: Operation,
    before_value: float,
    after_value: float,
) -> None:
    """Record a before/after change entry when a value actually changed."""

    spec = FIELD_SPECS[field_name]
    changes.append(
        AppliedParameterChange(
            field_name=field_name,
            field_label=spec.label,
            before_value=convert_for_display(before_value, spec.display_unit),
            after_value=convert_for_display(after_value, spec.display_unit),
            units=spec.display_unit,
            operation=operation,
        )
    )


def record_result_override_warning(
    warnings: list[str],
    field_name: str,
    parameter_value: float,
    visible_value: float,
) -> None:
    """Warn when the edited input differs from the recalculated live footing size."""

    if field_name not in {"trial_footing_width_ft", "trial_footing_length_ft"}:
        return
    if abs(parameter_value - visible_value) <= EPSILON:
        return

    spec = FIELD_SPECS[field_name]
    display_parameter = format_value(convert_for_display(parameter_value, spec.display_unit), spec.display_unit)
    display_visible = format_value(convert_for_display(visible_value, spec.display_unit), spec.display_unit)
    warnings.append(
        f"Updated {spec.label.lower()} input to {display_parameter}; the current calculation still recommends {display_visible}."
    )


def ensure_suggestion(suggestion: AISuggestion | dict[str, Any] | str) -> AISuggestion:
    """Accept a typed suggestion or parse a stored JSON/dict payload."""

    if isinstance(suggestion, AISuggestion):
        return suggestion
    return parse_ai_suggestion_json(suggestion)


def infer_confidence(
    actions: list[AICommandAction],
    warnings: list[str],
    corrections: list[FuzzyCorrection],
) -> Confidence:
    """Return a coarse confidence label for the parsed command."""

    if not actions:
        return "low"
    if warnings:
        return "medium"
    if corrections and min(item.confidence for item in corrections) < 0.92:
        return "medium"
    return "high"


def format_user_response(
    suggestion: AISuggestion,
    changes: list[AppliedParameterChange],
    warnings: list[str],
) -> str:
    """Return a concise professional user-facing summary."""

    correction_prefix = format_correction_prefix(suggestion.fuzzy_corrections)
    if changes:
        summary = join_phrases([format_change_phrase(change) for change in changes])
        return f"{correction_prefix}{summary}".strip()
    if warnings:
        return f"{correction_prefix}{warnings[0]}".strip()
    return f"{correction_prefix}{suggestion.reasoning_summary}".strip()


def format_correction_prefix(corrections: list[FuzzyCorrection]) -> str:
    """Return a compact correction prefix when fuzzy normalization made safe edits."""

    if not corrections:
        return ""
    items = [f"'{item.from_text}' to '{item.to_text}'" for item in corrections[:3]]
    if len(items) == 1:
        joined = items[0]
    elif len(items) == 2:
        joined = f"{items[0]} and {items[1]}"
    else:
        joined = f"{', '.join(items[:-1])}, and {items[-1]}"
    return f"Corrected {joined}. "


def format_change_phrase(change: AppliedParameterChange) -> str:
    """Return a short before/after phrase for one applied field change."""

    before_value = format_value(change.before_value, change.units)
    after_value = format_value(change.after_value, change.units)
    if change.operation in {"add", "multiply"} and change.after_value > change.before_value:
        verb = "Increased"
    elif change.operation in {"subtract", "multiply"} and change.after_value < change.before_value:
        verb = "Reduced"
    elif change.operation == "reset":
        verb = "Reset"
    else:
        verb = "Set"
    return f"{verb} {change.field_label.lower()} from {before_value} to {after_value}"


def convert_for_display(value: float, display_unit: str) -> float:
    """Convert canonical stored values to the chosen display unit."""

    if display_unit == "in":
        return value * 12.0
    return value


def format_value(value: float, units: str) -> str:
    """Format numeric values in a UI-friendly way."""

    digits = 0 if units in {"psi", "psf"} else 2
    return f"{value:.{digits}f} {units}"


def describe_target(target_id: Optional[str]) -> str:
    """Return a readable target label for parse summaries."""

    if target_id is None:
        return "the current model"
    if target_id in FIELD_SPECS:
        return FIELD_SPECS[target_id].label.lower()
    if target_id in TARGET_SPECS:
        return TARGET_SPECS[target_id].label.lower()
    return target_id.replace("_", " ")


def join_phrases(parts: list[str]) -> str:
    """Join phrases with natural English punctuation."""

    cleaned = [part for part in parts if part]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0] + "."
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}."
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}."


def dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return a list without duplicates while preserving the original order."""

    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


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
