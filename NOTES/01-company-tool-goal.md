# Company Tool Goal

Date: 2026-06-21

## The real goal

The company tool should do one job extremely well:

> Turn a vague target market into a reliable, reusable list of real companies that match the client's lead criteria.

This is not a contacts tool.

It is not an email finder.

It is not a CRM exporter with some search attached.

It is a company targeting engine.

## What the client actually needs

Your client is not asking:

> "Give me random businesses in Texas."

The client is asking:

> "Find the right companies I should sell to, based on my target market rules."

Those rules include:

- vertical focus;
- employee-size band;
- country;
- state;
- exclusions like franchise, chain, irrelevant subtype, or other disqualifiers.

So the product goal is not "search companies."

It is:

> search, qualify, remember, and deliver the right companies.

## Product definition

The company tool should be a local-first market intelligence system for target-company generation.

That means it should be excellent at four things:

1. understanding the requested ideal company profile;
2. finding candidate companies from multiple sources;
3. qualifying which candidates truly fit;
4. learning from past searches without becoming stale or polluted.

## Desired output

For any company search request, the system should return:

- a selected list of best-fit companies;
- a reserve list of additional qualified companies;
- an explainable rejected list;
- a reusable memory of what was learned.

Every company should have:

- canonical identity;
- evidence-backed vertical classification;
- evidence-backed geography;
- evidence-backed size view;
- evidence-backed exclusion/ownership view;
- confidence and reason trace.

## What success looks like

The company tool is successful if a client can say:

1. "I trust these companies are real."
2. "I trust these companies match my market."
3. "I understand why each company was included or excluded."
4. "The next search gets better because the system remembers prior work."

## What the product is not trying to optimize for

The rebuild should not optimize for:

- maximum raw result count;
- maximum number of search queries;
- giant crawling pipelines by default;
- one-provider dependency;
- one opaque score deciding everything.

Those are implementation details, not product value.

## Core product promise

The strongest version of this tool would promise:

> Give me your company ICP and exclusions, and I will produce the best possible list of target companies with memory, evidence, and repeatability.

## The key product shift

The most important shift for the rebuild is this:

### Old mindset

"Search the web and try to extract companies."

### Better mindset

"Maintain a reusable market graph of companies, and use each search request to query, expand, and refine that graph."

That shift matters because it changes everything:

- search becomes a means, not the product;
- backlog becomes memory, not leftovers;
- enrichment becomes qualification, not patchwork;
- sync becomes a downstream export, not part of the core product identity.

## Final one-sentence definition

If I had to define the company tool in one sentence, I would define it like this:

> A company-targeting engine that finds, qualifies, remembers, and exports the right businesses for a client's outbound workflow.
