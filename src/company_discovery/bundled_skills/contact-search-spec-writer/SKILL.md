---
name: contact-search-spec-writer
description: Convert natural-language requests for people at previously enriched companies into a validated contact_search_spec.json for the Leads CLI. Use when a user asks to find managers, owners, estimators, project managers, or other current employees across all or selected companies from a company enrichment run. Do not run discovery or add Apollo enrichment settings.
---

# Write Contact Search Specs

Create one strict JSON input for `leads contacts discover`.

## Workspace And CLI

Use `leads doctor` or `leads version` to confirm the workspace root. The root contains
`backups/`, `config/`, `data/`, `logs/`, `runs/`, `skills/`, and `specs/`.

- Write contact specs to `specs/contacts/`, for example
  `specs/contacts/contact_search_spec.json`.
- Company specs belong in `specs/companies/`; do not write company ICP specs here.
- Contact specs reference completed company enrichment runs stored under
  `runs/<company-discover-id>/enrich/<company-enrich-id>/`.
- Config is in `config/config.toml`; secrets are in `config/secrets.toml`; never expose secret
  values.
- The memory database is `data/company_memory.db`; use CLI commands rather than editing it.
- Backups are under `backups/`; CLI diagnostics are in `logs/leads.log`; installed skill metadata
  is under `skills/`.
- Useful setup/maintenance commands: `leads init`, `leads version`, `leads doctor`,
  `leads update --check`, `leads migrate --check`, and `leads skills status`.

## Workflow

1. Identify the completed company enrichment run that supplies the companies.
2. Default to its `ready` companies. Use `review` or `all` only when the user explicitly wants
   companies that were not fully ready.
3. Resolve company scope:
   - omit `domains` or use `[]` for every company in the chosen bucket;
   - use root domains for a requested subset;
   - never invent domains that are absent from the enrichment run.
4. Convert every requested role into a stable snake_case key and a focused list of title labels.
5. Default `max_per_company` to `1`. Increase it only when the user requests multiple people per
   company or the role naturally needs broader coverage.
6. Keep `current_only` and `require_role_match` true unless the user explicitly requests looser
   research.
7. Write JSON, then run `leads contacts validate-spec --spec <spec-path>`.
8. Correct validation errors before handing the spec to the discovery operator.

## Contract

```json
{
  "version": 1,
  "company_source": {
    "enrichment_run_id": "company-enrich-a1b2c3d4e5f6",
    "bucket": "ready",
    "domains": []
  },
  "roles": [
    {
      "key": "project_manager",
      "labels": ["project manager", "senior project manager"],
      "max_per_company": 1
    }
  ],
  "company_limit": null,
  "contact_limit": null,
  "current_only": true,
  "require_role_match": true,
  "memory_freshness_days": 30
}
```

## Role Rules

- Keep synonyms semantically close. Do not put `owner`, `estimator`, and `project manager` under
  one broad `manager` role.
- Preserve distinct user requests as distinct role objects.
- Use observed business titles, not department keywords alone.
- If “manager” is genuinely ambiguous and context does not resolve it, ask which management role
  they mean before creating the file.

## Guardrails

- JSON is the canonical format; do not produce YAML.
- Do not include company-discovery ICP fields such as state, vertical, size, or exclusions. The
  company enrichment run already defines company scope.
- Do not add email, phone, Apollo, or contact-enrichment settings.
- Do not silently include company enrichment review rows.
- Never expose API keys or environment values.
