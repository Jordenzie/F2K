"""Behavior tests for the first-pass footing sizing engine."""

from footing_prelim.calculations import design_rectangular_footing
from footing_prelim.models import FootingDesignInput


def warning_codes(result) -> set[str]:
    """Return warning codes for compact assertions."""

    return {warning.code for warning in result.warnings}


def test_design_returns_passing_case() -> None:
    """A moderate service load should produce a passing preliminary footing."""

    design_input = FootingDesignInput(
        service_axial_kips=200.0,
        service_mx_kip_ft=20.0,
        service_my_kip_ft=10.0,
        allowable_bearing_ksf=4.0,
        column_width_ft=1.5,
        column_length_ft=1.5,
        footing_thickness_ft=1.5,
    )

    result = design_rectangular_footing(design_input)

    assert result.bearing_pass is True
    assert result.outside_simplified_scope is False
    assert result.qmin_ksf >= 0.0
    assert result.summary.status == "PASS"
    assert "UPLIFT_WARNING" not in warning_codes(result)


def test_eccentricity_is_reported_for_biaxial_case() -> None:
    """The result should report eccentricities derived from the service moments."""

    design_input = FootingDesignInput(
        service_axial_kips=300.0,
        service_mx_kip_ft=60.0,
        service_my_kip_ft=30.0,
        allowable_bearing_ksf=5.0,
        column_width_ft=1.5,
        column_length_ft=2.0,
        footing_thickness_ft=1.75,
    )

    result = design_rectangular_footing(design_input)

    assert result.eccentricity_x_ft == 0.1
    assert result.eccentricity_y_ft == 0.2
    assert result.qmax_ksf > result.qmin_ksf


def test_uplift_warning_when_qmin_is_negative() -> None:
    """A highly eccentric case should warn when qmin falls below zero."""

    design_input = FootingDesignInput(
        service_axial_kips=50.0,
        service_mx_kip_ft=0.0,
        service_my_kip_ft=400.0,
        allowable_bearing_ksf=3.0,
        column_width_ft=1.5,
        column_length_ft=1.5,
        footing_thickness_ft=1.5,
    )

    result = design_rectangular_footing(design_input)

    assert result.full_contact_ok is False
    assert result.outside_simplified_scope is True
    assert result.qmin_ksf < 0.0
    assert "UPLIFT_WARNING" in warning_codes(result)


def test_middle_third_warning_is_raised() -> None:
    """A severe moment should trigger the middle-third warning."""

    design_input = FootingDesignInput(
        service_axial_kips=75.0,
        service_mx_kip_ft=300.0,
        service_my_kip_ft=0.0,
        allowable_bearing_ksf=4.0,
        column_width_ft=1.5,
        column_length_ft=1.5,
        footing_thickness_ft=1.5,
        max_footing_width_ft=20.0,
    )

    result = design_rectangular_footing(design_input)

    assert result.middle_third_ok is False
    assert "MIDDLE_THIRD_EXCEEDED" in warning_codes(result)


def test_nonpositive_axial_load_is_flagged_outside_scope() -> None:
    """Zero or uplift-only axial load is outside the simplified v1 engine scope."""

    design_input = FootingDesignInput(
        service_axial_kips=0.0,
        service_mx_kip_ft=0.0,
        service_my_kip_ft=0.0,
        allowable_bearing_ksf=4.0,
        column_width_ft=1.5,
        column_length_ft=1.5,
        footing_thickness_ft=1.5,
    )

    result = design_rectangular_footing(design_input)

    assert result.recommended_width_ft is None
    assert result.outside_simplified_scope is True
    assert result.summary.status == "OUTSIDE_SCOPE"
    assert "NONPOSITIVE_AXIAL_LOAD" in warning_codes(result)
