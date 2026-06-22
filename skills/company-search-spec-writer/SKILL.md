---
name: company-search-spec-writer
description: Turn natural-language company targeting or ICP requests into strict company_search_spec.json files for the Company Discovery CLI. Use when a user asks to find target companies, define a company ICP, prepare a company search, or translate company criteria such as vertical, geography, employee size, exclusions, and novelty into a runnable spec. Do not use for contact or person searches.
---

# Write a Company Search Spec

Create one `company_search_spec.json` in the user's working directory.

## Workflow

1. Extract only company-level criteria the user actually supplied.
2. Set `version` to `1` and require a positive `count`.
3. Use `verticals` for every new spec. Add one entry per requested vertical; multiple entries mean
   OR (separate company groups), never companies that must match every vertical.
4. Choose `known` vertical mode for a clear established category. Use a lowercase stable key.
5. Choose `exploratory` for a new or specialized vertical. Add concrete `seed_terms` and useful `anti_terms` derived from the vertical meaning, without adding ICP constraints.
6. Encode broad US geography as `{"country": "US", "states": []}`. Use two-letter uppercase state codes when states are requested.
7. Use an empty `company_size` object when no employee range was given. Never invent employee limits.
8. Use empty arrays for omitted include/exclude criteria. When the user explicitly excludes family
   businesses, set `exclude.structured.ownership_signals` to `["family_owned"]`. This tells enrichment
   to block a company when official-site or corroborating evidence identifies it as family-owned.
   Never invent this exclusion.
9. Default `novelty_mode` to `unused_memory`. This searches memory first but excludes every company
   that has ever been selected. Use `only_new` when the user wants external discovery only; it skips
   memory candidates and excludes known domains returned by search. Use `full_memory` only when the
   user explicitly permits reusing companies selected in prior runs.
10. Default `reserve_ratio` to `0.5`; this controls output capacity, not ICP fit.
11. Default `balance_mode` to `soft` for multiple verticals. Use `strict` only when equal caps matter more than reaching the requested count, and `none` only when distribution does not matter.
12. Write JSON, then run `leads companies validate-spec --spec company_search_spec.json`.
13. Fix validation errors before returning. Do not run discovery unless the user asked for it.

## Contract

Use this shape and omit no top-level fields except those with documented defaults:

```json
{
  "version": 1,
  "count": 50,
  "verticals": [
    {"mode": "known", "key": "construction", "label": "Construction"},
    {"mode": "known", "key": "healthcare", "label": "Healthcare"}
  ],
  "geography": {"country": "US", "states": ["TX"]},
  "company_size": {"employee_min": 20, "employee_max": 100},
  "include": {"keywords": [], "subtypes": []},
  "exclude": {
    "keywords": [],
    "ownership_types": [],
    "company_patterns": [],
    "structured": {"ownership_signals": []}
  },
  "novelty_mode": "unused_memory",
  "reserve_ratio": 0.5,
  "balance_mode": "soft"
}
```

Allowed novelty values are `unused_memory`, `only_new`, and `full_memory`.

- `unused_memory` (default): search memory first, but never select a company that was selected before.
- `only_new`: do not source candidates from memory and discard external results whose domains are already known.
- `full_memory`: search all matching memory, including companies selected in prior runs.
Allowed balance values are `soft`, `strict`, and `none`.

For an exploratory vertical, use:

```json
{
  "mode": "exploratory",
  "key": "marine-surveying",
  "label": "Marine Surveying",
  "seed_terms": ["marine surveying", "vessel inspection", "cargo survey"],
  "anti_terms": ["software", "directory", "marketplace"]
}
```

Allowed structured ownership signals are `family_owned`, `franchise`, `parent`, `subsidiary`,
`division`, and `acquired`. When a size bound is one-sided, include only the known bound. When
exclusions are omitted, keep all exclusion arrays empty. Preserve the user's ambiguity instead of
silently tightening the ICP.
