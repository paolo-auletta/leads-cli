# Publishing Implementation Contract

This is the phase 0 contract for turning the current CLI into a publishable `leads` product.
It captures the decisions that implementation phases should treat as fixed unless we explicitly
revise them.

## Product Contract

- User-facing product name: `leads`
- Python distribution name: `leads`
- CLI command: `leads`
- Internal Python package: `company_discovery`
- Default workspace model: one user-chosen workspace root
- Default workspace paths:
  - macOS: `~/Library/Application Support/Leads`
  - Linux: `~/.local/share/leads`
  - Windows: `%APPDATA%\Leads`
- V1 agent targets: Codex, Claude Code, and OpenCode
- V1 update stance: `leads update` guides users into a preflight-first agent workflow
- V1 DB stance: keep current schema creation behavior, add schema/version reporting now, and
  defer destructive or structural migration behavior to the migration phase

## Acceptance Criteria

Phase 1 is complete when:

- Runtime data no longer defaults to a repo-local `.company-discovery/` directory.
- The CLI creates one workspace root with standard `config`, `data`, `runs`, `specs`, `logs`,
  `backups`, and `skills` children.
- Configuration resolves from CLI/env/local config/defaults in the documented order where the
  command supports local overrides.
- `leads version`, `leads doctor`, and `leads config ...` exist and work without external APIs.

Phase 2 is complete when:

- `leads init` creates or repairs a local workspace, config, database, and selected skill installs.
- The bundled skill set is versioned and installable from the package.
- `leads skills list-targets`, `leads skills install`, `leads skills status`, and
  `leads skills reinstall` exist.
- Skill installation is idempotent and records local install metadata.

Phase 3 is complete when:

- A release manifest ships with the package.
- `leads update` explains the safe agent-led update flow without mutating local state.
- `leads update --check` reports CLI, skill bundle, and DB schema status.
- `leads update --check --json` returns machine-readable output.
- A bundled update skill explains the safe update workflow for agents.

## Deferred Decisions

- The long-term DB migration strategy is intentionally deferred to phase 4.
- Public installer script hosting URLs are intentionally deferred to phase 5.
- Renaming the internal import package from `company_discovery` to `leads` is not part of the
  publishing contract unless we choose to do a deeper namespace migration later.
