---
name: contact-discovery-operator
description: Validate, execute, inspect, export, and explain live contact discovery from an existing contact_search_spec.json. Use when a user asks an agent to find current role-matched people at companies from a completed enrichment run or review a prior contact discovery run. Use the separate contact-enrichment-operator skill for Apollo email or phone enrichment.
---

# Operate Contact Discovery

Find current people at already-enriched companies without changing the saved company scope.
For general questions about what Leads does, how the CLI works, or which workflow the user should
run, read `leads-onboarding-guide` first and use this skill only for contact discovery execution.

## Workspace And CLI

Use `leads doctor` or `leads version` to confirm the workspace root. The root contains
`backups/`, `config/`, `data/`, `logs/`, `runs/`, `skills/`, and `specs/`.

- Contact specs normally live in `specs/contacts/`; validate the exact spec path before running.
- Contact discovery artifacts live at
  `runs/<company-discover-id>/enrich/<company-enrich-id>/contacts/<contact-discover-id>/`
  with `accepted.csv`, `review.csv`, `rejected.csv`, `summary.md`, and `run.json`.
- The root workbook `runs/<company-discover-id>/leads.xlsx` is updated after contact discovery so
  its `Contacts` sheet contains accepted and review contacts with blank email and phone columns
  until contact enrichment runs.
- The source company enrichment run lives under
  `runs/<company-discover-id>/enrich/<company-enrich-id>/`.
- Config is in `config/config.toml`; secrets are in `config/secrets.toml`; never expose secret
  values.
- Contact discovery uses the configured LLM provider to evaluate current-company and role evidence.
  If discovery fails with a provider/model/key error, use `leads config llm` to update the LLM
  provider, model, base URL, and API key instead of editing config files by hand.
- The memory database is `data/company_memory.db`; use `leads contacts show-run` and inspect
  commands before direct DB inspection.
- Backups are under `backups/`; CLI diagnostics are in `logs/leads.log`; installed skill metadata
  is under `skills/`.
- Useful setup/maintenance commands: `leads init`, `leads version`, `leads doctor`,
  `leads config show`, `leads config llm`, `leads update --check`, `leads migrate --check`,
  and `leads skills status`.

## New Discovery

1. Locate the requested `contact_search_spec.json`.
2. Run `leads contacts validate-spec --spec <path>`.
3. Confirm the source company enrichment run, bucket, optional domain subset, roles, and caps.
4. Run `leads contacts discover --spec <path>`. Before launching live contact discovery, set the tool-call timeout to the largest value the agent runtime allows. If a numeric timeout is required, use at least 10 minutes for small tests, 30 minutes up to about 50 target contacts/companies, 60 minutes for about 50-150, and 120 minutes for larger or broad runs. Never use the default timeout for live discovery.
5. Let the command finish; do not launch a duplicate while it is active.
6. Report the contact run ID, companies loaded, memory reuse, live-web queries, and
   accepted/review/rejected counts.
7. Read the saved summary or `run.json` when explaining why people were accepted or held for
   review. Terminal progress is not the authoritative record.
8. Present the results with:
   - one compact count line for all verdicts;
   - one table for `accepted`;
   - one table for `review`.
   Do not show `rejected` rows by default unless the user asks, or unless there are no useful
   results and the rejection reasons are the important output.
9. Keep the default tables compact and systematic. Use these columns when they are available:
   `Company | Contact | Title | Role Key | LinkedIn | Status | Source | Notes`
10. Show at most about 15 rows per table by default. If there are more, say that additional rows
   are available in the exported artifacts.

The command checks fresh contact memory independently for every company and role. It searches Exa
only for remaining per-role gaps, then verifies identity, current-company evidence, and title fit.

## Follow-up Operations

- Show a run with `leads contacts show-run <contact-run-id>`.
- Inspect one person with `leads contacts inspect <contact-run-id> --person "Jane Smith"`.
- Regenerate artifacts with `leads contacts export <contact-run-id>`.

## Interpret Results

- `accepted.csv`: clear identity, explicit current-company tie, and explicit requested-role match.
- `review.csv`: plausible evidence that is not strong enough for automatic acceptance, including
  valid matches beyond a per-company role cap.
- `rejected.csv`: wrong company, former employee, wrong role, or ambiguous identity.
- `run.json`: complete role decisions, evidence, source URLs, query results, and memory/live source.

The CSV schema intentionally includes blank `email` and `phone` columns so later enrichment can
fill the same client-facing shape. Never describe those blank fields as failed enrichment.

## Guardrails

- Do not edit the spec during execution.
- Do not search arbitrary companies outside the source enrichment run.
- Do not describe a review contact as confirmed.
- Do not infer current employment from Apollo or old databases.
- Do not silently continue into contact enrichment; invoke the separate operator workflow when the
  user asks for email or phone data.
- Never expose API keys or raw environment values.
