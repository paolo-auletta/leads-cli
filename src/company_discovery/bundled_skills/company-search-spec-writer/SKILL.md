---
name: company-search-spec-writer
description: Turn natural-language company targeting or ICP requests into strict company_search_spec.json files for the Company Discovery CLI. Use when a user asks to find target companies, define a company ICP, prepare a company search, or translate company criteria such as vertical, geography, employee size, exclusions, and novelty into a runnable spec. Do not use for contact or person searches.
---

# Write a Company Search Spec

Create one `company_search_spec.json` under the Leads workspace unless the user gives another path.

## Workspace And CLI

Use `leads doctor` or `leads version` to confirm the workspace root. The root contains
`backups/`, `config/`, `data/`, `logs/`, `runs/`, `skills/`, and `specs/`.

- Write company specs to `specs/companies/`, for example
  `specs/companies/company_search_spec.json`.
- Contact specs belong in `specs/contacts/`; do not write contact specs here.
- Runtime config is in `config/config.toml`; secrets are in `config/secrets.toml`; never expose
  secret values.
- The SQLite memory DB is `data/company_memory.db`; use CLI commands rather than editing it.
- Run artifacts are saved under `runs/`; backups are saved under `backups/`; CLI diagnostics are in
  `logs/leads.log`; installed skill metadata lives under `skills/`.
- Useful setup/maintenance commands: `leads init`, `leads version`, `leads doctor`,
  `leads update --check`, `leads migrate --check`, and `leads skills status`.

## Workflow

1. Extract only company-level criteria the user actually supplied.
2. Set `version` to `1` and require a positive `count`.
3. Use `verticals` for every new spec. Add one entry per requested vertical; multiple entries mean
   OR (separate company groups), never companies that must match every vertical.
4. Each vertical should always use one simple shape: `key`, `label`, and optional query hints.
   Use a lowercase stable key.
5. Add `search_terms` only when the vertical is niche, ambiguous, or user wording needs stronger
   search hints. Add `exclude_terms` only when a few obvious search-time negatives help reduce
   noise. Do not invent ICP constraints.
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
12. Add `external_search` to every new spec. Default to `{"exa_searches": 8, "results_per_search": 5}` unless the user asks for a broader or cheaper search. `exa_searches` is the number of Exa searches per active vertical/lane; `results_per_search` is the number of Exa results requested by each search.
13. Write JSON, then run `leads companies validate-spec --spec <spec-path>`.
14. Fix validation errors before returning. Do not run discovery unless the user asked for it.

## Contract

Use this shape and omit no top-level fields except those with documented defaults:

```json
{
  "version": 1,
  "count": 50,
  "verticals": [
    {"key": "construction", "label": "Construction"},
    {"key": "healthcare", "label": "Healthcare"}
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
  "balance_mode": "soft",
  "external_search": {
    "exa_searches": 8,
    "results_per_search": 5
  }
}
```

Allowed novelty values are `unused_memory`, `only_new`, and `full_memory`.

- `unused_memory` (default): search memory first, but never select a company that was selected before.
- `only_new`: do not source candidates from memory and discard external results whose domains are already known.
- `full_memory`: search all matching memory, including companies selected in prior runs.
Allowed balance values are `soft`, `strict`, and `none`.
`external_search.exa_searches` may be 1-20. `external_search.results_per_search` may be
1-100. Keep the default `8` and `5` unless the user asks to make discovery broader, narrower,
cheaper, or more exhaustive.

For a niche or ambiguous vertical, add query hints like:

```json
{
  "key": "marine-surveying",
  "label": "Marine Surveying",
  "search_terms": ["marine surveying", "vessel inspection", "cargo survey"],
  "exclude_terms": ["software", "directory", "marketplace"]
}
```

Allowed structured ownership signals are `family_owned`, `franchise`, `parent`, `subsidiary`,
`division`, and `acquired`. When a size bound is one-sided, include only the known bound. When
exclusions are omitted, keep all exclusion arrays empty. Preserve the user's ambiguity instead of
silently tightening the ICP. Old specs that still use `mode`, `seed_terms`, or `anti_terms` remain
valid, but new specs should not emit them.
