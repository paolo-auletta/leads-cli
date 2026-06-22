---
name: company-enrichment-operator
description: Enrich company profiles from a completed Company Discovery run. Use when a user asks to enrich selected or reserve companies, continue from discovery to enrichment, retrieve company phone/address/independence, inspect enrichment evidence, refresh stale enrichment facts, or export ready/review/blocked company results. This skill operates on companies only, never contacts.
---

# Operate Company Enrichment

Consume a completed discovery run. Do not ask the user to restate its ICP or reconstruct input from
`selected.csv`; the database record is authoritative.

## Standard workflow

1. Identify the discovery run ID. Default to its `selected` bucket.
2. Run `leads companies show-run <discovery-run-id>` when its status or result count is unclear.
3. Explain that name, domain, vertical, geography, employee estimate, and ownership type are retained
   from discovery. Enrichment targets LinkedIn company profile, phone, complete address, and
   independence.
4. Run `leads companies enrich <discovery-run-id>`.
5. Read the final counts and artifact path. Report inherited facts, memory reuse, website retrieval,
   fallback searches, and ready/review/blocked totals.
   The returned enrichment run ID is sequential and human-readable, like `enrichment-run-1`.
6. Treat `enriched.csv` as the clean deliverable, `review.csv` as unresolved work, `blocked.csv` as
   conflicts, and `run.json` as the provenance and decision trace.

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

- Show a run with `leads companies show-enrichment <enrichment-run-id>`.
- Inspect provenance and trace with
  `leads companies inspect-enrichment <enrichment-run-id> --domain <domain>`.
- Regenerate artifacts with `leads companies export-enrichment <enrichment-run-id>`.

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
