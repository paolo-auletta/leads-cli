---
name: company-enrichment-operator
description: Enrich company profiles from a completed Company Discovery run. Use when a user asks to enrich selected or reserve companies, continue from discovery to enrichment, retrieve company phone/address/independence, inspect enrichment evidence, refresh stale enrichment facts, or export ready/review/blocked company results. This skill operates on companies only, never contacts.
---

# Operate Company Enrichment

Consume a completed discovery run. Do not ask the user to restate its ICP or reconstruct input from
`selected.csv`; the database record is authoritative.
For general questions about what Leads does, how the CLI works, or which workflow the user should
run, read `leads-onboarding-guide` first and use this skill only for company enrichment execution.

## Workspace And CLI

Use `leads doctor` or `leads version` to confirm the workspace root. The root contains
`backups/`, `config/`, `data/`, `logs/`, `runs/`, `skills/`, and `specs/`.

- Company discovery runs live at `runs/<company-discover-id>/`.
- Company enrichment artifacts live at
  `runs/<company-discover-id>/enrich/<company-enrich-id>/` with `enriched.csv`, `review.csv`,
  `blocked.csv`, `summary.md`, and `run.json`.
- The root workbook `runs/<company-discover-id>/leads.xlsx` is updated after company
  enrichment so the `Companies` sheet includes enriched fields, outcomes, conflicts, and review
  flags while preserving non-enriched selected/reserve rows already in the workbook.
- The database is `data/company_memory.db`; use `leads companies show-run`,
  `show-enrichment`, and inspect commands before direct DB inspection.
- Config is in `config/config.toml`; secrets are in `config/secrets.toml`; never expose secret
  values.
- Backups are under `backups/`; CLI diagnostics are in `logs/leads.log`; installed skill metadata
  is under `skills/`; specs live under `specs/companies/` and `specs/contacts/`.
- Useful setup/maintenance commands: `leads init`, `leads version`, `leads doctor`,
  `leads update --check`, `leads migrate --check`, and `leads skills status`.

## Standard workflow

1. Identify the discovery run ID. Default to its `selected` bucket.
2. Run `leads companies show-run <discovery-run-id>` when its status or result count is unclear.
3. Explain that name, domain, vertical, geography, employee estimate, and ownership type are retained
   from discovery. Enrichment targets LinkedIn company profile, phone, complete address, and
   independence.
4. Run `leads companies enrich <discovery-run-id>`.
5. Before launching live enrichment, set the tool-call timeout to the largest value the agent runtime allows. If a numeric timeout is required, use at least 30 minutes for small enrichment batches, 60 minutes for about 50-150 companies, and 120 minutes for larger batches. If the runtime maximum is too low for the requested batch, suggest splitting the run with limits or smaller scopes.
6. Read the final counts and artifact path. Report inherited facts, memory reuse, website retrieval,
   fallback searches, and ready/review/blocked totals.
   The returned enrichment run ID is random and prefixed, like `company-enrich-a1b2c3d4e5f6`.
7. Treat `enriched.csv` as the clean deliverable, `review.csv` as unresolved work, `blocked.csv` as
   conflicts, and `run.json` as the provenance and decision trace.
8. Present the results with:
   - one compact count line for all outcomes;
   - one table for `ready`;
   - one table for `review`.
   Do not show `blocked` rows by default unless the user asks, or unless there are no useful
   results and the blocking reasons are what the user needs next.
8. Keep the default tables compact and systematic. Use these columns when they are available:
   `Company | Domain | Vertical | Phone | City | State | LinkedIn | Independence | Outcome | Notes`
9. Show at most about 15 rows per table by default. If there are more, say that additional rows
   are available in the exported artifacts.

For a new search followed by enrichment, always use two separate commands:

```bash
leads companies discover --spec <spec-path>
leads companies enrich <discovery-run-id>
```

Wait for discovery to finish and use the exact run ID it returns. Never represent enrichment as a
discovery option.

## Options

- Use `--bucket reserve` only when the user asks to enrich reserve companies.
- Use `--limit N` for an explicitly bounded run.
- Use `--refresh contact` to refetch LinkedIn, phone, and location.
- Use `--refresh independence` to rerun only the parent/franchise check.
- Use `--refresh all` to ignore all fresh enrichment memory.
- Use `--allow-unknown-independence` only when the user accepts complete contact profiles whose
  independence could not be proven. Without it, those companies go to review.

## Follow-up operations

- Show a run with `leads companies show-enrichment <company-enrich-id>`.
- Inspect provenance and trace with
  `leads companies inspect-enrichment <company-enrich-id> --domain <domain>`.
- Regenerate artifacts with `leads companies export-enrichment <company-enrich-id>`.

## Guardrails

- Never treat `private`, `privately held`, LLC, partnership, or corporation as proof of independence.
- Explicit franchise, parent, subsidiary, division, or acquisition evidence blocks the company.
- If the discovery spec lists `family_owned` under `exclude.structured.ownership_signals`, explicit
  family-owned evidence blocks the company as a fit conflict. Without that requested exclusion,
  family-owned remains valid positive evidence of independence.
- Absence of franchise language is not proof; unresolved independence remains `unknown`.
- Never merge address pieces from separate offices. The selected address must be one complete block
  and, for state-scoped discovery, must be in the inherited state.
- Save only LinkedIn company profiles under `/company/`. Never save personal profiles, jobs, posts,
  or search pages. Prefer links found directly on the official company website.
- Do not silently replace discovery facts. Report identity, geography, and fit conflicts.
- Do not refresh employee data during the default pass; discovery already supplied it.
- Never expose API keys or raw environment values.
