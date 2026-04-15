"""Public package exports for the preliminary footing calculator."""

from footing_prelim.ai_assistant import (
    AIApplyResult,
    AIParameterChanges,
    AIParameterConstraints,
    AISuggestion,
    AppliedParameterChange,
    apply_changes,
    get_ai_suggestions,
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
    "AIParameterChanges",
    "AIParameterConstraints",
    "AISuggestion",
    "AppliedParameterChange",
    "CalculationWarning",
    "FootingDesignInput",
    "FootingDesignResult",
    "ResultSummary",
    "apply_changes",
    "design_rectangular_footing",
    "get_ai_suggestions",
    "run_ai_design_assistant_workflow",
]
