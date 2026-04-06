---
name: tam-builder
description: >
  End-to-end Total Addressable Market builder. Defines ICP segments, generates Apollo
  search config, discovers and scores companies via TAM Builder, enriches Tier 1-2
  companies with website and contact intel, and produces a comprehensive TAM report
  with market sizing, segmentation, and prioritized target list. The complete
  "who should we sell to and how big is the opportunity?" workflow.
tags: [lead-generation, research]
---

# TAM Builder

The complete "who should we sell to and how big is the opportunity?" workflow. Chains ICP identification, Apollo-powered company discovery, ICP scoring, company enrichment, and persona watchlist into a single end-to-end TAM build.

## Quick Start

```
Build a TAM for [company]. We sell [product] to [target]. Focus on [geo/industry/size].
```

With existing ICP:
```
Build a TAM for [client]. ICP is already defined. Use config at skills/capabilities/tam-builder/configs/[client].json.
```

Refresh existing TAM:
```
Refresh the TAM for [client]. Re-score, find new companies, deprecate stale ones.
```

## Inputs

| Input | Required | Source |
|-------|----------|--------|
| **Company name** | Yes | User provides |
| **Product/service description** | Yes | User provides or `clients/<client>/context.md` |
| **Target market description** | Yes | User provides (industries, geos, company size) |
| **Client context file** | Optional | `clients/<client>/context.md` |
| **Existing TAM config** | Optional | `skills/capabilities/tam-builder/configs/<client>.json` |
| **Existing ICP definition** | Optional | `clients/<client>/icp/` |

## Step-by-Step Process

### Phase 1: Context & ICP Definition

**Check if ICP already exists:**

```
clients/<client>/icp/
```

**If ICP exists:** Load it, confirm segments look current, summarize for the user. Skip to Phase 2.

**If no ICP exists:** Run `icp-identification`:

1. Research the company — product, pricing, customers, positioning
2. Analyze existing customers (from reviews, case studies, testimonials)
3. Identify 3-5 ICP segments with firmographic criteria:
   - Industry verticals
   - Company size (employee count ranges)
   - Geography
   - Funding stage / company maturity
   - Tech stack signals
   - Pain points / use cases
4. Rank segments by estimated market size and fit

**Output from this phase:**
- `clients/<client>/icp/segments.md` — ICP segment definitions with firmographics
- Clear target criteria for Apollo search configuration

### Phase 2: TAM Config Generation

Translate ICP segments into a TAM Builder config file.

1. **Map ICP segments to Apollo filters:**
   - Employee count ranges → `organization_num_employees_ranges`
   - Industry verticals → `q_organization_keyword_tags`
   - Geography → `organization_locations`

2. **Set scoring weights** based on ICP priorities:
   - Which dimensions matter most for this company's ICP?
   - Default weights: employee_count_fit (30), industry_fit (25), funding_stage_fit (20), geo_fit (15), keyword_match (10)
   - Adjust if certain dimensions are more important (e.g., industry-specific product → boost industry_fit)

3. **Configure tier thresholds:**
   - Tier 1 (≥75): Best-fit companies, highest priority
   - Tier 2 (≥50): Good-fit companies, worth pursuing
   - Tier 3 (<50): Marginal fit, monitor only

4. **Set watchlist personas** based on buyer personas:
   - Map ICP buyer titles to `person_titles`
   - Set appropriate seniority levels
   - Configure `personas_per_company` (default: 3)

5. **Present config to user for review** before proceeding.

**Output from this phase:**
- `skills/capabilities/tam-builder/configs/<client>.json` — ready-to-use TAM config

### Phase 3: TAM Discovery & Scoring

Run the TAM Builder capability skill through its safe pipeline.

**Step 3a: Preview (estimate size)**
```bash
python3 skills/capabilities/tam-builder/scripts/tam_builder.py \
  --config skills/capabilities/tam-builder/configs/<client>.json \
  --mode build --preview
```
Shows total company count and cost estimate. No database writes.

**Step 3b: Sample (validate scoring)**
```bash
python3 skills/capabilities/tam-builder/scripts/tam_builder.py \
  --config skills/capabilities/tam-builder/configs/<client>.json \
  --mode build --sample --test
```
Searches 1 page (~100 companies), scores in-memory, shows tier distribution and top companies. **No database writes.** Present results to user.

**Step 3c: Review with user**
- Show tier distribution (how many Tier 1 / 2 / 3)
- Show example Tier 1 companies — do they look right?
- Show example Tier 2 companies — reasonable?
- If scoring looks off → adjust config weights/thresholds and re-sample
- **Get explicit user approval before proceeding to full build**

**Step 3d: Full build (after approval)**
```bash
python3 skills/capabilities/tam-builder/scripts/tam_builder.py \
  --config skills/capabilities/tam-builder/configs/<client>.json \
  --mode build
```
Full Apollo search → upsert to Supabase → score → tier → persona watchlist.

**Output from this phase:**
- Companies upserted to Supabase `companies` table with ICP scores and tiers
- Personas upserted to Supabase `people` table for Tier 1-2 companies
- Console output with tier distribution and summary stats

### Phase 4: Tier 1 Enrichment

Enrich Tier 1 companies with additional intelligence. Run these in parallel:

**4a: Website Intel** — Run `landing-page-intel` for each Tier 1 company:
- Value proposition and positioning
- Target audience signals
- Product/feature highlights
- Pricing model
- Social proof and customer logos

**4b: Contact Discovery** — Run `company-contact-finder` for Tier 1 companies missing key personas:
- Find decision-makers matching ICP buyer titles
- Verify contact data
- Fill gaps in watchlist coverage

**Output from this phase:**
- `clients/<client>/tam/enrichment/<company-slug>.md` — per-company intel briefs
- Updated contact data in Supabase

### Phase 5: TAM Report

Synthesize all findings into a comprehensive TAM report.

1. **Pull TAM status** from Supabase:
```bash
python3 skills/capabilities/tam-builder/scripts/tam_builder.py \
  --config skills/capabilities/tam-builder/configs/<client>.json \
  --mode status
```

2. **Compile market sizing:**
   - Total companies discovered (TAM universe)
   - Tier 1 count and estimated revenue opportunity
   - Tier 2 count and estimated revenue opportunity
   - Market concentration analysis

3. **Build segmentation view:**
   - Companies by industry vertical
   - Companies by size band
   - Companies by geography
   - Cross-segment analysis

4. **Prioritized target list:**
   - Top 20 Tier 1 companies with enrichment highlights
   - Key contacts per company
   - Recommended approach angle per company

5. **Generate report.**

---

## Output

Save to `clients/<client>/tam/tam-report.md`

Also save sub-outputs:
- `clients/<client>/icp/segments.md` (ICP definition, reusable)
- `skills/capabilities/tam-builder/configs/<client>.json` (TAM config, reusable)
- `clients/<client>/tam/enrichment/` (per-company intel briefs)

### TAM Report Template

```markdown
# Total Addressable Market: [Company Name]

**Date:** [Date]
**Product:** [Product/service]
**Target market:** [Summary of ICP]
**Config:** `skills/capabilities/tam-builder/configs/<client>.json`

---

## Executive Summary

[5-7 sentences. How big is the market? How many high-fit companies exist? What's the
estimated revenue opportunity? Key segments and where the biggest concentrations are.
Top 3 insights and recommended next steps.]

---

## Market Sizing

### TAM Universe

| Metric | Count |
|--------|------:|
| Total companies discovered | [N] |
| Tier 1 (score ≥75) | [N] |
| Tier 2 (score ≥50) | [N] |
| Tier 3 (score <50) | [N] |
| Contacts identified | [N] |

### Revenue Opportunity Estimate

| Tier | Companies | Est. ACV | Est. Total Opportunity |
|------|----------:|----------:|-----------------------:|
| Tier 1 | [N] | $[X] | $[X] |
| Tier 2 | [N] | $[X] | $[X] |
| **Total addressable** | **[N]** | | **$[X]** |

*ACV estimate based on [product pricing / user-provided ACV].*

---

## Market Segmentation

### By Industry

| Industry | Tier 1 | Tier 2 | Total | % of TAM |
|----------|-------:|-------:|------:|---------:|
| [Industry] | [N] | [N] | [N] | [X%] |
| ... | | | | |

### By Company Size

| Employee Range | Tier 1 | Tier 2 | Total | % of TAM |
|----------------|-------:|-------:|------:|---------:|
| [Range] | [N] | [N] | [N] | [X%] |
| ... | | | | |

### By Geography

| Location | Tier 1 | Tier 2 | Total | % of TAM |
|----------|-------:|-------:|------:|---------:|
| [Geo] | [N] | [N] | [N] | [X%] |
| ... | | | | |

### Segment Insights

[2-3 paragraphs on where the market is concentrated, underserved segments,
and where the best opportunities cluster.]

---

## ICP Segments Used

| # | Segment | Description | Companies Found |
|---|---------|-------------|----------------:|
| 1 | [Name] | [One line] | [N] |
| 2 | [Name] | [One line] | [N] |
| ... | | | |

---

## Top 20 Target Companies (Tier 1)

| Rank | Company | Industry | Size | Score | Key Contact | Angle |
|-----:|---------|----------|-----:|------:|-------------|-------|
| 1 | [Name] | [Industry] | [N] | [Score] | [Name, Title] | [One-line approach] |
| 2 | ... | | | | | |
| ... | | | | | | |

### Company Highlights

For each Top 10 company, include:
- **[Company Name]** (Score: [X]) — [One sentence on what they do]. [Key insight from enrichment — positioning, pain point, or opportunity angle]. Contact: [Name, Title].

---

## Tier 2 Watchlist

| Company | Industry | Size | Score | Notes |
|---------|----------|-----:|------:|-------|
| [Name] | [Industry] | [N] | [Score] | [Why they're borderline / what would promote them] |
| ... | | | | |

---

## Recommended Next Steps

1. **[Action]** — [Why, expected impact]
2. **[Action]** — [Why, expected impact]
3. **[Action]** — [Why, expected impact]

---

## Appendix

### A. ICP Definition
→ `clients/<client>/icp/segments.md`

### B. TAM Config
→ `skills/capabilities/tam-builder/configs/<client>.json`

### C. Company Enrichment Briefs
→ `clients/<client>/tam/enrichment/`

### D. Scoring Methodology
- Employee count fit: [weight]%
- Industry fit: [weight]%
- Funding stage fit: [weight]%
- Geo fit: [weight]%
- Keyword match: [weight]%
- Tier 1 threshold: ≥[X], Tier 2 threshold: ≥[X]
```

---

## Parallelization

```
Phase 1: ICP Definition (if needed)
    ↓
Phase 2: Config Generation
    ↓
Phase 3: TAM Discovery (preview → sample → review → build)
    ↓
Phase 4: Enrichment (all Tier 1 companies in parallel)
    ↓
Phase 5: Report
```

If ICP and config already exist:
```
Phase 3: TAM Discovery → Phase 4: Enrichment → Phase 5: Report
```

Refresh mode (existing TAM):
```
Phase 3: TAM Refresh → Phase 4: Enrich new/promoted companies → Phase 5: Updated Report
```

## Tips

- **Always start with `--sample --test`.** Never go straight to a full build. The sample validates your config and scoring before committing to API calls and database writes.
- **Iterate on the config before building.** If sample results don't look right, adjust keyword tags, employee ranges, or scoring weights. Each sample costs almost nothing.
- **ACV estimate makes the report actionable.** Even a rough ACV turns "500 Tier 1 companies" into "$25M addressable opportunity." Ask the user for their ACV if not in context.
- **Enrichment is optional but high-value.** Skip Phase 4 for a quick TAM sizing. Run it when you need actionable target lists with approach angles.
- **Refresh quarterly.** Companies grow, raise funding, enter/exit your TAM. Use refresh mode to keep the TAM current without rebuilding from scratch.
- **Combine with outreach skills.** After building the TAM, use `setup-outreach-campaign` or `cold-email-outreach` to act on the Tier 1 list.
- **Multiple configs per client.** Create separate configs for different segments (e.g., `enterprise-fintech.json`, `midmarket-saas.json`) to build segment-specific TAMs.

## Dependencies

- Skills: `icp-identification`, `tam-builder` (capability), `landing-page-intel`, `company-contact-finder`
- Apollo API key (for company/people search)
- Supabase project (for TAM storage)
- Web search capability (for ICP research and enrichment)

## Cost

- Apollo API: Free tier covers company search and people search. Paid plans needed for high-volume builds (>5,000 companies).
- All other research uses free web search and web fetch.
