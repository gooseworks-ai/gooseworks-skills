#!/usr/bin/env python3
"""
Search Google Ads Transparency Center for competitor ads using Apify.
Resolves company name/domain to advertiser ID, then scrapes ad data.

Usage:
  python3 search_google_ads.py --company "Nike"
  python3 search_google_ads.py --domain "nike.com"
  python3 search_google_ads.py --advertiser-id "AR13129532367502835713"
"""

import json
import os
import sys
import argparse
import requests
import time as time_mod
import re
from urllib.parse import quote


ACTOR_ID = "xtech~google-ad-transparency-scraper"
BASE_URL = "https://api.apify.com/v2"

# Google Ads Transparency Center base URL
GADS_BASE = "https://adstransparency.google.com"


def get_token(cli_token=None):
    """Get Apify API token from CLI arg or APIFY_API_TOKEN env var."""
    token = cli_token or os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("Error: Apify token required. Use --token or set APIFY_API_TOKEN env var.", file=sys.stderr)
        sys.exit(1)
    return token


def resolve_advertiser_id(company=None, domain=None, token=None, timeout=120):
    """
    Resolve a company name or domain to a Google Ads Transparency advertiser ID.

    Strategy:
    1. If domain is provided, try searching Google Ads Transparency by domain
    2. If company name is provided, search by name
    3. Use a lightweight Apify web scraper to search the transparency center

    Args:
        company: Company name to search
        domain: Company domain (e.g. "nike.com")
        token: Apify API token
        timeout: Max seconds to wait

    Returns:
        dict with advertiser_id, advertiser_name, and ads_count, or None
    """
    search_term = domain or company
    if not search_term:
        return None

    print(f"Searching Google Ads Transparency Center for: {search_term}", file=sys.stderr)

    # Use a generic web scraper to search the transparency center
    # The transparency center URL format for search is:
    # https://adstransparency.google.com/?region=anywhere&domain=nike.com
    # or https://adstransparency.google.com/?region=anywhere&text=Nike

    # Approach: Use Apify's cheerio-scraper to extract advertiser IDs from search results
    scraper_actor = "apify~cheerio-scraper"

    if domain:
        search_url = f"{GADS_BASE}/?region=anywhere&domain={quote(domain)}"
    else:
        search_url = f"{GADS_BASE}/?region=anywhere&text={quote(search_term)}"

    # The Google Ads Transparency Center is a JS-heavy SPA, so cheerio won't work.
    # Instead, we'll try the internal API that the frontend calls.
    # Google's transparency center uses an internal API at:
    # https://adstransparency.google.com/anji/_/rpc/SearchService/SearchAdvertisers

    print(f"Attempting to resolve advertiser ID via Google Ads Transparency Center...", file=sys.stderr)

    # Try the Google Ads Transparency Center's internal search API
    # This is a protobuf-based API, but we can try a simpler approach:
    # Use Apify's web-scraper (Puppeteer-based) to render the JS and extract results
    scraper_actor = "apify~web-scraper"
    run_input = {
        "startUrls": [{"url": search_url}],
        "pageFunction": """async function pageFunction(context) {
            const { page, request } = context;
            // Wait for advertiser results to load
            await page.waitForSelector('advertiser-row, .advertiser-name, [data-advertiser-id], a[href*="/advertiser/"]', { timeout: 15000 }).catch(() => {});
            await new Promise(r => setTimeout(r, 3000));

            // Extract advertiser links and info
            const advertisers = await page.evaluate(() => {
                const results = [];
                // Look for advertiser links in the page
                const links = document.querySelectorAll('a[href*="/advertiser/"]');
                links.forEach(link => {
                    const href = link.getAttribute('href') || '';
                    const match = href.match(/\\/advertiser\\/(AR\\d+)/);
                    if (match) {
                        const name = link.textContent.trim() || '';
                        results.push({
                            advertiser_id: match[1],
                            advertiser_name: name,
                            url: 'https://adstransparency.google.com' + href,
                        });
                    }
                });
                // Deduplicate by ID
                const seen = new Set();
                return results.filter(r => {
                    if (seen.has(r.advertiser_id)) return false;
                    seen.add(r.advertiser_id);
                    return true;
                });
            });

            return advertisers;
        }""",
        "proxyConfiguration": {"useApifyProxy": True},
        "maxRequestsPerCrawl": 1,
    }

    resp = requests.post(
        f"{BASE_URL}/acts/{scraper_actor}/runs",
        json=run_input,
        params={"token": token},
    )
    resp.raise_for_status()
    run_data = resp.json()
    run_id = run_data["data"]["id"]
    print(f"Advertiser lookup run started (ID: {run_id})", file=sys.stderr)

    # Poll for completion
    deadline = time_mod.time() + timeout
    while time_mod.time() < deadline:
        status_resp = requests.get(
            f"{BASE_URL}/acts/{scraper_actor}/runs/{run_id}",
            params={"token": token},
        )
        status_resp.raise_for_status()
        status_data = status_resp.json()
        status = status_data["data"]["status"]

        if status == "SUCCEEDED":
            break
        elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
            print(f"Advertiser lookup {status}. Try providing --advertiser-id directly.", file=sys.stderr)
            return None

        time_mod.sleep(3)
    else:
        print("Advertiser lookup timed out. Try providing --advertiser-id directly.", file=sys.stderr)
        return None

    # Fetch results
    dataset_id = status_data["data"]["defaultDatasetId"]
    dataset_resp = requests.get(
        f"{BASE_URL}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json"},
    )
    dataset_resp.raise_for_status()
    results = dataset_resp.json()

    # The web-scraper returns items wrapped in arrays within pageFunction results
    advertisers = []
    for item in results:
        if isinstance(item, list):
            advertisers.extend(item)
        elif isinstance(item, dict):
            # Could be a single result or a wrapper
            if "advertiser_id" in item:
                advertisers.append(item)
            elif isinstance(item.get("result"), list):
                advertisers.extend(item["result"])

    if advertisers:
        print(f"Found {len(advertisers)} advertiser(s):", file=sys.stderr)
        for adv in advertisers[:5]:
            print(f"  - {adv.get('advertiser_name', 'Unknown')}: {adv.get('advertiser_id', 'N/A')}", file=sys.stderr)
        return advertisers[0]  # Return best match (first result)
    else:
        print("No advertisers found. Try providing --advertiser-id directly.", file=sys.stderr)
        return None


def run_ad_scraper(token, advertiser_ids, region="anywhere", max_ads=50, timeout=300):
    """
    Run the xtech Google Ad Transparency Scraper actor.

    Args:
        token: Apify API token
        advertiser_ids: List of advertiser IDs (e.g. ["AR13129532367502835713"])
        region: Region filter (default: "anywhere")
        max_ads: Maximum ads to return
        timeout: Max seconds to wait

    Returns:
        List of ad dicts from the actor's dataset
    """
    # Build the transparency center URLs for each advertiser
    start_urls = []
    for adv_id in advertiser_ids:
        url = f"{GADS_BASE}/advertiser/{adv_id}?region={region}"
        start_urls.append({"url": url})

    run_input = {
        "startUrls": start_urls,
        "maxItems": max_ads,
    }

    print(f"Starting Google Ads Transparency scraper...", file=sys.stderr)
    resp = requests.post(
        f"{BASE_URL}/acts/{ACTOR_ID}/runs",
        json=run_input,
        params={"token": token},
    )
    resp.raise_for_status()
    run_data = resp.json()
    run_id = run_data["data"]["id"]
    print(f"Run started (ID: {run_id})", file=sys.stderr)

    # Poll for completion
    deadline = time_mod.time() + timeout
    while time_mod.time() < deadline:
        status_resp = requests.get(
            f"{BASE_URL}/acts/{ACTOR_ID}/runs/{run_id}",
            params={"token": token},
        )
        status_resp.raise_for_status()
        status_data = status_resp.json()
        status = status_data["data"]["status"]

        if status == "SUCCEEDED":
            print("Scraping complete.", file=sys.stderr)
            break
        elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
            print(f"Actor run {status}.", file=sys.stderr)
            raise RuntimeError(f"Actor run {status}: {json.dumps(status_data['data'], indent=2)}")

        print(f"Status: {status}...", file=sys.stderr)
        time_mod.sleep(5)
    else:
        raise TimeoutError(f"Actor run did not complete within {timeout}s")

    # Fetch dataset items
    dataset_id = status_data["data"]["defaultDatasetId"]
    dataset_resp = requests.get(
        f"{BASE_URL}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json"},
    )
    dataset_resp.raise_for_status()
    ads = dataset_resp.json()
    print(f"Fetched {len(ads)} ads.", file=sys.stderr)
    return ads


def format_summary(ads):
    """Format ads as a human-readable summary."""
    lines = []
    lines.append(f"{'#':<4} {'Advertiser':<25} {'Format':<10} {'Region':<15} {'Ad Text (preview)'}")
    lines.append("-" * 110)
    for i, ad in enumerate(ads, 1):
        advertiser = str(ad.get("advertiser_name") or ad.get("advertiserName") or "Unknown")[:24]
        fmt = str(ad.get("format") or ad.get("adFormat") or ad.get("type") or "")[:9]
        region = str(ad.get("region") or ad.get("geoTarget") or "")[:14]

        text = (
            ad.get("ad_text")
            or ad.get("adText")
            or ad.get("text")
            or ad.get("headline")
            or ad.get("title")
            or ""
        )
        text_preview = str(text)[:45].replace("\n", " ") if text else ""

        lines.append(f"{i:<4} {advertiser:<25} {fmt:<10} {region:<15} {text_preview}")

    lines.append(f"\nTotal: {len(ads)} ads")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Search Google Ads Transparency Center for competitor ads using Apify",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search by company name (auto-resolves advertiser ID)
  %(prog)s --company "Nike"

  # Search by domain (more precise lookup)
  %(prog)s --domain "nike.com"

  # Direct advertiser ID (skip lookup)
  %(prog)s --advertiser-id "AR13129532367502835713"

  # Multiple advertiser IDs
  %(prog)s --advertiser-id "AR13129532367502835713,AR09876543210987654321"

  # With region filter
  %(prog)s --company "Shopify" --region US

  # Human-readable summary
  %(prog)s --domain "hubspot.com" --output summary
""",
    )

    parser.add_argument("--company", help="Company name to search for")
    parser.add_argument("--domain", help="Company domain (e.g. nike.com) for more precise lookup")
    parser.add_argument("--advertiser-id",
                        help="Google Ads advertiser ID(s), comma-separated (e.g. AR13129532367502835713). Skips lookup.")
    parser.add_argument("--region", default="anywhere",
                        help="Region filter (default: anywhere). Use country codes like US, GB, DE")
    parser.add_argument("--max-ads", type=int, default=50,
                        help="Max number of ads to return (default: 50)")
    parser.add_argument("--output", choices=["json", "summary"], default="json",
                        help="Output format (default: json)")
    parser.add_argument("--token", help="Apify API token (or set APIFY_API_TOKEN env var)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Max seconds to wait for Apify run (default: 300)")

    args = parser.parse_args()

    if not args.company and not args.domain and not args.advertiser_id:
        parser.error("At least one of --company, --domain, or --advertiser-id is required")

    token = get_token(args.token)

    # Resolve advertiser ID(s)
    advertiser_ids = []

    if args.advertiser_id:
        # Direct ID(s) provided — skip lookup
        advertiser_ids = [aid.strip() for aid in args.advertiser_id.split(",") if aid.strip()]
        print(f"Using provided advertiser ID(s): {', '.join(advertiser_ids)}", file=sys.stderr)
    else:
        # Need to resolve company/domain to advertiser ID
        result = resolve_advertiser_id(
            company=args.company,
            domain=args.domain,
            token=token,
        )
        if result and result.get("advertiser_id"):
            advertiser_ids = [result["advertiser_id"]]
            print(f"Resolved to: {result.get('advertiser_name', 'Unknown')} ({result['advertiser_id']})", file=sys.stderr)
        else:
            print("Could not resolve advertiser ID.", file=sys.stderr)
            print("Tips:", file=sys.stderr)
            print("  1. Try --domain instead of --company for more precise results", file=sys.stderr)
            print("  2. Search manually at https://adstransparency.google.com and use --advertiser-id", file=sys.stderr)
            print("  3. The advertiser ID is in the URL: /advertiser/AR...", file=sys.stderr)
            sys.exit(1)

    # Run the ad scraper
    ads = run_ad_scraper(
        token=token,
        advertiser_ids=advertiser_ids,
        region=args.region,
        max_ads=args.max_ads,
        timeout=args.timeout,
    )

    # Output
    if args.output == "summary":
        print(format_summary(ads))
    else:
        print(json.dumps(ads, indent=2))


if __name__ == "__main__":
    main()
