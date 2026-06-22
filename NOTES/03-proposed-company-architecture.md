# Proposed Company Architecture

Date: 2026-06-21

## Product model

I would rebuild the company side around four core layers:

1. ICP compiler;
2. company memory;
3. search and qualification engine;
4. output and sync handoff.

```text
user company request
    ->
ICP compiler
    ->
inventory-first search planner
    ->
candidate retrieval lanes
    ->
identity resolution
    ->
qualification engine
    ->
campaign selection + reserve
    ->
approval/export/sync handoff
```

## 1. ICP compiler

The input should become a clean `CompanySearchSpec`.

Example fields:

- verticals;
- size range;
- country;
- states;
- include tags;
- exclude tags;
- ownership rules;
- novelty policy;
- requested count;
- reserve ratio.

This object should be normalized before any search runs.

It should compile user language into internal rules such as:

- accepted vertical vocabulary;
- forbidden entity types;
- forbidden ownership patterns;
- region coverage policy;
- minimum evidence needed per field.

## 2. Company memory

This should be the heart of the system.

The memory layer should store:

- canonical company entities;
- aliases;
- domains;
- locations;
- source sightings;
- evidence claims;
- qualification outcomes;
- campaign history;
- sync history.

### Why this matters

Without this, every run starts from zero.

With this, each run becomes:

- partly search;
- partly retrieval from memory;
- partly correction of prior knowledge.

## 3. Inventory-first search planner

Before searching externally, the planner should ask:

1. Which companies in memory already match this spec?
2. Which almost match but need re-checking?
3. Which quota cells are still underfilled?
4. Which deficits justify external search?

This keeps the good part of V2, but makes it central.

## 4. Retrieval lanes

I would separate retrieval into bounded lanes instead of one giant blended process.

### Lane A: structured sources

Examples:

- NPPES;
- licensing registries;
- association rosters;
- known vertical-specific datasets.

Best for:

- strong entity precision;
- vertical grounding;
- repeatable ingestion.

### Lane B: company search providers

Examples:

- Exa company search;
- future structured company providers.

Best for:

- broad discovery with useful firmographic hints.

### Lane C: directory and list mining

Examples:

- chapter directories;
- member rosters;
- public firm lists.

Best for:

- vertical-specific recall.

### Lane D: local corroboration search

Examples:

- place listings;
- official website confirmation;
- map/business identity sources.

Best for:

- confirming operating presence and official domain.

The lanes should produce the same normalized output shape.

## 5. Identity resolution

This should stay strict.

It should prefer duplicate companies over bad merges.

Priority order should be roughly:

1. external provider IDs;
2. official domain;
3. place/licensing identifiers;
4. normalized name + region + corroborating signals.

Ambiguous matches should stay unresolved until more evidence arrives.

## 6. Qualification engine

This is where the company tool becomes truly useful.

The engine should score separate dimensions, not one hidden score.

### Required dimensions

- identity confidence;
- vertical fit;
- geography fit;
- size fit;
- ownership/exclusion fit;
- operating status;
- evidence freshness;
- source corroboration depth.

### Output states

- `selected_ready`
- `reserve_ready`
- `needs_research`
- `known_mismatch`
- `noise`
- `suppressed`

That is close to V2, but I would use names that map more directly to product semantics.

## 7. Selection engine

Selection should operate on qualified companies, with constraints such as:

- requested count;
- quota cells;
- source diversity;
- geography diversity;
- parent-group diversity;
- novelty preference.

This layer should be deterministic and explainable.

No LLM should directly decide the final list.

## 8. Research tasks

For `needs_research`, the system should create explicit research tasks like:

- confirm employee range;
- verify independence;
- confirm regional presence;
- confirm official website.

This is better than mixing unresolved companies into the same pool as clearly qualified ones.

## 9. Company profile enrichment

I would keep enrichment, but redefine it.

It should no longer mean:

- "ask Apollo and fill blanks."

It should mean:

> build the best canonical profile for already-qualified companies.

That profile should include:

- company name;
- official domain;
- phone;
- address;
- state;
- vertical;
- employee estimate/range;
- independence view;
- confidence summary.

Apollo can still be a source, but not the shape of the product.

## 10. Sync handoff

Sync should consume a stable approved company profile table.

The sync layer should be thin.

Its responsibilities should be:

- readiness checks;
- payload mapping;
- upsert behavior;
- event logging.

Not qualification logic.

## My recommended product boundary

If we rebuild cleanly, the company product should end here:

> qualified company inventory plus campaign outputs

Everything after that:

- approval;
- sync;
- CRM-specific payloads;

should be adapters around that core.
