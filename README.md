# Leads

An agent-first, memory-first company and contact research engine. Strict JSON specs drive
deterministic memory retrieval, focused Exa searches, structured LLM evaluation, targeted
official-site enrichment, persistence, and reviewable CSV/Markdown/JSON artifacts.

Design and rebuild notes live in [`NOTES/`](./NOTES/README.md).

## Install

The canonical install path is `pipx`. The package is published as `leads-cli` because `leads`
is already taken on PyPI, but it still installs the `leads` command. The installer scripts are
thin convenience wrappers around `pipx install/reinstall leads-cli`, followed by `leads init`.
They create the Leads pipx environment with Python 3.13 by default, and modern pipx versions will
fetch that Python automatically if it is missing.
On Windows ARM64, the PowerShell installer uses an installed Python 3.13 or installs it with
`winget` when available, because some pipx versions cannot fetch standalone Python builds on ARM64.

### macOS and Linux

```bash
curl -fsSL https://raw.githubusercontent.com/paolo-auletta/leads-cli/main/install.sh | bash
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/paolo-auletta/leads-cli/main/install.ps1 | iex
```

### Direct pipx install

```bash
pipx install --python 3.13 --fetch-python missing leads-cli
leads init
```

Use `LEADS_SKIP_INIT=1` with either installer when you want to install first and run onboarding
later. Set `LEADS_PYTHON_VERSION=3.12` or another supported version only if you need to override
the default installer Python.

## Onboarding

Run:

```bash
leads init
```

The wizard creates one local workspace, stores config and secrets, initializes the SQLite database,
and installs bundled skills into the agent targets you choose, such as Codex, Claude Code, or
OpenCode. After setup, use one of those agents to create a spec, run discovery, and summarize the
selected leads.

Runtime data defaults to the OS-appropriate Leads application data folder. Override it with
`LEADS_HOME=/path/to/data` when needed.

Leads supports OpenAI-compatible providers, Anthropic Claude, and Google Gemini from onboarding.
`LLM_RESPONSE_FORMAT=auto` uses strict JSON Schema with OpenAI, native structured-output APIs with
Anthropic/Gemini, and validated JSON Object mode with DeepSeek or other compatible providers.
Override it only when a provider documents support for a different mode.

## Workspace Layout

`leads init` creates one workspace root with these top-level directories:

```text
backups/
config/
data/
logs/
runs/
skills/
specs/
```

`config/` contains local settings, secrets, and runtime metadata. `data/company_memory.db` is the
SQLite memory database. `specs/companies/` and `specs/contacts/` are where agent-created specs
belong. `runs/` contains discovery and enrichment artifacts. `backups/` stores migration and reset
backups. `skills/` stores bundled skill copies and install metadata. `logs/leads.log` is a CLI
diagnostic log for troubleshooting; it is not lead evidence or a run artifact.

## Commands

```bash
leads init
leads doctor
leads init-db
leads version
leads update --check
leads migrate --check
leads config show
leads skills status
leads companies discover --spec company_search_spec.json
leads companies enrich DISCOVERY_RUN_ID
leads companies show-run RUN_ID
leads companies inspect RUN_ID --domain example.com
leads companies export RUN_ID
leads companies rerun RUN_ID
leads companies show-enrichment ENRICHMENT_RUN_ID
leads companies inspect-enrichment ENRICHMENT_RUN_ID --domain example.com
leads companies export-enrichment ENRICHMENT_RUN_ID
leads contacts validate-spec --spec contact_search_spec.json
leads contacts discover --spec contact_search_spec.json
leads contacts enrich CONTACT_DISCOVERY_RUN_ID
leads contacts show-run CONTACT_DISCOVERY_RUN_ID
leads contacts inspect CONTACT_DISCOVERY_RUN_ID --person "Jane Smith"
leads contacts export CONTACT_DISCOVERY_RUN_ID
leads contacts show-enrichment CONTACT_ENRICHMENT_RUN_ID
leads contacts inspect-enrichment CONTACT_ENRICHMENT_RUN_ID --person "Jane Smith"
leads contacts export-enrichment CONTACT_ENRICHMENT_RUN_ID
```

`leads init-db` creates `company_memory.db` and its schema. If the database already exists, it
asks before resetting it. An accepted reset moves the existing `runs/` directory to a timestamped
archive such as `runs-previousdb-20260622T184500Z/`, then creates a new empty `runs/` directory.

`leads migrate --check` is read-only. `leads migrate --apply` creates a timestamped backup before
supported structural schema changes and refuses unknown migration paths.

Use `--verbose` on `discover` to print generated queries and candidate-level decisions.

## Development Setup

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/leads init
```

For a local smoke test, create or copy a company spec, configure provider keys during onboarding,
then run:

```bash
leads companies discover --spec company_search_spec.json
```

## Multiple verticals

Use `verticals` to request OR semantics: companies may match construction, healthcare, or
engineering; they do not need to match all three. Each vertical gets an independent memory scan,
gap calculation, Exa query plan, and evaluation lane.

Each vertical now uses one simple shape: `key`, `label`, and optional query hints. Use
`search_terms` when the label alone is too broad or niche, and `exclude_terms` when a vertical
needs a few search-time negatives. Old specs that still contain `mode`, `seed_terms`, or
`anti_terms` remain readable and normalize to the new shape.

`balance_mode` controls final selection. `soft` (the default) fills an equal quality-gated floor
per vertical, then reallocates unused slots to good companies from stronger lanes. `strict` keeps
equal caps and may return fewer companies. `none` selects good companies in discovery order.

The legacy single `vertical` object remains accepted for existing specs.

## Memory policy

`novelty_mode` controls whether saved companies can enter a run:

- `unused_memory` (default) searches memory first and only considers companies never selected before.
- `only_new` skips memory candidates and removes externally rediscovered domains already in memory.
- `full_memory` searches all matching memory, including companies selected in previous runs.

Old `prefer_new` and `allow_known` specs remain readable and normalize to `unused_memory` and
`full_memory`, respectively.

## Enrichment

Enrichment is always a separate command run after discovery completes:

```bash
leads companies discover --spec company_search_spec.json
leads companies enrich DISCOVERY_RUN_ID
```

It consumes selected companies directly from the completed discovery run. It retains company
name, root domain, target vertical, geography, employee estimate, ownership type, and discovery
evidence, then finds only the missing LinkedIn company profile, phone, complete in-scope address,
and independence status.

Each enrichment execution gets a random run ID such as `company-enrich-a1b2c3d4e5f6`. That ID is
used both for CLI follow-up commands and the enrich artifact folder under the source discovery run.

Fresh enrichment facts are reused by company/domain before any website request. The bounded website
pass reads the homepage and best contact/location/about pages; unresolved fields can use a narrow
Exa corroboration search. Output is split into `enriched.csv`, `review.csv`, and `blocked.csv`, while
the enrichment `run.json` keeps field provenance, conflicts, and the per-company trace.

LinkedIn enrichment first checks company-profile links exposed by the official website, including
footer icon links. Only `/company/...` URLs are accepted; personal profiles, jobs, and posts are
discarded. If the official site has no profile link, enrichment performs a narrow LinkedIn company
search. The normalized URL and its source page are saved in enrichment memory and exported as
`linkedin_url`.

By default, complete profiles with unknown independence remain in review. Add
`--allow-unknown-independence` only when that uncertainty is acceptable. Generic values such as
`privately_held` never count as proof of independence.

To exclude family businesses during enrichment, add this to the discovery spec:

```json
"exclude": {
  "structured": {"ownership_signals": ["family_owned"]}
}
```

Enrichment still records the company as independent, but sends it to `blocked.csv` with a
`fit_conflict` and `excluded_family_owned` flag. The ownership signal is retained in enrichment
memory, so the same rule applies when a later run reuses fresh facts.

## Contact Discovery

Contact discovery is a separate phase after company enrichment. It starts from a completed
`company-enrich-<id>`, uses only its ready companies by default, and finds current people matching
structured role targets.

```bash
cp examples/contact_search_spec.json contact_search_spec.json
leads contacts validate-spec --spec contact_search_spec.json
leads contacts discover --spec contact_search_spec.json
```

For every company and role, the command reuses accepted contact memory from the last 30 days, then
uses one Exa people-index query plus one official-domain evidence query for each remaining
per-company gap. The LLM evaluates identity, current employment at the exact target company, and
requested-title fit. A model cannot force an acceptance when those explicit checks are not
satisfied.

Artifacts are split into `accepted.csv`, `review.csv`, and `rejected.csv`. All three use the same
client-facing columns:

```text
company_name, company_domain, contact_name, title, linkedin_url,
email, phone, status, notes
```

`email` and `phone` are intentionally blank during discovery. Full queries, raw Exa results,
evidence, role keys, verdict details, and memory/live source decisions are retained in `run.json`.

## Contact Enrichment

Contact enrichment is a separate Apollo-backed command after contact discovery:

```bash
leads contacts enrich contact-discover-a1b2c3d4e5f6
```

Only accepted contacts enter enrichment. Live-web discovery remains authoritative for the person's
identity, current company, title, role, and LinkedIn URL; Apollo can add email and phone channels
but cannot overwrite those facts. Exact identity and company/email-domain checks classify each
person as `ready`, `review`, or `blocked`, with raw Apollo trace and flags retained in `run.json`.

Apollo bulk requests are sent in groups of 10. Phone and waterfall requests are asynchronous, so
the default email-and-phone command requires `APOLLO_WEBHOOK_URL` and polls Apollo's request result
until completion. Use `--no-phone` for an email-only run when a webhook is unavailable. Fresh
Apollo results are reused for 14 days unless `--refresh` is supplied.

Artifacts live below the source contact run in
`contacts/contact-discover-<id>/enrich/contact-enrich-<id>/` and retain the same compact
client columns used by discovery. Output is split into `ready.csv`, `review.csv`, and `blocked.csv`.
