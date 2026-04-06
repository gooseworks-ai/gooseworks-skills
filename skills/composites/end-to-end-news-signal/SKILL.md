---
name: end-to-end-news-signal
version: 1.0.0
description: >
  Full pipeline from news signal discovery to outreach-ready campaign.
  Scans the web for recent news events — regulation changes, acquisitions,
  product launches, market shifts, crises, partnerships, earnings, and any
  other public event — qualifies affected companies against your ICP, identifies
  the connection between the news and your product, finds decision-makers,
  drafts personalized email sequences using the news as the hook, and packages
  for your outreach tool. Combines multi-source signal discovery with
  news-signal-outreach into a single zero-to-campaign workflow. No company
  list required.
tags: [lead-generation, outreach]

graph:
  provides:
    - discovered-news-signals         # News events with affected companies
    - icp-qualified-targets           # Companies/people from the news that fit ICP
    - connection-angles               # How the news connects to your product
    - contact-list                    # Decision-makers at qualified companies
    - personalized-email-sequences    # Outreach drafts using the news as the hook
    - campaign-package                # Outreach-tool-ready campaign
  requires:
    - your-company-context            # What you sell, who you sell to, proof points
    - target-news-categories          # e.g. "regulation", "acquisition", "product launch"
  connects_to:
    - skill: cold-email-outreach
      when: "User wants to launch the campaign via Smartlead or other outreach tool"
      passes: contact-list, personalized-email-sequences
    - skill: linkedin-outreach
      when: "User wants LinkedIn outreach alongside email"
      passes: contact-list
  capabilities: [web-search, apify-search, contact-finding, email-drafting]
---

# End-to-End News Signal

Full pipeline from news signal discovery to outreach-ready campaign in a single run. No company list required — this skill discovers relevant news events from scratch across multiple sources, extracts affected companies, qualifies them against your ICP, identifies the connection between the news and your product, finds the right people, drafts personalized emails using the news as the hook, and packages everything for your outreach tool.

This is the broadest end-to-end signal composite. While funding, hiring, and leadership change composites handle specific, predictable signal types, this one handles the long tail — regulation changes, acquisitions, product launches, market shifts, crises, partnerships, earnings events, and any other public event that creates a reason to reach out.

## When to Auto-Load

Load this composite when:
- User says "find news I can use for outreach", "news-based prospecting", "end-to-end news signal"
- User says "scan for news in [industry] and reach out to affected companies"
- User wants to go from zero to outreach campaign based on recent news events
- User has no existing company list but wants to find companies affected by recent events
- User mentions a news category (regulation, acquisition, market shift) and wants outreach built around it
- User says "find companies affected by [event/trend] and reach out"

Do NOT load if:
- User already has a specific news item or URL → use `news-signal-outreach` instead
- User already has a company list and wants news angles → use `news-signal-outreach` (Mode B)
- The signal is specifically funding → use `end-to-end-funding-signal`
- The signal is specifically hiring → use `end-to-end-hiring-signal`
- The signal is specifically a leadership change → use `end-to-end-leadership-change-signal`

## Architecture

This composite chains multi-source signal discovery into `news-signal-outreach` (qualification → connection angle → contacts → emails → handoff). The discovery layer's output feeds directly into the outreach pipeline.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                        END-TO-END NEWS SIGNAL                                    │
│                                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐  ┌────────┐  │
│  │ DISCOVER │─▶│ EXTRACT  │─▶│ QUALIFY  │─▶│  FIND    │─▶│DRAFT │─▶│ LAUNCH │  │
│  │ Signals  │  │ & Angle  │  │ & Rank   │  │ People   │  │Emails│  │        │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────┘  └────────┘  │
│       │              │             │              │            │          │       │
│  Multi-source   Parse news,   ICP filter +   Buyer        News-as-    Tool-     │
│  web scan       ID connection  prioritize    personas +    hook email  agnostic  │
│  (no input      angle          by strength   contact tool  sequences   export    │
│   list)                                                                          │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Step 0: Configuration (One-Time Setup)

On first run, collect and store all configuration needed for the full pipeline. Skip on subsequent runs.

### News Discovery Config

| Question | Options | Stored As |
|----------|---------|-----------|
| What news categories are most relevant to your product? | regulation, acquisition, product launch, market expansion, cost cutting, partnership, crisis, earnings, industry trend, competitive move (multi-select) | `target_news_categories` |
| Any industry filters? | SaaS, AI, fintech, healthtech, cybersecurity, etc. (or "all") | `target_industries` |
| Any geography filters? | US, EMEA, APAC, etc. (or "all") | `target_geographies` |
| How far back should we search? | 3 / 7 / 14 / 30 days | `lookback_days` |
| Any keywords or topics to prioritize? | Free text (e.g. "HIPAA", "AI regulation", "supply chain") | `priority_keywords` |

### ICP Definition

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What does your company do? (1-2 sentences) | Relevance matching | `company_description` |
| What problem do you solve? | Connection angle identification | `pain_point` |
| What company sizes do you sell to? | ICP filter | `target_company_size` |
| Any disqualifiers? | Hard no's | `disqualifiers` |
| What specific outcomes does your product deliver? | Relevance angle building | `product_outcomes` |
| Name 2-3 proof points (customers, metrics) | Email credibility | `proof_points` |

### Contact Finding Config

| Question | Options | Stored As |
|----------|---------|-----------|
| Who are your buyers? (titles) | Free text | `buyer_titles` |
| Who are your champions? (titles) | Free text | `champion_titles` |
| How should we find contacts? | Apollo / LinkedIn Sales Nav / Clearbit / Web search / Manual | `contact_tool` |
| Do you have API access? | Yes (provide key) / No (use web search) | `contact_api_access` |

### Outreach Config

| Question | Options | Stored As |
|----------|---------|-----------|
| Where do you want outreach sent? | Smartlead / Instantly / Outreach.io / Lemlist / Apollo / CSV export | `outreach_tool` |
| Email or multi-channel? | Email only / Email + LinkedIn | `outreach_channels` |

**Store config in:** `clients/<client-name>/config/end-to-end-news-signal.json` or equivalent.

---

## Step 1: Discover News Signals

**Purpose:** Scan multiple web sources for recent news events matching the target categories, industries, and keywords. No company list input needed.

### Input Contract

```
target_news_categories: string[]    # From config
target_industries: string[]         # From config (optional)
target_geographies: string[]        # From config (optional)
lookback_days: integer              # From config (default: 7)
priority_keywords: string[]         # From config (optional)
```

### Process

Run all source searches in parallel:

#### A) Web Search (WebSearch tool — free)

Run 6-10 varied queries combining news categories with industries:
- `"[industry] [news_category] announced this week 2026"`
- `"new regulation [industry] 2026"`
- `"[industry] acquisition announced"`
- `"[industry] product launch 2026"`
- `"[industry] expansion layoffs restructuring"`
- `"[priority_keyword] news 2026"`
- `"[industry] company acquired OR partnered OR launched OR expanded"`

For each result, extract: headline, event category, companies mentioned, date, source URL.

#### B) Twitter Search (twitter-scraper — ~$0.05-0.10)

```bash
python3 skills/twitter-scraper/scripts/search_twitter.py \
  --query "\"[priority_keyword]\" AND ([industry] OR [news_category_terms])" \
  --since <lookback-start> --until <today> --max-tweets 50 --output json
```

News often breaks on Twitter first. Founder and executive posts signal events before press coverage.

#### C) Hacker News (hacker-news-scraper — free)

```bash
python3 skills/hacker-news-scraper/scripts/search_hn.py \
  --query "[priority_keyword] OR [industry] [news_category]" \
  --days <lookback_days> --min-points 5 --output json
```

Tech and business news surfaces early on HN, especially regulation, launches, and acquisitions.

#### D) Reddit Search (reddit-scraper — ~$0.05-0.10)

```bash
python3 skills/reddit-scraper/scripts/search_reddit.py \
  --subreddit "[relevant_subreddits]" \
  --keywords "[priority_keywords],[news_category_terms]" \
  --days <lookback_days> --sort hot --output json
```

Industry-specific subreddits surface news with practitioner commentary that reveals impact.

### Consolidation

1. **Deduplicate** across sources. Same news event from multiple sources = higher confidence.
2. **Filter** by target categories, industries, and geographies.
3. **Group** by event — multiple articles about the same event collapse into one signal with multiple sources.
4. **Score** each signal:
   - +3: Appears in multiple sources
   - +3: Category matches `target_news_categories` exactly
   - +2: Contains `priority_keywords`
   - +2: Industry matches `target_industries`
   - +1: Published within last 3 days
   - +1: High engagement (comments, shares, upvotes)
   - -1: Category outside target set
   - -2: Geography mismatch (if filter specified)
5. **Rank** by score descending.

### Output Contract

```
discovered_signals: [
  {
    headline: string
    event_category: string            # "regulation", "acquisition", "expansion", etc.
    event_date: string
    full_summary: string              # 2-3 sentence summary
    source_urls: string[]
    sources: string[]                 # ["web", "twitter", "hn", "reddit"]
    companies_mentioned: [
      {
        name: string
        domain: string | null
        role_in_news: string          # "subject", "affected", "partner", "competitor"
        industry: string
      }
    ]
    people_mentioned: [
      {
        name: string
        title: string | null
        company: string
        role_in_news: string
      }
    ]
    affected_industries: string[]
    confidence: "high" | "medium"
    score: integer
    priority_keyword_matches: string[]
  }
]
```

### Human Checkpoint

```
Found X news signals matching your criteria across Y sources:

| Rank | Headline | Category | Date | Companies | Sources | Score |
|------|----------|----------|------|-----------|---------|-------|
| 1    | FDA announces new telehealth regulation | Regulation | 2026-04-03 | 5 mentioned, ~50 affected | web, hn, reddit | 11 |
| 2    | Acme acquires BetaCo for $200M | Acquisition | 2026-04-01 | 2 mentioned | web, twitter | 8 |
| 3    | New AI safety framework released | Regulation | 2026-04-02 | 3 mentioned | web, hn | 7 |
| ...  | ...      | ...      | ...  | ...       | ...     | ...   |

Proceed to extraction and qualification? You can remove any signals before continuing.
```

---

## Step 2: Extract Entities & Qualify Against ICP

**Purpose:** For each discovered signal, extract all affected companies (including those implied but not mentioned), then qualify against ICP. Combines the Parse & Extract and ICP Qualification steps from `news-signal-outreach`.

### Input Contract

```
discovered_signals: [...]            # From Step 1 output
icp_criteria: {
  target_industries: string[]
  target_company_size: string
  target_geographies: string[]
  disqualifiers: string[]
}
your_company: {
  description: string
  pain_point: string
}
```

### Process

For each discovered signal:

1. **Extract directly mentioned companies and people** from the signal summary and source content.

2. **Expand to implied companies:**
   - "New FDA regulation on telehealth" → search for telehealth companies, not just those in the article
   - "Major data breach at [company]" → the breached company AND their competitors
   - "Industry report shows X trend" → companies in that industry
   - Use web search to identify specific companies in affected spaces

3. **Qualify each company against ICP:**
   - Check industry against `target_industries`
   - Estimate company size (from news context or quick web search)
   - Check geography if relevant
   - Check against `disqualifiers`

4. **Assign priority tiers:**
   - **Tier 1 (Act Today):** Direct subject of the news + strong ICP fit + event within 7 days
   - **Tier 2 (Act This Week):** Directly affected by the news + ICP fit + event within 14 days
   - **Tier 3 (Queue):** Indirectly affected or thematic connection + ICP fit
   - **Drop:** No ICP fit or disqualified

### Output Contract

```
qualified_targets: [
  {
    entity: {
      type: "company" | "person"
      name: string
      company: string
      domain: string | null
      role_in_news: string
      industry: string
      estimated_size: string | null
    }
    news: {
      headline: string
      event_category: string
      event_date: string
      full_summary: string
      source_urls: string[]
    }
    icp_assessment: {
      fit: "strong" | "moderate"
      industry_match: boolean
      size_match: boolean | "unknown"
      reasoning: string
    }
    priority_tier: "tier_1" | "tier_2" | "tier_3"
  }
]
dropped_targets: [
  { name: string, reason: string }
]
```

### Human Checkpoint

```
## Extraction & Qualification Results

### Signal: "FDA announces new telehealth regulation"

#### Tier 1 — Act Today (X companies)
| Company | Role in News | Industry | Size | ICP Fit | Why |
|---------|-------------|----------|------|---------|-----|
| TeleHealth Co | Subject | Healthcare SaaS | ~200 | Strong | Core ICP, directly impacted |

#### Tier 2 — Act This Week (X companies)
| Company | Role in News | Industry | Size | ICP Fit | Why |
|---------|-------------|----------|------|---------|-----|
| MedTech Inc | Affected | HealthTech | ~500 | Moderate | Adjacent, needs compliance |

#### Tier 3 — Queue (X companies)
| Company | Role in News | Industry | Size | ICP Fit | Why |
|---------|-------------|----------|------|---------|-----|

#### Dropped (X)
| Company | Reason |
|---------|--------|

[Repeat for each signal]

Approve before we identify connection angles?
```

---

## Step 3: Identify Connection Angles

**Purpose:** The critical thinking step. For each qualified target, determine the specific connection between the news event and your product. Why should they care about your product RIGHT NOW because of THIS news? Pure LLM reasoning.

### Input Contract

```
qualified_targets: [...]              # From Step 2 output
your_company: {
  description: string
  pain_point: string
  product_outcomes: string[]
  proof_points: string[]
}
```

### Process

For each qualified target, answer three questions:

#### Question 1: "Why does this news create urgency for our product?"

Map the news event category to a product relevance pattern:

| Event Category | How It Creates Urgency | Example |
|---------------|----------------------|---------|
| **Regulation change** | They need to comply, your product helps them comply or adapt faster | "New data privacy law → they need [your compliance tool] before enforcement date" |
| **Acquisition / Merger** | Systems need integration, processes need standardization | "Acquired a company → need to unify [function your product handles]" |
| **Market expansion** | New market = new challenges, need tools that scale | "Expanding to EMEA → need [your product] for localized [function]" |
| **Product launch** | Scaling up means scaling operations | "Launching enterprise tier → need [your product] to handle enterprise [function]" |
| **Competitive pressure** | Competitor moved, they need to respond | "Competitor launched [X] → they need to level up [area your product addresses]" |
| **Cost cutting / Layoffs** | Do more with less, automation becomes essential | "Cut 15% of staff → need [your product] to maintain output with smaller team" |
| **Crisis / Incident** | Reactive buying — they need a solution NOW | "Data breach → urgently need [your security product]" |
| **Partnership** | New partner = new workflows | "Partnered with [company] → need [your product] to support the integration" |
| **Earnings / Growth** | Over-performing = scaling. Under-performing = efficiency | "Revenue grew 3x → [function your product handles] can't keep up manually" |
| **Industry trend** | Category awareness is high, they're evaluating | "Industry report says [trend] → they're likely evaluating solutions" |

#### Question 2: "What's the specific angle?"

Craft a one-sentence connection:
```
"Because [news event], [company] now needs [specific outcome your product delivers]."
```

#### Question 3: "How strong is this connection?"

| Strength | Criteria | Example |
|----------|---------|---------|
| **Direct** | The news explicitly describes a problem your product solves | Layoff in your product's department → they need automation |
| **Adjacent** | The news implies a downstream need your product addresses | Market expansion → implies scaling → need for your tool |
| **Thematic** | The news is in the same category as your product's domain | Industry report about the trend you're in → awareness play |

#### Framework Selection

| Connection Strength | Framework | Why |
|--------------------|-----------|-----|
| **Direct** | **Signal-Proof-Ask** | The news IS the hook — reference it directly, show proof, ask |
| **Adjacent** | **PAS** | Problem (implied by the news) → Agitate → Solve |
| **Thematic** | **AIDA** | Attention (news) → Interest → Desire → Action |

### Output Contract

```
connection_angles: [
  {
    entity: { ... }
    news: { ... }
    icp_assessment: { ... }
    priority_tier: string
    connection: {
      urgency_reason: string
      specific_angle: string
      connection_strength: "direct" | "adjacent" | "thematic"
      timing_note: string
      recommended_framework: string
    }
  }
]
```

### Human Checkpoint

```
## Connection Angles

### Direct Connections (X targets) — Act quickly
| Entity | News | Angle | Timing |
|--------|------|-------|--------|
| Acme Corp | Acquired BetaCo | "Need to unify CRM systems — [product] does this in 30 days" | This week |

### Adjacent Connections (X targets)
| Entity | News | Angle | Timing |
|--------|------|-------|--------|
| MedTech Inc | Expanding to EMEA | "Localized [function] becomes a requirement" | This month |

### Thematic Connections (X targets)
| Entity | News | Angle | Timing |
|--------|------|-------|--------|
| HealthCo | Industry report on [trend] | "Likely evaluating [category] solutions" | Flexible |

Approve these angles before we find contacts?
```

---

## Step 4: Find Decision-Makers

**Purpose:** For each qualified target with a connection angle, find people matching buyer/champion personas, prioritized by relevance to the news event.

### Input Contract

```
connection_angles: [...]              # From Step 3 output
buyer_titles: string[]                # From config
champion_titles: string[]             # From config
contact_tool: string                  # From config
max_contacts_per_company: integer     # Default: 3-5
```

### Process

1. **For each company, use the configured `contact_tool`** to find people matching buyer and champion titles.

2. **Prioritize contacts by news relevance:**

   | News Category | Prioritize These Contacts |
   |--------------|--------------------------|
   | Regulation / Compliance | Legal, Compliance, Operations leadership |
   | Acquisition / Merger | COO, CTO, VP Operations, Integration leads |
   | Market expansion | VP Sales, VP Marketing, Country/Regional leads |
   | Cost cutting / Layoffs | COO, CFO, VP Operations |
   | Product launch | CTO, VP Product, VP Engineering |
   | Crisis / Incident | CISO, VP Engineering, CTO (security), CEO/COO (operational) |
   | General growth | Default to `buyer_titles` from config |

3. **For each contact, note their relevance to the news** — are they directly affected, the decision-maker for the response, or the person who feels the pain?

4. **Cap** at max_contacts_per_company (3-5).

5. **Deduplicate** against `contact-cache` to avoid repeat outreach across runs.

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
      news_relevance: string
    }
    company: {
      name: string
      domain: string
      priority_tier: string
    }
    connection: {
      specific_angle: string
      connection_strength: string
      urgency_reason: string
    }
    news: {
      headline: string
      event_category: string
      source_url: string | null
    }
  }
]
contacts_without_email: [...]         # Same structure, flagged for manual lookup
```

### Human Checkpoint

```
## Contacts Found

### Acme Corp — "Acquired BetaCo" (Direct connection, Tier 1)
| Name | Title | Role | Why This Person | Email |
|------|-------|------|----------------|-------|
| Sarah Kim | COO | Buyer | Owns post-acquisition integration | ✓ |
| David Park | VP Operations | Champion | Manages unified workflows | ✓ |

### MedTech Inc — "Expanding to EMEA" (Adjacent connection, Tier 2)
| Name | Title | Role | Why This Person | Email |
|------|-------|------|----------------|-------|
| ... | ... | ... | ... | ... |

Total: X contacts across Y companies (Z without email)

Approve before we draft emails?
```

---

## Step 5: Draft Personalized Emails

**Purpose:** Draft outreach where the news event is the hook, your product is the solution, and the email demonstrates you understand their specific situation. Pure LLM reasoning.

### Input Contract

```
contacts: [...]                       # From Step 4 output
your_company: {
  description: string
  pain_point: string
  product_outcomes: string[]
  proof_points: string[]
}
sequence_config: {
  touches: integer                    # Default: 3
  timing: integer[]                   # Default varies by connection strength
  tone: string                        # Default: "casual-direct"
  cta: string                         # Default: "15-min call"
}
```

### Process

1. **Adjust sequence timing by connection strength:**

   | Strength | Timing | Rationale |
   |----------|--------|-----------|
   | **Direct** | Day 1 / 3 / 7 | Urgency is real — they're actively dealing with this |
   | **Adjacent** | Day 1 / 5 / 12 | Standard — urgency is implied, not immediate |
   | **Thematic** | Day 1 / 7 / 14 | Slower cadence — awareness, not crisis response |

2. **Build the email around the news, not the product.** The news is the subject. Your product is the punchline.

   | Element | Source | How to Use |
   |---------|--------|-----------|
   | News hook | Step 1 `headline` | Open with what happened — show you're informed |
   | Impact on them | Step 3 `urgency_reason` | Explain what this means for their specific role |
   | Your angle | Step 3 `specific_angle` | Connect the dots to your product naturally |
   | Proof | Config `proof_points` | Show a peer who faced a similar situation |
   | CTA | Config | Low-friction ask |

3. **Email structure by connection strength:**

   **Direct connection (Signal-Proof-Ask):**
   ```
   Hook: Reference the specific news event
   Impact: What this means for them (1 sentence)
   Proof: A peer who faced the same situation and used your product
   Ask: Soft CTA
   ```

   **Adjacent connection (PAS):**
   ```
   Problem: The downstream challenge the news creates
   Agitate: What happens if they don't address it (1 sentence)
   Solve: How your product helps, with a proof point
   Ask: Soft CTA
   ```

   **Thematic connection (AIDA):**
   ```
   Attention: Reference the news/trend
   Interest: How it relates to their company specifically
   Desire: What your product does in this context
   Action: Soft CTA
   ```

4. **Generate emails per `email-drafting` skill rules:**
   - Touch 1: 50-90 words. Hook with news signal + proof + soft CTA
   - Touch 2: 30-50 words. New angle (different proof point or asset offer)
   - Touch 3: 20-40 words. Social proof drop or breakup
   - All hard rules apply: no filler, no "just checking in", one CTA per email

5. **Sensitivity rules for negative news:**
   - **Layoffs:** Empathetic. "I know this is a tough time." Never say "your layoffs mean you need us!"
   - **Data breach / Security incident:** Helpful, not salesy. Wait 48-72 hours before reaching out.
   - **Earnings miss:** Efficiency-focused. Don't reference the miss in the subject line.
   - **Executive departure:** Skip the drama. Focus on the company's direction.
   - **Lawsuit / Legal trouble:** Only reach out if your product directly helps with compliance/legal.
   - **Rule of thumb:** If you wouldn't bring it up face-to-face at a conference, don't put it in a cold email.

### Output Contract

```
email_sequences: [
  {
    contact: { full_name, email, title, company_name, role_type, news_relevance }
    news_context: { headline, event_category, source_url }
    connection: { specific_angle, connection_strength }
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

Present 3-5 sample sequences (one per connection strength / tier combination):

```
## Sample Emails for Review

### Direct Connection: Sarah Kim, COO @ Acme Corp
News: Acme acquired BetaCo | Angle: CRM unification | Framework: Signal-Proof-Ask

**Touch 1 — Day 1**
Subject: Unifying Acme + BetaCo systems
> Hi Sarah — saw the BetaCo acquisition. Congrats. The integration
> sprint typically surfaces a CRM unification challenge fast —
> two systems, overlapping data, different workflows.
>
> [Peer company] faced the same thing after their acquisition last year.
> [Product] had both systems unified in 30 days. Happy to share how.
>
> Worth a 15-minute call?

**Touch 2 — Day 3**
> [New angle — data migration complexity, with a specific metric]

**Touch 3 — Day 7**
> [Breakup with offer to share the integration playbook]

---

### Adjacent Connection: Dr. Lee, VP Product @ MedTech Inc
News: EMEA expansion | Angle: Localization needs | Framework: PAS

**Touch 1 — Day 1**
Subject: EMEA expansion + [function] localization
> [full email]

---

Approve these samples? I'll generate the rest in the same style.
Iterate? Tell me what to change (tone, length, angle, CTA).
```

---

## Step 6: Launch Campaign

**Purpose:** Package contacts + email sequences for the configured outreach tool.

### Input Contract

```
email_sequences: [...]                # From Step 5 output
outreach_tool: string                 # From config
outreach_channels: string             # From config
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
  signals_used: integer
  connection_breakdown: {
    direct: integer
    adjacent: integer
    thematic: integer
  }
  next_action: string
}
```

### Human Checkpoint

```
## Campaign Ready

Tool: [configured tool]
Signal type: News-triggered
Signals used: X news events
Contacts: N people across M companies
Connection strengths: X direct, Y adjacent, Z thematic
Tier breakdown: A Tier 1, B Tier 2, C Tier 3
Sequence: 3 touches (timing varies by connection strength)
File: output/{campaign-name}-{date}.csv

Ready to launch? (Final gate before emails are sent or files are created)
```

---

## Execution Summary

| Step | What | Tool | Checkpoint | Time |
|------|------|------|------------|------|
| 0 | Config | None | First run only | 5 min (once) |
| 1 | Discover news signals | WebSearch + Twitter + HN + Reddit | Review discovered signals | 3-5 min |
| 2 | Extract & qualify | Web search (expansion) + LLM reasoning | Approve qualified targets | 3-5 min |
| 3 | Connection angles | LLM reasoning | Approve angles + strength ratings | 3-5 min |
| 4 | Find people | Configurable (Apollo, LinkedIn, etc.) | Approve contact list | 2-3 min |
| 5 | Draft emails | LLM reasoning | Review samples, iterate | 5-10 min |
| 6 | Launch | Configurable (Smartlead, CSV, etc.) | Final approval | 1 min |

**Total: ~20-30 minutes** from "find me news I can use for outreach" to outreach-ready campaign.

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

- **Direct connections are rare but powerful.** Most news creates adjacent or thematic connections. When you find a direct one, prioritize it — these convert at 2-3x the rate.
- **Speed matters for direct connections.** The first vendor to reference a relevant news event looks informed. The fifth looks like they're running the same playbook.
- **Don't force weak connections.** If you can't articulate the angle in one sentence, the connection is too weak. Drop it.
- **News about competitors is gold.** If a competitor raises funding, gets acquired, has a breach, or launches a product — their customers are suddenly open to conversations.
- **Negative news requires a 48-72 hour cooling period.** Reaching out the day of a layoff or breach is predatory. Wait, then lead with empathy.
- **Industry reports and trend pieces make great thematic triggers.** "The Gartner report on [category] just dropped — here's what it means for [company]."
- **Run weekly** — fresh news keeps outreach relevant and timely.
- **3-5 contacts per company** avoids carpet-bombing.
- **Track contacts in `contact-cache`** to avoid duplicate outreach across weekly runs.
- **Route embedded signals to specialist composites.** News often contains funding, hiring, or leadership signals. Route those to the dedicated composite for better outreach.
- **Multi-source appearances are the strongest signal** — a story on TechCrunch + HN + Twitter is higher quality than a single-source mention.

## Example Prompt

> "Scan for news in cybersecurity and healthtech from the past week. We sell compliance automation for mid-market SaaS companies. Our buyers are VP Engineering and CISOs. Focus on regulation changes, data breaches, and acquisition activity. Find contacts via web search and export to CSV."

The agent should run the full pipeline: discover signals → extract & qualify → connection angles → find contacts → draft emails → export CSV.
