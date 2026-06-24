---
name: leads-update-operator
description: Safely guide updates for the Leads CLI, bundled agent skills, local database schema, and workspace backups.
---

# Operate Leads Updates

Use this skill when a user asks to update, upgrade, repair, or check the installed Leads tool.

## Workspace And CLI

Use `leads doctor` or `leads version` to confirm the workspace root. The root contains
`backups/`, `config/`, `data/`, `logs/`, `runs/`, `skills/`, and `specs/`.

- `config/config.toml` stores non-secret settings; `config/secrets.toml` stores API keys and
  webhook secrets; `config/runtime.json` stores schema, skill, and install metadata.
- `data/company_memory.db` is the SQLite memory DB.
- `runs/` stores discovery, enrichment, contact discovery, and contact enrichment artifacts.
- `specs/companies/` and `specs/contacts/` store agent-created spec files.
- `backups/` stores migration and reset backups.
- `logs/leads.log` stores CLI diagnostics; it is not run evidence and should not be summarized as
  a lead result.
- `skills/` stores bundled skill copies and install metadata. Use `leads skills ...` commands
  instead of manually editing installed skill files.

Core commands to know: `leads init`, `leads version`, `leads doctor`, `leads config show`,
`leads skills status`, `leads skills install`, `leads skills reinstall`, `leads update --check`,
`leads migrate --check`, and `leads migrate --apply`.

## Safe Update Flow

1. Run `leads update --check` first.
2. Prefer `leads update --check --json` when you need exact fields for an explanation.
3. Report the manifest source. `remote` means the check found the latest published release
   manifest; `bundled` means it fell back to the manifest inside the currently installed package.
4. Report CLI, skill bundle, and database schema changes separately.
5. If `cli_update_required` is true, tell the user to upgrade the package outside the running CLI,
   normally with `pipx upgrade leads-cli`, then rerun `leads update --check`.
6. Explain whether a backup or migration is required.
7. If migration is required, run `leads migrate --check` or `leads migrate --check --json` and
   explain the migration action, backup path behavior, and risk summary.
8. Ask the user before applying structural database changes.
9. After the CLI package is current, use `leads update --apply` to apply local migrations and
   reinstall previously installed skill bundles. Use `--yes` only after explicit approval.
10. Use a large tool-window timeout, around 10 minutes, so package upgrades, backups, migrations,
   and skill reinstalls can finish.
11. Do not assume a migration is harmless just because the command exists.

## Interpretation

- `cli_update_required` means the installed package version differs from the release manifest.
- `skills_update_required` means bundled agent skills should be reinstalled or synced.
- `migration_required` means the local schema and release manifest disagree, or the release
  explicitly requires migration.
- `migration_supported_by_installed_cli` false means the user must upgrade `leads-cli` before
  running migration apply; the current binary does not contain the needed migration code.
- `backup_required` means the update plan expects a database backup before structural work.
- `confirmation_required` means the agent should pause and get explicit user approval.
- `leads migrate --check` is read-only and reports the local DB migration action.
- `leads migrate --apply` creates a timestamped backup before supported structural changes and
  refuses unknown migration paths.
- After an external package upgrade, data commands may refuse to run until migration is handled.
  That is intentional; use `leads update --check`, `leads migrate --check`, and
  `leads update --apply`.

## Guardrails

- Do not run destructive database operations from a plain update request.
- Do not hide skill updates inside a generic success message.
- Do not delete runs, specs, logs, backups, or the database unless the user explicitly confirms.
- Never expose API keys or raw secret values from the workspace config.
