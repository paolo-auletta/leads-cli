# Codebase Review

Date: 2026-06-22

## Scope

This review focused on the kinds of slips we already found:

- stale concepts that remain in docs, skills, or tests after the runtime changed;
- schema versus runtime contract drift;
- edge-case behavior that looks fine in normal runs but breaks expectations in small or odd cases;
- inconsistent developer ergonomics across similar surfaces.

I also reran the test suite during this pass. It is currently green.

## Implementation status

These findings were fixed after the review:

- `reserve_count` now uses an explicit ceiling policy and preserves `reserve_ratio = 0` as no reserve pool.
- The company schema now accepts current vertical fields and legacy aliases without allowing duplicate alias pairs.
- The contact schema now matches runtime role-key normalization for spaces, hyphens, and uppercase input.
- The stale `exploratory vertical` wording was removed from the discovery operator skill.
- Happy-path tests now use canonical company vertical specs, with legacy support isolated to compatibility tests.
- `ContactSearchSpec.from_file(...)` now reports missing files with the same clean `ValueError` style as company specs.

## Findings

### 1. `reserve_ratio` uses Python `round()`, which makes reserve capacity behave unexpectedly

Files:

- `src/company_discovery/domain/spec.py:217`

Problem:

`CompanySearchSpec.reserve_count` is computed with:

```python
return round(self.count * self.reserve_ratio)
```

This is risky because Python uses bankers rounding.

Examples with the current default `reserve_ratio = 0.5`:

- `count = 1` -> reserve count becomes `0`
- `count = 3` -> reserve count becomes `2`
- `count = 5` -> reserve count becomes `2`

Impact:

- very small runs can silently get no reserve pool at all;
- odd requested counts produce non-intuitive reserve sizes;
- selection capacity and lane balancing become harder to reason about.

Why this matters:

The reserve pool is part of the product behavior, not just an implementation detail. If the default says "half as many reserves", users and future maintainers will expect a predictable rule such as floor or ceil, not bankers rounding.

Recommendation:

Choose an explicit policy and encode it directly:

- `math.floor(count * ratio)` if reserves should never exceed the ratio target;
- `math.ceil(count * ratio)` if every non-zero ratio should produce some reserve coverage;
- or a custom rule like `max(1, floor(...))` for small runs.

### 2. The JSON Schema files are not the runtime contract and already drift from actual validation behavior

Files:

- `src/company_discovery/cli.py:571`
- `src/company_discovery/cli.py:705`
- `src/company_discovery/domain/spec.py:39`
- `src/company_discovery/domain/spec.py:188`
- `src/company_discovery/domain/contact_spec.py:40`
- `schemas/company_search_spec.schema.json:13`
- `schemas/contact_search_spec.schema.json:24`

Problem:

The CLI validation commands call the Pydantic models directly:

- company specs go through `CompanySearchSpec.from_file(...)`
- contact specs go through `ContactSearchSpec.from_file(...)`

The schema files are not used in that validation path, and they are not equivalent to runtime behavior.

Concrete mismatches found:

- company runtime still accepts legacy vertical fields through aliases:
  - `mode`
  - `seed_terms`
  - `anti_terms`
- the company schema no longer allows those legacy fields at all.

- contact runtime normalizes role keys before validation:
  - `"Project Manager"` becomes `project_manager`
  - `"project-manager"` becomes `project_manager`
- the contact schema requires the final normalized regex shape up front and would reject those raw inputs.

Impact:

- an external agent or tool that relies on the schema can disagree with the CLI;
- "valid according to schema" and "valid according to the app" are not the same thing;
- future changes can drift again because the schemas are not exercised by the runtime.

Why this matters:

This project is intentionally agent-first and spec-driven. If the contract has two competing sources of truth, the agent surface gets brittle fast.

Recommendation:

Pick one of these directions:

1. Make Pydantic the only contract and stop presenting the schema files as authoritative.
2. Keep schema files, but generate them from the runtime models or validate them in tests against real examples and legacy inputs.

### 3. The `exploratory vertical` concept is still present in an operator skill after being removed from the runtime contract

Files:

- `skills/company-discovery-operator/SKILL.md:14`

Problem:

The discovery operator skill still tells the agent to report "`exploratory vertical`" as an open mode.

That concept no longer exists in the canonical runtime spec. The vertical contract is now:

- `key`
- `label`
- optional `search_terms`
- optional `exclude_terms`

Impact:

- an agent following the skill can reintroduce obsolete language;
- users can get explanations that do not match what the CLI actually validates or prints;
- future prompts may keep generating needless conceptual baggage we already removed.

Recommendation:

Update the operator skill so it talks only about the current open modes:

- national geography
- no size filter
- no custom exclusions

If needed, mention "vertical search hints present" separately, but not as a mode.

### 4. Tests still lean heavily on legacy spec shapes, so they do not strongly protect the new canonical contract

Files:

- `tests/integration/test_cli.py:94`
- `tests/integration/test_cli.py:112`
- `tests/integration/test_pipeline.py:258`
- `tests/integration/test_contact_discovery_pipeline.py:150`
- `tests/unit/test_spec.py:57`

Problem:

Several tests still build company specs with legacy `mode` fields. That is useful for backward-compat coverage, but right now the suite leans too much on legacy examples and not enough on the new canonical shape.

Impact:

- backward compatibility is tested;
- canonical agent-facing output is not tested as strongly as it should be;
- a future regression in the new `search_terms` / `exclude_terms` shape could slip through while the suite still passes on legacy payloads.

Recommendation:

Split this more deliberately:

- keep a small explicit set of legacy-compat tests;
- migrate most happy-path fixtures to the new canonical spec shape;
- add one or two direct tests that prove canonical vertical hints survive validation and export correctly.

### 5. Company and contact spec loaders handle missing files inconsistently

Files:

- `src/company_discovery/domain/spec.py:203`
- `src/company_discovery/domain/contact_spec.py:78`

Problem:

`CompanySearchSpec.from_file(...)` catches `FileNotFoundError` and turns it into a clean `ValueError`.

`ContactSearchSpec.from_file(...)` does not. It only catches bad JSON.

Impact:

- the CLI hides most of this because Typer checks `exists=True`;
- library callers or future code paths will get inconsistent errors depending on whether they load a company or contact spec.

Recommendation:

Make the contact loader mirror the company loader for consistency.

## Overall take

The runtime itself is in much better shape than the old design, and the major pipelines are coherent.

The main remaining risk is not "core logic is broken." It is "the contract is starting to live in too many places":

- Pydantic models
- schema files
- skills
- tests
- notes

When those drift, the system feels messier than it really is.

## Suggested cleanup order

1. Fix reserve-count rounding.
2. Clean the stale `exploratory vertical` wording from the discovery operator skill.
3. Decide whether schema files are authoritative or informational.
4. Rebalance the tests so canonical spec shapes dominate and legacy coverage is isolated.
5. Make contact spec file loading match company spec loading.
