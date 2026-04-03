#!/usr/bin/env python3
"""
LinkedIn Post Research — Search LinkedIn posts by keyword via Crustdata API.

Usage:
    python3 search_posts.py --keyword "AI sourcing" --keyword "talent sourcing tools"
    python3 search_posts.py --keyword "recruiting automation" --time-frame past-week
    python3 search_posts.py --keyword "AI sourcing" --pages 3 --output csv --output-file results.csv
    python3 search_posts.py --keywords-file keywords.txt --time-frame past-week

Environment:
    CRUSTDATA_API_TOKEN  — Required. Your Crustdata API token.
"""

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Install with: pip3 install requests", file=sys.stderr)
    sys.exit(1)

API_BASE = "https://api.crustdata.com"
KEYWORD_SEARCH_ENDPOINT = "/screener/linkedin_posts/keyword_search"

VALID_TIME_FRAMES = ["past-day", "past-week", "past-month", "past-quarter", "past-year", "all-time"]
VALID_SORT_BY = ["relevance", "date"]


def get_token():
    token = os.environ.get("CRUSTDATA_API_TOKEN", "") or os.environ.get("CRUSTDATA_API_KEY", "")
    if not token:
        print("ERROR: CRUSTDATA_API_TOKEN or CRUSTDATA_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)
    return token


def search_keyword(token, keyword, time_frame, sort_by, page, limit):
    """Search LinkedIn posts for a single keyword on a single page via POST."""
    url = f"{API_BASE}{KEYWORD_SEARCH_ENDPOINT}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Token {token}",
    }
    payload = {
        "keyword": keyword,
        "page": page,
        "sort_by": sort_by,
        "date_posted": time_frame,
    }
    if limit:
        payload["limit"] = limit

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=90)
        if resp.status_code == 401:
            print(f"ERROR: Authentication failed. Check your CRUSTDATA_API_TOKEN/CRUSTDATA_API_KEY.", file=sys.stderr)
            return keyword, page, []
        if resp.status_code == 429:
            print(f"WARN: Rate limited on keyword '{keyword}' page {page}. Waiting 5s...", file=sys.stderr)
            time.sleep(5)
            resp = requests.post(url, headers=headers, json=payload, timeout=90)
        resp.raise_for_status()
        data = resp.json()

        # Response is a list of post objects
        if isinstance(data, list):
            return keyword, page, data
        elif "posts" in data:
            return keyword, page, data["posts"]
        elif "data" in data and "details" in data["data"]:
            return keyword, page, data["data"]["details"]
        else:
            for key in data:
                if isinstance(data[key], list) and len(data[key]) > 0:
                    return keyword, page, data[key]
            print(f"WARN: Unexpected response shape for '{keyword}' page {page}: {list(data.keys())}", file=sys.stderr)
            return keyword, page, []

    except requests.exceptions.HTTPError as e:
        print(f"ERROR: HTTP {e.response.status_code} for keyword '{keyword}' page {page}: {e}", file=sys.stderr)
        return keyword, page, []
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Request failed for keyword '{keyword}' page {page}: {e}", file=sys.stderr)
        return keyword, page, []


def extract_post_row(post, keyword):
    """Extract a flat row from a post object."""
    return {
        "author": post.get("actor_name", "") or "",
        "keyword": keyword,
        "reactions": post.get("total_reactions", 0) or 0,
        "comments": post.get("total_comments", 0) or 0,
        "date": post.get("date_posted", "") or "",
        "post_preview": (post.get("text") or "")[:200].replace("\n", " ").strip(),
        "url": post.get("share_url", "") or "",
        "backend_urn": post.get("backend_urn", "") or "",
        "num_shares": post.get("num_shares", 0) or 0,
        "reactions_by_type": json.dumps(post.get("reactions_by_type", {})),
        "is_repost": post.get("is_repost_without_thoughts", False),
    }


def run_search(keywords, time_frame, sort_by, pages, limit, max_workers):
    """Run parallel keyword searches across all keywords and pages."""
    token = get_token()

    # Build all (keyword, page) combinations
    tasks = []
    for kw in keywords:
        for page in range(1, pages + 1):
            tasks.append((kw, page))

    all_posts = []
    seen_urns = set()
    total_api_calls = len(tasks)
    completed = 0

    print(f"Searching {len(keywords)} keywords × {pages} pages = {total_api_calls} API calls...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(search_keyword, token, kw, time_frame, sort_by, page, limit): (kw, page)
            for kw, page in tasks
        }

        for future in as_completed(futures):
            kw, page = futures[future]
            keyword, pg, posts = future.result()
            completed += 1

            for post in posts:
                urn = post.get("backend_urn", "")
                if not urn or urn in seen_urns:
                    continue
                seen_urns.add(urn)
                all_posts.append(extract_post_row(post, keyword))

            print(f"  [{completed}/{total_api_calls}] '{keyword}' page {pg}: {len(posts)} posts ({len(seen_urns)} unique total)", file=sys.stderr)

    # Sort by reactions descending
    all_posts.sort(key=lambda x: x["reactions"], reverse=True)
    return all_posts


def output_json(posts, output_file):
    """Output posts as JSON."""
    data = json.dumps(posts, indent=2, ensure_ascii=False)
    if output_file:
        with open(output_file, "w") as f:
            f.write(data)
        print(f"Wrote {len(posts)} posts to {output_file}", file=sys.stderr)
    else:
        print(data)


def output_csv(posts, output_file):
    """Output posts as CSV."""
    fieldnames = ["author", "keyword", "reactions", "comments", "date", "post_preview", "url", "backend_urn", "num_shares"]
    f = open(output_file, "w", newline="") if output_file else sys.stdout
    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(posts)
    if output_file:
        f.close()
        print(f"Wrote {len(posts)} posts to {output_file}", file=sys.stderr)


def output_summary(posts):
    """Print a summary table to stderr."""
    print(f"\n{'='*80}", file=sys.stderr)
    print(f"  RESULTS: {len(posts)} unique posts found", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    if not posts:
        print("  No posts found.", file=sys.stderr)
        return

    # Top posts table
    top = posts[:20]
    print(f"  {'Author':<25} {'Keyword':<25} {'React':>6} {'Cmts':>6} {'Date':<12} Preview", file=sys.stderr)
    print(f"  {'-'*25} {'-'*25} {'-'*6} {'-'*6} {'-'*12} {'-'*40}", file=sys.stderr)
    for p in top:
        author = (p["author"] or "Unknown")[:24]
        keyword = (p["keyword"] or "")[:24]
        preview = (p["post_preview"] or "")[:40]
        print(f"  {author:<25} {keyword:<25} {p['reactions']:>6} {p['comments']:>6} {p['date']:<12} {preview}", file=sys.stderr)

    # Keyword breakdown
    keyword_counts = {}
    for p in posts:
        kw = p["keyword"]
        keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
    print(f"\n  Posts per keyword:", file=sys.stderr)
    for kw, count in sorted(keyword_counts.items(), key=lambda x: -x[1]):
        print(f"    {kw}: {count}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Search LinkedIn posts by keyword via Crustdata API")
    parser.add_argument("--keyword", "-k", action="append", default=[], help="Keyword to search (repeatable)")
    parser.add_argument("--keywords-file", "-f", help="File with one keyword per line")
    parser.add_argument("--time-frame", "-t", default="past-month", choices=VALID_TIME_FRAMES, help="Time filter (default: past-month)")
    parser.add_argument("--sort-by", "-s", default="relevance", choices=VALID_SORT_BY, help="Sort order (default: relevance)")
    parser.add_argument("--pages", "-p", type=int, default=1, help="Number of pages per keyword (default: 1, ~5 posts/page)")
    parser.add_argument("--limit", "-l", type=int, default=None, help="Exact number of posts to return per call (1-100)")
    parser.add_argument("--output", "-o", default="json", choices=["json", "csv", "summary"], help="Output format (default: json)")
    parser.add_argument("--output-file", help="Write output to file instead of stdout")
    parser.add_argument("--max-workers", type=int, default=6, help="Max parallel API calls (default: 6)")

    args = parser.parse_args()

    # Collect keywords
    keywords = list(args.keyword)
    if args.keywords_file:
        with open(args.keywords_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    keywords.append(line)

    if not keywords:
        print("ERROR: Provide at least one keyword via --keyword or --keywords-file", file=sys.stderr)
        sys.exit(1)

    # Run search
    posts = run_search(keywords, args.time_frame, args.sort_by, args.pages, args.limit, args.max_workers)

    # Output
    if args.output == "json":
        output_json(posts, args.output_file)
    elif args.output == "csv":
        output_csv(posts, args.output_file)

    # Always print summary to stderr
    output_summary(posts)


if __name__ == "__main__":
    main()
