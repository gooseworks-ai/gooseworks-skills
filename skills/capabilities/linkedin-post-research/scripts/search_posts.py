#!/usr/bin/env python3
"""
LinkedIn Post Research — Search LinkedIn posts by keyword via Crustdata API.

Usage:
    python3 search_posts.py --keyword "AI sourcing" --keyword "talent sourcing tools"
    python3 search_posts.py --keyword "recruiting automation" --time-frame past-week
    python3 search_posts.py --keyword "AI sourcing" --pages 3 --output csv --output-file results.csv
    python3 search_posts.py --keywords-file keywords.txt --time-frame past-week

Environment:
    GOOSEWORKS_API_KEY   — Required. GooseWorks API key (proxies to Crustdata).
    CRUSTDATA_API_TOKEN  — Fallback if GOOSEWORKS_API_KEY is not set.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

GOOSEWORKS_API_BASE = os.environ.get("GOOSEWORKS_API_BASE", "https://app.gooseworks.ai")
API_BASE = f"{GOOSEWORKS_API_BASE}/v1/proxy/crustdata"
KEYWORD_SEARCH_ENDPOINT = "/screener/linkedin_posts/keyword_search"

VALID_TIME_FRAMES = ["past-day", "past-week", "past-month", "past-quarter", "past-year", "all-time"]
VALID_SORT_BY = ["relevance", "date"]
MAX_RETRIES = 3


def get_auth_headers():
    """Build auth headers using GooseWorks API key or direct Crustdata token."""
    gw_key = os.environ.get("GOOSEWORKS_API_KEY", "")
    if gw_key:
        return {
            "Authorization": f"Bearer {gw_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    cd_token = os.environ.get("CRUSTDATA_API_TOKEN", "") or os.environ.get("CRUSTDATA_API_KEY", "")
    if cd_token:
        return {
            "Authorization": f"Token {cd_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    print("ERROR: Set GOOSEWORKS_API_KEY or CRUSTDATA_API_TOKEN.", file=sys.stderr)
    sys.exit(1)


def search_keyword(headers, keyword, time_frame, sort_by, page, limit):
    """Search LinkedIn posts for a single keyword on a single page via POST.

    Returns:
        (keyword, page, list_of_post_dicts)
    """
    url = f"{API_BASE}{KEYWORD_SEARCH_ENDPOINT}"
    payload = {
        "keyword": keyword,
        "page": page,
        "sort_by": sort_by,
        "date_posted": time_frame,
    }
    if limit:
        payload["limit"] = limit

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                posts = _extract_posts_from_response(data)
                return keyword, page, posts
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            if e.code == 401:
                print(f"ERROR: Authentication failed (401). Check API credentials.", file=sys.stderr)
                return keyword, page, []
            if e.code == 429:
                retry_after = 5
                try:
                    retry_after = json.loads(error_body).get("retry_after", 5)
                except (json.JSONDecodeError, AttributeError):
                    pass
                print(f"WARN: Rate limited on '{keyword}' page {page}. Waiting {retry_after}s...", file=sys.stderr)
                time.sleep(retry_after)
                continue
            if e.code >= 500 and attempt < MAX_RETRIES - 1:
                wait = 4 * (2 ** attempt)
                print(f"WARN: Server error ({e.code}) on '{keyword}' page {page}. Retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"ERROR: HTTP {e.code} for '{keyword}' page {page}: {error_body[:300]}", file=sys.stderr)
            return keyword, page, []
        except urllib.error.URLError as e:
            if attempt < MAX_RETRIES - 1:
                wait = 4 * (2 ** attempt)
                print(f"WARN: Connection error on '{keyword}' page {page}: {e}. Retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"ERROR: Connection failed for '{keyword}' page {page}: {e}", file=sys.stderr)
            return keyword, page, []

    return keyword, page, []


def _extract_posts_from_response(data):
    """Handle various Crustdata response shapes."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "posts" in data:
            return data["posts"]
        if "data" in data and isinstance(data["data"], dict) and "details" in data["data"]:
            return data["data"]["details"]
        for key in data:
            if isinstance(data[key], list) and data[key]:
                return data[key]
    return []


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
    headers = get_auth_headers()

    tasks = [(kw, page) for kw in keywords for page in range(1, pages + 1)]
    all_posts = []
    seen_urns = set()
    total_api_calls = len(tasks)
    completed = 0

    print(f"Searching {len(keywords)} keywords × {pages} pages = {total_api_calls} API calls...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(search_keyword, headers, kw, time_frame, sort_by, page, limit): (kw, page)
            for kw, page in tasks
        }

        for future in as_completed(futures):
            keyword, pg, posts = future.result()
            completed += 1

            for post in posts:
                urn = post.get("backend_urn", "")
                if not urn or urn in seen_urns:
                    continue
                seen_urns.add(urn)
                all_posts.append(extract_post_row(post, keyword))

            print(f"  [{completed}/{total_api_calls}] '{keyword}' page {pg}: {len(posts)} posts ({len(seen_urns)} unique total)", file=sys.stderr)

    # Sort by total engagement (reactions + comments + shares) descending
    all_posts.sort(key=lambda x: x["reactions"] + x["comments"] + x["num_shares"], reverse=True)
    return all_posts


def output_json(posts, output_file):
    data = json.dumps(posts, indent=2, ensure_ascii=False)
    if output_file:
        with open(output_file, "w") as f:
            f.write(data)
        print(f"Wrote {len(posts)} posts to {output_file}", file=sys.stderr)
    else:
        print(data)


def output_csv(posts, output_file):
    fieldnames = ["author", "keyword", "reactions", "comments", "date", "post_preview", "url", "backend_urn", "num_shares"]
    f = open(output_file, "w", newline="") if output_file else sys.stdout
    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(posts)
    if output_file:
        f.close()
        print(f"Wrote {len(posts)} posts to {output_file}", file=sys.stderr)


def output_summary(posts):
    print(f"\n{'='*80}", file=sys.stderr)
    print(f"  RESULTS: {len(posts)} unique posts found", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    if not posts:
        print("  No posts found.", file=sys.stderr)
        return

    top = posts[:20]
    print(f"  {'Author':<25} {'Keyword':<25} {'React':>6} {'Cmts':>6} {'Shares':>6} {'Date':<12} Preview", file=sys.stderr)
    print(f"  {'-'*25} {'-'*25} {'-'*6} {'-'*6} {'-'*6} {'-'*12} {'-'*40}", file=sys.stderr)
    for p in top:
        author = (p["author"] or "Unknown")[:24]
        keyword = (p["keyword"] or "")[:24]
        preview = (p["post_preview"] or "")[:40]
        print(f"  {author:<25} {keyword:<25} {p['reactions']:>6} {p['comments']:>6} {p['num_shares']:>6} {p['date']:<12} {preview}", file=sys.stderr)

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

    posts = run_search(keywords, args.time_frame, args.sort_by, args.pages, args.limit, args.max_workers)

    if args.output == "json":
        output_json(posts, args.output_file)
    elif args.output == "csv":
        output_csv(posts, args.output_file)

    output_summary(posts)


if __name__ == "__main__":
    main()
