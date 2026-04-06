---
name: linkedin-post-research
description: Search LinkedIn posts by keywords using Crustdata API directly, deduplicate and sort by engagement. Outputs to CSV or JSON. Use when researching LinkedIn content around specific topics.
---

# LinkedIn Post Research

Search LinkedIn for posts matching keywords via the Crustdata API, deduplicate results, and output sorted by engagement.

## Quick Start

Requires `GOOSEWORKS_API_KEY` environment variable (or `CRUSTDATA_API_TOKEN` as fallback). No external dependencies — uses Python stdlib only.

```bash
# Single keyword search
python3 skills/linkedin-post-research/scripts/search_posts.py \
  --keyword "AI sourcing" \
  --time-frame past-week

# Multiple keywords, output CSV
python3 skills/linkedin-post-research/scripts/search_posts.py \
  --keyword "talent sourcing tools" \
  --keyword "recruiting automation" \
  --keyword "AI sourcing" \
  --time-frame past-week \
  --output csv \
  --output-file results.csv

# Keywords from file, multiple pages
python3 skills/linkedin-post-research/scripts/search_posts.py \
  --keywords-file keywords.txt \
  --time-frame past-week \
  --pages 3 \
  --output json \
  --output-file results.json

# Summary only (prints to stderr)
python3 skills/linkedin-post-research/scripts/search_posts.py \
  --keyword "recruiting stack" \
  --output summary
```

## Inputs

- **Keywords**: Search terms — pass via `--keyword` flags or `--keywords-file` (one per line)
- **Time frame**: `past-day`, `past-week`, `past-month`, `past-quarter`, `past-year`, `all-time` (default: `past-month`)
- **Pages**: Number of pages per keyword (default: 1, ~5 posts/page). Max 20.
- **Sort by**: `relevance` or `date` (default: `relevance`)

## CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--keyword`, `-k` | *required* | Keyword to search (repeatable) |
| `--keywords-file`, `-f` | — | File with one keyword per line (lines starting with # are ignored) |
| `--time-frame`, `-t` | `past-month` | Time filter |
| `--sort-by`, `-s` | `relevance` | Sort order |
| `--pages`, `-p` | `1` | Pages per keyword (~5 posts per page) |
| `--limit`, `-l` | — | Exact number of posts per API call (1-100) |
| `--output`, `-o` | `json` | Output format: `json`, `csv`, `summary` |
| `--output-file` | stdout | Write output to file |
| `--max-workers` | `6` | Max parallel API calls |

## How It Works

1. Takes keywords via CLI args or file
2. Calls Crustdata's `/screener/linkedin_posts/keyword_search` API in parallel for all (keyword × page) combinations
3. Deduplicates posts across keywords by `backend_urn`
4. Sorts by total engagement (reactions + comments + shares) descending
5. Outputs JSON, CSV, or summary

## Output Schema (JSON)

```json
{
  "author": "Jane Smith",
  "keyword": "AI sourcing",
  "reactions": 142,
  "comments": 28,
  "date": "2026-02-20",
  "post_preview": "First 200 chars of the post text...",
  "url": "https://www.linkedin.com/posts/...",
  "backend_urn": "urn:li:activity:123456789",
  "num_shares": 12,
  "reactions_by_type": "{\"LIKE\": 100, \"EMPATHY\": 30, \"PRAISE\": 12}",
  "is_repost": false
}
```

## Output Columns (CSV)

| Column | Description |
|--------|-------------|
| author | LinkedIn post author name |
| keyword | Which search keyword matched this post |
| reactions | Total reaction count |
| comments | Total comment count |
| date | Post date (YYYY-MM-DD) |
| post_preview | First ~200 characters of the post |
| url | Direct link to the LinkedIn post |
| backend_urn | Unique post identifier |
| num_shares | Number of shares |

## Crustdata API Details

**Endpoint:** `GET https://api.crustdata.com/screener/linkedin_posts/keyword_search`

**Parameters:**
- `keyword` — Search term
- `page` — Page number (1-based, ~5 posts per page)
- `sort_by` — `relevance` or `date`
- `date_posted` — Time filter (past-day, past-week, etc.)
- `limit` — Exact number of posts to return (1-100)

**Auth:** `Authorization: Bearer <GOOSEWORKS_API_KEY>` (via GooseWorks proxy) or `Authorization: Token <CRUSTDATA_API_TOKEN>` (direct)

**Credit usage:** 1 credit per post returned.

**Rate limits:** Searches run in parallel (default 6 workers). The script handles 429 responses with automatic retry.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOSEWORKS_API_KEY` | Yes* | GooseWorks API key (proxies to Crustdata) |
| `CRUSTDATA_API_TOKEN` | Fallback | Direct Crustdata API token (used if GOOSEWORKS_API_KEY is not set) |

## Cost

~1 credit per post returned. Searching 10 keywords × 1 page = ~50 posts = ~50 credits.

## Chaining with Other Skills

After getting the post list, common next steps:

1. **Extract commenters** → `linkedin-commenter-extractor` — pass post URLs to find warm leads
2. **Research authors** → web search on high-engagement post authors
3. **Qualify leads** → `lead-qualification` — score extracted people against ICP

Example pipeline:
```bash
# Step 1: Search posts
python3 skills/linkedin-post-research/scripts/search_posts.py \
  --keyword "AI sourcing" --keyword "recruiting automation" \
  --time-frame past-week --output json --output-file posts.json

# Step 2: Extract post URLs for commenter extraction
cat posts.json | python3 -c "
import json, sys
posts = json.load(sys.stdin)
# Filter: keep posts with 5+ comments
for p in posts:
    if p['comments'] >= 5:
        print(p['url'])
" > post_urls.txt

# Step 3: Extract commenters from those posts
while read url; do
  python3 skills/linkedin-commenter-extractor/scripts/extract_commenters.py --post-url "\$url" --output json
done < post_urls.txt
```
