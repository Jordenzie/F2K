"""First-pass preliminary footing sizing and bearing calculations."""

from __future__ import annotations

import math

from footing_prelim.models import (
    CalculationWarning,
    FootingDesignInput,
    FootingDesignResult,
    ResultSummary,
)


def required_footing_area_sqft(service_axial_kips: float, allowable_bearing_ksf: float) -> float:
    """Return the gross area required from axial load alone."""

    if service_axial_kips <= 0.0:
        raise ValueError("Service axial load must be positive for area sizing.")
    if allowable_bearing_ksf <= 0.0:
        raise ValueError("Allowable bearing pressure must be positive.")
    return service_axial_kips / allowable_bearing_ksf


def compute_eccentricities_ft(
    service_axial_kips: float,
    service_mx_kip_ft: float,
    service_my_kip_ft: float,
) -> tuple[float, float]:
    """Convert service moments to plan eccentricity.

    `My` produces eccentricity in the footing length direction (`x`).
    `Mx` produces eccentricity in the footing width direction (`y`).
    """

    if service_axial_kips <= 0.0:
        raise ValueError("Service axial load must be positive for eccentricity calculations.")

    eccentricity_x_ft = service_my_kip_ft / service_axial_kips
    eccentricity_y_ft = service_mx_kip_ft / service_axial_kips
    return eccentricity_x_ft, eccentricity_y_ft


def bearing_pressures_ksf(
    service_axial_kips: float,
    width_ft: float,
    length_ft: float,
    eccentricity_x_ft: float,
    eccentricity_y_ft: float,
) -> tuple[float, float]:
    """Return the maximum and minimum soil bearing pressures."""

    if width_ft <= 0.0 or length_ft <= 0.0:
        raise ValueError("Footing dimensions must be positive.")

    average_bearing_ksf = service_axial_kips / (width_ft * length_ft)
    pressure_factor = (
        1.0
        + 6.0 * abs(eccentricity_x_ft) / length_ft
        + 6.0 * abs(eccentricity_y_ft) / width_ft
    )
    qmax_ksf = average_bearing_ksf * pressure_factor

    pressure_factor = (
        1.0
        - 6.0 * abs(eccentricity_x_ft) / length_ft
        - 6.0 * abs(eccentricity_y_ft) / width_ft
    )
    qmin_ksf = average_bearing_ksf * pressure_factor
    return qmax_ksf, qmin_ksf


def trial_footing_dimensions_ft(design_input: FootingDesignInput, required_area_sqft: float) -> tuple[float, float]:
    """Build an initial rectangular footing from area and column aspect ratio."""

    ratio = 1.0
    if design_input.column_width_ft > 0.0 and design_input.column_length_ft > 0.0:
        ratio = design_input.column_length_ft / design_input.column_width_ft
        ratio = min(max(ratio, 0.5), 2.0)

    width_ft = math.sqrt(required_area_sqft / ratio)
    length_ft = width_ft * ratio

    width_ft = max(width_ft, design_input.column_width_ft, design_input.min_footing_width_ft)
    length_ft = max(length_ft, design_input.column_length_ft, design_input.min_footing_length_ft)

    width_ft = round_up_to_increment(width_ft, design_input.dimension_increment_ft)
    length_ft = round_up_to_increment(length_ft, design_input.dimension_increment_ft)
    return width_ft, length_ft


def round_up_to_increment(value: float, increment: float) -> float:
    """Round a positive value up to the next configured increment."""

    if increment <= 0.0:
        raise ValueError("Dimension increment must be positive.")
    return math.ceil(value / increment) * increment


def is_within_middle_third(
    width_ft: float,
    length_ft: float,
    eccentricity_x_ft: float,
    eccentricity_y_ft: float,
) -> bool:
    """Return True when both eccentricities remain within the kern limits."""

    return abs(eccentricity_x_ft) <= length_ft / 6.0 and abs(eccentricity_y_ft) <= width_ft / 6.0


def design_rectangular_footing(design_input: FootingDesignInput) -> FootingDesignResult:
    """Size a rectangular footing using first-pass bearing and eccentricity checks.

    The function intentionally stays narrow in scope for v1.
    Future expansion points are marked with TODO comments instead of being
    partially implemented here.
    """

    validate_basic_inputs(design_input)

    assumptions = default_assumptions()
    if design_input.service_axial_kips <= 0.0:
        warning = CalculationWarning(
            code="NONPOSITIVE_AXIAL_LOAD",
            message="Nonpositive service axial load is outside the simplified footing sizing scope.",
        )
        return FootingDesignResult(
            input_data=design_input,
            required_area_sqft=None,
            recommended_width_ft=None,
            recommended_length_ft=None,
            provided_area_sqft=None,
            eccentricity_x_ft=None,
            eccentricity_y_ft=None,
            qmax_ksf=None,
            qmin_ksf=None,
            bearing_pass=False,
            middle_third_ok=False,
            full_contact_ok=False,
            outside_simplified_scope=True,
            warnings=[
                warning,
                CalculationWarning(
                    code="OUTSIDE_SIMPLIFIED_SCOPE",
                    message="Preliminary only - verify this case in full design software.",
                ),
            ],
            assumptions=assumptions,
            summary=ResultSummary(
                status="OUTSIDE_SCOPE",
                governing_check="Nonpositive service axial load.",
                bearing_utilization=0.0,
            ),
        )

    required_area = required_footing_area_sqft(
        design_input.service_axial_kips,
        design_input.allowable_bearing_ksf,
    )
    eccentricity_x_ft, eccentricity_y_ft = compute_eccentricities_ft(
        design_input.service_axial_kips,
        design_input.service_mx_kip_ft,
        design_input.service_my_kip_ft,
    )

    width_ft, length_ft = trial_footing_dimensions_ft(design_input, required_area)

    best_result = evaluate_design_state(
        design_input=design_input,
        required_area_sqft=required_area,
        width_ft=width_ft,
        length_ft=length_ft,
        eccentricity_x_ft=eccentricity_x_ft,
        eccentricity_y_ft=eccentricity_y_ft,
        assumptions=assumptions,
    )

    while width_ft <= design_input.max_footing_width_ft and length_ft <= design_input.max_footing_length_ft:
        if (
            best_result.bearing_pass
            and best_result.middle_third_ok
            and best_result.full_contact_ok
            and not best_result.outside_simplified_scope
        ):
            return best_result

        next_width_ft, next_length_ft = next_trial_dimensions(
            design_input=design_input,
            current_width_ft=width_ft,
            current_length_ft=length_ft,
            eccentricity_x_ft=eccentricity_x_ft,
            eccentricity_y_ft=eccentricity_y_ft,
            qmax_ksf=best_result.qmax_ksf or 0.0,
            qmin_ksf=best_result.qmin_ksf or 0.0,
        )

        if next_width_ft == width_ft and next_length_ft == length_ft:
            break

        width_ft, length_ft = next_width_ft, next_length_ft
        best_result = evaluate_design_state(
            design_input=design_input,
            required_area_sqft=required_area,
            width_ft=width_ft,
            length_ft=length_ft,
            eccentricity_x_ft=eccentricity_x_ft,
            eccentricity_y_ft=eccentricity_y_ft,
            assumptions=assumptions,
        )

    return add_warning(
        best_result,
        CalculationWarning(
            code="SIZE_LIMIT_REACHED",
            message="Configured maximum footing dimensions were reached before the simplified checks passed.",
        ),
    )


def validate_basic_inputs(design_input: FootingDesignInput) -> None:
    """Raise an error for invalid numeric inputs that are not design cases."""

    if design_input.allowable_bearing_ksf <= 0.0:
        raise ValueError("Allowable bearing pressure must be positive.")
    if design_input.dimension_increment_ft <= 0.0:
        raise ValueError("Dimension increment must be positive.")
    if design_input.min_footing_width_ft <= 0.0 or design_input.min_footing_length_ft <= 0.0:
        raise ValueError("Minimum footing dimensions must be positive.")
    if design_input.max_footing_width_ft < design_input.min_footing_width_ft:
        raise ValueError("Maximum footing width cannot be smaller than the minimum width.")
    if design_input.max_footing_length_ft < design_input.min_footing_length_ft:
        raise ValueError("Maximum footing length cannot be smaller than the minimum length.")


def evaluate_design_state(
    design_input: FootingDesignInput,
    required_area_sqft: float,
    width_ft: float,
    length_ft: float,
    eccentricity_x_ft: float,
    eccentricity_y_ft: float,
    assumptions: list[str],
) -> FootingDesignResult:
    """Evaluate bearing and eccentricity checks for a single trial footing."""

    qmax_ksf, qmin_ksf = bearing_pressures_ksf(
        service_axial_kips=design_input.service_axial_kips,
        width_ft=width_ft,
        length_ft=length_ft,
        eccentricity_x_ft=eccentricity_x_ft,
        eccentricity_y_ft=eccentricity_y_ft,
    )

    provided_area_sqft = width_ft * length_ft
    middle_third_ok = is_within_middle_third(
        width_ft=width_ft,
        length_ft=length_ft,
        eccentricity_x_ft=eccentricity_x_ft,
        eccentricity_y_ft=eccentricity_y_ft,
    )
    full_contact_ok = qmin_ksf >= 0.0
    bearing_pass = qmax_ksf <= design_input.allowable_bearing_ksf and full_contact_ok
    outside_simplified_scope = not full_contact_ok

    warnings: list[CalculationWarning] = []
    if not middle_third_ok:
        warnings.append(
            CalculationWarning(
                code="MIDDLE_THIRD_EXCEEDED",
                message="Eccentricity exceeds the middle third in at least one direction.",
            )
        )
    if qmin_ksf < 0.0:
        warnings.append(
            CalculationWarning(
                code="UPLIFT_WARNING",
                message="qmin is below zero, indicating loss of full soil contact.",
            )
        )
    if qmax_ksf > design_input.allowable_bearing_ksf:
        warnings.append(
            CalculationWarning(
                code="BEARING_FAIL",
                message="Maximum soil pressure exceeds the allowable soil bearing pressure.",
            )
        )
    if outside_simplified_scope:
        warnings.append(
            CalculationWarning(
                code="OUTSIDE_SIMPLIFIED_SCOPE",
                message="This case is outside the simplified preliminary bearing model.",
            )
        )

    summary = ResultSummary(
        status=determine_status(bearing_pass, outside_simplified_scope, warnings),
        governing_check=determine_governing_check(
            qmax_ksf=qmax_ksf,
            qmin_ksf=qmin_ksf,
            allowable_bearing_ksf=design_input.allowable_bearing_ksf,
            middle_third_ok=middle_third_ok,
            outside_simplified_scope=outside_simplified_scope,
        ),
        bearing_utilization=qmax_ksf / design_input.allowable_bearing_ksf,
    )

    # TODO: Add one-way shear, punching shear, and flexure screening in later passes.
    return FootingDesignResult(
        input_data=design_input,
        required_area_sqft=required_area_sqft,
        recommended_width_ft=width_ft,
        recommended_length_ft=length_ft,
        provided_area_sqft=provided_area_sqft,
        eccentricity_x_ft=eccentricity_x_ft,
        eccentricity_y_ft=eccentricity_y_ft,
        qmax_ksf=qmax_ksf,
        qmin_ksf=qmin_ksf,
        bearing_pass=bearing_pass,
        middle_third_ok=middle_third_ok,
        full_contact_ok=full_contact_ok,
        outside_simplified_scope=outside_simplified_scope,
        warnings=warnings,
        assumptions=assumptions,
        summary=summary,
    )


def next_trial_dimensions(
    design_input: FootingDesignInput,
    current_width_ft: float,
    current_length_ft: float,
    eccentricity_x_ft: float,
    eccentricity_y_ft: float,
    qmax_ksf: float,
    qmin_ksf: float,
) -> tuple[float, float]:
    """Return the next trial dimensions using simple, readable growth rules."""

    increment = design_input.dimension_increment_ft
    next_width_ft = current_width_ft
    next_length_ft = current_length_ft

    width_ratio = abs(eccentricity_y_ft) / current_width_ft if current_width_ft else 0.0
    length_ratio = abs(eccentricity_x_ft) / current_length_ft if current_length_ft else 0.0

    if qmin_ksf < 0.0:
        if length_ratio >= width_ratio and current_length_ft < design_input.max_footing_length_ft:
            next_length_ft = min(current_length_ft + increment, design_input.max_footing_length_ft)
        elif current_width_ft < design_input.max_footing_width_ft:
            next_width_ft = min(current_width_ft + increment, design_input.max_footing_width_ft)
        return next_width_ft, next_length_ft

    if qmax_ksf > design_input.allowable_bearing_ksf:
        if current_width_ft <= current_length_ft and current_width_ft < design_input.max_footing_width_ft:
            next_width_ft = min(current_width_ft + increment, design_input.max_footing_width_ft)
        elif current_length_ft < design_input.max_footing_length_ft:
            next_length_ft = min(current_length_ft + increment, design_input.max_footing_length_ft)
        return next_width_ft, next_length_ft

    if current_width_ft < design_input.max_footing_width_ft:
        next_width_ft = min(current_width_ft + increment, design_input.max_footing_width_ft)
    if current_length_ft < design_input.max_footing_length_ft:
        next_length_ft = min(current_length_ft + increment, design_input.max_footing_length_ft)
    return next_width_ft, next_length_ft


def determine_status(
    bearing_pass: bool,
    outside_simplified_scope: bool,
    warnings: list[CalculationWarning],
) -> str:
    """Map result state to a simple status label."""

    if outside_simplified_scope:
        return "OUTSIDE_SCOPE"
    if bearing_pass and not warnings:
        return "PASS"
    if bearing_pass:
        return "PASS_WITH_WARNINGS"
    return "WARNING"


def determine_governing_check(
    qmax_ksf: float,
    qmin_ksf: float,
    allowable_bearing_ksf: float,
    middle_third_ok: bool,
    outside_simplified_scope: bool,
) -> str:
    """Return a readable summary of the governing condition."""

    if outside_simplified_scope and qmin_ksf < 0.0:
        return "Outside simplified scope: qmin < 0 causes loss of full soil contact."
    if not middle_third_ok:
        return "Eccentricity exceeds the middle third limit."
    if qmax_ksf > allowable_bearing_ksf:
        return "Bearing pressure governs: qmax exceeds allowable soil pressure."
    return "Bearing pressure is the governing implemented check."


def default_assumptions() -> list[str]:
    """Return standard assumptions attached to each first-pass result."""

    return [
        "Preliminary only - verify in full design software.",
        "Rectangular isolated footing under a single column.",
        "Service loads only.",
        "Uniform allowable soil bearing pressure.",
        "Linear soil pressure distribution with full contact required for acceptance.",
        "One-way shear, punching shear, and flexure are not yet implemented in this pass.",
    ]


def add_warning(result: FootingDesignResult, warning: CalculationWarning) -> FootingDesignResult:
    """Append a warning and refresh the summary status for a result."""

    warnings = list(result.warnings)
    warnings.append(warning)
    warnings.append(
        CalculationWarning(
            code="OUTSIDE_SIMPLIFIED_SCOPE",
            message="Preliminary only - verify this case in full design software.",
        )
    )
    result.warnings = deduplicate_warnings(warnings)
    result.outside_simplified_scope = True
    result.summary = ResultSummary(
        status="OUTSIDE_SCOPE",
        governing_check=warning.message,
        bearing_utilization=result.summary.bearing_utilization,
    )
    return result


def deduplicate_warnings(warnings: list[CalculationWarning]) -> list[CalculationWarning]:
    """Keep warning order while removing duplicate codes."""

    seen_codes: set[str] = set()
    unique_warnings: list[CalculationWarning] = []
    for warning in warnings:
        if warning.code in seen_codes:
            continue
        seen_codes.add(warning.code)
        unique_warnings.append(warning)
    return unique_warnings
