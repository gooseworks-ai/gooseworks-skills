---
name: landing-page-intel-extractor
description: >
  Extract competitor and customer intelligence from any company's landing page HTML.
  Fetches a target URL, parses the full HTML, and surfaces structured signals: named
  competitors, positioning claims, comparison pages, customer logos, testimonials,
  case studies, industries served, pricing model, integrations, and social proof.
  Produces a single intelligence brief ready for sales, marketing, or competitive strategy.
tags: [competitive-intel, research]
graph:
  provides: [competitor-list, customer-logos, testimonials, positioning-claims, pricing-signals, integration-list]
  requires: [target-url]
  connects_to:
    - skill: battlecard-generator
      when: "Competitor names have been extracted and you need battlecards"
      passes: "competitor-list, positioning-claims"
    - skill: icp-website-audit
      when: "You want to evaluate the site through ICP personas"
      passes: "target-url, competitor-list"
    - skill: competitor-ad-teardown
      when: "You want to see what ads a discovered competitor is running"
      passes: "competitor domains from competitor-list"
---

# Landing Page Intel Extractor

Turn any company's landing page into a structured intelligence brief. Fetches the HTML, extracts every competitive and customer signal on the page, and delivers a clean report you can hand to sales, marketing, or product.

**Core principle:** A company's landing page is a public declaration of strategy. The customers they showcase, the competitors they reference (or carefully avoid), the language they use, and the proof points they lead with — all of it is signal. This skill reads that signal systematically.

## When to Use

- "What can we learn about [company] from their website?"
- "Pull competitor and customer intel from [url]"
- "Who does [company] sell to? Who do they compete with?"
- "Extract intelligence from this landing page: [url]"
- "Scrape [company]'s site for competitive signals"
- Before a sales call — quickly understand a prospect's positioning
- Building a competitive landscape — extract intel from multiple sites

## Quick Start

```
Extract competitor and customer intelligence from https://example.com
```

Multiple pages:
```
Extract landing page intel from these URLs:
- https://example.com
- https://example.com/customers
- https://example.com/pricing
```

With comparison:
```
Extract intel from https://company-a.com and https://company-b.com, then compare their positioning.
```

## Inputs

| Input | Required | Source |
|-------|----------|--------|
| **Target URL(s)** | Yes | User provides |
| **Company name** | Optional | Inferred from page if not provided |
| **Specific focus** | Optional | e.g., "just competitors" or "just customers" |
| **Client context** | Optional | `clients/<client>/context.md` for framing |

## Step-by-Step Process

### Phase 1: Page Acquisition

Fetch the target URL(s) using WebFetch.

**Primary page** — always fetch:
```
WebFetch: [target_url]
```

**Discovery pages** — attempt to fetch these additional paths if they exist (non-blocking; skip 404s):
- `/customers` or `/case-studies`
- `/pricing`
- `/integrations` or `/partners`
- `/about`
- `/vs/` or `/compare/` or `/alternatives/`

These secondary pages often contain the richest competitive and customer signals. Check the primary page's navigation/footer for links to these sections first, then fetch the ones that exist.

### Phase 2: HTML Signal Extraction

Parse each fetched page and extract the following signal categories. Be thorough — look in headings, body text, image alt text, meta tags, schema markup, footer, and navigation.

#### 2A: Competitor Signals

| Signal | Where to Look |
|--------|--------------|
| **Named competitors** | Comparison pages (`/vs/`, `/alternatives/`), body text ("unlike [X]", "switch from [X]"), meta descriptions, alt text |
| **Implicit competitors** | Category claims ("the leading...", "#1 in..."), feature comparison tables without names, "why switch" sections |
| **Positioning against** | "Unlike other [category] tools", "not just another [X]", differentiation claims |
| **Comparison pages** | Any `/vs/[competitor]` or `/compare/` or `/alternatives/` URLs found in navigation or links |
| **Migration/switch content** | "Switch from [X]", "migrate from [X]", import tools mentioned |

#### 2B: Customer Signals

| Signal | Where to Look |
|--------|--------------|
| **Customer logos** | Logo bars/grids (img alt text, aria-labels, filenames), "trusted by" sections |
| **Testimonials** | Quote blocks, review widgets, named endorsements with title/company |
| **Case studies** | Links to `/case-studies/`, `/customers/[name]`, specific metrics ("increased X by Y%") |
| **Industries served** | Industry pages, solution verticals, "for [industry]" sections |
| **Company sizes** | "Enterprise", "SMB", "startup" language, pricing tier naming, seat-based pricing thresholds |
| **Named customers** | Mentioned anywhere in text, case studies, press mentions |

#### 2C: Positioning & Messaging Signals

| Signal | Where to Look |
|--------|--------------|
| **Hero headline** | H1 tag, hero section |
| **Value proposition** | Subheadline, first paragraph |
| **Category claim** | How they define their market category |
| **Key differentiators** | Feature highlights, "why us" section, unique claims |
| **Proof metrics** | Numbers in hero/social proof ("10,000+ teams", "99.9% uptime", "50M events/day") |
| **Awards/recognition** | G2 badges, analyst mentions, "leader in [report]" |

#### 2D: Product & GTM Signals

| Signal | Where to Look |
|--------|--------------|
| **Pricing model** | Pricing page, CTA language (free trial vs. demo vs. contact sales) |
| **Pricing tiers** | Tier names, feature gates, price points if visible |
| **Primary CTA** | Hero button — reveals their conversion strategy (PLG vs. sales-led) |
| **Secondary CTAs** | Other conversion paths offered |
| **Integrations** | Integration pages, "connects with" sections, partner logos |
| **Platform/tech signals** | API mentions, SDK references, infrastructure claims |
| **Security/compliance** | SOC2, HIPAA, GDPR badges or claims |

### Phase 3: Enrichment (Optional)

If the user wants deeper context, use WebSearch to:

1. **Verify competitor relationships** — search `"[company] vs [competitor]"` to confirm competitive dynamics
2. **Identify unlisted competitors** — search `"[company] alternatives"` or `"[company] competitors"`
3. **Validate customer claims** — search `"[customer] + [company]"` for case studies or press mentions
4. **Check recent news** — funding, pivots, rebrand, leadership changes that add context

Only do this if the user asks for "deep" analysis or specifies enrichment. By default, stick to what's on the page.

### Phase 4: Intelligence Report

Compile all extracted signals into the structured output below.

---

## Output

Save to `clients/<client-name>/intel/landing-page-intel-[company]-[YYYY-MM-DD].md`

If no client context, output directly.

### Report Template

```markdown
# Landing Page Intelligence: [Company Name]

**URL:** [primary url]
**Extracted:** [date]
**Pages analyzed:** [list of URLs fetched]

---

## Executive Summary

[3-5 sentences. What does this company do, who do they sell to, who do they compete with, and what's their core positioning bet? Note anything surprising or notable.]

---

## Competitor Intelligence

### Named Competitors

| Competitor | How Referenced | Where Found | Context |
|-----------|---------------|-------------|---------|
| [Name] | [Comparison page / "switch from" / body mention] | [URL + section] | [Quote or context] |

### Comparison Pages Found

| URL | Competitor | Positioning Angle |
|-----|-----------|------------------|
| [/vs/competitor] | [Name] | [How they position against them] |

### Implicit Competitive Positioning

- **Category claim:** "[Exact claim from page]"
- **Differentiation language:** [How they describe what makes them different]
- **"Not" positioning:** [What they explicitly say they are NOT — often reveals who they compete with]

### Competitive Landscape Summary

[2-3 sentences. Who are the main competitors based on page signals? Where does this company position itself in the market? Any competitors conspicuously absent?]

---

## Customer Intelligence

### Customer Logos Identified

| Customer | Source | Section |
|----------|--------|---------|
| [Company name from logo/alt text] | [URL] | [e.g., "Trusted by" bar, case study] |

### Testimonials

| Quote | Person | Title | Company |
|-------|--------|-------|---------|
| "[Quote]" | [Name] | [Title] | [Company] |

### Case Studies

| Customer | Headline/Metric | URL |
|----------|----------------|-----|
| [Name] | "[Metric or headline]" | [Link if available] |

### Industries & Segments

| Industry/Vertical | Evidence |
|-------------------|----------|
| [Industry] | [Page section, solution page, case study] |

### Target Company Profile

- **Company sizes:** [Enterprise / Mid-market / SMB / Startup — based on language, pricing, logos]
- **Buyer persona signals:** [Titles mentioned, "for [role]" language, use-case framing]
- **Geographic signals:** [Languages offered, regional pricing, office locations]

---

## Positioning & Messaging

### Core Messaging

| Element | Extracted Text |
|---------|---------------|
| **Hero headline** | "[Exact text]" |
| **Subheadline** | "[Exact text]" |
| **Category** | [How they define their category] |
| **Primary CTA** | "[Button text]" → [Action: demo/trial/signup] |

### Key Differentiators Claimed

1. [Differentiator] — "[Supporting text from page]"
2. [Differentiator] — "[Supporting text from page]"
3. [Differentiator] — "[Supporting text from page]"

### Social Proof Metrics

| Metric | Value | Where |
|--------|-------|-------|
| [Type: customers, users, events, uptime] | [Number] | [Section] |

### Trust Signals

- **Awards/recognition:** [G2, analyst reports, awards]
- **Security/compliance:** [SOC2, HIPAA, GDPR, etc.]
- **Partnerships:** [Named partners, certified integrations]

---

## Product & GTM Signals

### Pricing Model

- **Model type:** [Free / Freemium / Free trial / Contact sales / Usage-based / Seat-based]
- **Visible pricing:** [Yes/No — if yes, summarize tiers]
- **PLG vs Sales-led:** [Based on CTA strategy and pricing visibility]

### Integrations Discovered

| Integration | Category |
|-------------|----------|
| [Name] | [CRM / Analytics / Communication / etc.] |

### Technology Signals

[API availability, SDK mentions, platform claims, infrastructure details]

---

## Key Takeaways

### For Sales

- [Insight relevant to selling against or to this company]
- [Key objection or positioning to be aware of]

### For Marketing

- [Messaging angle opportunity]
- [Competitive positioning gap]

### For Product

- [Feature or integration signal]
- [Market direction implied by their roadmap/positioning]

---

## Raw Signals Log

[Optional — full list of every extracted signal with source URL and page location, for audit purposes]
```

---

## Multiple URL Mode

When given multiple URLs (e.g., a company's homepage + customers page + pricing):

1. Fetch all pages in parallel
2. Deduplicate signals across pages
3. Note which page each signal came from
4. Produce a single consolidated report

## Comparison Mode

When given two or more company URLs:

1. Run the full extraction for each company
2. Add a **Comparison** section at the end:

```markdown
## Head-to-Head Comparison

| Dimension | [Company A] | [Company B] |
|-----------|:-----------:|:-----------:|
| Category claim | [claim] | [claim] |
| Primary CTA | [CTA] | [CTA] |
| Customer count signal | [metric] | [metric] |
| Named customers | [count] | [count] |
| Competitors referenced | [list] | [list] |
| Pricing model | [model] | [model] |
| Key differentiator | [claim] | [claim] |

### Positioning Overlap
[Where they compete directly — same claims, same customers, same language]

### Positioning Gaps
[Where one has signals the other doesn't — potential opportunities]
```

## Cost

Free — no paid APIs. All extraction is done via WebFetch and optional WebSearch.

| Component | Cost |
|-----------|------|
| WebFetch (page retrieval) | Free |
| WebSearch (enrichment, optional) | Free |
| Analysis | Free (LLM reasoning) |
| **Total** | **Free** |

## Tools Required

- **WebFetch** — for retrieving page HTML
- **WebSearch** — for optional enrichment (competitor verification, customer validation)
- No API keys or paid tools required

## Tips

- **Start with the homepage, then expand.** The homepage gives you positioning and social proof. Add `/customers`, `/pricing`, and `/vs/` pages for richer data.
- **Check comparison pages first.** If a company has `/vs/` or `/alternatives/` pages, those are goldmines for competitive intel. The primary page nav or footer usually links to them.
- **Logo bars are noisy.** Not every logo is a current customer — some are "compatible with" or "integrates with." Look at the section heading for context.
- **Alt text is your friend.** Customer logos often have company names in `alt` attributes or filenames even when not visible as text.
- **Run on competitors too.** Extract intel from your competitor's site to see who *they* sell to and compete with. The overlap (or lack thereof) is valuable signal.
- **Pair with battlecard-generator.** Once you have the competitor list, feed it into `battlecard-generator` for full competitive battlecards.
- **Pair with icp-website-audit.** Use the extracted customer/industry signals to inform persona building, then audit the site through those personas.
- **Refresh quarterly.** Landing pages change. Run this periodically to catch positioning shifts, new competitors, and customer additions.
