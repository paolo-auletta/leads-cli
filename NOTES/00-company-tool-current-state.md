# Company Tool Current State

Date: 2026-06-21

## Scope

This document is only about the company side of the product.

It excludes:

- people/contact discovery;
- contact enrichment;
- contact approval logic.

It includes:

- company discover;
- company enrich;
- company sync;
- the reusable backlog/inventory behavior that sits between them.

## What the current company tool is trying to do

At a high level, the current company tool tries to answer this question:

> Given a target market, which companies are real, relevant, in-range, independent enough, and safe enough to hand off into the client's sales workflow?

That means the company side is not just "searching businesses."

It is trying to do five jobs:

1. search for possible companies;
2. resolve duplicates into canonical companies;
3. decide whether each company fits the target profile;
4. enrich accepted companies with better firmographic details;
5. sync only approved, CRM-ready companies to HubSpot.

## Current workflow shape

```text
campaign request
    ->
discover candidate companies
    ->
build local inventory / backlog
    ->
select + reserve campaign-ready companies
    ->
company enrichment
    ->
human approval
    ->
HubSpot sync
```

## Discover: how it currently works

The best current implementation is `discovery_v2`.

Its mental model is stronger than the older "search results -> keywords -> pick winners" flow.

### 1. Discovery starts as a campaign

A run is created with constraints like:

- target vertical;
- target geography;
- requested count;
- employee min/max;
- novelty policy;
- reserve ratio;
- source diversity caps;
- provider budgets.

This is already a good idea.

The request is not "get me 100 raw results."

It is "build enough usable company inventory to satisfy this market request."

### 2. The request is split into quota cells

The system can split the request into cells like:

- `construction + TX`
- `construction + CA`
- `healthcare + FL`

Each cell has:

- a selected target;
- a reserve target.

This is one of the strongest parts of the current design because it prevents one big state or one easy source from dominating everything.

### 3. It first tries to reuse prior inventory

Before searching again, V2 checks reusable entities already stored locally.

Roughly:

- if a company was previously discovered;
- if it matches the same vertical and region;
- if it was not already synced;
- if policy allows reuse;

then it can be re-assessed for the new campaign before spending search budget again.

This is the piece you said you like, and I agree it is valuable.

It is basically the seed of a long-term market memory.

### 4. It runs retrieval strategies, not one generic search

Each vertical has a playbook with strategies such as:

- Exa company search;
- directory-based Exa search;
- structured sources like NPPES for family practices.

That is much better than one prompt inventing random queries forever.

### 5. Retrieval creates source records, not final companies

The system separates:

- `source records`: what a source claimed it found;
- `entities`: canonical company identities built across many sightings.

This is also a strong design choice.

A directory result is not trusted as "the company record." It is only one sighting.

### 6. Entity resolution merges sightings into canonical companies

The resolver tries to match by things like:

- provider-specific ID;
- domain;
- normalized name + geography.

This is an attempt to answer:

> Is this the same company we saw before, or a new one?

That is necessary if the tool is ever going to build real reusable company memory.

### 7. Evidence is collected for each entity

The system then collects claims such as:

- likely vertical;
- likely operating region;
- website-live signal;
- employee-size evidence;
- parent/franchise signals.

This is important because it moves the tool closer to evidence-backed qualification instead of loose ranking.

### 8. Each company is assessed into a bucket

A company can land in buckets like:

- `selected`
- `ready_reserve`
- `research_needed`
- `out_of_profile`
- `rejected_source_noise`
- `suppressed`

This is conceptually very good.

It means the system recognizes that:

- some companies are good now;
- some are plausible but incomplete;
- some are definitely wrong;
- some should never come back.

### 9. Selection is constrained, not purely ranked

Selection is not just "top N by score."

It also tries to respect:

- quota cell targets;
- source share caps;
- city concentration caps.

That is another strong idea because it protects list quality.

### 10. It creates reserve inventory and supports refill

If downstream enrichment rejects a selected company, the system can promote from reserve and refill the same quota cell.

That is much better than restarting the whole process from scratch.

## Enrich: how it currently works

The current company enrichment stage is narrower than discovery.

Its job is mostly:

- take selected companies;
- add Apollo organization facts;
- fill missing fields;
- reject some companies if Apollo shows they are out of the requested size range.

### What enrich does well today

- Reuses prior Apollo matches for the same domain to avoid duplicate credit spend.
- Adds useful firmographic fields like phone, address, employee estimate, industry, Apollo org ID.
- Records evidence rows instead of silently overwriting everything.
- Can re-score the company profile after enrichment.

### What enrich is not yet doing well enough

- It is still too Apollo-shaped.
- It is not a true multi-lane company-profile builder.
- It acts more like a fact patcher than a deep company qualification engine.

In other words:

discover tries to decide "is this probably a good company?"

enrich tries to patch in better data afterward.

That separation is reasonable, but the enrich stage still feels more tactical than product-defining.

## Sync: how it currently works

Sync is the final outbound stage.

It only pushes companies that are considered CRM-ready.

### Company sync gate today

A company is eligible for live sync only if it is:

- accepted;
- independent enough;
- in the requested employee range;
- human approved.

### Sync behavior

The tool:

- builds a HubSpot company payload;
- upserts the company;
- records sync events;
- supports dry-run previews.

This stage is actually fairly clean conceptually.

Its problem is not that sync itself is wrong.

Its problem is that the upstream product still needs a cleaner identity and a clearer contract.

## What is good in the current company tool

These ideas are worth preserving:

1. Discovery as a campaign with explicit constraints.
2. Quota cells instead of one global ranking pool.
3. Reusable inventory/backlog before new search spend.
4. Source records separate from canonical companies.
5. Evidence-backed assessment buckets.
6. Reserve inventory and automatic refill.
7. Human approval before CRM sync.

## What is messy or still wrong

These are the main structural problems:

### 1. The product identity is blurred

Right now the company system is half:

- search engine,
- research engine,
- enrichment engine,
- CRM gate.

Those are all necessary, but their boundaries are not clean enough.

### 2. Search is still too strategy-centric and not criteria-centric

The user need is:

- "find me the right companies under these constraints."

But much of the current system still thinks in terms of:

- "which retrieval strategy should we try next?"

That matters internally, but it should not be the product's core mental model.

### 3. Vertical and geography handling are stronger than exclusion handling

You specifically need negative criteria like:

- exclude franchisees;
- exclude national chains;
- exclude irrelevant subtypes;
- exclude specific ownership patterns.

The current design can represent some of this, but it is not yet first-class enough.

### 4. Size qualification is improved, but still not product-central

The client cares deeply about size range.

That means employee-band qualification should not feel like one evidence dimension among many.

It should be one of the main product pillars.

### 5. The backlog is valuable but still underdefined

The current reuse behavior is promising, but the system still needs a clearer answer to:

- what exactly gets remembered;
- when memory is trusted;
- when memory expires;
- how memory helps future searches without biasing them badly.

## Most important conclusion

The current company tool is best understood as:

> a campaign-based company qualification engine with reusable inventory

not as:

> a simple scraper, search wrapper, or Apollo add-on.

That framing is important because the rebuild should not optimize for "more search results."

It should optimize for:

- correct company identification;
- strong market-fit qualification;
- reusable company memory;
- reliable CRM handoff.
