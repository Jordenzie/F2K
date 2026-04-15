# AI Command Layer

This project now uses a deterministic natural-language command pipeline in `footing_prelim/ai_assistant.py` instead of freeform AI text edits.

## Pipeline

1. `normalize_user_text()` cleans punctuation, normalizes units, and applies high-confidence typo corrections.
2. `build_structured_actions()` splits the request into clauses and resolves each clause into one or more `AICommandAction` objects.
3. `resolve_target_id()`, `refine_target_id()`, `infer_operation()`, and the quantity/unit helpers map plain English into real editable footing fields.
4. `execute_actions()` validates every proposed edit, updates the real `FootingDesignInput`, reruns `design_rectangular_footing()`, and records before/after changes.
5. `format_user_response()` turns the applied action list into a concise user-facing explanation.

The command layer always converts the request into structured actions before mutating the model. The frontend never applies freeform text directly.

## Fuzzy Matching

Fuzzy handling is intentionally conservative:

- `EXPLICIT_TOKEN_CORRECTIONS` covers common engineering typos and known misspellings.
- `VOCABULARY_TOKENS` is built from real field aliases, target aliases, unit tokens, and command words.
- `normalize_token()` only auto-corrects unknown words when the similarity score is high enough.
- Every applied correction is stored in `fuzzy_corrections` so the UI response can acknowledge it.

To add new misspellings or shorthand later:

1. Add the typo to `EXPLICIT_TOKEN_CORRECTIONS` when the correction is safe and obvious.
2. Add new engineering vocabulary or unit tokens to the field aliases, target aliases, or vocabulary builder.
3. Add tests for the new phrasing in `tests/test_ai_assistant.py`.

## Adding Editable Fields

The editable command surface is driven by metadata:

- `FIELD_SPECS` defines the real editable model fields, labels, units, limits, and aliases.
- `TARGET_SPECS` defines virtual groups such as footing plan dimensions or service loads.

To add a new editable input:

1. Add the real field to `FootingDesignInput`.
2. Add a matching `FieldSpec` with limits, units, and aliases.
3. If the field belongs to a grouped concept, update `TARGET_SPECS`.
4. Extend the target refinement or operation logic only if the new field introduces a new command pattern.
5. Add parser and workflow tests that prove the new field works through natural-language commands.

## Extending Beyond Isolated Footings

The command layer is intentionally generic:

- actions are field-based, not footing-specific
- target groups are metadata-driven
- validation is separated from parsing
- recalculation happens after structured actions are applied

To support future foundation types, keep the same layers and swap in:

- a different input model
- a different field/target registry
- a different calculation engine

The parsing and validation patterns can stay the same as long as new element types expose their editable fields through metadata the same way this footing model does.
