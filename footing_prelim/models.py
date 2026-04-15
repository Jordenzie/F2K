"""Structured models for the preliminary footing calculator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FootingDesignInput:
    """Input data for a preliminary isolated footing sizing run.

    Units:
    - axial load: kips
    - moments: kip-ft
    - dimensions: ft
    - soil bearing: ksf
    - material strengths: ksi
    """

    service_axial_kips: float
    service_mx_kip_ft: float = 0.0
    service_my_kip_ft: float = 0.0
    allowable_bearing_ksf: float = 3.0
    column_width_ft: float = 1.5
    column_length_ft: float = 1.5
    footing_thickness_ft: float = 1.5
    concrete_strength_ksi: float = 4.0
    steel_yield_ksi: float = 60.0
    dimension_increment_ft: float = 0.5
    min_footing_width_ft: float = 2.0
    min_footing_length_ft: float = 2.0
    max_footing_width_ft: float = 30.0
    max_footing_length_ft: float = 30.0


@dataclass
class CalculationWarning:
    """A stable warning entry returned with a result object."""

    code: str
    message: str


@dataclass
class ResultSummary:
    """High-level summary intended for UI badges or reports."""

    status: str
    governing_check: str
    bearing_utilization: float


@dataclass
class FootingDesignResult:
    """Structured design result for the first-pass preliminary engine."""

    input_data: FootingDesignInput
    required_area_sqft: Optional[float]
    recommended_width_ft: Optional[float]
    recommended_length_ft: Optional[float]
    provided_area_sqft: Optional[float]
    eccentricity_x_ft: Optional[float]
    eccentricity_y_ft: Optional[float]
    qmax_ksf: Optional[float]
    qmin_ksf: Optional[float]
    bearing_pass: bool
    middle_third_ok: bool
    full_contact_ok: bool
    outside_simplified_scope: bool
    warnings: list[CalculationWarning] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    summary: ResultSummary = field(
        default_factory=lambda: ResultSummary(
            status="WARNING",
            governing_check="No calculation performed.",
            bearing_utilization=0.0,
        )
    )
