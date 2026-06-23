# Publishing, Onboarding, and Update Plan

## Final design decisions

These are the decisions we already made and should treat as fixed unless we explicitly revisit them:

- Distribution should be built on `pipx`.
- The product should use one local workspace root.
- The user should choose that one workspace root during onboarding.
- The user should not be allowed to split runs, specs, DB, logs, or backups across multiple folders.
- Onboarding should include selectable skill installation targets for the agent platforms the user
  actually uses.
- Updates should be agent-friendly and explain impact clearly before destructive or structural
  changes happen.

This note rewrites the plan around those decisions.

## Product shape

The product is:

- one Python CLI package
- installed through `pipx`
- wrapped by convenience installers per operating system
- backed by one user-chosen local workspace directory
- shipped with a bundled set of installable agent skills

So the install story is not “Python or curl”. It is:

- `pipx` is the real installation mechanism
- `curl` or PowerShell are convenience bootstraps
- the CLI itself owns onboarding, skill installation, and update guidance

## Publishing plan

### Core install mechanism

Publish the package so users end up with:

```bash
pipx install company-discovery
```

This should be the canonical install path under the hood on every platform.

Reasons:

- multiplatform without inventing separate packaging logic per OS
- isolated dependencies
- easy upgrades
- less fragile than asking users to manage virtualenvs manually

### User-facing install entry points

We should expose three user-facing install paths:

#### macOS and Linux

```bash
curl -fsSL https://.../install.sh | bash
```

That script should:

- detect whether `pipx` is installed
- install `pipx` if missing
- ensure `pipx` is on PATH when possible
- run `pipx install company-discovery` or `pipx upgrade company-discovery`
- finish by launching `leads init`

#### Windows

```powershell
irm https://.../install.ps1 | iex
```

That script should do the Windows equivalent:

- detect `pipx`
- install it if missing
- install or upgrade the package
- launch `leads init`

#### Explicit fallback

For users who do not want bootstrap scripts:

```bash
pipx install company-discovery
leads init
```

This should always remain documented.

## One user-chosen workspace root

We decided to let the user choose one root folder during onboarding, but only one.

That means the product should:

- ask for one workspace root
- place everything inside it
- not allow separate folder choices for DB, runs, specs, logs, or backups

Recommended behavior:

- suggest an OS-appropriate default path
- let the user accept it or replace it
- then derive every internal path from that root

Suggested defaults:

- macOS: `~/Library/Application Support/CompanyDiscovery`
- Linux: `~/.local/share/company-discovery`
- Windows: `%APPDATA%\CompanyDiscovery`

Use `platformdirs` to resolve this cleanly.

Inside that workspace:

```text
CompanyDiscovery/
  config/
    config.toml
    secrets.toml
    runtime.json
  data/
    company_memory.db
  runs/
  specs/
    companies/
    contacts/
  backups/
  logs/
  skills/
    bundle/
    installs.json
```

Rules:

- onboarding asks for one workspace root
- onboarding does not ask separately for DB, runs, specs, logs, or backups
- all internal paths are derived from the chosen root
- advanced users can inspect files, but the product does not ask them to design the filesystem

This is much better for support, docs, and upgrade safety.

## Onboarding flow

The onboarding entrypoint should be:

```bash
leads init
```

This should be an interactive wizard.

### What `leads init` should do

1. Ask the user to choose one workspace root, with a strong default suggestion.
2. Create it if needed and explain what will be stored there.
3. Ask which LLM provider to use.
4. Ask for the LLM API key.
5. Ask for the default model.
6. Optionally configure Exa.
7. Optionally configure Apollo.
8. Detect supported agent platforms on the machine.
9. Show a selectable list of detected and supported platforms.
10. Install the bundled skills into the selected platforms.
11. Initialize the local DB if missing.
12. Run a health check.
13. Print a handoff message for the selected agents plus a suggested first test prompt.

### What onboarding should not ask

- not where to save runs
- not where to save specs
- not where to save the DB
- not where to save logs
- not where to save backups

Those are all derived from the one workspace root the user chose.

## Post-onboarding handoff

Once onboarding is complete, the CLI should not stop with a generic success message.

It should print:

- where the workspace root was created
- which agent targets received the skills
- a short suggestion to use one of those agents to start finding leads
- one copy-paste test prompt

Example:

```text
Setup complete.

Workspace:
/Users/name/CompanyDiscovery

Installed skills:
- Codex
- Claude Code
- OpenCode

Now use one of those agents to find the best leads with this system.

Suggested test prompt:
"Use the company search spec writer and company discovery operator to create a small test spec for
10 US companies in a niche I choose, run it, and summarize the selected leads."
```

The exact wording can improve later, but the product should clearly bridge setup into first value.

## Configuration model

Configuration should be local-first, not env-first.

Priority order:

1. CLI flags
2. process environment
3. local config in the workspace
4. built-in defaults

Recommended file split:

- `config/config.toml`: non-secret settings
- `config/secrets.toml`: API keys
- `config/runtime.json`: installed versions, migrations, install metadata

Example `config.toml`:

```toml
[llm]
provider = "openai"
base_url = "https://api.openai.com/v1"
model = "gpt-5-mini"
response_format = "auto"

[providers.exa]
enabled = true

[providers.apollo]
enabled = false
webhook_url = ""
```

Example `secrets.toml`:

```toml
[llm]
api_key = "..."

[providers.exa]
api_key = "..."

[providers.apollo]
api_key = "..."
```

Recommended commands:

```bash
leads config show
leads config set llm.provider openai
leads config set llm.model gpt-5-mini
leads config set-secret llm.api_key
leads doctor
leads version
```

## Agent skill installation

This should be a first-class product surface, not an afterthought.

The onboarding UX should look and feel like the multi-select agent installer flow from tools like
`skills.sh`: show supported targets, let the user select where to install, and then install the
same bundled skills into those destinations.

### Recommended onboarding interaction

During `leads init`, after provider setup:

- detect supported agents/platforms already installed or available
- show a selectable list
- allow the user to choose one, many, or all
- install only to the selected targets

This is better than:

- forcing all platforms
- requiring manual copying
- burying skill install in docs

### Recommended commands

```bash
leads skills list-targets
leads skills install
leads skills install --target codex
leads skills install --target codex --target claude-code --target opencode
leads skills status
leads skills reinstall
```

### Installer behavior

The CLI should:

- know which skill bundle ships with the installed CLI version
- detect platform-specific install roots
- copy or sync the bundle into the selected targets
- record install metadata locally
- make repeated installs idempotent

Suggested install metadata:

```json
{
  "skill_bundle_version": "2026.06.1",
  "installs": [
    {
      "target": "codex",
      "status": "ok",
      "installed_at": "2026-06-22T21:15:00Z"
    },
    {
      "target": "opencode",
      "status": "ok",
      "installed_at": "2026-06-22T21:15:05Z"
    }
  ]
}
```

## Update philosophy

We should not design updates as one opaque command that mutates everything silently.

Instead, updates should be:

- explicit
- inspectable
- reversible when possible
- easy for a human or an agent to reason about

This matters because a CLI update may imply:

- code changes
- new skills
- DB migrations
- changed run/artifact expectations

Those are not all the same thing.

## Agent-guided update model

This is the preferred direction.

Instead of telling users “run this random update command and hope”, we should support a workflow
where the user can ask their agent to update the system, and the agent uses CLI feedback to explain
the consequences before proceeding.

### Desired flow

1. User asks their agent to update the tool.
2. The agent runs `leads update --check`.
3. The CLI returns structured, readable feedback.
4. The agent explains:
   - whether the CLI package should be upgraded
   - whether skills should be updated
   - whether a DB migration is needed
   - whether backups will be created
   - whether there is risk or incompatibility
5. The user chooses whether to continue.
6. The agent runs the next command.

This means the CLI must provide excellent preflight output.

### Recommended commands

```bash
leads update
leads update --check
leads update --apply
leads migrate --check
leads migrate --apply
leads skills status
leads skills install
```

### Meaning of `leads update`

If the user runs plain:

```bash
leads update
```

the CLI should not immediately mutate anything.

Instead, it should print a message that strongly suggests using one of the installed agents for the
update flow, because the agent can inspect the preflight output and explain the consequences before
proceeding.

That message should include:

- a short explanation
- the recommended next step
- a copy-paste prompt for the user's agent

Example behavior:

```text
We suggest updating this tool through one of your installed agents.

Why:
- the update may include CLI changes
- skills may need to be updated
- the database may need migration
- your agent can inspect the update plan and explain what will happen before applying changes

Suggested prompt:
"Please update my leads tool safely. First run `leads update --check`, explain whether the CLI,
skills, or database need changes, tell me what backups or migrations will happen, and ask for
confirmation before applying anything structural."
```

This keeps `leads update` user-friendly without making it a dangerous all-in-one command.

### Recommended `update --check` output

It should clearly report:

- installed CLI version
- latest available CLI version
- installed skill bundle version
- target skill bundle version
- current DB schema version
- target DB schema version
- whether migration is required
- whether backup will be created
- whether user confirmation is required
- a short risk summary

Ideally this should have:

- a human-readable table
- a machine-readable mode such as `--json`

That makes it useful both in terminal and through agents.

`leads update --check`, `leads update --apply`, and the migration subcommands are primarily
agent-facing operational commands, even though a power user can still run them directly.

## Update skill

We should ship a small dedicated skill that explains how updates work and guides an agent through
the safe flow.

That skill should instruct the agent to:

- run the preflight/update-check command first
- never assume a migration is harmless
- report required skill updates separately from DB changes
- explain consequences clearly to the user
- ask before applying structural changes

This is a good fit for agent platforms because the agent becomes the safe interface around the CLI.

## What `leads update` should and should not do

### It should

- guide the user toward the agent-based update flow
- tell the user or agent what needs to happen
- provide the copy-paste prompt for the agent
- avoid doing structural work on its own

### It should not

- immediately start applying updates
- silently destroy the DB
- silently rewrite runs
- silently reinstall skills everywhere
- hide big changes behind one generic success message

## Open decision: DB migrations versus reset/archive

This is still not fully settled.

We know we need a safer model than the current “delete DB and archive runs” approach, but we have
not yet chosen the exact long-term strategy for major incompatible changes.

Two realistic directions:

### Option A: migrate-first

- use real schema migrations
- back up first
- upgrade in place when possible
- reserve resets for exceptional cases

### Option B: archive-and-rebuild for major versions

- keep migrations for minor/additive changes
- for big incompatible releases, archive old DB and runs clearly
- initialize a fresh workspace state
- keep old artifacts inspectable but separated

Current leaning:

- migrate-first for normal evolution
- archive-and-rebuild only for truly incompatible major jumps

But this still needs a final policy decision.

## Open decision: how much should `update --apply` do by itself

We also still need to settle whether `leads update --apply` should:

- only handle the package + skill sync
- or also perform DB migrations automatically when the user confirms

Current leaning:

- `update --check` is always safe
- `update --apply` can do safe package/skill work
- structural DB changes should still require a very explicit confirmation step

## Release artifact plan

Each release should ship:

- the Python package
- the macOS/Linux installer script
- the Windows installer script
- bundled skills
- release notes
- upgrade notes
- a machine-readable release manifest

Suggested manifest fields:

```json
{
  "cli_version": "0.3.0",
  "skill_bundle_version": "2026.06.1",
  "schema_version": 5,
  "requires_migration": true,
  "breaking": false
}
```

That gives the CLI something concrete to compare against in `update --check`.

## Implementation plan

### Phase 1: fixed local runtime

- add `platformdirs`
- define the fixed workspace root per OS
- stop depending on repo-local `.company-discovery/`
- add local config/secrets/runtime files
- add `leads init`, `leads doctor`, and `leads version`

### Phase 2: skill installer

- formalize the bundled skill set
- add target detection
- add selectable installation flow
- add `leads skills ...` commands
- record installs locally

### Phase 3: update preflight

- add release manifest support
- add `leads update --check`
- add machine-readable output
- add the update skill for agents

### Phase 4: DB change policy

- choose and implement the migration model
- add backups
- add `migrate --check` and `migrate --apply`
- document major-version behavior

### Phase 5: public install polish

- publish the package
- publish `install.sh`
- publish `install.ps1`
- update the README to lead with the installer and `leads init`

## Publish-ready user experience

The target experience should be:

### macOS/Linux

```bash
curl -fsSL https://.../install.sh | bash
leads init
```

### Windows

```powershell
irm https://.../install.ps1 | iex
leads init
```

### During onboarding

- user configures provider + keys
- user selects agent platforms from a list
- skills get installed into the selected targets
- workspace is initialized automatically

### Later update flow

- user asks their agent to update
- agent runs `leads update --check`
- CLI explains impact
- agent explains it to the user
- user decides whether to proceed

That is the right mental model for this product.

## Bottom line

The final design is:

- `pipx` underneath
- curl/PowerShell as OS-specific bootstraps
- one fixed local workspace
- selectable skill installation targets during onboarding
- update flows designed to cooperate well with agents
- structural changes surfaced clearly before anything risky happens

That is simpler, more supportable, and more consistent than a highly customizable installer with
hidden update behavior.
