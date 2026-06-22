# Company Discovery

An agent-first, memory-first company targeting and enrichment engine. A strict JSON spec drives
deterministic memory retrieval, focused Exa searches, structured LLM evaluation, targeted
official-site enrichment, persistence, and reviewable CSV/Markdown/JSON artifacts.

Design and rebuild notes live in [`NOTES/`](./NOTES/README.md).

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp examples/company_search_spec.json company_search_spec.json
export EXA_API_KEY=...
export LLM_API_KEY=...
leads companies discover --spec company_search_spec.json
```

Runtime data defaults to `.company-discovery/`. Override it with
`COMPANY_DISCOVERY_HOME=/path/to/data`.

`LLM_RESPONSE_FORMAT=auto` uses strict JSON Schema with OpenAI and validated JSON Object mode
with DeepSeek or other compatible providers. Override it only when a provider documents support
for a different mode.

## Commands

```bash
leads companies discover --spec company_search_spec.json
leads companies enrich DISCOVERY_RUN_ID
leads companies show-run RUN_ID
leads companies inspect RUN_ID --domain example.com
leads companies export RUN_ID
leads companies rerun RUN_ID
leads companies show-enrichment ENRICHMENT_RUN_ID
leads companies inspect-enrichment ENRICHMENT_RUN_ID --domain example.com
leads companies export-enrichment ENRICHMENT_RUN_ID
```

Use `--verbose` on `discover` to print generated queries and candidate-level decisions.

## Multiple verticals

Use `verticals` to request OR semantics: companies may match construction, healthcare, or
engineering; they do not need to match all three. Each vertical gets an independent memory scan,
gap calculation, Exa query plan, and evaluation lane.

`balance_mode` controls final selection. `soft` (the default) fills an equal quality-gated floor
per vertical, then reallocates unused slots to good companies from stronger lanes. `strict` keeps
equal caps and may return fewer companies. `none` selects good companies in discovery order.

The legacy single `vertical` object remains accepted for existing specs.

## Memory policy

`novelty_mode` controls whether saved companies can enter a run:

- `unused_memory` (default) searches memory first and only considers companies never selected before.
- `only_new` skips memory candidates and removes externally rediscovered domains already in memory.
- `full_memory` searches all matching memory, including companies selected in previous runs.

Old `prefer_new` and `allow_known` specs remain readable and normalize to `unused_memory` and
`full_memory`, respectively.

## Enrichment

Enrichment is always a separate command run after discovery completes:

```bash
leads companies discover --spec company_search_spec.json
leads companies enrich DISCOVERY_RUN_ID
```

It consumes selected companies directly from the completed discovery run. It retains company
name, root domain, target vertical, geography, employee estimate, ownership type, and discovery
evidence, then finds only the missing phone, complete in-scope address, and independence status.

Fresh enrichment facts are reused by company/domain before any website request. The bounded website
pass reads the homepage and best contact/location/about pages; unresolved fields can use a narrow
Exa corroboration search. Output is split into `enriched.csv`, `review.csv`, and `blocked.csv`, while
the enrichment `run.json` keeps field provenance, conflicts, and the per-company trace.

By default, complete profiles with unknown independence remain in review. Add
`--allow-unknown-independence` only when that uncertainty is acceptable. Generic values such as
`privately_held` never count as proof of independence.

To exclude family businesses during enrichment, add this to the discovery spec:

```json
"exclude": {
  "structured": {"ownership_signals": ["family_owned"]}
}
```

Enrichment still records the company as independent, but sends it to `blocked.csv` with a
`fit_conflict` and `excluded_family_owned` flag. The ownership signal is retained in enrichment
memory, so the same rule applies when a later run reuses fresh facts.
