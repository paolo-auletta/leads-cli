# Structured Exclusion Checks In Discovery

Date: 2026-06-22

## Goal

Move important exclusions from weak text heuristics into the discovery qualification flow.

The idea is simple:

> if we already know how to gather evidence to confirm something positive about a company, we should
> be able to use the same evidence ladder to confirm something that disqualifies it.

Examples:

- exclude family-owned businesses;
- exclude franchises or franchisees;
- exclude subsidiaries or divisions of larger groups;
- exclude companies acquired by a parent;
- later, exclude other explicit business traits the user cares about.

This should happen mainly during discovery, not enrichment.

Enrichment should stay focused on completing the company profile after discovery has already decided
the company is worth keeping.

## Why the current exclusion model is not enough

Today the search spec mainly supports:

- `exclude.keywords`
- `exclude.ownership_types`
- `exclude.company_patterns`

That is useful for cheap filtering, but it is not enough for business-level exclusions such as
`family_owned`.

The problem is that many exclusions are not:

- normalized provider fields;
- obvious string matches in the name;
- consistently present in one search snippet.

They are evidence-based facts that often require:

1. a first pass from memory or search snippets;
2. a targeted official-site check;
3. sometimes a narrow corroboration search.

That is exactly the same shape as the current independence resolution.

## Main design decision

Structured exclusions should be a discovery-stage verification pass for shortlisted candidates.

Not every raw search result needs a deep exclusion check.

The right order is:

```text
memory retrieval
  ->
cheap deterministic filters
  ->
external search
  ->
candidate normalization + dedupe
  ->
LLM fit evaluation
  ->
shortlist of plausible candidates
  ->
structured exclusion verification
  ->
selected / reserve / rejected
```

This keeps cost under control while still letting exclusions be evidence-backed.

## What belongs in discovery vs enrichment

## Discovery owns

- fit to the requested ICP;
- geography/vertical/size qualification;
- explicit exclusion verification requested by the user;
- shortlist decisions;
- saving reusable exclusion facts to memory.

## Enrichment owns

- phone;
- complete address;
- final reusable company profile fields;
- optional refresh of exclusion facts only when explicitly requested later.

So the core rule is:

If an exclusion affects whether the company should be selected at all, it belongs in discovery.

## Exclusion types

We should separate exclusions into two classes.

### 1. Cheap exclusions

These remain deterministic and run very early.

Examples:

- junk domains;
- obvious directories and aggregators;
- name-pattern exclusions;
- exact user keywords in title/snippet/memory text;
- already known blocked domains.

These are fast and should stay simple.

### 2. Structured exclusions

These are evidence-driven and only run for promising candidates.

Examples:

- `family_owned`
- `franchise`
- `franchisee`
- `parent_owned`
- `subsidiary`
- `division`
- `acquired`

Later we can add other categories, but v1 should start with ownership and independence-related
signals because they already match the current evidence model best.

## Recommended spec redesign

Do not replace the current exclusion fields.

Keep them for cheap filtering and add a new structured block.

Suggested v1 shape:

```json
{
  "exclude": {
    "keywords": [],
    "ownership_types": [],
    "company_patterns": [],
    "structured": {
      "ownership_signals": ["family_owned", "franchise", "subsidiary", "division", "acquired"]
    }
  }
}
```

This stays simple and avoids inventing a giant rule language too early.

Important behavior:

- `keywords` are cheap text filters;
- `ownership_types` are direct provider/memory field filters;
- `structured.ownership_signals` means "actively verify these signals and exclude the company if
  confirmed."

This gives the agent a clean way to express:

- "avoid franchises"
- "exclude family-owned businesses"
- "exclude subsidiaries"

without pretending those are the same thing.

## Candidate states after exclusion verification

A structured exclusion check should produce one of three outcomes:

- `clear`: no requested exclusion signal was found;
- `confirmed_exclusion`: at least one requested exclusion signal was explicitly found;
- `unresolved`: the system could not confidently determine the answer.

Those should map to discovery buckets like this:

- `clear` -> eligible for normal selected/reserve ranking;
- `confirmed_exclusion` -> rejected;
- `unresolved` -> reserve by default, unless the run explicitly allows uncertain exclusions.

This is important.

We should not silently reject a company just because the system failed to confirm or deny a
structured exclusion.

The system should reject only on explicit evidence.

## Evidence ladder for structured exclusions

Use the same evidence ladder as independence, but only when needed.

### Step 1: Memory facts

Before any new fetch, check whether company memory already contains a fresh structured exclusion
fact for the requested signal.

Examples:

- last run confirmed `family_owned`;
- last run confirmed `not family_owned`;
- last run confirmed `franchise`.

If a fresh fact exists, reuse it.

This is the biggest leverage point because repeated client ICPs will often ask for similar things.

### Step 2: Existing search evidence

If the current memory record or new search result already contains strong evidence in title/snippet,
use it.

Examples:

- "family-owned roofing contractor"
- "a franchise location of ..."
- "part of the ABC Group"

This may be enough to confirm an exclusion without another fetch.

### Step 3: Official-site verification

If the candidate is still promising and the exclusion is unresolved, inspect a very small official
site pack:

1. homepage;
2. about page;
3. contact/footer;
4. legal/company page if present.

Do not crawl the whole site.

The system should look specifically for the requested structured signals, not run broad enrichment.

### Step 4: Narrow corroboration search

If still unresolved and the candidate is near the cutoff, run a narrow corroboration query.

Examples:

- `"Acme Builders" site:acme.com family owned`
- `"Acme Builders" franchise`
- `"Acme Builders" subsidiary`

This should be a bounded fallback, not a second discovery pass.

## Suggested discovery pipeline changes

Add a new sub-stage after the first fit shortlist:

```text
fit-qualified candidates
  ->
structured exclusion verifier
  ->
bucketing
```

The verifier should:

1. read requested structured exclusions from the spec;
2. skip itself entirely when none are requested;
3. run only on candidates that are already good enough to matter;
4. reuse fresh memory facts first;
5. fetch the smallest useful evidence pack only when necessary;
6. persist the exclusion result and evidence back to memory.

This keeps the feature targeted and cheap.

## Data model

Discovery memory should store exclusion facts separately from generic candidate evaluation.

Suggested concept:

```json
{
  "domain": "acme.com",
  "exclusion_facts": [
    {
      "signal": "family_owned",
      "status": "yes",
      "source": "official_site",
      "source_urls": ["https://acme.com/about"],
      "evidence": ["Acme is a family-owned construction company."],
      "observed_at": "2026-06-22T19:30:00Z"
    },
    {
      "signal": "franchise",
      "status": "no",
      "source": "official_site",
      "source_urls": ["https://acme.com/about"],
      "evidence": ["No franchise language found; ownership page says independently operated."],
      "observed_at": "2026-06-22T19:30:00Z"
    }
  ]
}
```

Important point:

These should be signal-by-signal facts, not one giant `excluded = true` blob.

That way a later search can ask:

- exclude family-owned;
- but not care about franchise;

and memory can answer precisely.

## Freshness policy

Not all exclusion facts age the same way.

Reasonable v1 defaults:

- `family_owned`: long freshness window;
- `franchise`: medium freshness window;
- `subsidiary` / `acquired` / `division`: shorter freshness window because ownership changes more.

If a fact is stale, the verifier can re-check it only for shortlisted candidates.

## LLM prompt changes

Do not ask the evaluator to improvise exclusion logic from scratch every time.

Instead, split responsibilities:

### Fit evaluator

Answers:

- does this look like a company in the requested vertical/geography/size?
- is there obvious exclusion evidence in the current snippets?

### Structured exclusion extractor

Answers:

- which requested exclusion signals are explicitly supported by supplied pages/snippets?
- which are explicitly contradicted?
- which remain unknown?

This is closer to the current enrichment extractor model and should be easier to trust.

## Output and trace behavior

The run should show exclusion work explicitly.

Good discovery progress could look like:

```text
MEMORY      checking saved candidates with spec filters
SEARCH      generating Exa queries
SEARCH      collecting external candidates
FIT         evaluating 42 normalized candidates
EXCLUDE     verifying structured exclusions for 11 shortlisted companies
EXCLUDE     reused 7 exclusion facts from memory
EXCLUDE     fetched 4 official-site packs
SELECT      8 selected, 5 reserve, 12 rejected
```

Per-company trace in `run.json` should show:

- which exclusion signals were requested;
- whether the answer came from memory, search evidence, official site, or corroboration;
- whether the result was `clear`, `confirmed_exclusion`, or `unresolved`;
- which bucket decision that caused.

This matters a lot for trust.

## Agent skill changes

The spec-writing skill should learn one new behavior:

When the user expresses a business trait they want excluded and it maps to a supported structured
signal, write it into `exclude.structured`.

Examples:

- "exclude family-owned businesses" -> `ownership_signals: ["family_owned"]`
- "avoid franchisees" -> `ownership_signals: ["franchise"]`
- "exclude companies owned by larger groups" -> `ownership_signals: ["parent", "subsidiary", "division", "acquired"]`

The discovery operator skill should explain that:

- cheap exclusions run first;
- structured exclusions are only verified for promising candidates;
- explicit evidence rejects;
- unresolved cases usually fall to reserve, not hard rejection.

## Recommended implementation phases

### Phase 1: Spec and memory model

- add `exclude.structured.ownership_signals`
- add validation for allowed signal names
- add persisted exclusion-fact storage in memory

### Phase 2: Discovery verifier

- add a structured exclusion verifier stage after first-pass fit evaluation
- reuse memory facts before any fetch
- support official-site mini-pack retrieval for unresolved candidates

### Phase 3: Reporting and UX

- show exclusion progress in CLI output
- write per-company exclusion traces to `run.json`
- show rejection reasons using explicit signal names

### Phase 4: Skill updates

- update the spec-writer skill to emit structured exclusions
- update the discovery operator skill to explain exclusion behavior clearly

## Recommended v1 boundary

To keep this sane, v1 should support structured exclusions only for ownership-related signals:

- `family_owned`
- `franchise`
- `parent`
- `subsidiary`
- `division`
- `acquired`

That is enough to solve the immediate business need without building a giant generic rule engine.

Later, if needed, the same pattern can expand to other explicit company traits.

## Final recommendation

Yes, the same evidence methods used to confirm company fit should also be used to confirm
disqualifying traits.

But they should be used in a controlled place:

- during discovery;
- only for shortlisted candidates;
- with memory reuse first;
- with explicit signal-based outputs;
- and with unresolved cases separated from confirmed exclusions.

That gives us a system that is much more useful than raw keyword exclusions, while still staying
small enough to trust and debug.
