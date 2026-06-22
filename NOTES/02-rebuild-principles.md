# Rebuild Principles

Date: 2026-06-21

## Principle 1: search quality is the product

The company side lives or dies on one thing:

can it reliably find the right companies?

Everything else is downstream of that.

So the rebuild should prioritize:

- retrieval quality;
- qualification quality;
- explainability;
- reuse of prior knowledge.

## Principle 2: criteria must be first-class

The client thinks in criteria, not implementation details.

The system should be built around filters like:

- verticals;
- employee range;
- country;
- state;
- included traits;
- excluded traits;
- ownership constraints;
- novelty preferences.

These should be first-class objects in the system, not loose flags attached to a run.

## Principle 3: one company, one canonical identity

The core record should always be a canonical company entity.

Search results, directory rows, provider payloads, website pages, and later enrichments are all evidence about that entity.

This prevents:

- duplicate work;
- duplicate CRM records;
- inconsistent memory;
- broken backlog reuse.

## Principle 4: separate retrieval from qualification

Retrieval should answer:

- where can we find plausible candidates?

Qualification should answer:

- does this company fit the ICP?

These are different jobs and should be separate modules.

## Principle 5: the backlog is memory, not a dumping ground

What you liked in V2 should survive, but in a cleaner form.

Backlog should become:

- a reusable market memory;
- indexed by company identity and profile traits;
- decayed by freshness;
- corrected by downstream outcomes.

It should not just mean:

- "stuff we found before but didn't use."

## Principle 6: exclusions are as important as matches

A strong system does not just know how to include.

It must know how to exclude with confidence.

Examples:

- franchisee;
- subsidiary of a national parent;
- association;
- software vendor instead of construction firm;
- hospital system instead of independent clinic;
- giant multi-state firm outside size target.

Negative logic should be designed as seriously as positive logic.

## Principle 7: size must be a core reasoning layer

Employee range is one of the client's primary filters.

So the rebuild should treat size qualification as a dedicated subsystem, not a minor afterthought.

That means:

- store ranges, not fake exact counts;
- support multiple size signals;
- mark unknown size separately from bad size;
- use size confidence in selection.

## Principle 8: campaigns should query inventory, not recreate reality

Each new search should not behave as if the world is blank.

Instead:

1. search the existing company memory;
2. reuse what is still valid;
3. identify deficits;
4. run targeted expansion only where needed.

This is cheaper, faster, and more compounding over time.

## Principle 9: every decision must be explainable

For each company, we should be able to answer:

- why it was selected;
- why it was reserved;
- why it was rejected;
- what evidence is missing;
- what changed since last time.

If the system cannot explain a decision, it is too opaque.

## Principle 10: sync is not the product core

CRM sync matters, but it is downstream.

The core company product should end at:

- validated company inventory;
- campaign output;
- approval-ready artifacts.

Sync should consume that output, not shape the architecture.
