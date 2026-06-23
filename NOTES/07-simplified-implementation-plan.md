# Simplified Implementation Plan

Date: 2026-06-21

## Goal

Build a clean v1 of the company discovery system that is:

- agent-first;
- spec-driven;
- Exa-first;
- LLM-evaluated;
- simple enough to trust and iterate on.

This plan intentionally avoids rebuilding the old overcomplicated discovery architecture.

The goal of v1 is not perfect automation.

The goal of v1 is:

> take a user request for target companies, turn it into a structured search spec, run a focused discovery flow, and return a strong first batch of companies with saved memory for reuse later.

## Product shape for v1

The v1 workflow should be:

```text
User
  ->
Agent
  ->
search spec file
  ->
CLI command
  ->
spec validation
  ->
local memory/backlog filtering
  ->
reuse of in-scope saved companies
  ->
gap detection
  ->
LLM query generation
  ->
Exa search
  ->
candidate normalization + dedupe
  ->
LLM candidate evaluation
  ->
selected / reserve / rejected
  ->
save results to memory
```

## Core v1 principles

### 1. The agent is the main interface

Most users will not write CLI commands by hand.

They will ask an agent for something like:

- "find me 50 construction companies in Texas"
- "look for healthcare clinics in California"
- "find engineering firms in the US, avoid franchises if possible"

So the real interface is:

- user request
- agent interpretation
- machine-readable search spec

The CLI should consume that spec.

### 2. The spec is the contract

The search spec is the source of truth for discovery.

The CLI should not rely on a giant number of flags.

The search spec should be:

- strict;
- validated;
- versioned;
- machine-friendly;
- easy for the agent to generate.

### 3. Exa is the only external discovery provider in v1

Do not build multi-provider orchestration yet.

Start with:

- LLM-generated search queries;
- Exa execution;
- Exa result normalization.

That is enough for a strong first version.

### 4. LLM judgment is the real evaluator

Do not invent a fake scoring system too early.

Use deterministic logic only for obvious garbage:

- malformed domains;
- duplicates;
- known junk/listing domains;
- unusable results.

Everything else should be judged by the LLM against the requested ICP.

### 5. Memory should exist from day one

Even in v1, every discovery run should save:

- the search spec;
- generated queries;
- Exa results;
- normalized candidates;
- evaluation outcomes.

This creates the base for future reuse.

### 6. Memory must be the first retrieval layer

The saved reserve or backlog pool should not be a passive archive.

It should be the first place discovery looks.

That means the spec is not only an input to LLM prompting.

It is also an input to deterministic local filtering.

The intended order is:

1. parse and validate the spec;
2. deterministically filter the saved company pool;
3. inspect why matching companies were previously reserved, rejected, or skipped;
4. reuse what still fits now;
5. only then search Exa for the remaining gap.

This is one of the main reasons the spec must stay structured and strict.

## Scope of v1

## In scope

- company search spec file
- spec validator
- one company discovery CLI flow
- one agent skill for generating specs
- one agent skill for running discovery
- memory-first retrieval from saved company pool
- LLM query generation
- Exa retrieval
- candidate dedupe and normalization
- LLM company fit evaluation
- selected / reserve / rejected output
- result persistence

## Out of scope for v1

- multi-provider retrieval
- deep website crawling
- complex campaign refill logic
- advanced backlog segmentation
- automatic enrichment pipelines
- sync automation redesign
- mathematically weighted confidence engines

## Spec format plan

## Format choice

Use JSON as the canonical format in v1.

Why:

- stricter than YAML;
- easier to validate;
- easier to generate from LLM structured output;
- less whitespace ambiguity;
- easier to version with a JSON Schema.

YAML can be supported later as an optional convenience layer, but the core contract should be JSON.

## Canonical file name

Recommended file name:

`company_search_spec.json`

## Why the spec matters beyond prompting

The spec must be designed so code can use it deterministically against the saved company pool before any new web search happens.

Example:

- if the spec says `states = ["TX"]`
- the system should be able to filter stored candidates by `state = TX`
- then inspect why they were previously reserved, rejected, or not selected

So the spec must work for two jobs:

1. deterministic local retrieval
2. external query generation

If it only works well as LLM prompt material, it is not good enough.

## Proposed v1 spec shape

```json
{
  "version": 1,
  "count": 50,
  "verticals": [
    {"key": "construction", "label": "Construction"},
    {"key": "healthcare", "label": "Healthcare"}
  ],
  "geography": {
    "country": "US",
    "states": ["TX"]
  },
  "company_size": {
    "employee_min": 20,
    "employee_max": 100
  },
  "include": {
    "keywords": [],
    "subtypes": []
  },
  "exclude": {
    "keywords": ["franchise", "franchisee"],
    "ownership_types": ["franchise", "subsidiary"],
    "company_patterns": ["vendor", "association", "directory"]
  },
  "novelty_mode": "unused_memory",
  "balance_mode": "soft"
}
```

## Fields that must be filterable against memory

At minimum, the spec should support deterministic filtering on:

- each `verticals[].key`
- `geography.country`
- `geography.states`
- `company_size.employee_min`
- `company_size.employee_max`
- `exclude.keywords`
- `exclude.ownership_types`
- `novelty_mode`

These fields should map to normalized stored company attributes wherever possible.

## Optional behavior

The following should be allowed:

- no state list
- no size filter
- no exclusions

Those should normalize into explicit modes, for example:

- national geography mode
- no size filter mode
- default hygiene exclusions only

Even when fields are omitted, the normalized spec still needs to produce deterministic local filtering behavior.

Examples:

- no states means national search mode
- no size range means no size filtering
- no exclusions means default hygiene only

## Vertical shape

The spec should support one simple vertical object:

For established verticals, the label is often enough:

Example:

```json
{
  "vertical": {"key": "construction", "label": "Construction"}
}
```

For niche or ambiguous verticals, add optional query hints:

```json
{
  "vertical": {
    "key": "marine-surveying",
    "label": "Marine Surveying",
    "search_terms": ["marine surveying", "vessel inspection", "cargo survey"],
    "exclude_terms": ["software", "directory", "marketplace"]
  }
}
```

This keeps the same flexibility without forcing the agent to decide between artificial
`known` and `exploratory` modes.

## Multi-vertical behavior

Multiple verticals use OR semantics: the result contains separate companies from any requested
vertical, not companies required to operate in every vertical.

Compile each vertical into an independent discovery lane. Every lane gets its own:

- deterministic memory scan;
- remaining-gap calculation;
- LLM-generated Exa query plan;
- candidate evaluation against that one vertical;
- persisted `target_vertical` attribution.

Use `balance_mode = "soft"` by default. First give every vertical an equal quality-gated target,
then return unused capacity to a shared overflow pool. Fill that pool only with remaining
`good_fit` companies; never promote weak candidates to force symmetry.

Support two explicit alternatives:

- `strict`: enforce equal caps and accept a short result when a lane lacks enough good companies;
- `none`: ignore distribution and select good companies in discovery order.

The legacy singular `vertical` input remains valid, but new agent-generated specs should emit
`verticals` consistently.

## CLI plan

The CLI should be simple.

It should be designed to consume spec files and produce artifacts.

It should also feel alive while it is working.

The user should not stare at a dead terminal while the system is:

- checking memory
- generating queries
- calling Exa
- evaluating candidates
- saving results

The CLI should show clear progress and visually distinguish the major phases of discovery.

## Proposed v1 commands

### 1. `companies discover`

Primary entry point.

Example:

```bash
leads companies discover --spec company_search_spec.json
```

Responsibilities:

- load the search spec
- validate the spec
- normalize defaults
- filter saved backlog/company memory first
- determine reusable in-scope companies
- inspect prior reasons for non-selection where relevant
- measure the remaining gap
- generate Exa queries with the LLM
- call Exa
- normalize and dedupe candidates
- evaluate candidates with the LLM
- write results to persistence
- export output artifacts

Outputs:

- run ID
- summary counts
- output file paths

### Progress behavior for `companies discover`

This command should stream visible progress while it runs.

At minimum, the CLI should clearly separate:

1. memory search
2. external search
3. evaluation
4. persistence/export

The memory phase and external-search phase should look visually different so the user immediately understands whether the system is:

- reusing what it already knows
- or spending effort on new discovery

## Proposed CLI progress design

The CLI should use a staged progress view rather than a wall of logs.

Example shape:

```text
[1/5] Spec
  Loaded search spec
  Vertical: Construction
  Geography: TX, US
  Size: 20-100

[2/5] Memory Scan
  Searching saved company pool...
  42 prior companies matched the deterministic filters
  11 reusable reserve candidates found
  7 skipped due to prior hard mismatch
  Remaining gap: 32 companies

[3/5] External Search
  Generating Exa queries...
  Running query 1/8
  Running query 2/8
  ...
  Retrieved 96 raw candidates
  53 unique companies after dedupe

[4/5] Evaluation
  Evaluating candidate 1/53
  Evaluating candidate 2/53
  ...
  Selected: 28
  Reserve: 15
  Rejected: 10

[5/5] Save + Export
  Writing run data...
  Exporting CSV...
  Exporting Markdown summary...
  Done
```

## Visual language recommendation

The phases should not all look the same.

Recommended visual treatment:

- `Spec`: neutral or blue
- `Memory Scan`: green or archive-style visual treatment
- `External Search`: brighter search-oriented treatment
- `Evaluation`: yellow or review-oriented treatment
- `Save + Export`: neutral success treatment

The important part is not the exact colors.

The important part is that memory reuse and external search feel like two clearly different modes.

Example idea:

- memory phase uses labels like `MEMORY`, `REUSE`, `POOL`
- external phase uses labels like `SEARCH`, `EXA`, `QUERY`

That gives the workflow a clearer personality and makes the internal behavior legible.

## Progress details that should be shown

For a good operator experience, the CLI should report:

### During memory scan

- which deterministic filters were applied
- how many stored candidates matched
- how many were reusable
- how many were skipped due to past reasons
- what the remaining gap is

### During external search

- how many queries were generated
- which query number is currently running
- how many raw results have been collected so far
- how many unique candidates remain after dedupe

### During evaluation

- how many candidates are being evaluated
- current progress count
- rolling totals for selected, reserve, rejected

### During save/export

- when persistence starts
- when export artifacts are written
- final artifact paths

## Tone of CLI feedback

The CLI feedback should be concise, helpful, and calm.

It should avoid:

- noisy debug spam by default
- long raw payload dumps
- opaque spinner-only behavior

The user should always know:

- what phase the system is in
- whether it is using memory or doing new search
- roughly how far along it is
- what the current totals look like

## Verbosity levels

The CLI should support at least two modes:

### Default mode

Show:

- stage progress
- counts
- summaries
- final outputs

### Verbose mode

Show additionally:

- generated queries
- candidate-level evaluation summaries
- more detailed skip/reject reasons

This keeps the default experience clean while still making debugging possible.

### 2. `companies show-run`

Inspect the results of a run.

Example:

```bash
leads companies show-run <run-id>
```

Responsibilities:

- show search spec summary
- show generated queries
- show selected/reserve/rejected counts
- show artifact locations

### 3. `companies export`

Export selected results for review.

Example:

```bash
leads companies export <run-id>
```

Responsibilities:

- generate CSV and Markdown reports
- export selected and reserve candidates
- include evaluation reasons

### 4. `companies inspect`

Inspect one candidate or one domain in more detail.

Example:

```bash
leads companies inspect <run-id> --domain acmebuilders.com
```

Responsibilities:

- show raw Exa hits
- show normalized company record
- show LLM evaluation output
- show why it was selected, reserved, or rejected

### 5. `companies rerun`

Rerun an existing spec or tweak a prior run.

Example:

```bash
leads companies rerun <run-id>
```

Responsibilities:

- reuse prior spec
- optionally regenerate queries
- run again with the same contract

## CLI commands explicitly not needed in v1

Avoid adding these yet:

- discovery continue
- refill
- research queue processing
- advanced backlog promotion
- multi-stage enrichment triggers

Those can come later if the simpler flow proves insufficient.

## Agent skill plan

The skill system matters as much as the CLI.

We need at least two agent skills.

## Skill 1: `company-search-spec-writer`

Purpose:

teach the agent how to turn a user request into a valid `company_search_spec.json`.

Responsibilities:

- extract target vertical
- extract count
- extract geography
- extract size range if present
- extract exclusions if present
- choose a stable vertical `key` and `label`
- add optional `search_terms` or `exclude_terms` only when the vertical needs query hints
- write valid JSON only
- avoid inventing constraints the user did not ask for

Rules:

- if the user does not specify size, do not add fake size limits
- if the user does not specify exclusions, leave them empty except for default system hygiene
- if the geography is broad, encode it explicitly
- if the vertical is niche or ambiguous, add targeted search hints instead of a special mode

Expected output:

- one valid `company_search_spec.json`

## Skill 2: `company-discovery-operator`

Purpose:

teach the agent how to execute discovery using the spec file and how to explain the results.

Responsibilities:

- confirm the spec path
- run `leads companies discover --spec ...`
- inspect the results
- summarize selected / reserve / rejected outputs
- tell the user what the run found and where the artifacts are

Rules:

- do not rewrite the spec unless asked
- do not silently change constraints
- surface important missing-input conditions, such as:
  - no size filter
  - no exclusions
  - national search mode

## Optional future skill

### `company-search-refiner`

Purpose:

help the agent revise the spec after a poor run.

Useful later for:

- adding exclusions
- narrowing geography
- introducing a size range
- improving weak vertical hints into cleaner reusable presets

Not required for first implementation.

## Discovery service plan

The main service should be a clean pipeline with a small number of steps.

## Step 1: Load and validate spec

Input:

- `company_search_spec.json`

Responsibilities:

- schema validation
- normalize defaults
- reject malformed or contradictory specs

Output:

- normalized spec object

## Step 2: Filter local memory/backlog first

Input:

- normalized spec

Responsibilities:

- query the saved company pool deterministically
- filter by structured spec fields such as:
  - vertical
  - country
  - state
  - size bounds where available
  - exclusion markers where available
  - novelty mode
- retrieve previously reserved or otherwise reusable companies first
- inspect prior reasons for reserve, reject, or skip
- decide which previously seen companies are in scope now

Important:

Past non-selected companies should not all be treated the same.

Examples:

- previously reserved because stronger candidates already filled the count
- previously rejected due to size mismatch
- previously uncertain because size was unknown
- previously excluded by old exclusions that do not apply now

These cases need different reuse behavior.

Output:

- local in-scope reusable candidates
- local excluded candidates with reusable reasons
- remaining market gap to fill externally

For multi-vertical searches, perform this step separately per vertical. Reusable companies from a
strong lane remain available for soft overflow, while deficient lanes continue to external search.

## Step 3: Generate Exa queries with the LLM

Input:

- one single-vertical lane spec
- that lane's remaining market gap

Responsibilities:

- generate a small batch of search queries
- diversify phrasing
- include vertical, geography, and size intent if present
- include exclusion intent where helpful

Recommended query count:

- 6 to 12 queries

Output:

- structured list of Exa queries

Do not ask the LLM or Exa to interpret a blended `construction + healthcare` vertical. Generate
and execute a separate query plan for each lane.

## Step 4: Run Exa

Input:

- generated queries

Responsibilities:

- run company search against Exa
- collect raw result payloads
- save per-query result groups

Output:

- raw Exa search results

## Step 5: Normalize and dedupe candidates

Responsibilities:

- extract domain
- extract company name
- retain Exa entity ID if available
- retain relevant raw snippets and metadata
- merge duplicates across queries

Output:

- normalized candidate list

## Step 6: Deterministic hygiene filtering

Responsibilities:

- remove obvious junk
- remove malformed records
- remove clear duplicate domains
- remove obvious list/directory pages when they are not company entities

Important:

This step should stay intentionally narrow.

It should not try to solve full qualification.

## Step 7: LLM candidate evaluation

Responsibilities:

- evaluate each candidate against the ICP
- return a structured judgment

Recommended output shape:

```json
{
  "company_name": "Acme Builders",
  "domain": "acmebuilders.com",
  "fit": "good_fit",
  "vertical_match": "yes",
  "geography_match": "likely",
  "size_match": "unknown",
  "excluded": "no",
  "reason": "Texas commercial builder with relevant services and an official company website.",
  "evidence": [
    "website language suggests commercial construction",
    "domain appears to be the operating company website"
  ]
}
```

Possible `fit` values:

- `good_fit`
- `possible_fit`
- `bad_fit`

These map naturally to:

- selected
- reserve
- rejected

## Step 8: Persist memory

Save:

- spec
- generated queries
- raw Exa results
- normalized candidates
- LLM evaluations
- final buckets

This is the foundation for later reuse.

## Step 9: Export artifacts

Produce:

- selected companies CSV
- reserve companies CSV
- rejected companies CSV
- Markdown summary report
- JSON run payload for debugging

## Persistence plan

We do not need the final perfect data model in v1.

But we do need enough structure to preserve learning.

## Minimum tables or entities

### `company_discovery_runs`

Stores:

- run ID
- spec payload
- created at
- status
- summary counts

### `company_discovery_queries`

Stores:

- run ID
- generated query text
- query order

### `company_discovery_raw_results`

Stores:

- run ID
- query ID
- raw Exa payload
- observed URL
- observed title

### `company_candidates`

Stores:

- run ID
- canonical name
- domain
- normalized payload
- dedupe key
- normalized vertical
- normalized country
- normalized state
- employee_min if known
- employee_max if known
- ownership_type if known
- prior bucket
- prior reason

### `company_candidate_evaluations`

Stores:

- candidate ID
- LLM evaluation payload
- fit outcome
- reason

## Memory-first retrieval requirements

For the memory-first model to work, saved candidates cannot live only as vague text blobs.

We need enough normalized structure to filter them before asking an LLM anything.

At minimum, saved records should expose fields like:

- company name
- domain
- vertical
- country
- state
- employee minimum if known
- employee maximum if known
- ownership type if known
- prior bucket
- prior reason
- excluded flag if applicable
- last seen or last evaluated timestamp

This does not need to be perfect on day one, but it has to be good enough for deterministic retrieval.

## How prior reasons should be stored

Do not store prior outcomes as only a flat status.

We should preserve why a company landed where it did.

Examples:

- reserved because count was already full
- rejected due to size mismatch
- rejected due to geography mismatch
- rejected due to vertical mismatch
- uncertain because size was missing
- uncertain because geography was missing

This matters because future specs may change what is reusable.

Example:

- a company rejected for California may be valid for Texas
- a company reserved because count was full is a strong reuse candidate
- a company rejected for size should usually stay out if the same size range applies again

This is enough to get started without overbuilding.

## Output behavior plan

At the end of a run, the system should clearly say:

- how many companies were found in local memory first
- how many were reusable
- how many were skipped due to prior hard mismatch
- how much remaining gap required Exa search
- how many queries were generated
- how many raw Exa results were retrieved
- how many unique candidate companies remained after dedupe
- how many were selected
- how many were reserve
- how many were rejected

It should also explicitly state any missing constraints, for example:

- no size filter applied
- no custom exclusions applied
- national search mode used

That transparency is important.

## CLI feedback requirement

Showing progress is not optional.

The implementation should explicitly include user-facing feedback for long-running operations, especially discovery.

The `companies discover` command should visibly show:

- when it is scanning memory
- when it switches to external discovery
- how many candidates it has found and reused
- how many still need to be found
- how far evaluation has progressed
- when results are being saved and exported

This should be treated as part of the product experience, not as a minor polish item.

## Suggested folder responsibilities

One possible new shape:

```text
new-system/
  domain/
  schemas/
  services/
  adapters/
  prompts/
  skills/
  reports/
```

Suggested responsibilities:

- `schemas/`: JSON Schema for `company_search_spec.json`
- `services/`: validation, query generation, evaluation orchestration
- `adapters/`: Exa and LLM clients
- `prompts/`: query generation and candidate evaluation prompts
- `skills/`: agent instructions for spec writing and discovery operation

## Implementation phases

## Phase 1: Spec and skills

Build:

- `company_search_spec.json` schema
- spec validator
- `company-search-spec-writer` skill
- `company-discovery-operator` skill

Success criteria:

- an agent can reliably generate valid spec files

## Phase 2: CLI skeleton

Build:

- `companies discover --spec ...`
- `companies show-run`
- `companies export`

Success criteria:

- the discovery pipeline can be invoked cleanly end to end

## Phase 3: Memory-first retrieval

Build:

- deterministic filtering from spec to saved company pool
- reusable-candidate selection logic
- prior-reason reuse logic
- gap measurement

Success criteria:

- a new search checks local memory before external discovery

## Phase 4: Query generation and Exa integration

Build:

- LLM query generation prompt
- Exa search adapter
- raw result persistence

Success criteria:

- one spec reliably produces raw company candidates

## Phase 5: Candidate normalization and evaluation

Build:

- dedupe logic
- hygiene filter
- LLM evaluation prompt
- selected / reserve / rejected assignment

Success criteria:

- runs produce usable company lists with clear reasons

## Phase 6: Reports and memory

Build:

- CSV exports
- Markdown report
- saved run history and candidate evaluations

Success criteria:

- results are reviewable and reusable

## Key risks

### 1. The spec may still be too loose

Mitigation:

- keep the schema small
- require explicit modes for missing constraints

### 2. LLM query generation may be noisy

Mitigation:

- keep query count small
- use strict prompt templates
- inspect saved generated queries

### 3. Exa results may be inconsistent

Mitigation:

- persist raw results
- keep normalization simple
- avoid overclaiming structured certainty

### 4. LLM evaluation may still be wrong

Mitigation:

- require structured JSON output
- store reasons and evidence
- support quick manual inspection

## Final recommendation

The v1 implementation should deliberately choose simplicity over ambition.

The system we should build first is not:

- a giant autonomous discovery framework

It is:

> an agent-driven company search pipeline with a strict spec, Exa retrieval, LLM judgment, and saved memory

That version is realistic, debuggable, and much more likely to become a solid foundation than another overengineered discovery rewrite.
