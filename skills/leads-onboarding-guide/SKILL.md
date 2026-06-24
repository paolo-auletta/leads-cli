---
name: leads-onboarding-guide
description: Guide a newly installed Leads user through what the tool can do, the main company and contact workflows, useful commands, adjustable parameters, and how to collaborate with an agent. Use when a user says they just installed Leads, asks what to do next, asks what Leads can do, asks for a tour, or appears to have an empty/new workspace.
---

# Guide New Leads Users

Use this skill to orient a user in plain language. Keep the tone practical and reassuring: the
user does not need to memorize commands or schemas because they can ask their agent for help at
any step.

## Workspace And CLI

Use `leads doctor` or `leads version` to confirm the workspace root. The root contains
`backups/`, `config/`, `data/`, `logs/`, `runs/`, `skills/`, and `specs/`.

- `config/config.toml` stores settings; `config/secrets.toml` stores API keys. Never reveal secret
  values.
- `data/company_memory.db` is the local memory database.
- `specs/companies/` and `specs/contacts/` are where agent-created search specs belong.
- `runs/` stores saved discovery and enrichment results.
- `skills/` stores bundled agent skills and install metadata.
- `backups/` stores migration and reset backups.
- `logs/leads.log` stores CLI diagnostics; it is not run evidence and should not be summarized as
  a lead result.
- Useful setup/maintenance commands: `leads init`, `leads version`, `leads doctor`,
  `leads update --check`, `leads migrate --check`, and `leads skills status`.

## Fresh Install Check

When the user seems newly installed or asks what to do next:

1. Run `leads version` and `leads doctor`.
2. Run `leads skills status` if the user is asking about agent capabilities.
3. Treat the workspace as fresh when `runs/` has no discovery/enrichment run folders and
   `specs/companies/` and `specs/contacts/` are empty or contain only examples.
4. If required API keys are missing, explain the impact simply: no LLM key means agents cannot
   generate/evaluate searches; no Exa key means live company/contact discovery cannot search the
   web; no Apollo key means contact email/phone enrichment cannot run.

## Plain-Language Overview

Explain Leads as four connected stages:

- Company discovery finds companies matching an ideal customer profile.
- Company enrichment fills in company details such as phone, address, LinkedIn, and independence
  signals.
- Contact discovery finds current people at the enriched companies who match target roles.
- Contact enrichment uses Apollo to add work emails and, when configured, phone data.

Emphasize that the agent can handle the details: the user can describe the target market in normal
language, ask for changes, ask why a result was selected, or ask to inspect saved evidence.

## Suggested Agent Workflow

Recommend this flow for a new user:

1. Ask the user for a target market in plain language: industry, geography, company size, and
   exclusions.
2. Create a company search spec in `specs/companies/`.
3. Validate it, explain the search budget, then run company discovery.
4. Show selected and reserve companies in compact tables.
5. Enrich selected companies.
6. Review ready/review/blocked company outcomes.
7. Ask which roles to find, then create a contact search spec in `specs/contacts/`.
8. Run contact discovery.
9. If Apollo is configured, enrich accepted contacts; otherwise explain that contact details can
   be added later when the user has an Apollo API key.

Useful first prompt:

```text
I just installed Leads. Help me find 25 companies in a niche I describe, explain the plan before
running it, and show me selected and reserve results in tables.
```

## What Users Can Tweak

For company discovery, explain these knobs in simple terms:

- Target industry or multiple verticals.
- Geography, such as country and states.
- Company size range.
- Exclusions, such as franchises, public companies, directories, irrelevant services, or known
  bad-fit keywords.
- Novelty policy: reuse memory first, find only new domains, or allow full memory reuse.
- Search budget: default to `external_search.exa_searches = 8` and
  `external_search.results_per_search = 5`, but increase for broader markets or decrease for
  quick tests.

For company enrichment, explain:

- Which discovery bucket to enrich, usually `selected`.
- Optional limits for tests.
- Whether to refresh cached company facts.
- Whether unknown independence is acceptable.

For contact discovery, explain:

- Which company enrichment run to use.
- Target roles and title keywords.
- Seniority or department preferences.
- Whether to search only ready companies or include review companies.

For contact enrichment, explain:

- Apollo API key is required.
- Phone enrichment also needs a public HTTPS Apollo webhook URL.
- Email-only mode is available with `--no-phone` when no webhook is configured.

## Main Commands To Mention

Do not overwhelm the user with every command. Mention the important ones and offer to run them:

- `leads init`: set up the workspace, API keys, and agent skills.
- `leads doctor`: check configuration and workspace health.
- `leads version`: show CLI, skill bundle, schema, and workspace.
- `leads companies validate-spec --spec <path>`: check a company spec.
- `leads companies discover --spec <path>`: run company discovery.
- `leads companies enrich <company-discover-id>`: enrich discovered companies.
- `leads contacts validate-spec --spec <path>`: check a contact spec.
- `leads contacts discover --spec <path>`: find contacts at enriched companies.
- `leads contacts enrich <contact-discover-id>`: add Apollo contact details.
- `leads skills status`: check which agent skills are installed.

## Response Style

- Start with a short, friendly explanation of what Leads can do for the user's sales/research
  workflow.
- Give a suggested next action, not a command dump.
- Make it clear that the user can just chat with their agent: ask for a niche, ask to change the
  filters, ask what happened in a run, ask to inspect evidence, or ask what each setting means.
- If the user wants to proceed, offer a small first run before a large one.
- Keep outputs table-oriented when summarizing discovery or enrichment results.
