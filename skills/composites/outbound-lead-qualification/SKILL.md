---
name: outbound-lead-qualification
version: 1.0.0
description: >
  Qualifies outbound and cold lead lists against ICP criteria — company fit, person fit, and
  reachability. Handles any list source: scraped prospects, event attendees, purchased lists,
  Apollo/Clay exports, or manually built target accounts. Enriches sparse records via Apify
  LinkedIn scraping, scores each lead on a 0-100 composite scale, and outputs a tiered CSV
  with qualification verdicts, reasoning, and recommended outreach priority.
tags: [lead-generation]

graph:
  provides:
    - qualified-prospect-list       # Leads scored with ICP fit, tier, and reasoning
    - qualification-csv             # Flat CSV with all qualification data
    - outreach-priority-queue       # Tier-ordered list ready for sequencing
  requires:
    - prospect-list                 # Any lead list — CSV, Google Sheet, pasted URLs, etc.
    - your-company-context          # ICP definition, product description, buyer personas
  connects_to:
    - skill: lead-qualification
      when: "Uses the qualification engine's intake and scoring logic"
      receives: qualification-prompt
    - skill: cold-email-outreach
      when: "Qualified leads are ready for cold outreach"
      passes: outreach-priority-queue
    - skill: champion-move-outreach
      when: "Qualified leads match champion-move signals (job changers)"
      passes: qualified-prospect-list
    - skill: hiring-signal-outreach
      when: "Qualified leads came from hiring signal lists"
      passes: qualified-prospect-list
    - skill: funding-signal-outreach
      when: "Qualified leads came from funding signal lists"
      passes: qualified-prospect-list
  capabilities: [web-search, contact-enrichment, crm-lookup]
---

# Outbound Lead Qualification

Takes any list of outbound prospects and qualifies each against your ICP. Unlike `inbound-lead-qualification` (which has intent signals from the lead coming to you), this skill works with cold lists where you have no intent data — qualification is purely on fit.

## When to Auto-Load

Load this composite when:
- User says "qualify these prospects", "score this lead list", "which of these are worth reaching out to"
- User provides a CSV, Google Sheet, or list of LinkedIn URLs for outbound
- An upstream signal composite (funding, hiring, news) produced a prospect list that needs qualification
- User exported leads from Apollo, Clay, LinkedIn Sales Nav, or similar tools

Do NOT load when:
- Leads are inbound (demo requests, signups, content downloads) — use `inbound-lead-qualification` instead
- User wants triage/prioritization of inbound — use `inbound-lead-triage`

## Architecture

```
[Prospect List] → Step 1: Load ICP & Parse → Step 2: Enrich Sparse Records → Step 3: Company Qualification → Step 4: Person Qualification → Step 5: Reachability & Signal Check → Step 6: Score & Tier → Step 7: Output CSV
```

---

## Step 0: Configuration (Once Per Client)

On first run, establish the ICP definition and tool preferences. Save to `clients/<client-name>/config/outbound-lead-qualification.json`.

```json
{
  "icp_definition": {
    "company_size": {
      "min_employees": null,
      "max_employees": null,
      "sweet_spot": "",
      "notes": ""
    },
    "industry": {
      "target_industries": [],
      "excluded_industries": [],
      "notes": ""
    },
    "use_case": {
      "primary_use_cases": [],
      "secondary_use_cases": [],
      "anti_use_cases": [],
      "notes": ""
    },
    "company_stage": {
      "target_stages": [],
      "excluded_stages": [],
      "notes": ""
    },
    "geography": {
      "target_regions": [],
      "excluded_regions": [],
      "notes": ""
    }
  },
  "buyer_personas": [
    {
      "name": "",
      "titles": [],
      "seniority_levels": [],
      "departments": [],
      "is_economic_buyer": false,
      "is_champion": false,
      "is_user": false
    }
  ],
  "hard_disqualifiers": [],
  "hard_qualifiers": [],
  "list_source_context": {
    "source": "Apollo | Clay | LinkedIn Sales Nav | event | scraped | manual | signal-composite | other",
    "source_detail": "",
    "original_targeting_criteria": ""
  },
  "crm_access": {
    "tool": "Supabase | HubSpot | Salesforce | CSV export | none",
    "access_method": "",
    "tables_or_objects": []
  },
  "qualification_prompt_path": "path/to/lead-qualification/prompt.md or null"
}
```

**If `lead-qualification` capability already has a saved qualification prompt:** Reference it directly — don't rebuild ICP criteria from scratch.

**On subsequent runs:** Load config silently.

---

## Step 1: Load ICP Criteria & Parse Leads

### Process
1. Load the client's ICP config (or qualification prompt from `lead-qualification` capability)
2. Parse the prospect list — accept any format:
   - CSV file with any column structure
   - Google Sheet URL (read via Rube MCP)
   - LinkedIn profile URLs — one or more inline
   - Apollo/Clay/Sales Nav export
   - Pasted list of names/companies/emails
   - Output from an upstream signal composite
3. Detect the list source and note it — source context affects scoring nuance:
   - **Signal-sourced lists** (funding, hiring, news): Higher baseline relevance — these were already filtered by a signal
   - **Tool exports** (Apollo, Clay): Usually pre-filtered by some criteria — check what
   - **Event attendees**: Have implicit topic interest
   - **Purchased/scraped lists**: Lowest baseline quality — expect higher disqualification rates
4. Inventory available data per lead:
   - **Have:** Fields present in the input
   - **Need:** Fields required for qualification but missing
   - **Gap report:** "X leads have LinkedIn URL, Y have company + title, Z have only name/email"

### Output
- Parsed lead list with field inventory
- Gap report for the user
- Source classification

### Human Checkpoint
If >60% of leads are missing both company name AND title AND LinkedIn URL, warn: "This list is very sparse. I can try enriching from emails/names, but expect lower accuracy. Proceed or provide a richer list?"

---

## Step 2: Enrich Sparse Records

### When to Run
- Any lead missing company, title, or industry
- Leads with LinkedIn URLs but no structured profile data
- Skip for leads that already have full company + title + industry data

### Process

**Path A — LinkedIn URL available:**
Run the batch enrichment script from the `lead-qualification` capability:

```bash
python3 skills/lead-qualification/scripts/enrich_leads.py INPUT_CSV \
  --output ENRICHED_CSV \
  --cache-hours 24
```

Use `--dry-run` first to show cost estimate. Cost: ~$3 per 1,000 profiles.

**Path B — No LinkedIn URL, but have name + company:**
- Web search for "[Name] [Company] LinkedIn" to find the profile URL
- Then run Path A enrichment
- Batch these lookups — don't search one at a time

**Path C — Only email available:**
- Extract domain from email
- If corporate domain: look up company, search for the person by name + company
- If personal email (gmail, yahoo, etc.): flag as `enrichment_limited` — qualify on whatever data is available

**Path D — Name only:**
- Too ambiguous without additional context. Flag as `insufficient_data`.
- Recommend the user provide more identifying information.

### Output
- Enriched CSV with: `enriched_title`, `enriched_company`, `enriched_industry`, `enriched_location`, `enriched_connections`, `enriched_education`, `enriched_experience_years`, `enriched_headline`, `enriched_about`, `enrichment_status`
- Enrichment summary: "Enriched X/Y leads. Z failed. W had cached data."

---

## Step 3: Company Qualification

### Process
For each lead's company, evaluate against every ICP company dimension:

**Dimension 1 — Company Size**
- Check employee count against ICP range
- Sources: enrichment data, LinkedIn company page, web search
- Score: `match` | `borderline` | `mismatch` | `unknown`
- Note: For subsidiaries/divisions, evaluate the relevant unit

**Dimension 2 — Industry**
- Check against target and excluded industry lists
- Be smart about classification: "AI-powered HR platform" matches both "AI/ML" and "HR Tech"
- Score: `match` | `adjacent` (related but not core target) | `mismatch` | `unknown`

**Dimension 3 — Company Stage**
- Seed, Series A, Series B+, Growth, Public, Bootstrapped
- Sources: Crunchbase, news, enrichment data
- Score: `match` | `borderline` | `mismatch` | `unknown`

**Dimension 4 — Geography**
- Check HQ location and/or the specific person's location
- For remote-first companies, check where the majority of the team is
- Score: `match` | `borderline` | `mismatch` | `unknown`

**Dimension 5 — Use Case Fit**
- Based on what the company does, could they plausibly use the product?
- For outbound, this is the most important dimension — there's no intent signal, so fit must be strong
- Sources: company website, product description, job postings, tech stack signals
- Score: `strong_fit` | `moderate_fit` | `weak_fit` | `no_fit` | `unknown`

### Output
Each lead gets a `company_qualification` block:
```json
{
  "company_size": { "score": "", "value": "", "reasoning": "" },
  "industry": { "score": "", "value": "", "reasoning": "" },
  "stage": { "score": "", "value": "", "reasoning": "" },
  "geography": { "score": "", "value": "", "reasoning": "" },
  "use_case": { "score": "", "value": "", "reasoning": "" },
  "company_verdict": "qualified | borderline | disqualified | insufficient_data"
}
```

---

## Step 4: Person Qualification

### Process
For each lead's contact person, evaluate against buyer persona criteria:

**Dimension 1 — Title/Role Match**
- Check title against buyer persona title lists
- Handle variations: "VP of Marketing" = "Vice President, Marketing" = "VP Marketing"
- Adjust for company size: a "Director" at a 10-person startup ≠ "Director" at a 10,000-person enterprise
- Score: `exact_match` | `close_match` | `adjacent` | `mismatch` | `unknown`

**Dimension 2 — Seniority Level**
- Map to: Individual Contributor, Manager, Director, VP, C-Level, Founder
- Check against ICP seniority requirements
- For outbound, seniority matters more — you're cold-reaching, so you need someone with authority to respond
- Score: `match` | `too_junior` | `too_senior` | `unknown`

**Dimension 3 — Department**
- Engineering, Product, Marketing, Sales, Operations, Finance, HR, etc.
- Check against ICP department targets
- Score: `match` | `adjacent` | `mismatch` | `unknown`

**Dimension 4 — Authority Type**
- Based on title + seniority + company size, classify:
  - `economic_buyer` — Can sign the check
  - `champion` — Wants it, can influence the decision
  - `user` — Would use it daily, can validate need
  - `evaluator` — Tasked with research, limited decision power
  - `gatekeeper` — Can block but not approve
  - `unknown`

**Dimension 5 — Reachability Assessment**
- Unlike inbound (where the lead reached out), outbound requires you to reach them
- Check: Do we have a work email? LinkedIn URL? Phone?
- Score: `highly_reachable` (work email + LinkedIn) | `reachable` (one channel) | `low_reachability` (personal email only or no contact info) | `unreachable`

### Output
Each lead gets a `person_qualification` block:
```json
{
  "title_match": { "score": "", "value": "", "reasoning": "" },
  "seniority": { "score": "", "value": "", "reasoning": "" },
  "department": { "score": "", "value": "", "reasoning": "" },
  "authority_type": "",
  "reachability": { "score": "", "channels": [], "reasoning": "" },
  "person_verdict": "qualified | borderline | disqualified | insufficient_data",
  "mismatch_type": "null | right_company_wrong_person | right_person_wrong_company"
}
```

---

## Step 5: Reachability & Signal Check

### Process

**Signal Overlap Check:**
For each lead, check if any signal composites have already flagged this company:
- Search Supabase signals table (if available) for the company
- Check if the company appeared in recent funding/hiring/news signal runs
- If match found: Flag as `signal_boosted` with signal type and date

**CRM/Pipeline Check:**
- Search CRM for the company in active deals
- If match found: Flag as `in_pipeline` — the outbound might conflict with an existing deal
- Search customer database: Flag as `existing_customer` for expansion plays
- Search outreach logs: Flag as `previously_contacted` with outcome

**Timing Signals:**
- Recent funding round → Good timing for budget conversations
- Recent leadership change → Potential openness to new vendors
- Recent hiring spree in relevant department → Growing team = growing need
- Recent layoffs → Bad timing, budget likely frozen
- Recent competitor mention → Awareness of the problem space

### Output
Each lead gets:
```json
{
  "signal_flags": [],
  "pipeline_status": "new | existing_customer | in_pipeline | previously_contacted",
  "pipeline_detail": "",
  "timing_signals": [],
  "timing_verdict": "good_timing | neutral | bad_timing"
}
```

---

## Step 6: Score & Tier

### Scoring Logic

Combine all dimensions into a final qualification verdict. Weights are shifted compared to inbound because there's no intent signal — fit must carry the entire decision.

**Composite Score Calculation:**

| Dimension | Weight | Possible Values |
|-----------|--------|-----------------|
| Use Case Fit | 30% | strong=100, moderate=60, weak=20, no_fit=0, unknown=30 |
| Industry | 20% | match=100, adjacent=60, mismatch=0, unknown=30 |
| Person Title/Role | 15% | exact=100, close=75, adjacent=40, mismatch=0, unknown=30 |
| Company Size | 10% | match=100, borderline=50, mismatch=0, unknown=30 |
| Person Seniority | 10% | match=100, too_junior=20, too_senior=60, unknown=30 |
| Company Stage | 5% | match=100, borderline=50, mismatch=0, unknown=30 |
| Geography | 5% | match=100, borderline=50, mismatch=0, unknown=30 |
| Reachability | 5% | highly_reachable=100, reachable=60, low=20, unreachable=0 |

**Hard overrides (bypass the score):**
- Any hard disqualifier present → `disqualified` regardless of score
- Any hard qualifier present → `qualified` regardless of score (but still show full breakdown)
- Existing customer → Route separately as expansion opportunity
- In active pipeline → Flag for sales coordination, don't disqualify

**Signal boosters (add to final score):**
- Signal-sourced lead (from funding/hiring/news composite): +5 points
- Positive timing signal: +5 points
- Multiple contact channels available: +3 points

**Signal dampeners (subtract from final score):**
- Bad timing signal (layoffs, budget freeze): -10 points
- Previously contacted, no response: -5 points
- Previously contacted, rejected: -10 points (but don't auto-disqualify — circumstances change)

**Verdict thresholds (stricter than inbound — no intent signal):**
- **Score >= 80:** `tier_1` — Strong fit, prioritize outreach
- **Score 65-79:** `tier_2` — Good fit, include in sequences
- **Score 50-64:** `tier_3` — Moderate fit, lower priority or batch outreach
- **Score 35-49:** `borderline` — Marginal fit, consider only if pipeline is thin
- **Score < 35:** `disqualified` — Does not fit ICP, do not reach out

**Sub-verdicts for routing:**
- `tier_1_signal_boosted` — Tier 1 AND has timing/signal boost → Outreach immediately
- `tier_1_standard` — Tier 1, no special signals → High-priority sequence
- `tier_2_standard` — Good fit → Standard sequence
- `tier_3_batch` — Moderate fit → Batch/automated sequence
- `borderline_hold` — Marginal → Hold for now, revisit if pipeline is thin
- `disqualified_wrong_company` — Company doesn't fit
- `disqualified_wrong_person` — Company fits but person doesn't → find the right person
- `disqualified_unreachable` — Fits but no way to contact
- `existing_customer_expansion` — Already a customer → Route to CS/AM
- `pipeline_conflict` — Already in active deal → Coordinate with deal owner

### Output
Each lead gets:
```json
{
  "composite_score": 0,
  "verdict": "",
  "sub_verdict": "",
  "outreach_priority": 1,
  "top_qualification_reasons": [],
  "top_disqualification_reasons": [],
  "summary": "One sentence: why this lead is/isn't a fit"
}
```

---

## Step 7: Output CSV

### Parallelized Qualification

Before producing the output, the actual qualification (Steps 3-6) MUST be parallelized for lists over 10 leads.

**Parallelization protocol:**
1. Run a calibration batch of 5-10 leads first, present to the user for approval
2. Once approved, split remaining leads into batches of ~15
3. Launch ALL batches simultaneously using parallel Task agents
4. Merge results preserving original row order
5. Validate completeness: qualified + disqualified + failed = total

### CSV Structure

Produce a CSV with ALL input fields preserved plus qualification columns appended:

**Core qualification columns:**
- `qualification_verdict` — tier_1 | tier_2 | tier_3 | borderline | disqualified
- `qualification_sub_verdict` — tier_1_signal_boosted | tier_1_standard | tier_2_standard | tier_3_batch | borderline_hold | disqualified_wrong_company | disqualified_wrong_person | disqualified_unreachable | existing_customer_expansion | pipeline_conflict
- `composite_score` — 0-100
- `outreach_priority` — 1 (highest) to 5 (lowest)
- `summary` — One sentence qualification reasoning

**Enrichment columns (if enrichment was run):**
- `enriched_title`, `enriched_company`, `enriched_industry`, `enriched_location`
- `enriched_headline`, `enriched_experience_years`
- `enrichment_status` — success | cached | failed | skipped

**Company qualification columns:**
- `company_size_score` — match | borderline | mismatch | unknown
- `industry_score` — match | adjacent | mismatch | unknown
- `stage_score` — match | borderline | mismatch | unknown
- `geography_score` — match | borderline | mismatch | unknown
- `use_case_score` — strong | moderate | weak | no_fit | unknown

**Person qualification columns:**
- `title_match_score` — exact_match | close_match | adjacent | mismatch | unknown
- `seniority_score` — match | too_junior | too_senior | unknown
- `authority_type` — economic_buyer | champion | user | evaluator | gatekeeper | unknown
- `reachability_score` — highly_reachable | reachable | low_reachability | unreachable
- `mismatch_type` — null | right_company_wrong_person | right_person_wrong_company

**Signal & pipeline columns:**
- `pipeline_status` — new | existing_customer | in_pipeline | previously_contacted
- `pipeline_detail` — One sentence on the overlap
- `signal_flags` — Any signal composite matches
- `timing_verdict` — good_timing | neutral | bad_timing

### Primary Output: Google Sheets via Rube MCP

Use `RUBE_SEARCH_TOOLS` to find Google Sheets tools, then:
1. Create a new sheet: `[Campaign Name] - Qualified Prospects - [Date]`
2. Write all columns with formatting:
   - Bold header row with dark background
   - Color-code verdict: green (tier 1-2), yellow (tier 3), orange (borderline), red (disqualified)
   - Color-code outreach priority: 1=green, 2=blue, 3=yellow, 4=orange, 5=red
   - Add filter row for sorting by verdict/priority
3. Create a "Summary" tab with the stats from below

### Fallback: CSV

If Rube MCP is unavailable:
1. Write CSV to `clients/<client-name>/leads/outbound-qualified-[date].csv`
2. Tell the user the file path

### Summary Report

After producing the output, present:

```markdown
## Outbound Qualification Results: [Campaign Name]

**List source:** [source type and detail]
**Total prospects processed:** X

### Qualification Breakdown
| Tier | Count | % | Action |
|------|-------|---|--------|
| Tier 1 (strong fit) | X | Y% | Priority outreach |
| Tier 2 (good fit) | X | Y% | Standard sequences |
| Tier 3 (moderate fit) | X | Y% | Batch outreach |
| Borderline | X | Y% | Hold / revisit |
| Disqualified | X | Y% | Do not contact |

### Signal & Pipeline Flags
- Signal-boosted leads: X
- Existing customers (expansion): X (route to CS)
- Already in pipeline: X (coordinate with deal owner)
- Previously contacted: X

### Top Qualification Reasons
1. [reason] — X leads
2. [reason] — X leads

### Top Disqualification Reasons
1. [reason] — X leads
2. [reason] — X leads

### Data Quality
- Fully enriched: X leads
- Partially enriched: X leads
- Enrichment failed: X leads
- Insufficient data: X leads

**Output:** [Google Sheet link or CSV path]
```

---

## Handling Edge Cases

**Large lists (500+ leads):**
- Run enrichment in batches of 50 to avoid Apify rate limits
- Parallelize qualification aggressively — use 10 concurrent batches
- Present progress updates every 100 leads

**Duplicate companies across leads:**
- Qualify the company once, apply to all leads from that company
- Person qualification runs individually
- Flag multi-threading opportunity: "4 people from [Company] in this list — consider account-based approach"

**Leads from signal composites:**
- These were already filtered by a signal (funding, hiring, news) — they have a baseline relevance
- Don't re-check the signal; trust it. Focus qualification on ICP fit
- Apply the +5 signal boost to the score

**Previously disqualified leads appearing again:**
- If a lead was disqualified in a prior run but shows up in a new list, re-qualify
- Circumstances change: new role, company grew, new funding
- Note in reasoning: "Previously disqualified on [date] for [reason]. Re-evaluated because [what changed]."

**Right company, wrong person:**
- Don't disqualify the company. Mark sub-verdict as `disqualified_wrong_person`
- Recommend: "Company [X] is a strong fit. Consider finding [target title] there instead."

**Leads with only personal email (gmail, yahoo):**
- Low reachability for outbound — personal emails are bad for cold outreach
- Still qualify on fit. If fit is strong, recommend finding work email via Apollo or similar
- Score reachability as `low_reachability`

**Conflicting data between sources:**
- Prefer enriched LinkedIn data over self-reported/scraped data
- Prefer recent data over stale data
- Note conflicts in reasoning: "LinkedIn says VP of Engineering, input says CTO — using LinkedIn (more recent)"

---

## Tools Required

- **Apify LinkedIn Enrichment** — `skills/lead-qualification/scripts/enrich_leads.py` for batch profile enrichment
  - Requires `APIFY_API_TOKEN` environment variable
  - Run with `--dry-run` first to preview cost
- **Web Search** — to research companies and fill gaps when enrichment is sparse
- **Fetch (web page)** — to pull company pages, LinkedIn profiles
- **Rube MCP** — for Google Sheets input/output
  - `RUBE_SEARCH_TOOLS` — discover available tools
  - `RUBE_MANAGE_CONNECTIONS` — ensure Google Sheets connection is active
  - `RUBE_REMOTE_WORKBENCH` — execute sheet operations
- **CRM access** — to check pipeline, existing customers, outreach history
- **Supabase client** — for pipeline/signal lookups
- **Task tool** — to parallelize lead processing across subagents (mandatory for Step 7)
- **Read/Write** — for CSV I/O and config management
- **Glob/Grep** — to find existing qualification prompt files

---

## Example Usage

### Qualify an Apollo export:
```
Qualify these prospects from Apollo: [CSV path or Google Sheet URL]
```
→ Agent loads ICP, enriches sparse records, qualifies, outputs tiered CSV.

### Qualify leads from a signal composite:
```
Take the funding signal leads from last week's run and qualify them against our ICP.
```
→ Agent loads signal output, applies signal boost, qualifies, tiers for outreach.

### Qualify event attendees:
```
Here's the attendee list from the AI conference: [CSV]. Qualify them for outreach.
```
→ Agent notes event source, enriches, qualifies with event-topic context.

### Reuse existing qualification prompt:
```
Qualify these leads using @skills/lead-qualification/qualification-prompts/series-a-saas.md
— list: [Google Sheet URL]
```
→ Skips ICP setup, goes straight to enrichment + qualification.

### Re-qualify with updated criteria:
```
Lower the company size minimum to 20 employees and add "developer tools" as a target industry.
Re-qualify the borderline leads.
```
→ Updates config, re-runs only borderline leads, re-tiers.
