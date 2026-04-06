---
name: linkedin-outreach-campaign
version: 1.0.0
description: >
  End-to-end LinkedIn outreach composite. Finds prospects through LinkedIn
  engagement signals (post comments, topic discussions, competitor mentions),
  researches their profiles and activity, qualifies by ICP fit and LinkedIn
  activity level, drafts personalized connection requests and follow-up
  sequences, and exports for the user's LinkedIn outreach tool. Tool-agnostic —
  works with Dripify, Botdog, Expandi, PhantomBuster, or manual CSV.
tags: [outreach]

graph:
  provides:
    - linkedin-prospect-list         # Qualified prospects discovered via LinkedIn signals
    - linkedin-message-sequences     # Personalized connection requests + follow-ups + InMail
    - linkedin-campaign-export       # Tool-ready CSV for the user's LinkedIn outreach tool
  requires:
    - target-topics                  # Topics, pain points, or keywords to find prospects around
    - your-company-context           # What you sell, ICP, proof points
  connects_to:
    - skill: linkedin-post-research
      when: "Finding relevant LinkedIn posts and conversations to mine for prospects"
      passes: target-topics
    - skill: linkedin-commenter-extractor
      when: "Extracting people who engaged with relevant posts"
      passes: post-urls
    - skill: linkedin-profile-post-scraper
      when: "Researching prospect profiles and recent activity"
      passes: linkedin-urls
    - skill: linkedin-outreach
      when: "Building and exporting the campaign CSV"
      passes: linkedin-prospect-list, linkedin-message-sequences
  capabilities: [linkedin-research, contact-enrichment, message-drafting, campaign-export]
---

# LinkedIn Outreach Campaign

Finds prospects directly on LinkedIn by mining engagement signals — who's commenting on relevant posts, discussing pain points you solve, engaging with competitor content, or following KOLs in your space. Researches each prospect's profile and recent activity, qualifies by ICP fit and signal strength, then drafts personalized LinkedIn sequences using what they've actually said and done on the platform.

**Why LinkedIn-native prospecting works:** Instead of starting with a cold list and hoping someone's on LinkedIn, you start with people who are *already talking about the problem you solve*. The connection request references something they actually said or did. It's not cold — it's warm by context.

## When to Auto-Load

Load this composite when:
- User says "find prospects on LinkedIn", "LinkedIn outreach campaign", "find people talking about X on LinkedIn"
- User wants to build a LinkedIn campaign from scratch (no existing lead list)
- User wants to find and reach people engaging with competitor content on LinkedIn
- User has topics or pain points and wants to find prospects organically on LinkedIn

---

## Step 0: Configuration (One-Time Setup)

On first run for a client/user, collect and store these preferences. Skip on subsequent runs.

### ICP Definition

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What does your product do? (1-2 sentences) | Match prospects to relevance | `company_description` |
| What problem do you solve? | Identify pain-point discussions | `pain_point` |
| What titles are you targeting? | Filter prospects by role | `target_titles` |
| What industries? | Filter by industry | `target_industries` |
| What company sizes? | Filter by company size | `target_company_sizes` |
| Any geographic focus? | Filter by location | `target_locations` |

### Signal Discovery Config

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What topics should we search for? (pain points, industry terms, use cases) | LinkedIn post search queries | `search_topics` |
| Any competitor names to monitor? | Find people engaging with competitors | `competitor_names` |
| Any KOLs or influencers in your space? | Mine their comment sections | `kol_names` |
| Any LinkedIn hashtags to track? | Additional signal source | `tracked_hashtags` |
| How far back should we look for activity? | Recency filter | `lookback_days` (default: 30) |

### Outreach Config

| Question | Options | Stored As |
|----------|---------|-----------|
| Which LinkedIn outreach tool? | Dripify / Botdog / Expandi / PhantomBuster / Manual CSV | `outreach_tool` |
| Preferred tone? | Casual Professional / Thought Leader / Provocative / Enterprise Formal / Custom | `tone_preset` |
| Follow-ups after connection? | Default: 3 | `followup_count` |
| Timing between messages? | Default: Day 0 / Day 3 / Day 7 / Day 14 | `sequence_timing` |
| Include InMail fallback? | Default: yes | `include_inmail` |

### Proof Points

| Question | Purpose | Stored As |
|----------|---------|-----------|
| Name 2-3 customers or case studies | Social proof in follow-ups | `proof_points` |
| Key metric or result to reference? | Credibility anchor | `key_metric` |
| Any content (articles, reports) to share? | Value-first follow-up material | `shareable_content` |

**Store config in:** `clients/<client-name>/config/linkedin-outreach-campaign.json` or equivalent.

---

## Step 1: Discover Prospects via LinkedIn Signals

**Purpose:** Find people actively discussing topics relevant to your product by mining LinkedIn posts, comments, and engagement.

### Input Contract

```
search_topics: string[]           # From config
competitor_names: string[]        # From config
kol_names: string[]               # From config
tracked_hashtags: string[]        # From config
lookback_days: integer            # From config (default: 30)
target_titles: string[]           # From config — used to filter discovered people
```

### Process

Run these discovery channels in parallel:

1. **Pain-point post mining** — Use `linkedin-post-research` to find posts discussing `search_topics`:
   - Search each topic as a keyword query
   - Collect posts with high engagement (10+ comments)
   - Extract post URLs for commenter mining

2. **Competitor content mining** — Search for posts by or mentioning `competitor_names`:
   - Find posts from competitor company pages or employees
   - Find posts where users mention competitors by name
   - People engaging with competitor content are actively evaluating solutions

3. **KOL comment mining** — For each person in `kol_names`:
   - Use `linkedin-profile-post-scraper` to get their recent posts
   - Collect high-engagement posts relevant to your space
   - These comment sections are goldmines of ICP prospects

4. **Hashtag mining** — Search posts under `tracked_hashtags`:
   - Find active discussions in your space
   - Collect post URLs for commenter extraction

5. **Extract commenters** — For all collected post URLs, use `linkedin-commenter-extractor`:
   - Pull commenter name, title, company, LinkedIn URL, and comment text
   - The comment text is your personalization signal — save it

6. **Deduplicate** — Merge all discovered people, remove duplicates by LinkedIn URL. Track which signals each person triggered (they may appear in multiple channels).

### Output Contract

```
discovered_prospects: [
  {
    person: {
      full_name: string
      title: string
      company: string
      linkedin_url: string
      location: string | null
    }
    signals: [
      {
        type: "pain_comment" | "competitor_engagement" | "kol_engagement" | "hashtag_discussion"
        source_post_url: string
        source_post_topic: string
        comment_text: string | null        # Their actual words — best personalization data
        engagement_type: "comment" | "like" | "repost"
        discovered_date: string
      }
    ]
    signal_count: integer                  # How many signals this person triggered
    strongest_signal_type: string
  }
]
```

### Human Checkpoint

```
## Prospects Discovered

Discovery channels:
- Pain-point posts: Found X posts, extracted Y commenters
- Competitor content: Found X posts, extracted Y commenters
- KOL comments: Found X posts, extracted Y commenters
- Hashtag discussions: Found X posts, extracted Y commenters

Total unique prospects (deduplicated): Z

| Name | Title | Company | Signals | Strongest Signal | Sample Comment |
|------|-------|---------|---------|-----------------|----------------|
| Jane Smith | VP Ops | Acme | 3 | Pain comment | "We've been struggling with..." |
| Tom Lee | Director Sales | Beta | 2 | Competitor engagement | "Switched from [competitor] to..." |
| ... | ... | ... | ... | ... | ... |

Proceed to qualification? (Y/n)
```

---

## Step 2: Qualify & Prioritize

**Purpose:** Filter discovered prospects against ICP criteria and rank by signal strength and outreach readiness. Pure LLM reasoning — no tool dependency.

### Input Contract

```
discovered_prospects: [...]        # From Step 1
target_titles: string[]            # From config
target_industries: string[]        # From config
target_company_sizes: string[]     # From config
target_locations: string[]         # From config
```

### Process

For each prospect, evaluate:

| Criterion | Weight | How to Assess |
|-----------|--------|---------------|
| **Title match** | Highest | Does their title match or map to `target_titles`? VP Ops ≈ Director Operations ≈ Head of Ops. |
| **Signal strength** | High | Pain comment > competitor engagement > KOL engagement > hashtag discussion. Multiple signals > single signal. |
| **Comment substance** | High | Did they say something specific about the pain, or just "great post"? Substantive comments = stronger signal. |
| **Company fit** | Medium | Does their company match `target_industries` and `target_company_sizes`? |
| **Recency** | Medium | Activity within 7 days > 14 days > 30 days. Recent = top of mind. |
| **Location fit** | Low | Match `target_locations` if specified. |

### Scoring

- **Tier 1 (Act Today):** Title match + substantive pain comment or competitor engagement within 7 days. They're actively thinking about the problem.
- **Tier 2 (Act This Week):** Title match + any signal within 14 days. Good fit, moderate urgency.
- **Tier 3 (Queue):** Partial title match or weaker signals. Worth connecting but lower priority.
- **Drop:** No title match and no substantive signal. Generic "great post" commenters with no ICP fit.

For each qualified prospect, generate:
- **Relevance reasoning:** Why this person is worth reaching out to
- **Personalization hook:** The specific thing they said or did that you'll reference in the connection request
- **Recommended angle:** What framing to use based on their signal type

### Output Contract

```
qualified_prospects: [
  {
    ...discovered_prospect_fields,
    priority_tier: "tier_1" | "tier_2" | "tier_3"
    relevance_reasoning: string
    personalization_hook: string       # The specific comment/action to reference
    recommended_angle: "pain_based" | "competitor_switch" | "kol_mutual_interest" | "topic_peer"
  }
]
dropped_prospects: [
  { full_name: string, company: string, drop_reason: string }
]
```

### Human Checkpoint

```
## Qualification Results

### Tier 1 — Act Today (X prospects)
| Name | Title | Company | Signal | Hook |
|------|-------|---------|--------|------|
| Jane Smith | VP Ops | Acme | Pain comment 2d ago | "We've been struggling with manual carrier check calls" |

### Tier 2 — Act This Week (X prospects)
| ... |

### Tier 3 — Queue (X prospects)
| ... |

### Dropped (X prospects)
| Name | Reason |
|------|--------|
| ... | Generic engagement, no title match |

Approve this list before we research profiles?
```

---

## Step 3: Research Prospect Profiles

**Purpose:** Deep-research each qualified prospect's LinkedIn profile and recent posts to build a rich personalization layer beyond the initial signal.

### Input Contract

```
qualified_prospects: [...]          # From Step 2 (Tier 1 and Tier 2 only — skip Tier 3 for now)
max_profiles_to_research: integer   # Default: 50 (respect rate limits)
```

### Process

For each Tier 1 and Tier 2 prospect, use `linkedin-profile-post-scraper`:

1. **Scrape profile data:**
   - Current role and tenure
   - Previous roles (career trajectory)
   - Education
   - Headline and about section
   - Skills and endorsements

2. **Scrape recent posts (last 30 days):**
   - Topics they post about
   - Engagement levels on their posts
   - Tone and communication style (formal vs. casual — mirror it)

3. **Build personalization brief per prospect:**
   - **Primary hook:** The signal that discovered them (from Step 1)
   - **Secondary hooks:** Anything from their profile/posts that adds depth
     - Career move ("Congrats on the move to Acme 6 months ago")
     - Content they posted ("Your take on X was spot on")
     - Mutual connections or shared background
   - **Tone match:** How formal/casual they are on LinkedIn — mirror this in outreach
   - **Avoid:** Topics they seem passionate about that could backfire (politics, controversy)

### Output Contract

```
enriched_prospects: [
  {
    ...qualified_prospect_fields,
    profile: {
      headline: string
      current_role_tenure: string
      previous_company: string | null
      about_summary: string | null
    }
    recent_posts: [
      {
        topic: string
        engagement: integer
        date: string
      }
    ]
    personalization_brief: {
      primary_hook: string             # From discovery signal
      secondary_hooks: string[]        # From profile/post research
      tone_match: "casual" | "professional" | "formal"
      avoid_topics: string[]
    }
  }
]
```

### Human Checkpoint

```
## Profile Research Complete

Researched X profiles (Tier 1: Y, Tier 2: Z)

### Sample Personalization Briefs

**Jane Smith — VP Ops @ Acme (Tier 1)**
- Primary hook: Commented "We've been struggling with manual carrier check calls" on FreightWaves post
- Secondary: Joined Acme 8 months ago from FedEx. Posts about ops efficiency weekly.
- Tone: Casual professional. Uses contractions, short sentences.
- Angle: Pain-based — reference her comment directly

**Tom Lee — Director Sales @ Beta (Tier 1)**
- Primary hook: Engaged with [competitor] post about their new feature
- Secondary: Previously at a company that used your product category. Posts about sales automation.
- Tone: Thought-leader style. Long-form posts with data.
- Angle: Competitor switch — he's evaluating options

Ready to draft messages?
```

---

## Step 4: Draft Personalized LinkedIn Sequences

**Purpose:** For each enriched prospect, draft a personalized LinkedIn sequence: connection request + follow-ups + optional InMail. Every message references something specific to the prospect. Pure LLM reasoning.

### Input Contract

```
enriched_prospects: [...]          # From Step 3
your_company: {
  description: string
  pain_point: string
  proof_points: string[]
  key_metric: string
  shareable_content: string[]
}
sequence_config: {
  followup_count: integer          # Default: 3
  timing: integer[]                # Default: [0, 3, 7, 14]
  tone_preset: string              # From config
  include_inmail: boolean          # Default: true
}
```

### Process

1. **Select sequence template** based on the prospect's `recommended_angle`:

   | Angle | Template | Connection Request Hook |
   |-------|----------|------------------------|
   | `pain_based` | `pain-language.md` | Reference their exact comment about the pain |
   | `competitor_switch` | `competitor-engagement.md` | Reference the competitor content they engaged with |
   | `kol_mutual_interest` | `kol-engagement.md` | Reference the KOL and the topic |
   | `topic_peer` | `database-search.md` | Reference the topic they were discussing |

2. **Apply tone calibration:**
   - Start with the user's `tone_preset` from config
   - Adjust toward the prospect's `tone_match` from Step 3 (if they're casual, lean casual even if the preset is formal)
   - Load tone guidelines from `templates/tone-presets.json`

3. **Draft each message in the sequence:**

   **Connection Request (300 chars max):**
   - Open with the primary hook — reference their specific comment or engagement
   - One sentence of relevance — why connecting makes sense
   - No pitch, no CTA, no selling — just earn the accept
   - MUST be under 300 characters. Count every character. Rewrite if over — never truncate.

   **Follow-up 1 — Day 3 (value-first):**
   - Brief thanks for connecting (one clause)
   - Share something useful: an insight related to what they commented on, a relevant article from `shareable_content`, or an observation about their company
   - End with a question, not a pitch

   **Follow-up 2 — Day 7 (social proof):**
   - Reference a proof point or case study from `proof_points`
   - Connect it to their specific situation (their company, their role, the pain they mentioned)
   - Make a specific, low-commitment ask (15-min call, async question, or send them something)

   **Follow-up 3 — Day 14 (breakup):**
   - Acknowledge you've reached out a few times
   - One-line value recap tied to their original signal
   - Leave the door open without pressure
   - Shortest message in the sequence

   **InMail — Day 7 (for non-acceptors, if enabled):**
   - Subject: 200 chars max — curiosity-driven, references their signal
   - Body: 1,900 chars max — standalone pitch since they haven't connected
   - Must work cold — include full context, proof, and CTA

4. **Character limit enforcement:** After generating every message, count characters. If over the limit, rewrite. Never truncate.

### Output Contract

```
message_sequences: [
  {
    prospect: {
      full_name: string
      linkedin_url: string
      title: string
      company: string
      priority_tier: string
    }
    personalization: {
      primary_hook: string
      angle: string
      tone_match: string
    }
    sequence: [
      {
        step: "connection_request" | "followup_1" | "followup_2" | "followup_3" | "inmail"
        send_day: integer
        subject: string | null         # Only for InMail
        message: string
        character_count: integer
        personalization_used: string   # What specific detail was referenced
      }
    ]
  }
]
```

### Human Checkpoint

Present 3-5 sample sequences showing different angles and tiers:

```
## Sample Sequences for Review

### Jane Smith — VP Ops @ Acme (Tier 1, Pain-based)
Signal: Commented about struggling with manual carrier check calls

**Connection Request (Day 0)** — 247 chars
> Hey Jane — saw your comment on the FreightWaves post about carrier
> check calls. We've been solving that exact problem for logistics
> companies. Would love to connect and swap notes.

**Follow-up 1 (Day 3)**
> Thanks for connecting, Jane. Given what you mentioned about manual
> carrier calls — we just published data on how 3PL companies are
> cutting that process from 15 minutes to 30 seconds. Want me to
> send it over?

**Follow-up 2 (Day 7)**
> Quick one: [Customer] had the same challenge at Acme's scale.
> They automated 80% of carrier check calls in the first month.
> Worth a 15-min look at how they did it?

**Follow-up 3 (Day 14)**
> Last note from me, Jane. If carrier calls are still eating your
> team's time, happy to share what's working for similar companies.
> No rush — the offer stands.

---

### Tom Lee — Director Sales @ Beta (Tier 1, Competitor switch)
[similar format]

---

Approve these samples? I'll generate the rest in the same style.
```

---

## Step 5: Export & Handoff

**Purpose:** Package all sequences into a tool-ready format and export for the user's LinkedIn outreach tool. Delegates to the `linkedin-outreach` capability for tool-specific CSV formatting and Supabase logging.

### Input Contract

```
message_sequences: [...]           # From Step 4
outreach_tool: string              # From config
campaign_name: string              # From Phase 0 or auto-generated
```

### Process

1. **Generate universal CSV** with columns:
   ```
   linkedin_url, first_name, last_name, company, title, connection_request, followup_1, followup_2, followup_3, inmail_subject, inmail_body
   ```

2. **Format for selected tool** — apply column mapping per tool adapter (see `linkedin-outreach` capability for tool-specific formats):
   - **Dripify:** `Profile URL`, `Note`, `Message 1`, `Message 2`, `Message 3`
   - **Botdog:** `linkedin_profile_url`, `connection_note`, `message_1`, `message_2`, `message_3`
   - **Expandi:** `LinkedIn URL`, `Connection message`, `Follow-up #1`, `Follow-up #2`, `Follow-up #3`
   - **PhantomBuster:** `profileUrl`, `message` (separate CSVs per action)
   - **Manual:** Universal CSV format with instructions

3. **Save export file** to `skills/linkedin-outreach/output/{campaign-name}-{YYYY-MM-DD}.csv`

4. **Log to Supabase** (after user approval):
   - Insert records into `outreach_log` with `channel: "linkedin"`, `status: "exported"`
   - Update `last_contacted` on people records
   - Cooldown activates for 84 days across all channels

### Output Contract

```
campaign_package: {
  campaign_name: string
  tool: string
  file_path: string
  prospect_count: integer
  tier_breakdown: { tier_1: integer, tier_2: integer, tier_3: integer }
  sequence_structure: string       # e.g. "Connection + 3 follow-ups + InMail"
  signal_breakdown: {
    pain_comment: integer
    competitor_engagement: integer
    kol_engagement: integer
    hashtag_discussion: integer
  }
  next_action: string
}
```

### Human Checkpoint

```
## Campaign Ready

Campaign: {name}
Tool: {tool}
Prospects: X total (Tier 1: Y, Tier 2: Z)
Sequence: Connection + 3 follow-ups + InMail fallback
Timing: Day 0 → Day 14

Signal breakdown:
- Pain comments: X prospects
- Competitor engagement: Y prospects
- KOL engagement: Z prospects
- Topic discussions: W prospects

Export file: {file_path}

Ready to finalize and log? (Y/n)
```

---

## Execution Summary

| Step | Tool Dependency | Human Checkpoint | Typical Time |
|------|----------------|-----------------|--------------|
| 0. Config | None | First run only | 5 min (once) |
| 1. Discover | linkedin-post-research, linkedin-commenter-extractor | Review prospects found | 5-10 min |
| 2. Qualify | None (LLM reasoning) | Approve tier rankings | 2-3 min |
| 3. Research | linkedin-profile-post-scraper | Review personalization briefs | 3-5 min |
| 4. Draft | None (LLM reasoning) | Review sample sequences | 5-10 min |
| 5. Export | linkedin-outreach (CSV adapter) | Final launch approval | 1-2 min |

**Total human review time: ~20-30 minutes**

---

## Tips

- **Comments > likes.** Someone who wrote a substantive comment about a pain point is 10x more valuable than someone who liked a post. Prioritize commenters.
- **Mirror their tone.** If a prospect writes casually on LinkedIn, send a casual connection request. If they write long-form thought pieces, match that energy. Tone mismatch kills acceptance rates.
- **The connection request is everything.** On LinkedIn, the connection request is the gatekeeper. If they don't accept, nothing else matters. Spend 80% of your personalization effort on the 300-character connection note.
- **Don't reference the signal too literally.** "I saw you commented on X's post" is fine. "I saw you wrote 'We've been struggling with manual carrier check calls' on the FreightWaves post from March 12th" is creepy. Paraphrase and be natural.
- **Batch by signal type for consistency.** When reviewing samples in Step 4, review all pain-based sequences together, then all competitor-switch sequences. This helps you calibrate tone consistently within each angle.
- **Tier 3 prospects are great for InMail testing.** Since they're lower priority, use them to test InMail subject lines and copy before spending InMail credits on Tier 1 prospects.
- **Rate limits matter.** LinkedIn tools have daily connection request limits (typically 20-50/day). Start with Tier 1 prospects so your highest-value targets go out first.
