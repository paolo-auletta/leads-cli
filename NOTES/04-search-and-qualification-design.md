# Search And Qualification Design

Date: 2026-06-21

## The main problem to solve

You said the tool must become extremely good at finding the right companies.

That means we should design around this exact question:

> For a given ICP, how do we maximize precision first, then recall, without losing explainability?

## Recommended search model

I would use a three-stage model:

1. inventory retrieval;
2. external candidate expansion;
3. evidence-based qualification.

## Stage 1: inventory retrieval

Search the local company memory first.

This should support fast filtering by:

- vertical;
- employee-band status;
- country/state;
- exclusion flags;
- freshness;
- prior disposition.

This gives immediate wins for repeat or adjacent searches.

## Stage 2: external candidate expansion

Only search externally where memory does not satisfy the request.

### Expansion should happen by deficit

Not:

- "run all strategies every time."

Instead:

- "Texas healthcare shortfall of 12";
- "construction in CA has poor size confidence";
- "engineering reserve is weak in San Diego."

That makes the search planner more rational.

## Stage 3: evidence-based qualification

Every plausible candidate should be evaluated along a fixed set of dimensions.

## Search spec design

The user-facing company request should support:

- `verticals`
- `employee_range`
- `country`
- `states`
- `include_keywords`
- `exclude_keywords`
- `exclude_ownership_types`
- `exclude_company_patterns`
- `novelty_mode`
- `count`
- `reserve_ratio`

### Important note

`exclude_keywords` alone is not enough.

We need structured exclusion types too.

Example:

- `exclude_ownership_types = ["franchise", "subsidiary"]`
- `exclude_company_patterns = ["hospital_system", "association", "vendor"]`

This is much cleaner than letting the whole exclusion story live in prompt text.

## Qualification dimensions

### 1. Vertical fit

Questions:

- Is it actually in the requested vertical?
- Is it an operating business in that vertical?
- Is it a subtype we want or want to exclude?

Examples:

- construction firm yes;
- construction software vendor no;
- healthcare clinic yes;
- hospital network maybe no depending on rules.

### 2. Geography fit

Questions:

- Does the company operate in the requested state?
- Is the state just a headquarters clue, or a real operating presence?
- Is this local enough for the client's needs?

### 3. Size fit

Questions:

- Do we have direct headcount evidence?
- Do we only have indirect evidence?
- Is the company clearly in range, likely in range, overlapping, or unknown?

### 4. Ownership and exclusions

Questions:

- Is this independent?
- Is it a franchisee?
- Is it owned by a parent group the client would reject?
- Is it part of a pattern we explicitly exclude?

### 5. Identity quality

Questions:

- Do we know the official domain?
- Do we trust this is a real company entity?
- Could this be a duplicate or a directory artifact?

## Size reasoning redesign

This should become a dedicated module.

### Acceptable size signals

- provider headcount ranges;
- official staff/team roster lower bounds;
- public firmographic estimates;
- licensing roster scale clues;
- number of locations with calibrated priors;
- Apollo organization size as one corroborating source.

### Size output shape

For each company, store:

- `size_lower_bound`
- `size_upper_bound`
- `size_verdict`
- `size_confidence`
- `size_sources`
- `size_last_verified_at`

This lets the selection engine reason about size explicitly.

## Exclusion engine redesign

This is one of the biggest opportunities.

Right now exclusion logic exists, but not strongly enough.

I would define a dedicated exclusion engine with:

- phrase rules;
- source-specific rules;
- ownership rules;
- manual blocklist;
- learned exclusion outcomes from prior campaigns.

### Example output

```json
{
  "excluded": true,
  "reason_code": "franchise_pattern",
  "confidence": 0.93,
  "evidence": [
    {
      "source": "official_site",
      "url": "https://example.com/about",
      "text": "Proud franchisee of ..."
    }
  ]
}
```

## Selection policy

Selected companies should usually require:

- high identity confidence;
- confirmed or likely vertical fit;
- confirmed geography fit;
- in-range or likely in-range size;
- no strong exclusion evidence.

Reserve companies can allow more uncertainty, but not total ambiguity.

## Research-needed policy

Companies should land in research-needed when they are promising but blocked on one decisive uncertainty, such as:

- size unknown;
- independence unresolved;
- official domain ambiguous;
- regional presence unclear.

That queue is valuable because it prevents wasteful re-search and prevents low-confidence auto-selection.

## Most important search recommendation

The company search engine should be optimized for:

> finding fewer, better, more defensible companies first

before trying to maximize surface-area recall.

That is the right tradeoff for your client's use case.
