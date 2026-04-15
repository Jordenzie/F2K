"""Public package exports for the preliminary footing calculator."""

from footing_prelim.calculations import design_rectangular_footing
from footing_prelim.models import (
    CalculationWarning,
    FootingDesignInput,
    FootingDesignResult,
    ResultSummary,
)

__all__ = [
    "CalculationWarning",
    "FootingDesignInput",
    "FootingDesignResult",
    "ResultSummary",
    "design_rectangular_footing",
]
