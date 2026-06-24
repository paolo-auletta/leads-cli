---
name: company-discovery-operator
description: Validate, execute, inspect, rerun, and explain Company Discovery CLI runs from an existing company_search_spec.json. Use when a user asks an agent to run company discovery, find companies from a prepared spec, inspect a discovered domain, export a run, or summarize selected, reserve, and rejected company results. Do not rewrite the ICP or work on contacts.
---

# Operate Company Discovery

Run company discovery from an existing spec without silently changing it.
For general questions about what Leads does, how the CLI works, or which workflow the user should
run, read `leads-onboarding-guide` first and use this skill only for discovery execution.

## Workspace And CLI

Use `leads doctor` or `leads version` to confirm the workspace root. The root contains
`backups/`, `config/`, `data/`, `logs/`, `runs/`, `skills/`, and `specs/`.

- Company specs normally live in `specs/companies/`; validate the exact spec path before running.
- Company discovery artifacts are saved under `runs/<company-discover-id>/` with `selected.csv`,
  `reserve.csv`, `rejected.csv`, `summary.md`, `run.json`, and `leads.xlsx`.
- `leads.xlsx` is the consolidated client-facing workbook in the discovery run root. After
  discovery, its `Companies` sheet contains selected and reserve companies and its `Contacts`
  sheet is empty.
- Config lives in `config/config.toml`; secrets live in `config/secrets.toml`; never expose secret
  values.
- The memory database is `data/company_memory.db`; treat CLI output and saved artifacts as the
  normal interface.
- Backups are under `backups/`; CLI diagnostics are in `logs/leads.log`; installed skill metadata
  is under `skills/`.
- Useful setup/maintenance commands: `leads init`, `leads version`, `leads doctor`,
  `leads update --check`, `leads migrate --check`, and `leads skills status`.

## New discovery

1. Locate the requested `company_search_spec.json`.
2. Run `leads companies validate-spec --spec <path>`.
3. Report material open modes shown by validation: national geography, no size filter, or no custom exclusions.
4. State the novelty policy before running: `unused_memory` searches unused memory first,
   `only_new` bypasses memory candidates and suppresses known domains, and `full_memory` permits
   reuse of previously selected companies. If omitted, the policy is `unused_memory`.
5. For multi-vertical specs, report the balance mode and treat each vertical as an independent memory and external-search lane.
6. Report the external search budget before running. If omitted, use the normalized defaults:
   `external_search.exa_searches = 8` and `external_search.results_per_search = 5`.
7. Run `leads companies discover --spec <path>`. Add `--verbose` only when detailed queries and candidate decisions help diagnose the run. Before launching live discovery, set the tool-call timeout to the largest value the agent runtime allows. If a numeric timeout is required, use at least 10 minutes for small tests, 30 minutes up to about 50 target companies, 60 minutes for about 50-150 target companies, and 120 minutes for larger or broad runs. Never use the default timeout for live discovery.
8. Let the command finish. Do not launch a duplicate while the original process is active.
9. Read the final counts and Markdown summary path.
10. Summarize memory reuse, known-domain suppression for `only_new`, external-search volume,
   selected/reserve/rejected counts, per-vertical outcomes, and any shortfall.
11. Present the results with:
   - one compact count line for all buckets;
   - one table for `selected`;
   - one table for `reserve`.
   Do not show `rejected` rows by default unless the user asks, or unless there are no useful
   results and the failure reasons are the main thing that matters.
12. Keep the default tables compact and systematic. Use these columns when they are available:
   `Company | Domain | Vertical | State | Size | Fit | Source | Notes`
13. Show at most about 15 rows per table by default. If there are more, say that additional rows
   are available in the exported artifacts.

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
