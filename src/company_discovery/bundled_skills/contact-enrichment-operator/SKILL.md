---
name: contact-enrichment-operator
description: Enrich accepted live-web contact discoveries with Apollo email and phone data, inspect provider mismatches, and export outreach-ready results. Use when a user asks to find contact details, emails, or phone numbers for people in a completed contact discovery run, rerun Apollo enrichment, or review a prior contact enrichment run.
---

# Operate Contact Enrichment

Use Apollo only after contact discovery has established the person's identity, current company,
and requested-role fit.

## Workspace And CLI

Use `leads doctor` or `leads version` to confirm the workspace root. The root contains
`backups/`, `config/`, `data/`, `logs/`, `runs/`, `skills/`, and `specs/`.

- Contact discovery artifacts live under
  `runs/<company-discover-id>/enrich/<company-enrich-id>/contacts/<contact-discover-id>/`.
- Contact enrichment artifacts live under
  `runs/<company-discover-id>/enrich/<company-enrich-id>/contacts/<contact-discover-id>/enrich/<contact-enrich-id>/`
  with `ready.csv`, `review.csv`, `blocked.csv`, `summary.md`, and `run.json`.
- Config is in `config/config.toml`; secrets are in `config/secrets.toml`; never expose API keys or
  webhook values.
- The memory database is `data/company_memory.db`; use `leads contacts show-run`,
  `show-enrichment`, and inspect commands before direct DB inspection.
- Backups are under `backups/`; CLI diagnostics are in `logs/leads.log`; installed skill metadata
  is under `skills/`; specs live under `specs/companies/` and `specs/contacts/`.
- Useful setup/maintenance commands: `leads init`, `leads version`, `leads doctor`,
  `leads update --check`, `leads migrate --check`, and `leads skills status`.

## Configure Apollo

Require `APOLLO_API_KEY`.

For the default email-and-phone flow, also require a public HTTPS `APOLLO_WEBHOOK_URL`; Apollo's
phone and waterfall enrichment are asynchronous. Never print either environment value.

If no webhook endpoint is available, run email-only enrichment with `--no-phone`.

## Run Enrichment

1. Identify the completed `contact-discover-<id>` requested by the user.
2. Run `leads contacts show-run <contact-run-id>` to confirm scope and accepted count.
3. Run `leads contacts enrich <contact-run-id>` for email and phone.
4. Use `--no-phone` only when the user wants email-only enrichment or no webhook is configured.
5. Use `--refresh` only when the user explicitly wants to ignore fresh 14-day Apollo memory.
6. Report the contact enrichment run ID and ready/review/blocked counts.
7. Read `summary.md` or `run.json` before explaining mismatches.
8. Present the results with:
   - one compact count line for all outcomes;
   - one table for `ready`;
   - one table for `review`.
   Do not show `blocked` rows by default unless the user asks, or unless there are no useful
   results and the blocking reasons are what the user needs next.
9. Keep the default tables compact and systematic. Use these columns when they are available:
   `Company | Contact | Title | Email | Phone | Status | Apollo Match | Notes`
10. Show at most about 15 rows per table by default. If there are more, say that additional rows
   are available in the exported artifacts.

The command enriches accepted contacts only. It batches up to 10 people per Apollo request, polls
asynchronous request IDs, and saves `contact-enrich-<id>` below the source contact run.

## Follow-Up Operations

- Show a run: `leads contacts show-enrichment <contact-enrich-id>`
- Inspect a person: `leads contacts inspect-enrichment <run-id> --person "Jane Smith"`
- Regenerate artifacts: `leads contacts export-enrichment <run-id>`

## Interpret Results

- `ready.csv`: identity matches and a work channel is supported by the target company domain.
- `review.csv`: identity is credible, but Apollo company data, email domain, or channel context is
  stale or ambiguous.
- `blocked.csv`: no credible Apollo identity match or no usable email/phone was returned.
- `run.json`: discovery snapshot, Apollo metadata, raw provider record, deterministic checks,
  flags, and outcome.

Apollo never overrides the live-web company, title, LinkedIn URL, or role. A stale Apollo employer
is a review signal, not proof that discovery was wrong.

## Guardrails

- Do not enrich review or rejected discovery contacts automatically.
- Do not describe review rows as outreach-ready.
- Do not use personal email addresses without explicit human review.
- Do not expose API keys, webhook secrets, or raw environment values.
- Do not retry failed paid requests blindly; inspect the stored run and provider error first.
