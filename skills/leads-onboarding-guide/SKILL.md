---
name: leads-onboarding-guide
description: Central guide for explaining how Leads works. Use when a user says they just installed Leads, asks what to do next, asks what Leads can do, asks how any Leads CLI workflow/command/setting/update works, asks for a tour, or appears to have an empty/new workspace.
---

# Guide New Leads Users

Use this skill as the central hub for explaining Leads in plain language. When a user asks how the
tool works, what a command does, what they can tweak, what a workspace file means, or what to do
after install, read this skill first before reaching for a more specialized operator skill.

Keep the tone practical and reassuring: the user does not need to memorize commands or schemas
because they can ask their agent for help at any step.

## When To Use This Hub

Use this guide before or alongside other Leads skills when:

- The user is new, confused, or asks for a non-technical explanation.
- The user asks what Leads can do, how the CLI works, or which command to run.
- The user asks about specs, runs, database memory, skills, config, updates, or API keys.
- The user asks how to customize company/contact discovery or enrichment.
- The user wants a recommended workflow before running a specialist skill.

After orienting the user, route execution work to the specialist skills: company spec writing,
company discovery, company enrichment, contact spec writing, contact discovery, contact enrichment,
or updates.

## Workspace And CLI

Use `leads doctor` or `leads version` to confirm the workspace root. The root contains
`backups/`, `config/`, `data/`, `logs/`, `runs/`, `skills/`, and `specs/`.

- `config/config.toml` stores settings; `config/secrets.toml` stores API keys. Never reveal secret
  values.
- `data/company_memory.db` is the local memory database.
- `specs/companies/` and `specs/contacts/` are where agent-created search specs belong.
- `runs/` stores saved discovery and enrichment results. Each company discovery run also has a
  consolidated workbook at `runs/<company-discover-id>/leads.xlsx` with `Companies` and `Contacts`
  sheets that update as enrichment/contact steps complete. It keeps selected and reserve companies,
  plus accepted and review contacts.
- `skills/` stores bundled agent skills and install metadata.
- `backups/` stores migration and reset backups.
- `logs/leads.log` stores CLI diagnostics; it is not run evidence and should not be summarized as
  a lead result.
- Useful setup/maintenance commands: `leads init`, `leads version`, `leads doctor`,
  `leads update --check`, `leads update --apply`, `leads migrate --check`,
  `leads migrate --apply`, and `leads skills status`.

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

## How The Agent Should Explain Leads

Explain that Leads is meant to be used conversationally with an agent:

- The user describes the market, roles, or outreach goal in normal language.
- The agent turns that request into a spec file, validates it, and explains the plan.
- The CLI performs repeatable searches, saves evidence, and writes artifacts under `runs/`.
- The agent summarizes the results in tables, helps inspect evidence, and tunes the next run.
- The local database remembers prior companies and runs so future searches can reuse or avoid
  known domains depending on the novelty policy.

Tell the user they can ask questions at any time, such as "why was this company selected?",
"make the search broader", "only include independent companies", "show me the evidence", or
"what does this setting mean?"

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
- `leads update --check`: check the latest release manifest and explain CLI, skill, and database
  changes before doing anything.
- `leads update --apply`: apply workspace-local update steps after the package is current, such as
  supported migrations and skill reinstalls.
- `pipx upgrade leads-cli`: upgrade the Python package itself when `leads update --check` says a
  newer CLI package exists. If the user installed with plain `pip`, use their normal `pip install
  --upgrade leads-cli` flow instead.

## Updates In Plain Language

Explain updates clearly because there are two different layers:

- The Python package layer is updated outside the running CLI, normally with
  `pipx upgrade leads-cli`. A running CLI should not try to replace itself.
- The workspace layer is handled by `leads update --check` and `leads update --apply`.
- `leads update --check` is useful because it reads the release manifest, reports whether the CLI,
  skill bundle, or database schema changed, explains backup/migration requirements, and shows next
  steps.
- `leads update --apply` is useful after the package is current because it performs safe local
  follow-up work: reinstalling updated skills, running supported migrations, and creating backups
  when required.
- Agents should run `leads update --check --json` when they need exact fields, explain the result
  in plain English, then ask before applying anything that changes the workspace.
- If `manifest_source` is `remote`, the check saw the latest public release manifest. If it is
  `bundled`, the CLI fell back to the manifest packaged inside the installed version, so the agent
  should explain the fallback and verify connectivity if needed.

## Response Style

- Start with a short, friendly explanation of what Leads can do for the user's sales/research
  workflow.
- Give a suggested next action, not a command dump.
- Make it clear that the user can just chat with their agent: ask for a niche, ask to change the
  filters, ask what happened in a run, ask to inspect evidence, or ask what each setting means.
- If the user wants to proceed, offer a small first run before a large one.
- Keep outputs table-oriented when summarizing discovery or enrichment results.
