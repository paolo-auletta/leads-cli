---
name: company-discovery-operator
description: Validate, execute, inspect, rerun, and explain Company Discovery CLI runs from an existing company_search_spec.json. Use when a user asks an agent to run company discovery, find companies from a prepared spec, inspect a discovered domain, export a run, or summarize selected, reserve, and rejected company results. Do not rewrite the ICP or work on contacts.
---

# Operate Company Discovery

Run company discovery from an existing spec without silently changing it.

## New discovery

1. Locate the requested `company_search_spec.json`.
2. Run `leads companies validate-spec --spec <path>`.
3. Report material open modes shown by validation: national geography, no size filter, no custom exclusions, or exploratory vertical.
4. State the novelty policy before running: `unused_memory` searches unused memory first,
   `only_new` bypasses memory candidates and suppresses known domains, and `full_memory` permits
   reuse of previously selected companies. If omitted, the policy is `unused_memory`.
5. For multi-vertical specs, report the balance mode and treat each vertical as an independent memory and external-search lane.
6. Run `leads companies discover --spec <path>`. Add `--verbose` only when detailed queries and candidate decisions help diagnose the run.
7. Let the command finish. Do not launch a duplicate while the original process is active.
8. Read the final counts and Markdown summary path.
9. Summarize memory reuse, known-domain suppression for `only_new`, external-search volume,
   selected/reserve/rejected counts, per-vertical outcomes, and any shortfall.

Discovery stops after saving and reporting its run ID. Never start enrichment through a discovery
flag. When the user also requests enrichment, finish discovery first and pass its saved run ID to
the separate enrichment workflow.

## Follow-up operations

- Inspect a run with `leads companies show-run <run-id>`.
- Inspect one domain with `leads companies inspect <run-id> --domain <domain>`.
- Regenerate artifacts with `leads companies export <run-id>`.
- Repeat the exact prior spec and its novelty policy using `leads companies rerun <run-id>`.

## Guardrails

- Do not edit or replace the spec unless the user asks to change the ICP.
- Do not hide a missing constraint or selected-count shortfall.
- Do not describe reserve companies as confirmed selections.
- Explain deterministic hygiene rejections separately from LLM ICP judgments when relevant.
- Treat the saved run and artifacts as authoritative; do not infer companies from terminal snippets alone.
- Never expose API keys or raw environment values.
