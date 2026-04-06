---
name: end-to-end-funding-signal
version: 1.0.0
description: >
  Full pipeline from funding signal discovery to outreach-ready campaign.
  Scans the web for recent funding announcements (no company list needed),
  qualifies against your company context, finds decision-makers, drafts
  personalized email sequences, and packages for your outreach tool.
  Combines funding-signal-monitor and funding-signal-outreach into a
  single zero-to-campaign workflow.
tags: [lead-generation, outreach]

graph:
  provides:
    - funded-company-list          # Discovered companies with recent funding
    - qualified-funded-companies   # Companies ranked by relevance to you
    - contact-list                 # Decision-makers at qualified companies
    - personalized-email-sequences # Ready-to-send email drafts
    - campaign-package             # Outreach-tool-ready campaign
  requires:
    - your-company-context         # What you sell, who you sell to, proof points
    - target-stages                # e.g. "Series A, Series B"
  connects_to:
    - skill: cold-email-outreach
      when: "User wants to launch the campaign via Smartlead or other outreach tool"
      passes: contact-list, personalized-email-sequences
    - skill: linkedin-outreach
      when: "User wants LinkedIn outreach alongside email"
      passes: contact-list
  capabilities: [web-search, apify-search, contact-finding, email-drafting]
---

# End-to-End Funding Signal

Full pipeline from signal discovery to outreach-ready campaign in a single run. No company list required — this skill discovers recently-funded companies from scratch, qualifies them against your context, finds the right people, drafts personalized emails, and packages everything for your outreach tool.

## When to Auto-Load

Load this composite when:
- User says "find recently funded companies and reach out to them"
- User says "end-to-end funding signal", "funding pipeline", "funding outreach from scratch"
- User wants to go from zero to outreach campaign based on funding signals
- User has no existing company list but wants to target companies that just raised

Do NOT load if:
- User already has a company list → use `funding-signal-outreach` instead
- User only wants to monitor signals without outreach → use `funding-signal-monitor` instead

## Architecture

This composite chains `funding-signal-monitor` (discovery) into `funding-signal-outreach` (qualification → contacts → emails → handoff). The monitor's output feeds directly into the outreach pipeline.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    END-TO-END FUNDING SIGNAL                             │
│                                                                          │
│  ┌───────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────┐ │
│  │ DISCOVER  │──▶│ QUALIFY  │──▶│  FIND    │──▶│  DRAFT   │──▶│LAUNCH│ │
│  │ Signals   │   │ & Rank   │   │  People  │   │  Emails  │   │      │ │
│  └───────────┘   └──────────┘   └──────────┘   └──────────┘   └──────┘ │
│       │                │              │              │             │      │
│  Multi-source     Your company   Buyer personas  Signal-based   Tool-    │
│  web scan         context (LLM)  + contact tool  personalization agnostic│
│  (no input list)                                  (LLM)         export   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Step 0: Configuration (One-Time Setup)

On first run, collect and store all configuration needed for the full pipeline. Skip on subsequent runs.

### Signal Discovery Config

| Question | Options | Stored As |
|----------|---------|-----------|
| What funding stages are you targeting? | Seed, Series A, Series B, Series C, Series D+ | `target_stages` |
| Any industry filters? | SaaS, AI, fintech, healthtech, devtools, etc. (or "all") | `target_industries` |
| Minimum funding amount? | e.g. "$5M" or none | `min_amount` |
| How far back should we search? | 7 / 14 / 30 days | `lookback_days` |

### Contact Finding Config

| Question | Options | Stored As |
|----------|---------|-----------|
| How should we find contacts? | Apollo / LinkedIn Sales Nav / Clearbit / Web search / Manual | `contact_tool` |
| Do you have API access? | Yes (provide key) / No (use web search) | `contact_api_access` |

### Outreach Config

| Question | Options | Stored As |
|----------|---------|-----------|
| Where do you want outreach sent? | Smartlead / Instantly / Outreach.io / Lemlist / Apollo / CSV export | `outreach_tool` |
| Email or multi-channel? | Email only / Email + LinkedIn | `outreach_channels` |

### Your Company Context

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What does your company do? (1-2 sentences) | Qualification + email personalization | `company_description` |
| What problem do you solve? | Email hook | `pain_point` |
| Who are your ideal buyers? (titles, departments) | Contact finding filters | `buyer_personas` |
| Name 2-3 proof points (customers, metrics, results) | Email credibility | `proof_points` |
| What's your product's price range? (SMB / Mid-Market / Enterprise) | Funding stage qualification | `price_tier` |

**Store config in:** `clients/<client-name>/config/end-to-end-funding-signal.json` or equivalent.

---

## Step 1: Discover Funding Signals

**Purpose:** Scan multiple web sources for recent funding announcements matching the target criteria. No company list input needed.

This step uses the `funding-signal-monitor` skill's multi-source approach.

### Input Contract

```
target_stages: string[]           # From config: ["Series A", "Series B"]
target_industries: string[]       # From config (optional)
min_amount: string | null         # From config (optional)
lookback_days: integer            # From config (default: 7)
```

### Process

Run all source searches in parallel:

#### A) Web Search (WebSearch tool — free)

Run 4-6 varied queries:
- `"Series A announced this week 2026"`
- `"Series B funding round 2026"`
- `"startup raised Series A"`
- `"raised $" AND "Series" AND "2026"`
- `"[industry] startup funding"` (if industry filter specified)

For each result, extract: company name, amount, stage, date, lead investors.

#### B) Twitter Search (twitter-scraper — ~$0.05-0.10)

```bash
python3 skills/twitter-scraper/scripts/search_twitter.py \
  --query "\"excited to announce\" AND (\"raised\" OR \"Series A\" OR \"Series B\" OR \"funding\")" \
  --since <lookback-start> --until <today> --max-tweets 50 --output json
```

Funding announcements often break on Twitter first via founder posts.

#### C) Hacker News (funding-signal-monitor helper script — free)

```bash
python3 skills/funding-signal-monitor/scripts/search_funding.py \
  --stages "Series A,Series B" --days 7 --min-points 5 --output json
```

#### D) Reddit Search (reddit-scraper — ~$0.05-0.10)

```bash
python3 skills/reddit-scraper/scripts/search_reddit.py \
  --subreddit "startups,SaaS,technology" \
  --keywords "raised,Series A,Series B,funding round" \
  --days 7 --sort hot --output json
```

### Consolidation

1. **Deduplicate** across sources. Same company from multiple sources = higher confidence.
2. **Filter** by target stages, industries, and min amount.
3. **Score** each company:
   - +3: Appears in multiple sources
   - +2: Stage matches target exactly
   - +2: Industry matches target
   - +1: High cloud likelihood (tech/SaaS/AI)
   - +1: Announced within last 3 days
   - -1: Stage outside target range
   - -2: Non-tech industry (unless specifically targeted)
4. **Rank** by score descending.

### Output Contract

```
discovered_companies: [
  {
    name: string
    domain: string
    industry: string
    funding_amount: string
    funding_stage: string
    funding_date: string
    lead_investors: string[]
    source_urls: string[]
    sources: string[]              # ["web", "twitter", "hn", "reddit"]
    confidence: "high" | "medium"
    score: integer
    outreach_angle_hint: string    # Stage-based angle from monitor
  }
]
```

### Human Checkpoint

```
Found X companies with recent funding matching your criteria:

| Rank | Company | Amount | Stage | Date | Sources | Confidence |
|------|---------|--------|-------|------|---------|------------|
| 1    | Acme    | $15M   | A     | 2026-03-28 | web, twitter, hn | High |
| 2    | Beta    | $40M   | B     | 2026-03-25 | web | Medium |
| ...  | ...     | ...    | ...   | ...  | ...     | ...        |

Proceed to qualification? You can remove any companies before continuing.
```

---

## Step 2: Qualify & Prioritize

**Purpose:** Rank discovered companies by relevance to your product. Pure LLM reasoning — no external tools needed.

### Input Contract

```
discovered_companies: [...]       # From Step 1 output
your_company: {
  description: string
  pain_point: string
  buyer_personas: string[]
  proof_points: string[]
  price_tier: string
}
```

### Process

For each discovered company, evaluate:

| Criterion | Weight | Assessment |
|-----------|--------|------------|
| Stage fit | High | Does funding stage match your price tier? A → SMB/mid-market, C → enterprise |
| Industry relevance | High | Is their industry one where your product solves a real problem? |
| Timing urgency | Medium | <14 days = urgent. 14-30 = viable. 30+ = cooling |
| Size signal | Medium | Post-raise team size. Enough people to need your product? |
| Round size | Low | Larger rounds = more budget for tooling |

Assign priority tiers:
- **Tier 1 (Act Today):** Stage fit + industry relevance + funded within 14 days
- **Tier 2 (Act This Week):** Two of three criteria, or 15-30 days with strong fit
- **Tier 3 (Queue):** Marginal fit or 30+ days old. Worth reaching out but not urgent
- **Drop:** No relevance to your product/market

For each qualified company, generate:
- **Relevance reasoning:** 1-2 sentences on why they'd care about your product now
- **Outreach angle:** Specific hook connecting their funding to your value
- **Recommended approach:** Direct pain-point, aspirational growth, or operational efficiency

### Output Contract

```
qualified_companies: [
  {
    ...discovered_company_fields,
    priority_tier: "tier_1" | "tier_2" | "tier_3"
    relevance_reasoning: string
    outreach_angle: string
    recommended_approach: string
    estimated_team_size: string
  }
]
dropped_companies: [
  { name: string, drop_reason: string }
]
```

### Human Checkpoint

```
## Qualification Results

### Tier 1 — Act Today (X companies)
| Company | Stage | Amount | Angle | Why |
|---------|-------|--------|-------|-----|

### Tier 2 — Act This Week (X companies)
| Company | Stage | Amount | Angle | Why |
|---------|-------|--------|-------|-----|

### Tier 3 — Queue (X companies)
| Company | Stage | Amount | Angle | Why |
|---------|-------|--------|-------|-----|

### Dropped (X companies)
| Company | Reason |
|---------|--------|

Approve before we find contacts? You can promote, demote, or drop any company.
```

---

## Step 3: Find Decision-Makers

**Purpose:** For each qualified company, find people matching your buyer personas.

### Input Contract

```
qualified_companies: [...]        # From Step 2 output
buyer_personas: [
  {
    title_patterns: string[]
    department: string
    seniority: string
    role_type: "buyer" | "champion" | "user"
  }
]
contact_tool: string              # From config
max_contacts_per_company: integer # Default: 3-5
```

### Process

For each qualified company, use the configured `contact_tool`:

1. **Search** for people matching buyer personas (title/seniority filters)
2. **Collect** per person: full name, title, email, LinkedIn URL, role type
3. **Prioritize:** Buyers → Champions → Users
4. **Cap** at max_contacts_per_company (3-5)
5. **Deduplicate** against `contact-cache` to avoid repeat outreach across runs

### Output Contract

```
contacts: [
  {
    person: {
      full_name: string
      first_name: string
      last_name: string
      title: string
      email: string | null
      linkedin_url: string | null
      role_type: "buyer" | "champion" | "user"
    }
    company: {
      name: string
      domain: string
      funding_amount: string
      funding_stage: string
      funding_date: string
      priority_tier: string
      outreach_angle: string
      relevance_reasoning: string
    }
  }
]
contacts_without_email: [...]     # Same structure, flagged for manual lookup
```

### Human Checkpoint

```
## Contacts Found

### Acme Corp (Tier 1 — Series A, $15M)
| Name | Title | Role | Email | LinkedIn |
|------|-------|------|-------|----------|

### Beta Inc (Tier 2 — Series B, $40M)
| Name | Title | Role | Email | LinkedIn |
|------|-------|------|-------|----------|

Total: X contacts across Y companies (Z without email)

Approve before we draft emails?
```

---

## Step 4: Draft Personalized Emails

**Purpose:** For each contact, draft a personalized email sequence connecting the funding signal to your product's value. Pure LLM reasoning.

### Input Contract

```
contacts: [...]                   # From Step 3 output
your_company: {
  description: string
  pain_point: string
  proof_points: string[]
}
sequence_config: {
  touches: integer                # Default: 3
  timing: integer[]               # Default: [1, 5, 12] (days)
  personalization_tier: 1 | 2 | 3 # Default: 2
  tone: string                    # Default: "casual-direct"
  cta: string                     # Default: "15-min call"
}
```

### Process

1. **Select framework:** Funding signal → **Signal-Proof-Ask** (reference raise, show proof, soft ask). If funding is for the exact problem you solve → **BAB** (before/after).

2. **Build personalization context per contact:**

   | Field | Source |
   |-------|--------|
   | Signal reference | Step 1 — "Congratulations on the $15M Series A" |
   | Company context | Step 2 — "As you scale post-raise..." |
   | Role-specific pain | Step 3 role_type — Buyer→budget, Champion→friction, User→workflow |
   | Proof point | Config — "Companies like [peer] use us to..." |
   | Outreach angle | Step 2 — "Scale fast with fresh capital" |

3. **Generate emails per `email-drafting` skill rules:**
   - Touch 1: 50-90 words. Hook with funding signal + proof + soft CTA
   - Touch 2: 30-50 words. New angle (different proof point or asset offer)
   - Touch 3: 20-40 words. Social proof drop or breakup
   - All hard rules apply: no filler, no "just checking in", one CTA per email

4. **By personalization tier:**
   - Tier 1: One template per touch with merge fields
   - Tier 2: One template per (role_type + priority_tier) combination
   - Tier 3: Unique email per contact

### Output Contract

```
email_sequences: [
  {
    contact: { full_name, email, company_name, priority_tier, ... }
    sequence: [
      {
        touch_number: integer
        send_day: integer
        subject: string
        body: string
        framework: string
        word_count: integer
      }
    ]
  }
]
```

### Human Checkpoint

Present 3-5 sample sequences (one per tier/role combination):

```
## Sample Emails for Review

### Jane Doe, VP Sales @ Acme Corp (Tier 1, Series A $15M)

**Touch 1 — Day 1**
Subject: Before the Series A hiring sprint
> [full email]

**Touch 2 — Day 5**
Subject: How [peer company] handled post-raise scaling
> [full email]

**Touch 3 — Day 12**
Subject: One last thought
> [full email]

Approve these samples? I'll generate the rest in the same style.
Iterate? Tell me what to change (tone, length, angle, CTA).
```

---

## Step 5: Launch Campaign

**Purpose:** Package contacts + email sequences for the configured outreach tool.

### Input Contract

```
email_sequences: [...]            # From Step 4 output
outreach_tool: string             # From config
outreach_channels: string         # From config
```

### Process

| Tool | Action |
|------|--------|
| **Smartlead** | Chain to `cold-email-outreach` Smartlead MCP automation |
| **Instantly** | Generate Instantly-format CSV |
| **Outreach.io** | Generate Outreach-compatible CSV |
| **Lemlist** | Generate Lemlist-format CSV |
| **Apollo** | Generate Apollo sequence import CSV |
| **CSV export** | Generate generic CSV with all fields |

If `outreach_channels` includes LinkedIn:
- Chain to `linkedin-outreach` for LinkedIn message sequences
- Output CSV for LinkedIn automation tool

### Output Contract

```
campaign_package: {
  tool: string
  file_path: string
  contact_count: integer
  sequence_touches: integer
  estimated_send_days: integer
  next_action: string
}
```

### Human Checkpoint

```
## Campaign Ready

Tool: [configured tool]
Contacts: X people across Y companies
Sequence: 3 touches over 12 days
Tier breakdown: Z Tier 1, W Tier 2, V Tier 3
File: output/{campaign-name}-{date}.csv

Ready to launch? (Final gate before emails are sent or files are created)
```

---

## Execution Summary

| Step | What | Tool | Checkpoint | Time |
|------|------|------|------------|------|
| 0 | Config | None | First run only | 5 min (once) |
| 1 | Discover signals | WebSearch + Twitter + HN + Reddit | Review discovered companies | 3-5 min |
| 2 | Qualify & rank | LLM reasoning | Approve tier rankings | 2-3 min |
| 3 | Find people | Configurable (Apollo, LinkedIn, etc.) | Approve contact list | 2-3 min |
| 4 | Draft emails | LLM reasoning | Review samples, iterate | 5-10 min |
| 5 | Launch | Configurable (Smartlead, CSV, etc.) | Final approval | 1 min |

**Total: ~15-25 minutes** from "find me funded companies to reach out to" to outreach-ready campaign.

## Cost

| Component | Cost |
|-----------|------|
| Web Search | Free |
| Hacker News (Algolia) | Free |
| Twitter scraper (Apify) | ~$0.05-0.10 |
| Reddit scraper (Apify) | ~$0.05-0.10 |
| Contact finding (varies by tool) | $0-0.50 |

**Typical run:** $0.10-0.70 total depending on contact tool.

## Tips

- **Run weekly** — funding signals have a 1-3 week outreach window before vendor flood
- **Tier 1 contacts within 48 hours** of funding announcement for maximum impact
- **3-5 contacts per company** is the sweet spot to avoid carpet-bombing
- **Multi-source appearances are the strongest signal** — a company on TechCrunch + HN + Twitter is higher quality
- **Don't mention the funding amount** in emails unless public and impressive. Focus on what the funding means for them
- **Track contacts in `contact-cache`** to avoid duplicate outreach across weekly runs
- **Web Search is your best discovery source** — Twitter and HN provide supplementary early signals

## Example Prompt

> "Find companies that raised Series A or B in the last week. We sell developer tools for API monitoring. Our buyers are VP Engineering and CTOs. Target SaaS and AI companies. Use web search for contacts and export to CSV."

The agent should run the full pipeline: discover → qualify → find contacts → draft emails → export CSV.
