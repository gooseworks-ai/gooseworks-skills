---
name: end-to-end-hiring-signal
version: 1.0.0
description: >
  Full-pipeline hiring signal composite. Monitors target companies for job
  postings your product replaces or augments, finds the right contacts (hiring
  managers, buyers, champions), drafts personalized outreach using the job
  posting as the hook, and hands off to the configured outreach tool. Bundles
  every capability skill needed so nothing is missing at runtime.
tags: [lead-generation, outreach]

graph:
  provides:
    - companies-with-hiring-signals
    - qualified-hiring-targets
    - contact-list
    - personalized-email-sequences
    - outreach-campaign-package
  requires:
    - company-list
    - your-company-context
  connects_to:
    - skill: cold-email-outreach
      when: "Sequences are approved and ready for launch"
      passes: contact-list, personalized-email-sequences
    - skill: linkedin-outreach
      when: "User wants LinkedIn outreach alongside or instead of email"
      passes: contact-list
  capabilities: [web-search, job-search, contact-finding, email-drafting, social-scraping]
---

# End-to-End Hiring Signal

Full pipeline from company list to launched outreach campaign, powered by hiring signals. This composite installs and orchestrates every skill needed — you don't need to install anything else.

**What it does:** Takes a list of target companies → detects job postings your product replaces or augments → finds the right people → drafts personalized outreach using the job posting as the hook → hands off to your outreach tool.

**Why hiring signals work:** When a company posts a job, they've already acknowledged the problem your product solves. They've budgeted for it (headcount is budget). Your outreach arrives at exactly the moment they're thinking about this problem.

## When to Auto-Load

Load this composite when:
- User says "run the full hiring signal pipeline", "find companies hiring for roles we replace and reach out"
- User has a company list and wants end-to-end hiring signal outreach
- An upstream workflow triggers a hiring signal sweep with outreach

## Included Skills

| Skill | Role in Pipeline |
|-------|-----------------|
| `hiring-signal-outreach` | Core workflow — signal detection, qualification, email drafting |
| `company-contact-finder` | Finds contacts at target companies |
| `contact-cache` | Deduplicates and caches contacts across runs |
| `cold-email-outreach` | Sends sequences via configured outreach tool |
| `email-drafting` | Email copy rules and frameworks |
| `linkedin-outreach` | LinkedIn connection/message sequences |
| `hacker-news-scraper` | Supplements signal detection via HN job posts |
| `reddit-scraper` | Supplements signal detection via Reddit hiring threads |
| `twitter-scraper` | Supplements signal detection via Twitter/X hiring announcements |

---

## Pipeline Overview

### Step 0: Configuration (One-Time)

Collect role mapping, signal detection config, contact finding config, outreach config, and company context. See `hiring-signal-outreach` SKILL.md for the full configuration table.

Key config items:
- **roles_replaced** — Job titles your product eliminates (strongest signal)
- **roles_augmented** — Job titles your product makes more effective
- **buyer_titles / champion_titles / user_titles** — Who to contact
- **jd_keywords** — Job description keywords indicating relevance
- **job_search_tool** — LinkedIn Jobs, Indeed, Apollo, Google Jobs, or web search
- **contact_tool** — Apollo, LinkedIn, Clearbit, or web search
- **outreach_tool** — Smartlead, Instantly, Outreach.io, Lemlist, or CSV

### Step 1: Detect Hiring Signals

For each company, search for active job postings matching `roles_replaced`, `roles_augmented`, or `jd_keywords`.

**Social signal supplement:** Use `hacker-news-scraper`, `reddit-scraper`, and `twitter-scraper` to catch hiring announcements that don't appear on job boards — "We're hiring!" tweets, HN "Who's Hiring" threads, and subreddit job posts.

Classify each posting as **replaces** (strongest), **augments** (good), or **keyword_match** (verify).

**Human checkpoint:** Review companies with hiring signals before proceeding.

### Step 2: Qualify & Prioritize

Rank companies into tiers:
- **Tier 1 (Act Today):** "Replaces" signal + posted within 7 days
- **Tier 2 (Act This Week):** "Replaces" 7-14 days old, or "Augments" <7 days with multiple postings
- **Tier 3 (Queue):** Weaker signals worth reaching out on

Generate outreach angle and recommended framing (replace / complement / scale) per company.

**Human checkpoint:** Approve tier rankings before contact finding.

### Step 3: Find Contacts

Using `company-contact-finder` and `contact-cache`:

1. **Hiring manager** — Person who posted or owns the role (strongest contact)
2. **Buyer** — Budget holder (buyer_titles)
3. **Champion** — Feels the pain daily (champion_titles)
4. **User** — Would operate the product (user_titles)

Cap at 3-5 contacts per company. Prioritize: hiring manager > buyer > champion > user.

**Human checkpoint:** Approve contact list before drafting.

### Step 4: Draft Personalized Emails

Using `email-drafting` rules, adapt framework by framing:
- **Replace** → Signal-Proof-Ask ("Before you fill that role…")
- **Complement** → BAB ("Your new hire will be 3x faster with…")
- **Scale** → PAS ("You need 5 people — or 1 person + our product")

Adapt angle by role_type (hiring manager, buyer, champion, user). Three-touch sequence per contact.

**Human checkpoint:** Review sample sequences before bulk generation.

### Step 5: Launch Campaign

Package contacts + sequences for the configured outreach tool via `cold-email-outreach` or `linkedin-outreach`. Export CSV if no tool is configured.

**Human checkpoint:** Final approval before launch.

---

## Execution Summary

| Step | Skills Used | Human Checkpoint |
|------|------------|-----------------|
| 0. Config | None | First run only |
| 1. Detect | hiring-signal-outreach, hacker-news-scraper, reddit-scraper, twitter-scraper | Review signals |
| 2. Qualify | hiring-signal-outreach | Approve tiers |
| 3. Contacts | company-contact-finder, contact-cache | Approve contacts |
| 4. Drafts | email-drafting, hiring-signal-outreach | Review samples |
| 5. Launch | cold-email-outreach, linkedin-outreach | Final approval |

---

## Tips

- **"Replaces" signals are gold.** They're literally budgeting for what you sell.
- **Time outreach to posting age.** Day 1-7: "Before you start interviewing." Day 7-14: "While you're evaluating." Day 14+: "Before you extend an offer."
- **Multiple postings for the same role = scaling signal.** 3x BDC reps means the cost comparison is 3x more compelling.
- **The hiring manager is your best first contact** — they own the problem. Separately reaching the buyer with an ROI angle creates a pincer effect.
- **Supplement job boards with social scrapers.** Many companies announce hiring on Twitter/X and HN before listings go live on LinkedIn.
