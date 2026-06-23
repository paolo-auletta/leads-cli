# Company Enrichment Redesign

Date: 2026-06-22

## Goal

Enrichment starts from companies already selected by discovery. It is not a second discovery or a
full re-evaluation of the same company.

Discovery already gives enrichment:

- `company_name`
- `domain`
- `vertical` and `target_vertical`
- `country`
- `state`
- `employee_min`
- `employee_max`
- `ownership_type`
- the fit verdict, reason, evidence, and source

The enrichment step should preserve those values, add the missing contact/location details, and
perform only the small number of checks required to make the record usable.

The main job is:

> Take an already-qualified company and complete its company profile without repeating work that
> discovery has already done.

## Final output

The requested output remains:

| Output field | Starting point | Enrichment behavior |
| --- | --- | --- |
| Company Name | Discovery | Carry forward; normalize display formatting only |
| Domain | Discovery | Carry forward as root domain; verify only on identity conflict |
| Phone | Missing | Find and normalize |
| Street Address | Missing | Find as part of one location block |
| City | Usually missing | Find as part of one location block |
| State | Discovery | Carry forward; use it to choose the correct location |
| Zip | Missing | Find as part of one location block |
| Vertical | Discovery | Carry forward `target_vertical`; revisit only on contradiction |
| Employee Estimate | Discovery range/count | Carry forward; refresh only when missing, stale, or contradictory |
| Independent? | Partially informed by `ownership_type` | Check specifically for franchise, subsidiary, or parent ownership |

This reduces the normal enrichment task to three real operations:

1. find a usable phone;
2. find a complete in-scope address;
3. resolve whether the company is independent from a franchise or parent organization.

Everything else is inherited by default.

## Discovery facts are first-class input

Enrichment should read the selected companies from the discovery run's stored data, not reconstruct
them by parsing `selected.csv`. The CSV is an export for people and interoperability; the database
and `run.json` preserve the structured candidate and evaluation records.

Each enrichment item starts with a discovery snapshot:

```json
{
  "discovery_run_id": "company-discover-a1b2c3d4e5f6",
  "company_id": 42,
  "company_name": "CSE Electric",
  "domain": "csetx.com",
  "vertical": "construction",
  "target_vertical": "construction",
  "country": "US",
  "state": "TX",
  "employee_min": 38,
  "employee_max": 38,
  "ownership_type": "privately_held",
  "fit": "good_fit",
  "discovery_evidence": [
    "Industry: Construction",
    "Headquarters: San Antonio, Texas, United States",
    "Employees: 38",
    "Type: Privately Held"
  ],
  "discovery_source": "memory"
}
```

These fields must retain their discovery provenance. Enrichment may produce a newer observation,
but it must not silently erase or overwrite the value that caused the company to be selected.

## Trust model

The fact that a field exists does not mean enrichment must prove it again. It means the field has a
known starting value and provenance.

Use three statuses for inherited fields:

- `inherited`: accepted from discovery without another lookup;
- `confirmed`: enrichment happened to observe the same value while finding missing data;
- `conflict`: enrichment found strong contradictory evidence.

The default is `inherited`. Confirmation is a useful side effect, not a requirement.

Examples:

- A contact page says `CSE Electric` and links to `csetx.com`: name/domain become `confirmed` at no
  extra search cost.
- The page gives a San Antonio address: discovery state `TX` becomes `confirmed` while the address
  is completed.
- The website says it is a division of a national group: ownership is a `conflict`, even if
  discovery stored `privately_held`.
- A LinkedIn snippet says 34 employees while discovery says 38: this is not a meaningful conflict;
  keep the discovery estimate unless the size threshold would be crossed.

## Important ownership distinction

`ownership_type` and `Independent?` are not the same field.

Values such as `private`, `privately held`, or `partnership` describe the organization's ownership
form. They do not guarantee that the company is not:

- a franchise location;
- a subsidiary;
- a portfolio company operating under a parent;
- a division or local branch of a larger organization.

Discovery's `ownership_type` should therefore be carried forward as evidence, but enrichment must
resolve a separate `independence_status`:

- `yes`: evidence supports a standalone company and no parent/franchise evidence is found;
- `no`: explicit franchise, subsidiary, division, or parent relationship is found;
- `unknown`: available sources do not support either conclusion strongly enough.

Never convert `privately_held` directly into `Independent? = Yes`.

## Redesigned pipeline

```text
selected discovery records
  ->
load inherited facts and prior enrichment memory
  ->
identify missing or stale fields
  ->
inspect official website contact/about/location pages
  ->
fill phone + complete address + independence status
  ->
use a structured business source only for unresolved gaps
  ->
detect material conflicts with discovery
  ->
export completed profile and save reusable facts
```

There is no normal "recompute vertical, size, geography, and identity" stage.

## Step 1: Seed from discovery and enrichment memory

For each selected company:

1. Load its discovery candidate and evaluation.
2. Copy the inherited fields into the enrichment working profile.
3. Load any previously enriched phone, address, and independence facts for the same domain.
4. Reuse fresh facts before making external requests.
5. Build a work list containing only missing or stale fields.

For a first enrichment run, the usual work list will be:

```text
phone, street_address, city, zip, independence_status
```

`state` is already known and acts as a constraint when selecting an address.

## Step 2: Retrieve the smallest useful website pack

Start from the known domain. This is targeted retrieval, not open-web company search.

Try the official website in this order:

1. homepage/footer;
2. contact page;
3. locations page;
4. about page;
5. legal/footer text if independence remains unresolved.

Stop as soon as the required facts are resolved. Do not crawl an entire website.

The same pages can provide several facts at once:

- footer: company name, phone, partial/full address;
- contact page: phone and full location block;
- about page: ownership, parent, franchise, or locally-owned language;
- locations page: correct office for the discovery state.

## Step 3: Resolve phone

Source priority:

1. official website contact page or footer;
2. structured business profile tied to the same domain;
3. search corroboration using the known company name and domain.

Rules:

- choose the general company or target-location phone, not a personal mobile or fax;
- normalize internally to E.164 when possible;
- keep a display-friendly version for CSV export;
- if there are multiple offices, pair the phone with the chosen address;
- preserve all observed alternatives as evidence, but export one primary phone.

## Step 4: Resolve the address block

Treat `street_address`, `city`, `state`, and `zip` as one fact. Mixing pieces from different sources
or offices can create a plausible but false address.

Source priority:

1. official contact or location page;
2. structured business profile tied to the known domain;
3. corroborating search result.

Selection rules:

- prefer a complete location in the discovery state;
- if discovery targets all of the US, use the stated headquarters or primary office;
- if several offices exist in the selected state, prefer headquarters, then the clearest primary
  operating location;
- if the only complete address is outside the discovery state, record a geography conflict instead
  of replacing the state silently;
- do not combine a website street address with a different provider's city or zip unless they are
  demonstrably the same location.

The discovered `state` is both inherited output and a deterministic selection filter.

## Step 5: Resolve independence

This is a narrow ownership check, not a broad company investigation.

Look for:

- "franchise", "franchisee", or franchise disclosure language;
- "a division of", "subsidiary of", "part of", "member of the ... group";
- parent-company branding, copyright, legal notices, or acquisition announcements;
- positive standalone evidence such as locally owned, independently owned, or family owned.

Decision rules:

- explicit parent/franchise evidence -> `no`;
- explicit independent/local/family ownership plus no contradictory evidence -> `yes`;
- self-contained brand plus corroborating private ownership and no contrary evidence -> `yes`, with
  lower confidence;
- absence of franchise language alone -> `unknown`, not `yes`;
- unresolved ambiguity -> `unknown` and route according to the run's export policy.

Discovery's `ownership_type` contributes evidence here, but does not decide the answer by itself.

## Step 6: Handle inherited-field conflicts

While visiting official pages, the system may encounter facts that differ from discovery. Only
material conflicts should interrupt enrichment.

### Company name and domain

- Cosmetic naming differences are normalized and accepted.
- A redirect to a clearly renamed but same company can be recorded as a new observation.
- A different company, directory, dead domain, or acquired brand creates `identity_conflict`.

### Vertical

- Keep `target_vertical` as the campaign label.
- Incidental services in another vertical do not change it.
- Explicit evidence that the company does not operate in the selected vertical creates
  `fit_conflict`.

### Country and state

- Matching address data confirms the inherited geography.
- A multi-office company remains valid if it has a real in-scope office.
- Strong evidence that it has no in-scope operation creates `geography_conflict`.

### Employee estimate

- Carry forward `employee_min` and `employee_max` by default.
- Do not spend an enrichment request merely to reconfirm them.
- Refresh only if missing, explicitly requested, stale under policy, or new evidence could move the
  company outside the search size range.
- Small differences between point estimates are normal and should not create a conflict.

When refreshed, preserve both observations and select a current range without fake precision.

## Sources and when to use them

### Official website

Default first source because the domain is already known. Best for phone, address, identity side
effects, and ownership language.

### Structured business profile provider

Fallback for unresolved phone/address fields or to resolve conflicting locations. The lookup must be
anchored by domain plus company name, and constrained by inherited geography where applicable.

### Search corroboration

Use narrowly for unresolved independence, missing contact data, or conflicts. It should not become
a second Exa discovery pass.

### LinkedIn or firmographic provider

Not part of the default path. Use only when employee values are missing/stale or the user explicitly
requests a refresh. This avoids paying again for data already present in discovery.

### Enrichment memory

Always check before external retrieval. Facts are stored per company/domain with source and freshness
so future discovery selections can reuse them.

## Internal data model

Keep the discovery snapshot separate from newly enriched facts:

```json
{
  "company_id": 42,
  "discovery": {
    "run_id": "company-discover-a1b2c3d4e5f6",
    "company_name": "CSE Electric",
    "domain": "csetx.com",
    "target_vertical": "construction",
    "country": "US",
    "state": "TX",
    "employee_min": 38,
    "employee_max": 38,
    "ownership_type": "privately_held",
    "fit": "good_fit",
    "evidence": ["..."]
  },
  "enrichment": {
    "phone": {
      "value": "+12105551234",
      "display_value": "(210) 555-1234",
      "source": "official_site",
      "source_url": "https://csetx.com/contact",
      "observed_at": "2026-06-22T12:00:00Z"
    },
    "location": {
      "street_address": "123 Example St",
      "city": "San Antonio",
      "state": "TX",
      "zip": "78201",
      "source": "official_site",
      "source_url": "https://csetx.com/contact",
      "observed_at": "2026-06-22T12:00:00Z"
    },
    "independence": {
      "status": "yes",
      "evidence": ["Official about page states family owned"],
      "source_urls": ["https://csetx.com/about"],
      "observed_at": "2026-06-22T12:00:00Z"
    }
  },
  "inherited_status": {
    "company_name": "confirmed",
    "domain": "confirmed",
    "vertical": "inherited",
    "country": "confirmed",
    "state": "confirmed",
    "employee_estimate": "inherited",
    "ownership_type": "inherited"
  },
  "outcome": "enriched_ready"
}
```

This prevents enrichment from obscuring where the original qualification facts came from.

## Outcome states

- `enriched_ready`: required new fields are usable and no material conflict exists;
- `enriched_with_gaps`: one or more permitted fields remain blank;
- `independence_unconfirmed`: contact/location data is ready but independence is unknown;
- `identity_conflict`: name/domain no longer appears to represent the selected company;
- `geography_conflict`: no valid operation/address exists in the required geography;
- `fit_conflict`: strong new evidence contradicts the selected vertical or size requirement;
- `enrichment_failed`: sources could not produce a usable profile.

## Export gate

Recommended default requirements:

- inherited company name and root domain are present;
- phone is present;
- one complete address block is present;
- address is compatible with the discovery geography;
- `target_vertical` is present;
- employee estimate is present only when the discovery spec included a size constraint;
- independence is not `no`.

Recommended independence policy:

- `yes` -> export-ready;
- `no` -> blocked;
- `unknown` -> review queue by default, optionally exportable through an explicit CLI flag.

The gate should not require enrichment to independently reconfirm all inherited discovery fields.

## Freshness and refresh policy

Only enrichment-owned facts need a normal freshness policy:

- phone: refresh after a configurable medium interval;
- address: refresh after a configurable medium interval;
- independence: refresh after a medium interval or when acquisition/parent evidence appears.

Inherited discovery facts follow discovery's own evaluation history. Employee estimates may be
refreshed on demand or under a shorter interval when company size is important.

Supported refresh scopes should be explicit:

```text
contact       phone + location
independence  parent/franchise check
employees     employee estimate only
all           all enrichment-owned facts plus requested employee refresh
```

## CLI design

Core commands:

```bash
leads companies enrich DISCOVERY_RUN_ID
leads companies show-enrichment ENRICHMENT_RUN_ID
leads companies inspect-enrichment ENRICHMENT_RUN_ID --domain example.com
leads companies export-enrichment ENRICHMENT_RUN_ID
```

Useful options:

```bash
leads companies enrich DISCOVERY_RUN_ID --bucket selected
leads companies enrich DISCOVERY_RUN_ID --limit 25
leads companies enrich DISCOVERY_RUN_ID --only-missing
leads companies enrich DISCOVERY_RUN_ID --refresh contact
leads companies enrich DISCOVERY_RUN_ID --refresh employees
leads companies enrich DISCOVERY_RUN_ID --allow-unknown-independence
```

Default behavior:

- input bucket is `selected`;
- inherited discovery facts are reused;
- fresh enrichment-memory facts are reused;
- only missing phone, address, and independence facts are fetched;
- employee data is not fetched again;
- material contradictions are surfaced, not silently overwritten.

## CLI progress experience

The CLI should make the reuse-versus-fetch distinction visible:

```text
Enriching discovery run company-discover-a1b2c3d4e5f6 (5 selected companies)

[1/5] CSE Electric
  INHERITED  name, domain, vertical, geography, employees, ownership type
  MEMORY     no reusable contact profile
  WEBSITE    found phone and San Antonio address
  OWNERSHIP  independent confirmed
  READY      10/10 output fields

[2/5] Intex Electrical
  INHERITED  7 discovery fields
  MEMORY     phone reused; address stale
  WEBSITE    address refreshed
  OWNERSHIP  unresolved -> review
  REVIEW     independence unknown
```

The summary should report saved work as well as fetched work:

```text
5 companies processed
35 discovery facts inherited
4 enrichment profiles reused from memory
3 websites fetched
1 structured fallback lookup
4 ready, 1 review, 0 blocked
```

## Agent skill requirements

The enrichment skill should teach the agent that enrichment consumes a discovery run, rather than
asking the user to restate the ICP or company fields.

The agent should:

- choose the discovery run and default to its `selected` bucket;
- explain that discovery facts will be retained;
- use the normal targeted pass unless the user asks to refresh employees or all facts;
- explain the handling of `Independent? = unknown` before sync/export if it affects results;
- summarize which facts were inherited, reused from memory, newly found, or conflicted.

The skill must not imply that `privately held` automatically means independent.

## Implementation plan

### Phase 1: Enrichment run foundation

- Add enrichment run, item, and field-evidence models.
- Load selected candidates directly from a discovery run in the repository.
- Persist an immutable discovery snapshot on each enrichment item.
- Add inherited-field statuses and enrichment outcomes.
- Implement CLI commands and progress events.

### Phase 2: Targeted official-site enrichment

- Fetch a bounded homepage/contact/location/about page pack from the known domain.
- Extract and normalize phone numbers.
- Extract complete address blocks without mixing offices.
- Select the address using inherited country/state constraints.
- Extract explicit parent, franchise, subsidiary, and independent ownership evidence.

### Phase 3: Resolution and fallback

- Add a structured business-profile adapter for missing/conflicting phone and address.
- Add narrow search corroboration for unresolved ownership or identity conflicts.
- Implement field resolution, conflict rules, and export gates.
- Write resolved enrichment facts back to reusable company memory.

### Phase 4: Optional employee refresh

- Add a firmographic/LinkedIn-style adapter only for missing, stale, or explicitly refreshed size
  data.
- Preserve discovery and enrichment observations separately.
- Detect only size-band conflicts that can affect ICP qualification.

### Phase 5: Agent skill and operational polish

- Add the enrichment operator skill.
- Document default and refresh modes.
- Add per-company traces to the enrichment `run.json`.
- Add CSV export with exactly the requested columns.

## V1 acceptance criteria

Given a discovery run like `company-discover-a1b2c3d4e5f6`, v1 must:

- retain the selected company's name, domain, target vertical, country, state, employee range, and
  ownership type;
- avoid external employee/vertical/company searches during the default enrichment pass;
- find phone, street address, city, and zip from the known company identity;
- evaluate independence separately from generic ownership type;
- expose inherited values and newly found evidence in `run.json`;
- never silently replace discovery facts when enrichment finds a contradiction;
- export one clean row per ready company with the requested columns.

## Product framing

Discovery answers:

> Is this a company we want?

Enrichment answers:

> Now that we already know who it is and why it fits, what contact/location information is missing,
> and is it truly independent enough to use?

That boundary keeps enrichment smaller, cheaper, and easier to trust.
