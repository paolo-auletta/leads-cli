---
name: contact-discovery-operator
description: Validate, execute, inspect, export, and explain live contact discovery from an existing contact_search_spec.json. Use when a user asks an agent to find current role-matched people at companies from a completed enrichment run or review a prior contact discovery run. This skill covers discovery only, not Apollo email or phone enrichment.
---

# Operate Contact Discovery

Find current people at already-enriched companies without changing the saved company scope.

## New Discovery

1. Locate the requested `contact_search_spec.json`.
2. Run `leads contacts validate-spec --spec <path>`.
3. Confirm the source company enrichment run, bucket, optional domain subset, roles, and caps.
4. Run `leads contacts discover --spec <path>`.
5. Let the command finish; do not launch a duplicate while it is active.
6. Report the contact run ID, companies loaded, memory reuse, live-web queries, and
   accepted/review/rejected counts.
7. Read the saved summary or `run.json` when explaining why people were accepted or held for
   review. Terminal progress is not the authoritative record.

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
- Do not run contact enrichment; it is a separate future workflow.
- Never expose API keys or raw environment values.
