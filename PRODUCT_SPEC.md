# MVP - Internal Spread Footing Preliminary Design Assistant

## Product Summary

This application is an internal structural engineering tool for rapid preliminary sizing of isolated rectangular spread footings under a single column.

It is intentionally limited in scope.

Every major screen, report, and exported result must reinforce the message:

**Preliminary only - verify in full design software.**

## Problem Statement

Legacy footing tools are often slow to use, visually cluttered, and unclear about what governs the design.

The replacement tool should:

- reduce tab-heavy workflow
- show live results as inputs change
- make governing checks obvious
- present warnings early and clearly
- keep calculations easy to audit

## Primary Users

- structural engineers performing early-stage footing sizing
- internal office users who need quick pass/fail guidance before detailed design

## Product Goals

- very fast input workflow
- fewer screens and less clutter than legacy tools
- live-updating results
- clear pass/fail status
- obvious governing check
- explicit warnings and scope limits
- clean internal report output

## Design Principles

The legacy reference screenshots show several problems that this v1 should avoid later in the UI layer:

- too many tabs for a small amount of core input
- weak visual hierarchy
- dense forms with little guidance
- pass/fail information buried inside tables
- too many rarely used controls shown at once

For v1, calculations and result objects should be designed so a cleaner interface can be added later without rewriting engineering logic.

## Scope for V1

Included:

- isolated rectangular spread footings only
- single column only
- service axial load `P`
- service biaxial moments `Mx` and `My`
- allowable soil bearing pressure
- column dimensions
- footing thickness
- simple material assumptions
- preliminary bearing and eccentricity screening

Excluded:

- combined footings
- strap footings
- mats or rafts
- piles or drilled piers
- settlement analysis
- detailed geotechnical modeling
- uplift dynamics or seismic foundation dynamics
- code-complete final design
- full load combination management
- rebar detailing drawings

## Required V1 Outputs

- required footing area
- recommended footing width and length
- eccentricity in each direction
- `qmax` and `qmin`
- bearing pass/fail
- warning if `qmin < 0`
- warning if eccentricity exceeds the middle third
- governing-check summary
- explicit outside-simplified-scope warnings
- final note stating the tool is preliminary only

## Engineering Assumptions for First Coding Pass

- consistent units: `kips`, `feet`, `ksf`, and `ksi`
- service-level loading only
- uniform allowable bearing pressure
- linear soil pressure distribution
- full-contact bearing assumed for acceptable simplified results
- footing is centered under the column in plan before load eccentricity is applied
- moments are converted to eccentricity by `e = M / P`
- `Mx` acts about the local `x` axis and produces eccentricity in the `y` direction
- `My` acts about the local `y` axis and produces eccentricity in the `x` direction

Not yet implemented in the first coding pass:

- one-way shear screening
- punching shear screening
- rough flexural steel estimate

These items should be added later without restructuring the package.

## Calculation Philosophy

The engine should favor:

- small readable functions
- explicit intermediate values
- structured result objects
- warning lists with stable codes
- assumptions returned with each result
- maintainable logic over optimization

If a case falls outside the simplified assumptions, the result should still be returned with warnings instead of pretending to produce a valid design.

## Simplified Outside-Scope Triggers in V1

The first-pass engine should flag a result as outside simplified scope when any of the following occurs:

- nonpositive service axial load
- `qmin < 0`, indicating loss of full soil contact
- the footing cannot be grown to an acceptable size within configured maximum dimensions

## Simplest Practical V1 Stack

- Python for engineering calculations
- standard-library `dataclasses` for structured inputs and results
- `pytest` for tests
- FastAPI later, once the calculation engine is stable
- frontend later, after the calculation contract is settled

Rationale:

- easy for engineers to read
- low setup overhead
- no unnecessary framework decisions in v1
- straightforward to audit and extend

## Proposed V1 Folder Structure

See `PROJECT_STRUCTURE.md`.

## V1 Deliverables in This Pass

- product spec
- proposed project structure
- Python calculation engine for first-pass bearing and eccentricity checks
- pytest coverage for core scenarios

## Product Reminder

All reports and major screens must end with:

**Preliminary only - verify in full design software.**
