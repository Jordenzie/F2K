# Proposed V1 Structure

```text
MVP/
|-- PRODUCT_SPEC.md
|-- PROJECT_STRUCTURE.md
|-- dev_server.py
|-- pyproject.toml
|-- footing_prelim/
|   |-- __init__.py
|   |-- calculations.py
|   `-- models.py
|-- web/
|   |-- app.js
|   |-- index.html
|   `-- styles.css
`-- tests/
    `-- test_calculations.py
```

## Why This Structure

- `footing_prelim/` keeps engineering logic separate from any future API or UI.
- `models.py` holds structured inputs and outputs.
- `calculations.py` holds small, auditable calculation functions.
- `tests/` stays focused on behavior, not implementation details.
- `dev_server.py` exposes the calculation engine to a small local browser prototype.
- `web/` contains the lightweight visual shell for live progress checks.
- `pyproject.toml` is enough for local `pytest` execution without framework overhead.

## Simplest Practical Stack for V1

- Python 3.9+
- `dataclasses` from the standard library
- `pytest`

## TODO for Later

- add `api/` when FastAPI endpoints are needed
- add `ui/` after the calculation contract is stable
- add report formatting and export helpers once output requirements settle
