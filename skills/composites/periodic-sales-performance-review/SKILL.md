---
name: periodic-sales-performance-review
version: 1.0.0
description: >
  Periodic sales performance review composite. Pulls rep-level and team-level
  sales data from any CRM or tracking system, analyzes performance across a
  user-defined period (weekly, monthly, quarterly), and produces both an
  executive summary and a detailed diagnostic. Covers quota attainment, activity
  metrics, deal progression, win/loss patterns, rep-level benchmarking, coaching
  opportunities, and forecast accuracy. Tool-agnostic — works with any CRM
  (Salesforce, HubSpot, Pipedrive, Close, Supabase, CSV).
tags: [research]

graph:
  provides:
    - sales-performance-executive-summary   # Quick snapshot for leadership
    - sales-performance-detailed-report     # Full diagnostic with rep-level data
    - rep-coaching-priorities               # Per-rep coaching recommendations
    - forecast-accuracy-analysis            # How accurate were prior forecasts
  requires:
    - deal-data                             # Pipeline/deal data from CRM or database
    - activity-data                         # Calls, emails, meetings per rep
    - your-company-context                  # What you sell, team structure, quotas
  connects_to:
    - skill: pipeline-review
      when: "Review surfaces pipeline health concerns requiring deeper diagnostic"
      passes: deal-data, pipeline-stages
    - skill: sales-coaching
      when: "Review identifies reps needing coaching on specific skills"
      passes: rep-coaching-priorities
    - skill: cold-email-outreach
      when: "Review reveals reps with low activity or stalled pipeline needing re-engagement"
      passes: stalled-leads, underperforming-segments
    - skill: sequence-performance
      when: "Review shows outbound campaigns underperforming for specific reps"
      passes: campaign-ids, rep-campaign-metrics
  capabilities: [data-analysis, reporting]
---

# Periodic Sales Performance Review

Pulls rep-level and team-level sales data from whatever system the user tracks performance in, analyzes it over a chosen period, and produces a report that answers the questions a sales leader actually cares about: Are we going to hit the number? Who's carrying the team? Who needs help? Where are the coaching opportunities? Are our forecasts reliable?

**Two output modes:**
- **Executive summary:** 1-page snapshot. Quota attainment, top/bottom performers, red flags, green lights. What a VP Sales reads before the Monday standup.
- **Detailed diagnostic:** Full rep-by-rep breakdown, activity analysis, deal progression, win/loss patterns, forecast accuracy, and coaching recommendations.

Both are always produced. The executive summary sits at the top of the report.

## When to Auto-Load

Load this composite when:
- User says "sales performance review", "team performance report", "how's the team doing", "rep scorecard"
- User says "weekly sales review", "monthly performance review", "quarterly sales analysis"
- User says "who's hitting quota", "quota attainment report", "rep performance"
- An upstream workflow (Pipeline Ops, management cadence) triggers an end-of-period review
- User asks about forecast accuracy, rep productivity, or team-level trends

---

## Step 0: Configuration (One-Time Setup)

On first run, collect and store these preferences. Skip on subsequent runs.

### Data Source Config

| Question | Options | Stored As |
|----------|---------|-----------|
| Where do you track deals/pipeline? | Salesforce / HubSpot / Pipedrive / Close / Supabase / Google Sheets / CSV / Other | `crm_tool` |
| How do we access it? | API / Export CSV / MCP tools / Direct query | `access_method` |
| Where do you track activity data? (calls, emails, meetings) | Same CRM / Outreach / Salesloft / Gong / Separate tracker / Manual / Not tracked | `activity_source` |

### Team Structure

| Question | Purpose | Stored As |
|----------|---------|-----------|
| Who are your sales reps? (names) | Rep-level analysis | `rep_names` |
| Is there a team/pod structure? (e.g., SMB team, Enterprise team, SDR vs AE) | Segment analysis | `team_structure` |
| Who manages each rep? | Manager-level rollup | `managers` |

**Example team structure:**
```
team_structure: {
  "SDR": ["Alex", "Jordan"],
  "AE - SMB": ["Sam", "Casey"],
  "AE - Enterprise": ["Morgan", "Riley"]
}
managers: {
  "SDR": "Taylor",
  "AE - SMB": "Jamie",
  "AE - Enterprise": "Jamie"
}
```

### Quota & Targets

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What is each rep's quota? (monthly or quarterly) | Quota attainment calculation | `rep_quotas` |
| What quota period do you use? (monthly / quarterly) | Normalize attainment | `quota_period` |
| What is the team-level target? | Team rollup | `team_target` |
| Do you have activity targets? (calls/day, emails/day, meetings/week) | Activity benchmarking | `activity_targets` |

**Example quota config:**
```
rep_quotas: {
  "Sam": 50000,
  "Casey": 50000,
  "Morgan": 150000,
  "Riley": 150000
}
quota_period: "monthly"
team_target: 400000
activity_targets: {
  "SDR": { "calls_per_day": 50, "emails_per_day": 80, "meetings_per_week": 10 },
  "AE": { "calls_per_day": 15, "emails_per_day": 20, "meetings_per_week": 8 }
}
```

### Pipeline Stage Definitions

| Question | Purpose | Stored As |
|----------|---------|-----------|
| What are your pipeline stages in order? | Map data to funnel | `pipeline_stages` |
| Which stage means "qualified"? | Qualification rate | `qualified_stage` |
| Which stage means "closed won"? | Win rate, revenue | `won_stage` |
| Which stage means "closed lost"? | Loss analysis | `lost_stage` |
| What is your expected sales cycle length? (days) | Velocity benchmarking | `expected_cycle_days` |

### Forecast Config (Optional)

| Question | Purpose | Stored As |
|----------|---------|-----------|
| Do you track forecasts? (commit, best case, pipeline) | Forecast accuracy analysis | `tracks_forecasts` |
| Where are forecasts recorded? | Pull forecast data | `forecast_source` |
| What forecast categories do you use? | Map to standard categories | `forecast_categories` |

**Store config in:** `clients/<client-name>/config/periodic-sales-performance-review.json` or equivalent.

---

## Step 1: Pull Performance Data

**Purpose:** Extract deal data, activity data, and (optionally) forecast data for the specified period.

### Input Contract

```
period: {
  type: "weekly" | "monthly" | "quarterly" | "custom"
  start_date: string              # ISO date (auto-calculated from type, or user-specified)
  end_date: string                # ISO date (default: today)
  comparison_period: boolean      # Include prior period for trend comparison (default: true)
}
crm_tool: string                  # From config
access_method: string             # From config
activity_source: string           # From config
rep_names: string[]               # From config
```

### Process

Pull three categories of data:

#### A) Deal Data (per rep)

| CRM | How to Pull |
|-----|-------------|
| **Salesforce** | SOQL query on Opportunity with Owner filter |
| **HubSpot** | Deals API filtered by owner |
| **Pipedrive** | Deals API filtered by owner |
| **Close** | Leads/Opportunities API by assigned user |
| **Supabase** | Query deals table with rep filter |
| **CSV** | User provides file, filter by owner column |

For each rep, pull:
- All deals closed (won + lost) in the period
- All deals created in the period
- All deals currently open (active pipeline)
- Deal amounts, stages, close dates, sources, loss reasons

#### B) Activity Data (per rep)

| Source | How to Pull |
|--------|-------------|
| **Salesforce** | Tasks + Events objects by owner |
| **HubSpot** | Engagements API by owner |
| **Outreach/Salesloft** | Activity metrics API |
| **Gong** | Call logs and meeting data |
| **Manual/CSV** | User provides activity log |

For each rep, pull:
- Calls made (count, duration if available)
- Emails sent (count, reply rate if available)
- Meetings held (count, no-shows if available)
- Proposals/demos delivered
- LinkedIn touches (if tracked)

#### C) Forecast Data (if tracked)

Pull the forecast submitted at the start of the period for comparison to actuals:
- Commit forecast per rep
- Best case forecast per rep
- Pipeline forecast per rep

### Data Standardization

Normalize all data into a standard structure:

```
performance_data: {
  current_period: {
    start_date: string
    end_date: string
    reps: [
      {
        name: string
        team: string | null
        manager: string | null
        quota: number

        revenue: {
          closed_won: number
          closed_lost_value: number
          deals_won: integer
          deals_lost: integer
          avg_deal_size: number | null
          largest_deal: { name: string, amount: number } | null
        }

        pipeline: {
          deals_created: integer
          pipeline_value_created: number | null
          open_deals: integer
          open_pipeline_value: number | null
          weighted_pipeline: number | null
        }

        activity: {
          calls: integer | null
          emails_sent: integer | null
          meetings_held: integer | null
          meetings_booked: integer | null
          proposals_sent: integer | null
          no_shows: integer | null
        } | null

        velocity: {
          avg_days_to_close: float | null
          avg_days_in_stage: { stage: string, days: float }[] | null
        } | null

        qualification: {
          meetings_to_qualified_rate: percentage | null
          qualified_deals: integer | null
        } | null

        deals_closed: [
          {
            name: string
            company: string
            amount: number
            stage: string            # won or lost
            close_date: string
            days_to_close: integer | null
            source: string | null
            loss_reason: string | null
          }
        ]

        forecast: {
          commit: number
          best_case: number
          pipeline: number
        } | null
      }
    ]
  }
  comparison_period: { ... } | null    # Same structure for prior period
}
```

### Human Checkpoint

```
## Performance Data Pulled

Source: [CRM name]
Activity source: [Activity tool name]
Current period: [start] to [end]
Comparison period: [start] to [end]

Reps found: [list of rep names]
Deals closed in period: X won, Y lost
Activity data available: [yes/partial/no]
Forecast data available: [yes/no]

Data looks correct? (Y/n)
```

---

## Step 2: Analyze Performance

**Purpose:** Run the full analysis across six dimensions. Pure computation + LLM reasoning.

### Input Contract

```
performance_data: { ... }           # From Step 1
rep_quotas: { ... }                 # From config
team_target: number                 # From config
activity_targets: { ... } | null    # From config
pipeline_stages: string[]           # From config
expected_cycle_days: integer        # From config
```

### Analysis Dimensions

Run all six analyses on the current period data. Where comparison period exists, calculate period-over-period trends.

---

#### Analysis 1: Quota Attainment

**Questions answered:** Are we going to hit the number? Who's on track and who isn't?

| Metric | How to Calculate |
|--------|-----------------|
| Team revenue closed | Sum of all reps' closed won |
| Team attainment | Team revenue / team target |
| Rep attainment | Each rep's closed won / their quota |
| Attainment distribution | How many reps at >100%, 80-100%, 50-80%, <50% |
| Run rate projection | (Revenue closed / days elapsed) × days in period |
| Gap to target | Team target - closed won - weighted pipeline |
| Rep ranking | Ordered by attainment % |
| vs. Prior period | Compare attainment percentages |

**Output:**
```
quota_attainment: {
  team: {
    target: number
    closed: number
    attainment_pct: percentage
    run_rate_projection: number
    projected_attainment_pct: percentage
    gap_to_target: number
    vs_prior_period: percentage_change | null
  }
  by_rep: [
    {
      name: string
      team: string | null
      quota: number
      closed: number
      attainment_pct: percentage
      run_rate_projection: number
      gap_to_quota: number
      rank: integer
      vs_prior_period: percentage_change | null
      status: "crushing" | "on_track" | "behind" | "at_risk"
    }
  ]
  distribution: {
    above_100: integer
    pct_80_to_100: integer
    pct_50_to_80: integer
    below_50: integer
  }
}
```

**Status thresholds** (adjusted for time elapsed in period):
- **Crushing:** >110% attainment (pace-adjusted)
- **On track:** 90-110% attainment (pace-adjusted)
- **Behind:** 60-90% attainment (pace-adjusted)
- **At risk:** <60% attainment (pace-adjusted)

---

#### Analysis 2: Activity Metrics

**Questions answered:** Are reps putting in the work? Who's active and who's coasting?

| Metric | How to Calculate |
|--------|-----------------|
| Calls per day (by rep) | Total calls / business days in period |
| Emails per day (by rep) | Total emails / business days in period |
| Meetings per week (by rep) | Total meetings / weeks in period |
| Proposals sent (by rep) | Count in period |
| Activity-to-meeting conversion | Meetings booked / (calls + emails) |
| Meeting-to-opportunity conversion | Qualified deals / meetings held |
| No-show rate | No-shows / meetings booked |
| vs. Targets | Compare to activity_targets |
| vs. Prior period | Compare activity volumes |
| Activity efficiency | Revenue closed per activity unit (calls, emails, meetings) |

**Output:**
```
activity_analysis: {
  by_rep: [
    {
      name: string
      team: string | null
      calls_per_day: float | null
      emails_per_day: float | null
      meetings_per_week: float | null
      proposals_sent: integer | null
      activity_to_meeting_rate: percentage | null
      meeting_to_opp_rate: percentage | null
      no_show_rate: percentage | null
      revenue_per_meeting: number | null
      vs_targets: {
        calls: "above" | "at" | "below" | null
        emails: "above" | "at" | "below" | null
        meetings: "above" | "at" | "below" | null
      } | null
      vs_prior_period: {
        calls_change: percentage | null
        emails_change: percentage | null
        meetings_change: percentage | null
      } | null
      activity_grade: "high" | "adequate" | "low" | "critical"
    }
  ]
  team_averages: {
    avg_calls_per_day: float | null
    avg_emails_per_day: float | null
    avg_meetings_per_week: float | null
    avg_revenue_per_meeting: number | null
  }
  efficiency_leaders: {
    most_efficient_rep: string         # Highest revenue per activity
    most_active_rep: string            # Highest total activity volume
    best_conversion_rep: string        # Highest meeting-to-opp rate
  }
}
```

**Activity grade thresholds** (relative to targets or team average):
- **High:** >120% of target/average
- **Adequate:** 80-120%
- **Low:** 50-80%
- **Critical:** <50%

---

#### Analysis 3: Deal Progression & Velocity

**Questions answered:** How fast are deals moving? Are deals progressing or stalling?

| Metric | How to Calculate |
|--------|-----------------|
| Avg days to close (by rep) | Mean days from created to closed won |
| Avg days to close (team) | Team-level mean |
| Stage velocity by rep | Avg days in each stage per rep |
| Deals progressed this period | Deals that moved forward at least one stage |
| Deals stalled | Deals with no stage change in period |
| Pipeline creation rate | New pipeline value created / target (should be 3x+) |
| Pipeline coverage by rep | Open weighted pipeline / remaining quota |
| Fastest deal | Shortest time from created to closed won |
| vs. Expected cycle | Compare avg days to close vs. expected_cycle_days |
| vs. Prior period | Compare velocity metrics |

**Output:**
```
deal_progression: {
  by_rep: [
    {
      name: string
      avg_days_to_close: float | null
      deals_progressed: integer
      deals_stalled: integer
      pipeline_created: number | null
      pipeline_coverage: float | null
      coverage_assessment: "healthy" | "adequate" | "at_risk" | "critical"
      fastest_deal: { name: string, days: integer } | null
      slowest_stage: { stage: string, avg_days: float } | null
    }
  ]
  team: {
    avg_days_to_close: float | null
    vs_expected_cycle: string
    total_pipeline_created: number | null
    total_pipeline_coverage: float | null
    deals_progressed: integer
    deals_stalled: integer
    stall_rate: percentage
    vs_prior_period: {
      velocity_change: string | null
      stall_rate_change: percentage_change | null
    } | null
  }
}
```

**Pipeline coverage thresholds:**
- **Healthy:** 3x+ remaining quota
- **Adequate:** 2-3x
- **At risk:** 1-2x
- **Critical:** <1x

---

#### Analysis 4: Win/Loss Patterns

**Questions answered:** Why are we winning? Why are we losing? Are there patterns by rep?

| Metric | How to Calculate |
|--------|-----------------|
| Win rate (by rep) | Won / (Won + Lost) |
| Win rate (team) | Team-level |
| Avg deal size won (by rep) | Mean amount of won deals per rep |
| Win rate by source (by rep) | Cross-reference source and outcome per rep |
| Top loss reasons (by rep) | Group loss_reason per rep |
| Top loss reasons (team) | Aggregate |
| Loss stage distribution | At which stage do deals die, per rep |
| Competitive losses | Deals lost to specific competitors |
| vs. Prior period | Compare win rates |

**Output:**
```
win_loss: {
  team: {
    win_rate: percentage
    deals_won: integer
    deals_lost: integer
    avg_deal_size_won: number | null
    total_revenue_lost: number | null
    vs_prior_period: percentage_change | null
    top_loss_reasons: [
      { reason: string, count: integer, percentage: percentage }
    ]
    loss_by_stage: [
      { stage: string, count: integer, percentage: percentage }
    ]
    competitive_losses: [
      { competitor: string, count: integer, deals: string[] }
    ] | null
  }
  by_rep: [
    {
      name: string
      win_rate: percentage
      deals_won: integer
      deals_lost: integer
      avg_deal_size_won: number | null
      vs_prior_period: percentage_change | null
      top_loss_reason: string | null
      loss_stage: string | null          # Stage where most losses occur
      notable_wins: [ { deal: string, amount: number } ] | null
    }
  ]
}
```

---

#### Analysis 5: Rep Benchmarking & Coaching Priorities

**Questions answered:** How do reps compare to each other? Where does each rep need help?

| Metric | How to Calculate |
|--------|-----------------|
| Composite performance score | Weighted: attainment (40%) + activity grade (20%) + win rate (20%) + pipeline coverage (20%) |
| Strength/weakness profile per rep | Best and worst metrics relative to team |
| Coaching priority ranking | Reps sorted by gap between potential and performance |
| Skill gaps | Inferred from data patterns (see below) |

**Skill gap inference logic:**

| Pattern | Inferred Gap | Coaching Focus |
|---------|-------------|----------------|
| High activity + low meetings | Messaging/targeting issue | Refine outreach copy, review ICP targeting |
| High meetings + low qualification rate | Discovery skills gap | Coach on discovery questions, qualification framework |
| High qualification + low win rate | Closing skills gap | Coach on negotiation, objection handling, proposals |
| Low activity + decent conversion | Activity discipline | Coach on daily rhythm, accountability, pipeline generation |
| High win rate + small deal sizes | Upsell/expansion gap | Coach on multi-threading, selling to value, expansion motions |
| Long cycle times vs. team avg | Deal management gap | Coach on next-step discipline, stakeholder mapping, urgency creation |
| High loss to competitors | Competitive positioning gap | Provide battlecards, coach on differentiation and displacement tactics |
| High no-show rate | Meeting confirmation process | Implement confirmation sequences, calendar management |

**Output:**
```
rep_benchmarking: {
  rankings: [
    {
      name: string
      composite_score: float               # 0-100
      rank: integer
      attainment_pct: percentage
      activity_grade: string
      win_rate: percentage
      pipeline_coverage: float
      trend: "improving" | "stable" | "declining" | null
    }
  ]
  coaching_priorities: [
    {
      rep_name: string
      priority: "urgent" | "high" | "medium" | "low"
      primary_gap: string                  # e.g., "discovery skills"
      evidence: string                     # The data pattern that reveals this gap
      recommended_coaching: string         # Specific action for their manager
      secondary_gaps: string[] | null
    }
  ]
  team_strengths: string[]                 # What the team does well
  team_weaknesses: string[]                # Systemic issues across multiple reps
}
```

**Coaching priority logic:**
- **Urgent:** Rep is <50% attainment AND activity is low — needs immediate intervention
- **High:** Rep is <80% attainment with identifiable skill gap — coaching can move the needle
- **Medium:** Rep is on track but has a specific area significantly below team average
- **Low:** Rep is performing well — coach to maintain and stretch

---

#### Analysis 6: Forecast Accuracy (if forecast data available)

**Questions answered:** How reliable are our forecasts? Who sandags? Who over-commits?

| Metric | How to Calculate |
|--------|-----------------|
| Team forecast accuracy | Actual closed / commit forecast |
| Rep forecast accuracy | Per-rep actual vs. commit |
| Over-commit rate | How often reps forecast more than they close |
| Sandbag rate | How often reps close significantly more than forecast |
| Best case realization | Actual / best case forecast |
| Forecast trend | Is accuracy improving or declining over time? |

**Output:**
```
forecast_accuracy: {
  team: {
    commit_forecast: number
    best_case_forecast: number
    actual_closed: number
    commit_accuracy: percentage           # Actual / commit
    best_case_realization: percentage
    accuracy_grade: "reliable" | "optimistic" | "conservative" | "unreliable"
  }
  by_rep: [
    {
      name: string
      commit_forecast: number
      actual_closed: number
      accuracy: percentage
      pattern: "accurate" | "over_commits" | "sandbags" | "volatile"
      deviation: number                   # Actual - commit
    }
  ]
  insights: string[]                      # Patterns observed
} | null
```

**Accuracy grades:**
- **Reliable:** Team closes within 90-110% of commit
- **Optimistic:** Team consistently closes <90% of commit
- **Conservative:** Team consistently closes >110% of commit (sandbagging)
- **Unreliable:** Wide variance, no consistent pattern

---

### Output Contract (Full Analysis)

```
analysis: {
  period: { type, start_date, end_date }
  quota_attainment: { ... }
  activity_analysis: { ... }
  deal_progression: { ... }
  win_loss: { ... }
  rep_benchmarking: { ... }
  forecast_accuracy: { ... } | null
}
```

No human checkpoint after this step — the analysis feeds directly into report generation.

---

## Step 3: Generate Report

**Purpose:** Transform the raw analysis into two report formats: an executive summary and a detailed diagnostic with rep-level coaching notes. Pure LLM reasoning.

### Input Contract

```
analysis: { ... }                     # From Step 2
rep_quotas: { ... }                   # From config
team_target: number                   # From config
activity_targets: { ... } | null      # From config
```

### Executive Summary Format

One page. Numbers and rankings. What a VP Sales needs to see in 60 seconds.

```
# Sales Performance Review — [Period Type]: [Start Date] to [End Date]

## Team Snapshot
| Metric | This Period | Prior Period | Change |
|--------|------------|-------------|--------|
| Revenue closed | $X | $Y | +/-Z% |
| Team attainment | X% | Y% | +/-Z pts |
| Deals won | X | Y | +/-Z |
| Avg deal size | $X | $Y | +/-Z% |
| Win rate | X% | Y% | +/-Z pts |
| Avg days to close | X | Y | +/-Z |
| Pipeline coverage | Xx | Yx | +/-Z |

## Rep Attainment Leaderboard
| Rank | Rep | Closed | Quota | Attainment | Status |
|------|-----|--------|-------|------------|--------|
| 1 | [Name] | $X | $Y | Z% | Crushing |
| 2 | [Name] | $X | $Y | Z% | On track |
| ... | ... | ... | ... | ... | ... |

## Red Flags
- [Any rep below 50% attainment — names and specifics]
- [Activity metrics below target]
- [Pipeline coverage below 2x for any rep]
- [Win rate declining]
- [Forecast accuracy deteriorating]

## Green Lights
- [Reps exceeding quota]
- [Metrics trending up]
- [Pipeline coverage healthy]
- [Wins against key competitors]

## Top 3 Actions
1. [Most impactful thing to do this week — e.g., "Coach [rep] on discovery — 8 meetings but 0 qualified deals"]
2. [Second most impactful]
3. [Third most impactful]
```

### Detailed Diagnostic Format

Full rep-by-rep breakdown with coaching recommendations.

```
# Sales Performance Diagnostic — [Period]

## 1. Quota Attainment
[Team attainment summary]
[Rep-by-rep attainment table]
[Run rate projections]
[Gap analysis — what's needed to hit the number]
[Commentary: are we going to make it? What needs to happen?]

## 2. Activity Analysis
[Team activity averages vs. targets]
[Rep-by-rep activity table]
[Efficiency metrics — revenue per meeting, conversion rates]
[Commentary: who's doing the work? Who's efficient vs. just busy?]

## 3. Deal Progression & Velocity
[Pipeline creation and coverage by rep]
[Velocity metrics — avg days to close, stage duration]
[Stalled deals by rep]
[Commentary: is the pipeline healthy? Where are bottlenecks?]

## 4. Win/Loss Analysis
[Team win rate and trends]
[Rep-by-rep win rates]
[Loss reasons — team-level and rep-level patterns]
[Competitive loss analysis]
[Commentary: why are we losing? Any rep-specific patterns?]

## 5. Rep Scorecards
[For each rep, a mini-scorecard]:

### [Rep Name] — [Status: Crushing / On Track / Behind / At Risk]
| Metric | Value | vs. Target | vs. Team Avg | Trend |
|--------|-------|-----------|-------------|-------|
| Attainment | X% | [+/-] | [+/-] | [up/down/flat] |
| Activity | [grade] | [+/-] | [+/-] | [up/down/flat] |
| Win rate | X% | — | [+/-] | [up/down/flat] |
| Avg deal size | $X | — | [+/-] | [up/down/flat] |
| Pipeline coverage | Xx | [+/-] | [+/-] | [up/down/flat] |

**Strengths:** [What this rep does well, with data]
**Gaps:** [Where they need improvement, with data]
**Coaching recommendation:** [Specific action for their manager]

## 6. Forecast Accuracy (if available)
[Team forecast accuracy]
[Rep-by-rep accuracy table]
[Patterns: who sandbags, who over-commits]
[Commentary: can we trust the forecast?]

## 7. Recommendations
[Numbered list of specific, actionable recommendations.
 Each recommendation cites the data point that drives it.]

### Urgent (This Week)
1. [Action — data point — expected impact]

### High Priority (This Month)
2. [Action — data point — expected impact]
3. [Action — data point — expected impact]

### Systemic (Ongoing)
4. [Process or tooling change — data point — expected impact]
```

### Recommendations Logic

Generate recommendations based on patterns found in the analysis:

| Pattern | Recommendation |
|---------|---------------|
| >50% of reps below 80% attainment | "This is a systemic issue, not individual. Review: targets too high? Market shifted? Product gaps? Pipeline generation insufficient?" |
| One rep significantly underperforming | "[Rep] is at X% attainment with [specific gap]. Schedule a 1:1 this week to [specific coaching action]." |
| Team activity below targets | "Activity is X% below target across the team. Re-establish daily rhythm: [specific cadence]. Consider shared accountability (leaderboard, daily standups)." |
| High activity + low conversion | "Activity volume is there but conversion is low. This is a skills issue, not an effort issue. Focus coaching on [discovery/closing/qualification] — the bottleneck is at [stage]." |
| Win rate declining period-over-period | "Win rate dropped from X% to Y%. Top new loss reason: [Z]. Investigate: competitor move? Product gap? Positioning drift?" |
| Pipeline coverage <2x for multiple reps | "X reps have <2x pipeline coverage. They will not hit quota without immediate pipeline generation. Activate [outbound/referral/event] campaigns this week." |
| Forecast accuracy below 80% | "Forecast accuracy is [X%]. [Pattern: over-commit/sandbagging]. Implement: [weekly commit review / staged forecasting / deal inspection criteria]." |
| One rep crushing while others struggle | "[Rep] is at X% attainment. Study what they're doing differently: [observation from data]. Consider peer coaching or ride-alongs." |
| High competitive loss rate | "Lost X deals to [competitor] this period. Distribute updated battlecards. Run a team session on competitive positioning." |
| Long average cycle length | "Deals are taking X days to close vs. Y expected. Bottleneck is [stage]. Coach reps on [multi-threading / next-step discipline / urgency creation]." |

### Output Contract

```
report: {
  executive_summary: string           # Markdown formatted
  detailed_diagnostic: string         # Markdown formatted
  rep_scorecards: [
    {
      rep_name: string
      status: "crushing" | "on_track" | "behind" | "at_risk"
      strengths: string[]
      gaps: string[]
      coaching_action: string
    }
  ]
  recommendations: [
    {
      priority: "urgent" | "high" | "medium" | "systemic"
      area: string
      recommendation: string
      data_point: string
      expected_impact: string
    }
  ]
}
```

### Human Checkpoint

Present the executive summary first, then offer the detailed diagnostic:

```
[Executive Summary rendered]

---

Full detailed diagnostic is also available with:
- Rep-by-rep scorecards with strengths, gaps, and coaching recommendations
- Deal-level analysis (progression, stalled deals, velocity)
- Win/loss deep dive with competitive analysis
- Forecast accuracy breakdown

Coaching priorities this period:
| Rep | Priority | Gap | Recommended Action |
|-----|----------|-----|--------------------|
| ... | ... | ... | ... |

Want to see the full diagnostic? Or drill into a specific rep's scorecard?
```

---

## Step 4: Export & Share (Optional)

**Purpose:** Save the report and optionally push it to the user's preferred location.

### Process

Based on user preference:

| Destination | How |
|-------------|-----|
| **Markdown file** | Save to `clients/<client>/reports/sales-performance-review-{date}.md` |
| **Google Sheets** | Export data tables (attainment, activity, win/loss) |
| **Notion** | Push to a Notion database page via Notion MCP |
| **Slack** | Send executive summary to a channel |
| **Email** | Send via agentmail |
| **stdout** | Just display it (default) |

---

## Execution Summary

| Step | Tool Dependency | Human Checkpoint | Typical Time |
|------|----------------|-----------------|--------------|
| 0. Config | None | First run only | 5 min (once) |
| 1. Pull Data | Configurable (CRM API, CSV, Supabase, etc.) | Verify data looks correct | 2-3 min |
| 2. Analyze | None (computation + LLM reasoning) | None — feeds directly to report | Automatic |
| 3. Generate Report | None (LLM reasoning) | Review executive summary, drill into reps | 10-15 min |
| 4. Export | Configurable (file, Sheets, Notion, etc.) | Optional | 1 min |

**Total human review time: ~15-20 minutes** for a full sales performance review that would normally take 1-2 hours of CRM digging and spreadsheet building.

---

## Adapting to Data Availability

Not every team tracks every metric. The analysis degrades gracefully:

| Missing Data | What Gets Skipped | Report Still Useful? |
|-------------|-------------------|---------------------|
| `activity data` | Activity analysis (Analysis 2), activity-based coaching | Yes — quota attainment, win/loss, pipeline analysis still run |
| `deal amounts` | Revenue metrics, quota attainment, deal size analysis | Partially — deal count analysis and win/loss still work |
| `forecast data` | Forecast accuracy (Analysis 6) | Yes — everything else still runs |
| `loss reasons` | Loss reason breakdown | Yes — win/loss rate and stage analysis still work |
| `source data` | Source-level win rate analysis | Yes — aggregate metrics still run |
| `comparison period` | Period-over-period trends, trend arrows | Yes — single period analysis still produces full report |
| `activity targets` | vs. target comparisons | Yes — rep-to-rep benchmarking still works |

**Minimum viable data for a useful report:** Rep names + deals closed (with amounts) + quota targets. Everything else enriches but isn't required.

---

## Cadence Guide

| Review Type | Period | Audience | Focus |
|-------------|--------|----------|-------|
| **Weekly standup** | Last 7 days | Sales team | Activity, deal updates, stuck deals, this week's priorities |
| **Monthly review** | Last 30 days | Sales leader | Full diagnostic: attainment, activity, coaching priorities |
| **Quarterly review** | Last 90 days | VP Sales / Founder | Trends, forecast accuracy, team composition, strategic decisions |
| **Annual review** | Last 12 months | Leadership | Rep performance trajectories, hiring/firing decisions, quota planning |

The report depth automatically scales with the period length. A weekly review emphasizes activity and deal movement. A quarterly review emphasizes attainment trends, coaching ROI, and forecast reliability.

---

## Tips

- **Run this on a consistent cadence.** The value compounds. A monthly review reveals trends. A quarterly review reveals who's improving and who's plateauing. Without consistency, you're always flying blind.
- **Don't just look at quota attainment.** A rep hitting quota through one large deal is different from a rep hitting quota through consistent execution. The underlying metrics tell you who is sustainably performing.
- **Activity metrics without conversion context are useless.** "Jordan made 500 calls" sounds impressive until you see 0 meetings booked. Always pair activity with outcomes.
- **The coaching section is the ROI.** The numbers tell you WHAT is happening. The coaching priorities tell you WHAT TO DO about it. A performance review without coaching actions is just a report card.
- **Watch for the "middle" reps.** Top performers and bottom performers get attention. The reps at 70-90% attainment often have the highest coaching ROI — they're close enough that fixing one skill gap puts them over the line.
- **Forecast accuracy is a team discipline, not individual talent.** If everyone's forecasts are off, it's a process problem. Implement deal inspection criteria: "What has to be true for this deal to close this period?"
- **Compare rep performance within segments, not across them.** An SMB AE closing $40K/month and an Enterprise AE closing $40K/month are having very different quarters. Always normalize for role and territory.
- **Use the trend data.** A rep at 60% attainment who was at 40% last month is improving. A rep at 90% who was at 120% last month is declining. Trajectory matters more than a single snapshot.
