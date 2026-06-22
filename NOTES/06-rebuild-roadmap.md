# Rebuild Roadmap

Date: 2026-06-21

## Recommendation

I would not "rewrite everything at once."

I would do a controlled rebuild around a new company-core model, while treating the current implementation as reference material only.

## Phase 1: product definition

Goal:

lock the company-only product contract before writing new code.

Deliverables:

- canonical definition of the company tool;
- search request schema;
- qualification dimensions;
- output states;
- company profile schema;
- memory/backlog rules.

## Phase 2: domain model and storage

Goal:

design the new persistent model before adapters and prompts.

Core entities:

- `company_search_spec`
- `company_campaign`
- `quota_cell`
- `company_entity`
- `company_alias`
- `company_location`
- `company_sighting`
- `company_claim`
- `company_assessment`
- `company_campaign_result`
- `company_profile`
- `company_sync_event`

## Phase 3: inventory-first engine

Goal:

get the reusable memory loop working first.

Capabilities:

- search existing company memory by spec;
- rank reusable candidates;
- surface deficits by quota cell;
- mark what needs external expansion.

## Phase 4: retrieval lanes

Goal:

plug external candidate sources into the new model.

Recommended order:

1. structured sources;
2. Exa company search;
3. directory/list mining;
4. local corroboration sources.

This order keeps the early system focused on quality over breadth.

## Phase 5: qualification engine

Goal:

turn candidates into explainable company decisions.

Capabilities:

- vertical fit reasoning;
- geography fit reasoning;
- size reasoning;
- ownership/exclusion reasoning;
- identity confidence;
- selection and reserve assignment.

## Phase 6: profile enrichment

Goal:

produce stable client-facing company records from selected companies.

Capabilities:

- field-family research lanes;
- Apollo as corroboration/fallback;
- canonical profile merge;
- confidence summary.

## Phase 7: approval and sync handoff

Goal:

keep outbound steps clean and thin.

Capabilities:

- approval artifacts;
- diff-aware re-approval rules;
- CRM payload mapping;
- dry-run previews;
- sync event logging.

## What I would build first in code

If we start implementation after this brainstorming stage, my first concrete build order would be:

1. new company domain model;
2. `CompanySearchSpec` compiler;
3. company memory query layer;
4. basic inventory-first campaign planner;
5. one good retrieval lane: Exa company search;
6. deterministic qualification engine;
7. reserve/refill;
8. profile enrichment;
9. sync adapter.

## What I would preserve from the old system

- campaign thinking;
- quota cells;
- reusable memory idea;
- evidence-backed buckets;
- reserve/refill behavior;
- approval before live sync.

## What I would intentionally not preserve as-is

- mixed old/new workflow naming;
- discovery logic spread across too many concepts;
- backlog as semi-leftovers;
- search-strategy-first mental model;
- enrichment as mostly Apollo gap-fill;
- sync concerns influencing core company architecture.

## Final recommendation

The rebuild should treat the company product as a standalone system with one mission:

> find and qualify the right companies better than a human doing manual lead research

If we keep that as the north star, the architecture decisions get much easier.
