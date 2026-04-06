---
name: end-to-end-leadership-change-signal
version: 1.0.0
description: >
  Full pipeline from leadership change discovery to outreach-ready campaign.
  Scans the web for recent executive moves (no company list needed),
  verifies and enriches via Apollo, evaluates relevance to your product,
  drafts personalized outreach tuned to the new leader's timing window and
  background, and packages for your outreach tool. Combines web-based
  discovery with the Apollo-powered leadership-change-outreach pipeline
  into a single zero-to-campaign workflow.
tags: [lead-generation, outreach]

graph:
  provides:
    - discovered-leadership-changes    # Companies with announced executive moves
    - verified-leadership-changes      # Apollo-verified changes with enrichment
    - qualified-leaders                # Leaders ranked by relevance to you
    - personalized-email-sequences     # Ready-to-send email drafts
    - campaign-package                 # Outreach-tool-ready campaign
  requires:
    - your-company-context             # What you sell, who you sell to, proof points
    - target-titles                    # e.g. "VP Sales, CRO, CMO"
  connects_to:
    - skill: cold-email-outreach
      when: "User wants to launch the campaign via Smartlead or other outreach tool"
      passes: qualified-leaders, personalized-email-sequences
    - skill: linkedin-outreach
      when: "User wants LinkedIn outreach alongside email"
      passes: qualified-leaders
  capabilities: [web-search, apollo-lead-finder, contact-finding, email-drafting, social-scraping]
---

# End-to-End Leadership Change Signal

Full pipeline from signal discovery to outreach-ready campaign in a single run. No company list required — this skill discovers recent leadership changes from the web, verifies them via Apollo, evaluates relevance to your product, drafts personalized outreach, and packages everything for your outreach tool.

**Why leadership changes work:** New leaders re-evaluate everything in their first 90 days. They inherit a vendor stack they didn't choose, a team they didn't build, and KPIs they need to hit fast. They're the most receptive buyers in any organization because they want quick wins, have mandate (and often budget) to make changes, and haven't yet formed loyalty to existing vendors.

**What makes this "end-to-end":** The base `leadership-change-outreach` skill requires a company list as input. This composite adds a discovery layer — scanning multiple web sources for leadership change announcements — so you can go from zero to outreach campaign without any input list.

## When to Auto-Load

Load this composite when:
- User says "find companies with new leadership and reach out to them"
- User says "end-to-end leadership change signal", "leadership change pipeline", "executive change outreach from scratch"
- User wants to go from zero to outreach campaign based on leadership change signals
- User has no existing company list but wants to target companies with new executives

Do NOT load if:
- User already has a company list → use `leadership-change-outreach` instead
- User only wants to monitor leadership changes without outreach → use web search manually

## Included Skills

| Skill | Role in Pipeline |
|-------|-----------------|
| `leadership-change-outreach` | Core workflow — Apollo detection, qualification, enrichment, email drafting |
| `company-contact-finder` | Finds additional contacts beyond the new leader (champions, users) |
| `contact-cache` | Deduplicates contacts across runs |
| `cold-email-outreach` | Sends sequences via configured outreach tool |
| `email-drafting` | Email copy rules and frameworks |
| `linkedin-outreach` | LinkedIn connection/message sequences |
| `linkedin-profile-post-scraper` | Scrapes new leader's LinkedIn posts for personalization hooks |
| `hacker-news-scraper` | Supplements signal detection via HN hiring threads |
| `reddit-scraper` | Supplements signal detection via Reddit announcements |
| `twitter-scraper` | Supplements signal detection via Twitter/X executive move announcements |

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                  END-TO-END LEADERSHIP CHANGE SIGNAL                         │
│                                                                              │
│  ┌───────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │ DISCOVER  │──▶│ VERIFY & │──▶│ EVALUATE │──▶│  DRAFT   │──▶│  LAUNCH  │ │
│  │ Signals   │   │ ENRICH   │   │ & RANK   │   │ Outreach │   │          │ │
│  └───────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘ │
│       │                │              │              │               │       │
│  Multi-source     Apollo free    Role relevance  Timing-aware    Tool-      │
│  web scan         search +       + timing +      personalized   agnostic    │
│  (no input list)  enrichment     background       sequences     export      │
│                   by ID          scoring          (LLM)                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Step 0: Configuration (One-Time Setup)

On first run, collect and store all configuration needed for the full pipeline. Skip on subsequent runs.

### Signal Discovery Config

| Question | Options | Stored As |
|----------|---------|-----------|
| What leadership titles are you targeting? | CRO, VP Sales, CMO, VP Marketing, etc. | `target_titles` |
| Any industry filters? | SaaS, AI, fintech, healthtech, etc. (or "all") | `target_industries` |
| How far back should we search? | 30 / 60 / 90 days (default: 90) | `lookback_days` |
| Minimum company size? | e.g. "50 employees" or none | `min_company_size` |

### Leader Relevance Mapping

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What does your product do? (1-2 sentences) | Match against leader mandates | `company_description` |
| What leader titles are **direct buyers** of your product? | Highest priority — they can sign the check | `buyer_leader_titles` |
| What leader titles could **champion** your product? | They'd advocate internally or be an entry point | `champion_leader_titles` |
| What leader titles have **mandates your product supports**? | Their goals align with your product's value | `aligned_leader_titles` |
| What departments are relevant? | Filter out irrelevant leadership changes | `relevant_departments` |

### Contact Finding Config

| Question | Options | Stored As |
|----------|---------|-----------|
| How should we find contacts? | Apollo / LinkedIn Sales Nav / Clearbit / Web search / Manual | `contact_tool` |
| Do you have Apollo API access? | Yes (provide key) / No (use web search) | `apollo_api_access` |

### Outreach Config

| Question | Options | Stored As |
|----------|---------|-----------|
| Where do you want outreach sent? | Smartlead / Instantly / Outreach.io / Lemlist / Apollo / CSV export | `outreach_tool` |
| Email or multi-channel? | Email only / Email + LinkedIn | `outreach_channels` |

### Your Company Context

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What problem do you solve? | Email hook | `pain_point` |
| Name 2-3 proof points (customers, metrics, results) | Email credibility | `proof_points` |
| What quick wins can a new leader get from your product? | First-90-days angle | `quick_wins` |
| What does the "before" state look like without your product? | Pain framing | `before_state` |

**Store config in:** `clients/<client-name>/config/end-to-end-leadership-change-signal.json` or equivalent.

---

## Step 1: Discover Leadership Change Signals

**Purpose:** Scan multiple web sources for recent leadership changes matching the target criteria. No company list input needed.

### Input Contract

```
target_titles: string[]            # From config: ["VP Sales", "CRO", "CMO"]
target_industries: string[]        # From config (optional)
lookback_days: integer             # From config (default: 90)
min_company_size: string | null    # From config (optional)
```

### Process

Run all source searches in parallel:

#### A) Web Search (WebSearch tool — free)

Run 6-8 varied queries:
- `"appointed as VP Sales" OR "named VP of Sales" 2026`
- `"new CRO" OR "new Chief Revenue Officer" announced 2026`
- `"joins as" AND ("VP" OR "Chief") AND 2026`
- `"promoted to VP" OR "promoted to Chief" 2026`
- `"excited to announce" AND ("VP" OR "SVP" OR "Chief") AND ("hired" OR "appointed" OR "joins")`
- `site:businesswire.com OR site:prnewswire.com "appointed" AND ("VP" OR "Chief") 2026`
- `"[industry] company" AND ("new hire" OR "appointed") AND ("VP" OR "Chief")` (if industry filter specified)
- `"executive appointment" OR "leadership appointment" AND "[target title]" 2026`

For each result, extract: person name, new title, company name, company domain, previous company, previous title, announcement date, source URL.

#### B) Twitter Search (twitter-scraper — ~$0.05-0.10)

```bash
python3 skills/twitter-scraper/scripts/search_twitter.py \
  --query "\"excited to share\" OR \"thrilled to announce\" AND (\"VP\" OR \"Chief\" OR \"Head of\") AND (\"new role\" OR \"joining\" OR \"starting\")" \
  --since <lookback-start> --until <today> --max-tweets 50 --output json
```

Founder/executive "new role" announcements often appear on Twitter/X before press releases. These are high-signal because the person themselves is announcing.

#### C) Hacker News (hacker-news-scraper — free)

```bash
python3 skills/hacker-news-scraper/scripts/search_hn.py \
  --query "appointed VP,new CRO,new CMO,executive hire" \
  --days <lookback_days> --min-points 3 --output json
```

HN "Who's Hiring" threads and company announcement posts sometimes surface executive moves at tech companies.

#### D) Reddit Search (reddit-scraper — ~$0.05-0.10)

```bash
python3 skills/reddit-scraper/scripts/search_reddit.py \
  --subreddit "startups,SaaS,technology,business" \
  --keywords "new VP,new CRO,new CMO,appointed,executive hire,leadership change" \
  --days <lookback_days> --sort hot --output json
```

#### E) LinkedIn Activity (linkedin-profile-post-scraper — optional)

If available, search for "new role" and "starting a new position" announcements from people with target titles. LinkedIn is the richest source of leadership change signals — most executives post when they change roles.

### Consolidation

1. **Deduplicate** across sources. Same person+company from multiple sources = higher confidence.
2. **Filter** by target titles, industries, and min company size.
3. **Score** each discovered change:
   - +3: Appears in multiple sources
   - +3: Person announced it themselves (Twitter/LinkedIn post)
   - +2: Title matches target buyer titles exactly
   - +2: External hire (not internal promotion)
   - +1: Announced within last 30 days
   - +1: Industry matches target
   - +1: Company recently raised funding (compounding signal)
   - -1: Title is tangential to target
   - -2: Announcement is 60+ days old
4. **Rank** by score descending.
5. **Extract domains** for all discovered companies (needed for Step 2 Apollo verification).

### Output Contract

```
discovered_changes: [
  {
    person_name: string
    new_title: string
    company_name: string
    company_domain: string
    company_industry: string | null
    previous_company: string | null
    previous_title: string | null
    announcement_date: string
    source_urls: string[]
    sources: string[]               # ["web", "twitter", "hn", "reddit", "linkedin"]
    self_announced: boolean         # Person announced it themselves
    confidence: "high" | "medium"
    score: integer
  }
]
```

### Human Checkpoint

```
Found X leadership changes matching your criteria:

| Rank | Person | New Title | Company | Previous Role | Date | Sources | Confidence |
|------|--------|-----------|---------|---------------|------|---------|------------|
| 1    | Jane Smith | VP Sales | Acme Corp | Dir Sales @ Beta Inc | 2026-03-15 | web, twitter, linkedin | High |
| 2    | Tom Brown | CRO | Gamma Inc | VP Rev @ Delta Co | 2026-03-01 | web | Medium |
| ...  | ...    | ...       | ...     | ...           | ...  | ...     | ...        |

Proceed to Apollo verification? You can remove any entries before continuing.
```

---

## Step 2: Verify & Enrich via Apollo

**Purpose:** Verify discovered leadership changes using Apollo's employment history data, and enrich with email, LinkedIn URL, and full career history. This replaces Step 1 of `leadership-change-outreach` — instead of scanning all employees at given companies, we target-verify the specific people we discovered.

### Input Contract

```
discovered_changes: [...]           # From Step 1 output
titles: string[]                    # From config (Apollo search titles)
lookback_days: integer              # From config
```

### Process

#### Phase 1: Apollo Free Search — Targeted Verification

For each discovered company domain, search Apollo for the specific person:

```python
filters = {
    'q_organization_domains': company_domain,
    'person_titles': [discovered_new_title],  # Narrow to the specific title
    'per_page': 25,
    'page': 1
}
```

Match results against the discovered person name (fuzzy match — Apollo obfuscates last names in free tier, so match on first name + title + company).

**Bonus discoveries:** While searching for the known person, Apollo may surface OTHER recent leadership changes at the same company that web search missed. Include these as bonus finds.

#### Phase 2: Local Post-Filter

Apply the strict post-filter from `leadership-change-outreach` to remove noise:
- Reject non-GTM functions (engineering, talent, legal, etc.)
- Reject regional/sub-segment roles (AVP, EMEA-specific, etc.)
- Reject Apollo garbage ("related to search terms")
- Require valid title prefix (VP/SVP/Head of/Chief/CRO/CMO/CCO/President)

#### Phase 3: Apollo Enrichment by ID (1 credit per person)

For each matched person, enrich using the `id` from free search:

```python
url = "https://api.apollo.io/api/v1/people/match"
payload = {"api_key": api_key, "id": person_id}
```

Returns: full name, employment_history (with start_date/end_date), linkedin_url, email + email_status, location.

**Rate limiting:** 0.5s delay every 5 requests. Respect `Retry-After` on 429s.

#### Phase 4: Change Verification

Cross-reference Apollo employment history against web-discovered data:
- **Confirmed:** Apollo start_date on current role aligns with web announcement date
- **Enriched:** Apollo provides additional details not in web announcement (previous roles, tenure)
- **Corrected:** Apollo shows different timing or title than web reported — use Apollo as ground truth
- **Unverified:** Person not found in Apollo — keep web data but flag as unverified

Determine change type from employment history:
- **new_hire**: Previous role was at a different company
- **internal_promotion**: Previous role was at the same company

### Output Contract

```
verified_changes: [
  {
    company: {
      name: string
      domain: string
      industry: string | null
    }
    new_leader: {
      full_name: string
      new_title: string
      start_date: string              # ISO date (month granularity from Apollo, or announcement date)
      previous_company: string
      previous_title: string
      change_type: "new_hire" | "internal_promotion"
      linkedin_url: string | null
      email: string | null
      email_status: string | null
      city: string | null
      state: string | null
      country: string | null
      verification: "confirmed" | "enriched" | "corrected" | "unverified"
    }
    discovery: {
      sources: string[]
      self_announced: boolean
      score: integer
    }
  }
]
bonus_discoveries: [...]             # Additional changes found via Apollo that weren't in web results
```

### Output Files

Save two files:
1. **CSV** (`leadership-change-scan.csv`) — all verified people sorted by start_date descending
2. **Markdown** (`leadership-change-discovery.md`) — formatted report with source summary

### Human Checkpoint

```
## Apollo Verification Results

Discovered: X changes → Verified: Y → Bonus discoveries: Z

| Person | Title | Company | Started | Change Type | Verification | Email |
|--------|-------|---------|---------|-------------|-------------|-------|
| Jane Smith | VP Sales | Acme Corp | 2026-03-01 | new_hire | Confirmed | jane@acme.com (verified) |
| Tom Brown | CRO | Gamma Inc | 2026-02-01 | new_hire | Enriched | tom@gamma.io (guessed) |

Credits used: Y + Z

Proceed with relevance evaluation? (Y/n)
```

---

## Step 3: Evaluate Relevance & Prioritize

**Purpose:** For each verified leadership change, evaluate whether the new leader is relevant to your product and determine the best outreach approach. Pure LLM reasoning — no external tools needed.

This step follows the `leadership-change-outreach` Step 2 evaluation framework exactly.

### Input Contract

```
verified_changes: [...]              # From Step 2 output
your_company: {
  description: string
  pain_point: string
  proof_points: string[]
  quick_wins: string[]
  before_state: string
}
buyer_leader_titles: string[]
champion_leader_titles: string[]
aligned_leader_titles: string[]
```

### Process

For each leadership change, evaluate across three dimensions:

#### A) Role Relevance

| Category | Match Criteria | Priority |
|----------|---------------|----------|
| **Direct buyer** | Title matches `buyer_leader_titles` | Highest — they can make the purchase decision |
| **Champion** | Title matches `champion_leader_titles` | High — they can advocate and influence the buyer |
| **Aligned mandate** | Title matches `aligned_leader_titles` | Medium — their goals benefit from your product |
| **No relevance** | Title matches none of the lists | Drop |

#### B) Timing Window

| Days in Role | Window | Outreach Tone |
|-------------|--------|---------------|
| 0-30 days | **Honeymoon** | "Welcome aboard — here's something to help you hit the ground running" |
| 31-60 days | **Assessment** | "Now that you've had a month to assess the stack, here's what peers are doing" |
| 61-90 days | **Action** | "You're probably finalizing your roadmap — here's a quick win to consider" |
| 90+ days | **Established** | Weaker signal but still valid — "Saw you joined [company] recently" |

#### C) Background Signal

| Background | Signal | How to Use |
|-----------|--------|-----------|
| Came from a **customer** of yours | Strongest possible — they already know your product | "You used [product] at [previous company] — want to bring it to [new company]?" |
| Came from a **competitor's customer** | They have experience with the category | "At [previous company] you used [competitor] — here's how [product] compares" |
| Came from **same industry** | They understand the pain points | Reference industry-specific problems they've seen |
| Came from **different industry** | Fresh perspective, may be open to new approaches | "The playbook from [old industry] doesn't always translate — here's what works in [new industry]" |
| **Internal promotion** | They know the existing stack and its shortcomings | "Now that you own the budget, here's what your team has been asking for" |

#### D) Discovery Signal Boost

Layer the discovery signal strength on top of the standard evaluation:
- **Self-announced** (posted about it on Twitter/LinkedIn): +1 tier. They're publicly signaling openness — great time to engage.
- **Multi-source** (appeared in 3+ sources): Higher profile change, likely a strategic hire with budget behind it.
- **Compounding signal** (company also recently raised / is hiring aggressively): Multiple buying signals compound. Prioritize these.

### Scoring

- **Tier 1 (Act Today):** Direct buyer + <30 days in role + external hire. OR: any role relevance + self-announced + <30 days.
- **Tier 2 (Act This Week):** Direct buyer 30-60 days in, OR champion <30 days, OR came from a customer/competitor customer, OR multi-source with compounding signals.
- **Tier 3 (Queue):** Aligned mandate, OR 60-90 days in role, OR internal promotion with champion title.
- **Drop:** No role relevance, OR >90 days in role with weak fit.

For each qualified leader, generate:
- **Relevance reasoning:** Why this leader would care about your product right now
- **Outreach angle:** The specific hook based on their role + timing + background
- **Key insight:** One thing about their situation that makes the outreach personal

### Output Contract

```
qualified_leaders: [
  {
    ...verified_change_fields,
    role_relevance: "direct_buyer" | "champion" | "aligned_mandate"
    timing_window: "honeymoon" | "assessment" | "action" | "established"
    background_signal: string
    discovery_boost: string | null    # "self_announced", "multi_source", "compounding"
    priority_tier: "tier_1" | "tier_2" | "tier_3"
    relevance_reasoning: string
    outreach_angle: string
    key_insight: string
  }
]
dropped_leaders: [
  { name: string, company: string, drop_reason: string }
]
```

### Human Checkpoint

```
## Relevance Evaluation

### Tier 1 — Act Today (X leaders)
| Leader | Company | Title | Days In | Type | Boost | Angle |
|--------|---------|-------|---------|------|-------|-------|
| Jane Smith | Acme | VP Sales | 15 | Direct buyer, Honeymoon | Self-announced | "You just posted about scaling outbound at Acme..." |

### Tier 2 — Act This Week (X leaders)
| ... |

### Tier 3 — Queue (X leaders)
| ... |

### Dropped (X leaders)
| Leader | Company | Reason |
|--------|---------|--------|

Approve before we draft outreach? You can promote, demote, or drop any leader.
```

---

## Step 4: Draft Personalized Outreach

**Purpose:** Draft outreach to each new leader that demonstrates you understand their situation. Pure LLM reasoning.

### Input Contract

```
qualified_leaders: [...]             # From Step 3 output
your_company: {
  description: string
  pain_point: string
  proof_points: string[]
  quick_wins: string[]
  before_state: string
}
sequence_config: {
  touches: integer                   # Default: 3
  timing: integer[]                  # Default: [1, 5, 12]
  tone: string                      # Default: "professional-sharp"
  cta: string                       # Default: "15-min intro call"
}
```

### Process

1. **Enrich personalization context** (optional, high-value):
   - Use `linkedin-profile-post-scraper` to check if the leader posted about their new role or shared priorities
   - Use web search to check for any company news beyond the leadership change

2. **Select framework based on role relevance:**
   - **Direct buyer** → **Signal-Proof-Ask** (reference the role change, show proof, ask for time)
   - **Champion** → **BAB** (before: the current state they inherited / after: what it looks like with your product / bridge: quick wins in 30 days)
   - **Aligned mandate** → **PAS** (problem: what their mandate implies / agitate: why current tools fall short / solve: your product)

3. **Build personalization from enriched profile:**

   | Personalization Element | Source | Example |
   |------------------------|--------|---------|
   | Role change reference | Step 1 discovery | "Congrats on the VP Sales role at Acme" |
   | Timing-aware framing | Step 3 timing_window | "Now that you've had a month to assess..." |
   | Background connection | Step 3 background_signal | "At Competitor Inc you used [similar tool]..." |
   | Self-announcement reference | Step 1 self_announced | "Your post about scaling outbound resonated..." |
   | Company context | Step 2 enrichment | "With Acme's recent growth plans..." |
   | Quick win offer | Config quick_wins | "Most VPs see [result] within their first 30 days with us" |

4. **Adapt email angle by timing window:**

   | Window | Touch 1 Approach | Subject Line Pattern |
   |--------|-----------------|---------------------|
   | **Honeymoon** (0-30d) | Welcome + quick win offer. Light touch — they're still onboarding. | "Quick win for your first 90 days at {company}" |
   | **Assessment** (31-60d) | Acknowledge they've been evaluating. Offer peer comparison. | "What other {title}s are doing differently" |
   | **Action** (61-90d) | They're making decisions now. Be direct about value. | "{Product} for {company}'s {goal}" |

5. **Follow `email-drafting` skill rules:**
   - Touch 1: 50-90 words. Reference the role change + one personalization hook + soft CTA.
   - Touch 2: 30-50 words. New proof point or quick-win offer.
   - Touch 3: 20-40 words. Peer social proof or graceful breakup.
   - **Tone: professional-sharp by default.** Executives respond to conciseness and specificity, not chattiness.

### Output Contract

```
email_sequences: [
  {
    leader: { full_name, email, title, company_name, role_relevance, timing_window, priority_tier }
    sequence: [
      {
        touch_number: integer
        send_day: integer
        subject: string
        body: string
        framework: string
        personalization_elements: {
          role_change: string
          timing: string
          background: string
          company_context: string
          linkedin_reference: string | null
        }
        word_count: integer
      }
    ]
  }
]
```

### Human Checkpoint

Present samples covering different timing windows and role types:

```
## Sample Outreach for Review

### Jane Smith, VP Sales @ Acme Corp
Tier 1 | Direct buyer | Honeymoon window (15 days) | Previously at Competitor Inc | Self-announced on LinkedIn

**Touch 1 — Day 1**
Subject: Quick win for your first 90 days at Acme
> Hi Jane — congrats on the move to Acme. Your post about building a
> "repeatable outbound engine" is exactly what drew me in.
>
> [Product] is what [peer company] brought in during a similar transition —
> [specific result] within 30 days.
>
> Worth a 15-minute intro?

**Touch 2 — Day 5**
Subject: The playbook from Competitor Inc → Acme
> [full email referencing their background]

**Touch 3 — Day 12**
Subject: One last thought
> [breakup email]

---

Approve these samples? I'll generate the rest in the same style.
Iterate? Tell me what to change (tone, length, angle, CTA).
```

---

## Step 5: Launch Campaign

**Purpose:** Package contacts + email sequences for the configured outreach tool. Identical to `leadership-change-outreach` Step 5.

### Input Contract

```
email_sequences: [...]               # From Step 4 output
outreach_tool: string                # From config
outreach_channels: string            # From config
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
Signal type: Leadership change
Contacts: X new leaders across Y companies
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
| 1 | Discover signals | WebSearch + Twitter + HN + Reddit + LinkedIn | Review discovered changes | 3-5 min |
| 2 | Verify & enrich | Apollo Free Search + Enrichment by ID | Approve verified list + credits | ~90 sec (machine) |
| 3 | Evaluate & rank | LLM reasoning | Approve tier rankings | 2-3 min |
| 4 | Draft outreach | LLM reasoning + LinkedIn scraper (optional) | Review samples, iterate | 5-10 min |
| 5 | Launch | Configurable (Smartlead, CSV, etc.) | Final approval | 1 min |

**Total: ~15-25 minutes** from "find me companies with new leaders to reach out to" to outreach-ready campaign.

## Cost

| Component | Cost |
|-----------|------|
| Web Search | Free |
| Hacker News (Algolia) | Free |
| Twitter scraper (Apify) | ~$0.05-0.10 |
| Reddit scraper (Apify) | ~$0.05-0.10 |
| Apollo enrichment | 1 credit per person verified (~20-40 credits typical) |
| LinkedIn profile scraper (optional) | ~$0.05-0.10 |

**Typical run:** $0.10-0.30 + 20-40 Apollo credits depending on discovery volume.

## Key Difference from Base Leadership Change Outreach

| | `leadership-change-outreach` | `end-to-end-leadership-change-signal` |
|---|---|---|
| **Input** | Company list (with domains) | Nothing — discovers from scratch |
| **Discovery** | None — scans given companies via Apollo | Multi-source web scan finds companies WITH changes |
| **Apollo usage** | Scans ALL employees at given companies (broad) | Verifies SPECIFIC people discovered by web scan (targeted) |
| **Credit efficiency** | Higher — enriches everyone matching title filter | Lower — only enriches people you already know changed roles |
| **Best for** | "Check my target account list for leadership changes" | "Find me new leaders to reach out to — I don't have a list" |

The base skill casts a wide net across known companies. This end-to-end version discovers the signal first, then uses Apollo for verification and enrichment — typically using fewer credits because you're only enriching confirmed changes rather than scanning entire orgs.

## Tips

- **Run bi-weekly or monthly** — leadership changes happen constantly but the 30-60 day outreach window means you don't need real-time monitoring
- **Self-announced changes are the highest-quality signals** — the person actively shared their move, making them more receptive to engagement
- **External hires are stronger signals than internal promotions** — external hires re-evaluate everything, internal promotions already know the vendor stack
- **The 30-60 day window is the sweet spot** — too early and they're onboarding, too late and they've already decided
- **Reference their LinkedIn "new role" post if they made one** — it shows you've done your homework and reveals their stated priorities
- **Don't mention the predecessor** — saying "replacing John" can be awkward. Just reference the role and the company
- **Quick wins beat big transformations** — new leaders need early credibility. Position as "a win in your first quarter" not "a 6-month implementation"
- **If they came from a customer of yours, that's the strongest hook** — lead with "You used [product] at [old company] — want to bring it to [new company]?"
- **Compounding signals are gold** — a new VP Sales at a company that just raised Series B and is hiring 5 SDRs? That's three signals pointing to the same buying moment
- **Track contacts in `contact-cache`** to avoid duplicate outreach across runs

## Example Prompt

> "Find companies that recently hired new VPs of Sales or CROs. We sell AI-powered sales coaching software. Our buyers are VP Sales and CRO. Target SaaS companies with 100+ employees. Use Apollo for verification and export to CSV."

The agent should run the full pipeline: discover → verify via Apollo → evaluate relevance → draft emails → export CSV.
