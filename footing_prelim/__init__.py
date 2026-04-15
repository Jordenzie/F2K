"""Public package exports for the preliminary footing calculator."""

from footing_prelim.ai_assistant import (
    AIApplyResult,
    AICommandAction,
    AISuggestion,
    AppliedParameterChange,
    FuzzyCorrection,
    apply_changes,
    get_ai_suggestions,
    parse_ai_suggestion_json,
    run_ai_design_assistant_workflow,
)
from footing_prelim.calculations import design_rectangular_footing
from footing_prelim.models import (
    CalculationWarning,
    FootingDesignInput,
    FootingDesignResult,
    ResultSummary,
)

__all__ = [
    "AIApplyResult",
    "AICommandAction",
    "AISuggestion",
    "AppliedParameterChange",
    "CalculationWarning",
    "FootingDesignInput",
    "FootingDesignResult",
    "FuzzyCorrection",
    "ResultSummary",
    "apply_changes",
    "design_rectangular_footing",
    "get_ai_suggestions",
    "parse_ai_suggestion_json",
    "run_ai_design_assistant_workflow",
]
