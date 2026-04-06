---
name: setup-outreach-campaign
version: 1.0.0
description: >
  End-to-end outreach campaign setup composite. Walks through ICP definition,
  signal source selection, outreach channel configuration, prospect list building,
  email/LinkedIn sequence drafting, and campaign launch. The one-stop orchestrator
  that replaces doing each step manually — go from "I want to run outreach" to a
  live campaign in a single session. Tool-agnostic — works with any signal source,
  contact finder, and outreach platform.
tags: [outreach, lead-generation]

graph:
  provides:
    - outreach-campaign-config       # Full campaign configuration (ICP, signals, channels)
    - qualified-prospect-list        # Researched and scored prospects ready for outreach
    - personalized-email-sequences   # Drafted sequences tailored to each prospect
    - campaign-export                # Tool-ready export for the user's outreach platform
  requires:
    - your-company-context           # What you sell, who you sell to, proof points
  connects_to:
    - skill: cold-email-outreach
      when: "User selects email as outreach channel"
      passes: qualified-prospect-list, personalized-email-sequences
    - skill: linkedin-outreach
      when: "User selects LinkedIn as outreach channel"
      passes: qualified-prospect-list
    - skill: hiring-signal-outreach
      when: "User selects hiring signals as a source"
      passes: company-list, your-company-context
    - skill: funding-signal-outreach
      when: "User selects funding signals as a source"
      passes: company-list, your-company-context
    - skill: news-signal-outreach
      when: "User selects news signals as a source"
      passes: company-list, your-company-context
    - skill: leadership-change-outreach
      when: "User selects leadership change signals as a source"
      passes: company-list, your-company-context
    - skill: champion-move-outreach
      when: "User selects champion tracking as a source"
      passes: people-list, your-company-context
  capabilities: [web-search, contact-finding, email-drafting, campaign-export]
---

# Setup Outreach Campaign

The single entry point for launching an outbound campaign from scratch. Instead of manually configuring ICP definitions, picking signal sources, finding contacts, and drafting sequences across multiple skills — this composite walks through the entire process in one session and wires up the right downstream skills automatically.

**Why this exists:** Most users don't know which signal composite to start with. They just know "I want to run outreach." This skill asks the right questions, picks the right approach, builds the prospect list, drafts the sequences, and hands off to the outreach tool — all in one flow.

## When to Auto-Load

Load this composite when:
- User says "set up an outreach campaign", "launch outbound", "build a campaign", "I want to start doing outreach"
- User wants to go from zero to a running outreach campaign in one session
- User has a new product/company and needs to define ICP + build their first campaign
- User says "help me find and reach out to prospects"

---

## Step 0: Company Context & ICP Definition

**Purpose:** Understand what the user sells, who they sell to, and what makes a good prospect. This is the foundation everything else builds on.

### Questions to Collect

#### Your Product

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What does your company do? (1-2 sentences) | Core positioning for outreach | `company_description` |
| What problem do you solve? | Email hook — the pain point you address | `pain_point` |
| What's your product category? | Signal matching | `product_category` |
| Name 2-3 proof points (customers, metrics, case studies) | Credibility in outreach | `proof_points` |
| What's your key differentiator vs. alternatives? | Competitive angle | `differentiator` |

#### Your ICP

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What job titles do you sell to? (decision makers) | Contact finding + email angle | `buyer_titles` |
| What job titles champion your product internally? | Secondary contacts | `champion_titles` |
| What industries do you target? | Company filtering | `target_industries` |
| What company sizes? (employee count or revenue) | Company filtering | `target_company_sizes` |
| Any geographic focus? | Company filtering | `target_geographies` |
| Any hard disqualifiers? (industries, company types to exclude) | Negative filtering | `disqualifiers` |

#### Outreach Preferences

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What outreach channels? | Email / LinkedIn / Both | `outreach_channels` |
| What outreach tool do you use? | Export formatting | `email_tool` (Smartlead, Instantly, CSV, etc.) |
| LinkedIn outreach tool? (if applicable) | Export formatting | `linkedin_tool` (Dripify, Expandi, CSV, etc.) |
| Preferred tone? | Sequence style | `tone` (casual-professional, thought-leader, direct, formal) |
| How many touches per sequence? | Sequence length | `sequence_touches` (default: 3) |
| Any existing email templates or angles that work? | Reuse what's proven | `existing_templates` |

**Store config in:** `clients/<client-name>/config/outreach-campaign.json`

### Human Checkpoint

```
## Campaign Configuration

Company: {company_description}
Problem solved: {pain_point}
Proof points: {proof_points}

ICP:
- Titles: {buyer_titles}
- Industries: {target_industries}
- Company size: {target_company_sizes}
- Geography: {target_geographies}

Outreach:
- Channels: {outreach_channels}
- Email tool: {email_tool}
- Tone: {tone}
- Touches: {sequence_touches}

Does this look right? (Y/n)
```

---

## Step 1: Select Signal Sources & Build Prospect List

**Purpose:** Determine where prospects will come from and build the initial list. The user can bring their own list or we generate one from signal sources.

### Input Contract

```
icp_criteria: {
  buyer_titles: string[]
  champion_titles: string[]
  target_industries: string[]
  target_company_sizes: string[]
  target_geographies: string[]
  disqualifiers: string[]
}
your_company: {
  company_description: string
  pain_point: string
  product_category: string
}
```

### Process

1. **Ask where prospects come from:**

   | Source | Description | When to Use |
   |--------|-------------|-------------|
   | **Existing list** | User has a CSV, CRM export, or Supabase list | They already have targets — skip to enrichment |
   | **Signal-based discovery** | Find companies showing buying signals | They need to build a list from scratch |
   | **LinkedIn prospecting** | Find people engaging with relevant topics on LinkedIn | They want warm LinkedIn-first outreach |
   | **Hybrid** | Existing list + signal-based expansion | They have some targets and want more |

2. **If signal-based discovery, select which signals to monitor:**

   Present the signal menu and recommend based on the user's product:

   | Signal | Best For | Downstream Skill |
   |--------|----------|-----------------|
   | **Hiring signals** | Products that replace or augment a hire | `hiring-signal-outreach` |
   | **Funding signals** | Products sold to growing/well-funded companies | `funding-signal-outreach` |
   | **News signals** | Products relevant to companies in the news (launches, expansions, challenges) | `news-signal-outreach` |
   | **Leadership changes** | Products sold to new leaders rebuilding their stack | `leadership-change-outreach` |
   | **Champion tracking** | Companies with existing relationships (past buyers, users who left) | `champion-move-outreach` |

   **Recommend signals based on product type:**
   - SaaS tools replacing manual work → Hiring signals (primary) + Funding signals (secondary)
   - Enterprise sales → Leadership changes (primary) + Funding signals (secondary)
   - SMB tools → Funding signals (primary) + News signals (secondary)
   - Existing customer base → Champion tracking (primary) + any other signal (secondary)

3. **If existing list, ingest and validate:**
   - Accept CSV, spreadsheet, or manual input
   - Required fields: company name, domain
   - Optional fields: industry, size, any existing contact info
   - Validate domains are reachable
   - Deduplicate

4. **If LinkedIn prospecting:**
   - Collect target topics, competitor names, KOLs to monitor
   - Hand off to `linkedin-outreach-campaign` composite
   - Return here for email follow-up layer if multi-channel

### Output Contract

```
prospect_source: "existing_list" | "signal_discovery" | "linkedin" | "hybrid"
selected_signals: string[]          # Which signals to run
companies: [
  {
    name: string
    domain: string
    source: string                  # "uploaded", "hiring_signal", "funding_signal", etc.
    industry: string | null
    size: string | null
  }
]
campaign_target_count: integer
```

### Human Checkpoint

```
## Prospect Source

Source: {prospect_source}
Signals selected: {selected_signals}
Companies: {count}

| Company | Domain | Source | Industry |
|---------|--------|-------|----------|
| Acme Corp | acme.com | Hiring signal | SaaS |
| Beta Inc | beta.io | Uploaded | Fintech |
| ... | ... | ... | ... |

Proceed to enrichment and contact finding? (Y/n)
```

---

## Step 2: Enrich Companies & Find Contacts

**Purpose:** Research each company for relevance, find the right people to contact, and get their email addresses.

### Input Contract

```
companies: [...]                     # From Step 1
buyer_titles: string[]               # From config
champion_titles: string[]            # From config
max_contacts_per_company: integer     # Default: 3
```

### Process

1. **Company enrichment** — For each company, gather:
   - What the company does (1-2 sentences)
   - Industry classification
   - Employee count
   - Location/HQ
   - Recent news or signals (funding, hiring, product launches)
   - Why they might need your product (relevance reasoning)

2. **ICP scoring** — Score each company against ICP criteria:
   - **Strong fit:** Matches industry, size, and geography. Clear use case.
   - **Moderate fit:** Matches 2 of 3 criteria. Likely use case.
   - **Weak fit:** Matches 1 criterion. Possible use case.
   - **No fit:** Doesn't match ICP. Drop with reason.

3. **Contact finding** — For each company that passes ICP scoring:
   - Search for people with `buyer_titles` first (decision makers)
   - Then `champion_titles` (internal advocates)
   - For each person, find: name, title, email, LinkedIn URL
   - Cap at `max_contacts_per_company`

4. **Email verification** — Flag email confidence:
   - **Verified:** Email confirmed deliverable
   - **Likely:** Pattern-matched email (firstname@domain.com)
   - **Not found:** Route to LinkedIn channel

### Output Contract

```
enriched_companies: [
  {
    company: {
      name: string
      domain: string
      description: string
      industry: string
      employee_count: string
      location: string
      icp_score: "strong" | "moderate" | "weak"
      relevance_reasoning: string
    }
    contacts: [
      {
        full_name: string
        first_name: string
        last_name: string
        title: string
        email: string | null
        linkedin_url: string | null
        role_type: "buyer" | "champion"
        email_confidence: "verified" | "likely" | "not_found"
      }
    ]
  }
]
dropped_companies: [
  { name: string, domain: string, drop_reason: string }
]
```

### Human Checkpoint

```
## Company Enrichment & Contacts

### Strong Fit ({count} companies)
| Company | Industry | Size | Contacts Found | Top Contact |
|---------|----------|------|---------------|-------------|
| Acme Corp | SaaS | 200 | 3 | Jane Doe, VP Sales |
| ... | ... | ... | ... | ... |

### Moderate Fit ({count} companies)
| ... |

### Dropped ({count} companies)
| Company | Reason |
|---------|--------|
| TinyCo | Below minimum size |

Total: {X} contacts across {Y} companies

Approve before we draft sequences? (Y/n)
```

---

## Step 3: Draft Personalized Sequences

**Purpose:** For each contact, draft a personalized outreach sequence. The sequence framework adapts based on the signal source that brought this company in and the contact's role type.

### Input Contract

```
enriched_companies: [...]            # From Step 2
your_company: {
  company_description: string
  pain_point: string
  proof_points: string[]
  differentiator: string
}
sequence_config: {
  touches: integer                   # From config (default: 3)
  timing: integer[]                  # Default: [1, 5, 12]
  tone: string                      # From config
  outreach_channels: string[]       # From config
}
```

### Process

1. **Select framework based on signal source:**

   | Source | Framework | Hook Strategy |
   |--------|-----------|--------------|
   | Hiring signal | Signal-Proof-Ask | Reference the job posting they're hiring for |
   | Funding signal | Trigger-Proof-Ask | Reference the funding round |
   | News signal | Relevance-Proof-Ask | Reference the news event |
   | Leadership change | Congrats-Proof-Ask | Reference the new appointment |
   | Uploaded list (no signal) | Pain-Proof-Ask | Lead with the pain point your product solves |
   | LinkedIn signal | Comment-Reference-Ask | Reference their LinkedIn activity |

2. **Adapt email angle by role type:**

   | Role Type | Angle | Example |
   |-----------|-------|---------|
   | **Buyer** | ROI / business outcome | "Companies like yours are saving X by..." |
   | **Champion** | Operational pain relief | "Your team spends X hours on... there's a faster way" |

3. **Draft each touch:**

   | Touch | Day | Purpose | Word Count |
   |-------|-----|---------|------------|
   | Touch 1 | 1 | Hook with signal/pain + proof point + soft ask | 50-90 words |
   | Touch 2 | 5 | Different angle or proof point + specific ask | 30-50 words |
   | Touch 3 | 12 | Social proof or breakup + final ask | 20-40 words |

4. **If multi-channel (email + LinkedIn):**
   - Draft LinkedIn connection request (300 chars max) referencing the same signal
   - Draft 2-3 LinkedIn follow-up messages
   - Coordinate timing: send connection request Day 1, email Touch 1 Day 2 (don't hit both channels simultaneously)

5. **Follow `email-drafting` skill hard rules:**
   - No filler words ("just", "honestly", "actually")
   - No rhetorical questions as openers
   - No "I hope this email finds you well" or similar
   - Subject lines under 6 words
   - Every sentence earns its place

### Output Contract

```
email_sequences: [
  {
    contact: {
      full_name: string
      email: string
      title: string
      role_type: string
      company_name: string
    }
    signal_source: string
    sequence: [
      {
        touch_number: integer
        send_day: integer
        channel: "email" | "linkedin"
        subject: string | null           # Email only
        body: string
        framework: string
        personalization_elements: {
          signal_hook: string             # What signal/pain was referenced
          proof_point: string             # What credibility was used
          company_relevance: string       # Why their company specifically
        }
        word_count: integer
      }
    ]
  }
]
linkedin_sequences: [                    # Only if multi-channel
  {
    contact: {
      full_name: string
      linkedin_url: string
      title: string
      company_name: string
    }
    connection_request: string           # 300 chars max
    followups: [
      {
        step: string
        send_day: integer
        message: string
        character_count: integer
      }
    ]
  }
]
```

### Human Checkpoint

Present 3-5 sample sequences covering different signal sources and role types:

```
## Sample Sequences for Review

### Acme Corp — Jane Doe, VP Sales (Buyer)
Signal: Hiring 2x SDRs | Framework: Signal-Proof-Ask

**Email Touch 1 — Day 1**
Subject: Those 2 SDR roles
> Hi Jane — noticed Acme is hiring two SDRs. Companies like [customer]
> found they could handle the same pipeline with one SDR plus [product].
> Worth a 15-min look?

**Email Touch 2 — Day 5**
Subject: Quick math on the SDR hires
> One more thought: two SDRs fully loaded is ~$140K/year.
> [Product] covers the same call volume for a fraction of that.
> [Customer] saw the numbers in 30 days. Want me to share the case study?

**Email Touch 3 — Day 12**
Subject: Last note
> Totally understand if the timing isn't right. If the SDR hiring
> is still in play, happy to show what [customer] did instead.
> Either way — no hard feelings.

---

### Beta Inc — Tom Lee, Director Ops (Champion)
Signal: Uploaded list (no signal) | Framework: Pain-Proof-Ask

**Email Touch 1 — Day 1**
Subject: {pain_point} at Beta
> [sequence content]

---

Approve these samples? I'll generate the rest in the same style.
```

---

## Step 4: Review & Finalize Campaign

**Purpose:** Final review of the complete campaign before export. Catch any issues, make last-minute edits, and confirm the campaign is ready.

### Process

1. **Campaign summary:**
   - Total contacts and companies
   - Breakdown by signal source
   - Breakdown by channel (email vs. LinkedIn)
   - Sequence structure and timing
   - Estimated send schedule

2. **Quality checks:**
   - No duplicate contacts across companies
   - All emails have valid-looking addresses
   - Subject lines are unique (no copy-paste feel)
   - Personalization elements are present in every touch
   - Word counts within guidelines
   - LinkedIn messages under character limits

3. **Final edits:**
   - Allow user to adjust tone, timing, or specific sequences
   - Swap proof points if user prefers different ones
   - Add/remove contacts

### Human Checkpoint

```
## Campaign Review

### Overview
- Companies: {X}
- Contacts: {Y}
- Channel: {email/linkedin/both}
- Sequence: {touches} touches over {days} days

### Breakdown by Signal Source
| Source | Companies | Contacts |
|--------|----------|----------|
| Hiring signal | X | Y |
| Uploaded list | X | Y |
| ... | ... | ... |

### Breakdown by Role Type
| Role | Count |
|------|-------|
| Buyer | X |
| Champion | Y |

### Quality Check
- Unique subject lines: PASS
- Personalization in all touches: PASS
- Word counts within range: PASS
- No duplicate contacts: PASS

Everything look good? Ready to export? (Y/n)
```

---

## Step 5: Export & Launch

**Purpose:** Package the campaign for the user's outreach tool and launch.

### Process

1. **Generate export file(s):**

   **For email campaigns:**
   - Format CSV for the configured `email_tool`:
     - **Smartlead:** `email, first_name, last_name, company, custom1 (subject_1), custom2 (body_1), custom3 (subject_2), ...`
     - **Instantly:** `email, first_name, last_name, company_name, personalization`
     - **Outreach.io:** API-ready JSON with sequence steps
     - **Lemlist:** `email, firstName, lastName, companyName, icebreaker`
     - **CSV (generic):** `email, first_name, last_name, company, title, subject_1, body_1, subject_2, body_2, subject_3, body_3`

   **For LinkedIn campaigns:**
   - Format CSV for the configured `linkedin_tool`:
     - **Dripify:** `Profile URL, Note, Message 1, Message 2, Message 3`
     - **Expandi:** `LinkedIn URL, Connection message, Follow-up #1, Follow-up #2`
     - **CSV (generic):** `linkedin_url, first_name, last_name, connection_request, followup_1, followup_2, followup_3`

2. **Save export files:**
   - Email: `output/{campaign-name}-email-{YYYY-MM-DD}.csv`
   - LinkedIn: `output/{campaign-name}-linkedin-{YYYY-MM-DD}.csv`

3. **Log to Supabase** (if configured):
   - Insert records into `outreach_log` with campaign metadata
   - Update `last_contacted` on people records
   - Activate 84-day cooldown across channels

### Output Contract

```
campaign_package: {
  campaign_name: string
  email_campaign: {
    tool: string
    file_path: string
    contact_count: integer
    sequence_touches: integer
    estimated_send_days: integer
  } | null
  linkedin_campaign: {
    tool: string
    file_path: string
    contact_count: integer
    sequence_structure: string
  } | null
  total_contacts: integer
  total_companies: integer
  signal_breakdown: {
    [signal_name]: integer
  }
  next_actions: string[]
}
```

### Human Checkpoint

```
## Campaign Ready to Launch

Campaign: {campaign_name}
Created: {date}

### Email Campaign
- Tool: {email_tool}
- File: {file_path}
- Contacts: {count}
- Sequence: {touches} touches over {days} days

### LinkedIn Campaign
- Tool: {linkedin_tool}
- File: {file_path}
- Contacts: {count}
- Sequence: Connection + {followup_count} follow-ups

### Total
- {total_contacts} contacts across {total_companies} companies
- Signals used: {signal_list}

### Next Steps
1. Import {email_file} into {email_tool}
2. Import {linkedin_file} into {linkedin_tool}
3. Set sending schedule (recommended: {X} emails/day, {Y} connections/day)
4. Monitor replies and move responders to CRM

Ready to finalize? (Y/n)
```

---

## Execution Summary

| Step | Tool Dependency | Human Checkpoint | Typical Time |
|------|----------------|-----------------|--------------|
| 0. Company context & ICP | None | Confirm configuration | 5 min |
| 1. Signal sources & prospect list | Configurable (signals, CSV, LinkedIn) | Review prospect sources | 3-5 min |
| 2. Enrich & find contacts | Web search + contact finder | Approve enriched list | 5-10 min |
| 3. Draft sequences | None (LLM reasoning) | Review sample sequences | 5-10 min |
| 4. Review & finalize | None | Final quality check | 2-3 min |
| 5. Export & launch | CSV generation | Launch approval | 1-2 min |

**Total human review time: ~20-35 minutes**

---

## Tips

- **Start with one signal source.** Don't try to run all five signal types in the first campaign. Pick the one most relevant to your product, prove it works, then layer on more.
- **Quality over quantity.** 50 highly personalized emails will outperform 500 generic ones. This skill prioritizes personalization depth.
- **Let the ICP definition do the filtering.** The tighter your ICP, the smaller but higher-quality your prospect list. A 5% reply rate on 50 perfect-fit prospects beats a 0.5% rate on 500 mediocre ones.
- **Multi-channel compounds results.** Email + LinkedIn together typically yields 2-3x the reply rate of either alone. The LinkedIn connection request warms them up before the email arrives.
- **Reuse what works.** After the first campaign, save winning subject lines, proof points, and angles. Future campaigns should build on proven messaging, not start from scratch.
- **Monitor and iterate.** After 50-100 sends, check open rates, reply rates, and positive reply rates. Adjust subject lines, proof points, and CTAs based on data. This skill sets up the campaign — the iteration happens in follow-up runs.
- **Don't skip the human checkpoints.** Each checkpoint exists because outreach quality drops dramatically without human review. Automated-and-sent is worse than reviewed-and-sent.
