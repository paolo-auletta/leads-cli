# Memory And Backlog Redesign

Date: 2026-06-21

## Why this matters

The best idea in the current V2 flow is not the Exa integration.

It is the idea that previous company work should compound.

That should become a first-class subsystem.

## Rename the concept

I would stop thinking of this as "backlog."

Backlog sounds like leftovers.

I would rename it to something like:

- company memory;
- market inventory;
- reusable company pool.

My preference is `company memory`.

## What company memory should store

For each canonical company:

- identity data;
- aliases;
- official domain;
- operating regions;
- vertical hypotheses;
- size evidence;
- exclusion evidence;
- ownership evidence;
- campaign history;
- enrichment history;
- sync history;
- freshness metadata.

## Campaign-specific state vs global state

This separation is critical.

### Global state

Facts about the company itself:

- who it is;
- where it operates;
- what vertical it belongs to;
- size evidence;
- whether it looks franchised or independent.

### Campaign state

Facts about the company relative to one search request:

- selected for this campaign;
- reserve for this campaign;
- out of profile for this campaign;
- needs more research for this campaign.

This avoids one of the common traps:

just because a company was rejected for one search does not mean it should be globally dead forever.

## Reuse policy

When a new request comes in, memory should be searched in tiers.

### Tier 1: confidently reusable

Companies that:

- match the spec;
- are fresh enough;
- are not synced/do-not-contact blocked;
- have strong evidence.

### Tier 2: reusable with re-check

Companies that:

- probably match;
- are somewhat stale;
- have partial uncertainty;
- need one or two decisive validations.

### Tier 3: not reusable unless rules changed

Companies that:

- were strongly excluded;
- were synced already if novelty is required;
- were marked bad/noise;
- are blocked by ownership or explicit client rule.

## Freshness model

The memory system should track freshness per fact family, not just per company.

Examples:

- company identity can stay valid for a long time;
- size evidence decays faster;
- ownership evidence decays moderately;
- operating region may need periodic re-checks.

That gives much better reuse quality than one generic `updated_at`.

## Outcome feedback loop

Memory should improve when downstream steps happen.

Examples:

- if enrichment confirms the company, confidence rises;
- if enrichment proves it is too large, size knowledge improves;
- if sync succeeded, novelty rules can suppress it;
- if a human rejects a false match, that should harden exclusion logic.

This is how the system gradually becomes smarter without "AI magic."

## Anti-pollution rules

Memory is powerful, but it can become toxic if bad facts harden too quickly.

So I would add rules like:

- no irreversible merge on weak evidence;
- no permanent global exclusion from one weak signal;
- no overwrite of strong facts by weaker sources;
- no stale company auto-selection without confidence review.

## The best version of memory

In the strongest design, a new company search feels like this:

1. retrieve already-known likely matches;
2. fill missing cells by new search;
3. qualify only the delta;
4. write back everything learned.

That is much more powerful than running the whole discovery machine fresh every time.
