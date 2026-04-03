#!/usr/bin/env python3
"""
Prospect Search — CrustData People Search + Supabase Dedup Pipeline
--------------------------------------------------------------------
Searches CrustData for ICP-matching leads, deduplicates against existing
Supabase leads via the exclude_profiles API feature, and stores net-new
results in the database.

Pipeline:
  1. Query Supabase for existing LinkedIn URLs
  2. Build CrustData search payload with exclude_profiles
  3. Paginate through results (rate-limited)
  4. Upsert new leads to Supabase
  5. Export CSV summary

Usage:
    python3 skills/crustdata-supabase/scripts/prospect_search.py \\
      --config skills/crustdata-supabase/configs/{client}.json \\
      [--test] [--yes] [--preview] [--dry-run]

Flags:
    --config     Path to client config JSON (required)
    --test       Limit to 1 page / 25 results max
    --yes        Skip cost confirmation prompt
    --preview    Show total count only (5 credits)
    --dry-run    No API calls, show what would happen
"""

import os
import sys
import json
import csv
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone

# Import shared supabase client from tools/supabase/
SUPABASE_TOOLS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "tools", "supabase"
)
sys.path.insert(0, os.path.abspath(SUPABASE_TOOLS))
from supabase_client import SupabaseClient

# ── Constants ────────────────────────────────────────────────────

CRUSTDATA_SEARCH_URL = "https://api.crustdata.com/screener/person/search/"
RESULTS_PER_PAGE = 25        # CrustData sync results per page
MAX_PAGE = 100               # CrustData max page number
RATE_LIMIT_DELAY = 4.0       # 15 req/min = 4s between requests
PAYLOAD_SIZE_LIMIT = 8_000_000  # 8MB safety margin (10MB actual)
MAX_RETRIES = 3

OUTPUT_COLS = [
    "Name",
    "Title",
    "Company",
    "Company LinkedIn URL",
    "Company Website",
    "Company Industry",
    "Company Headcount",
    "Company Type",
    "Person LinkedIn URL",
    "Region",
    "Headline",
    "Years of Experience",
    "Connections",
    "Skills",
    "Email",
]

MODE_CAPS = {
    "test": {"max_pages": 1, "label": "TEST"},
    "standard": {"max_pages": 20, "label": "STANDARD"},
    "full": {"max_pages": 100, "label": "FULL"},
}


# ── Config Loading ───────────────────────────────────────────────

def load_config(config_path):
    """Load and validate client config JSON."""
    with open(config_path) as f:
        config = json.load(f)

    required = ["client_name", "filters"]
    missing = [k for k in required if k not in config]
    if missing:
        print(f"ERROR: Config missing required fields: {missing}")
        sys.exit(1)

    if not isinstance(config["filters"], list) or not config["filters"]:
        print("ERROR: 'filters' must be a non-empty list of CrustData filter objects")
        sys.exit(1)

    # Defaults
    config.setdefault("search_config_name", os.path.splitext(os.path.basename(config_path))[0])
    config.setdefault("icp_segment", "")
    config.setdefault("post_processing", {})
    config.setdefault("max_pages", 20)
    config.setdefault("mode", "standard")

    return config


# ── Environment Loading ──────────────────────────────────────────

def load_env():
    """Walk up from script dir looking for .env, then check cwd."""
    candidates = []
    script_dir = os.path.dirname(os.path.abspath(__file__))
    d = script_dir
    for _ in range(5):
        candidates.append(os.path.join(d, ".env"))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    candidates.append(os.path.join(os.getcwd(), ".env"))

    env = {}
    for env_path in candidates:
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip().strip('"').strip("'")
            break

    # Validate required keys
    required_keys = ["CRUSTDATA_API_TOKEN", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [k for k in required_keys if not env.get(k)]
    if missing:
        print(f"ERROR: Missing environment variables: {missing}")
        print("  Add them to your .env file.")
        sys.exit(1)

    return env


# ── CrustData API ────────────────────────────────────────────────

def normalize_linkedin_url(url):
    """Normalize LinkedIn URL: lowercase, strip trailing slash and query params."""
    if not url:
        return ""
    url = url.split("?")[0].rstrip("/").lower()
    return url


def build_crustdata_payload(config, exclude_urls, page=1):
    """Build the POST body for /screener/person/search.

    Args:
        config: Client config dict with 'filters' and 'post_processing'.
        exclude_urls: List of LinkedIn URLs to exclude.
        page: Page number (1-indexed).

    Returns:
        Dict ready to be JSON-encoded as request body.
    """
    payload = {
        "filters": config["filters"],
        "page": page,
    }

    # Build post_processing
    post_processing = dict(config.get("post_processing", {}))

    # Merge exclude_profiles: config exclusions + Supabase URLs
    config_excludes = post_processing.get("exclude_profiles", [])
    all_excludes = list(set(config_excludes + exclude_urls))
    if all_excludes:
        post_processing["exclude_profiles"] = all_excludes

    if post_processing:
        payload["post_processing"] = post_processing

    return payload


def check_payload_size(payload):
    """Check if the JSON payload exceeds size limits.

    If too large, truncate exclude_profiles and log a warning.

    Returns:
        (payload, was_truncated)
    """
    raw = json.dumps(payload)
    if len(raw.encode("utf-8")) <= PAYLOAD_SIZE_LIMIT:
        return payload, False

    # Truncate exclude_profiles
    excludes = payload.get("post_processing", {}).get("exclude_profiles", [])
    if not excludes:
        return payload, False

    original_count = len(excludes)
    # Binary search for the right size
    while len(json.dumps(payload).encode("utf-8")) > PAYLOAD_SIZE_LIMIT and excludes:
        # Remove the first half (oldest URLs if list is ordered)
        half = len(excludes) // 2
        excludes = excludes[half:]
        payload["post_processing"]["exclude_profiles"] = excludes

    removed = original_count - len(excludes)
    print(f"  WARNING: Payload exceeded {PAYLOAD_SIZE_LIMIT // 1_000_000}MB limit.")
    print(f"  Truncated exclude_profiles: removed {removed} URLs, keeping {len(excludes)}")
    return payload, True


def crustdata_request(payload, token, retries=MAX_RETRIES):
    """Make a POST request to CrustData People Search.

    Handles rate limiting (429) with retry-after and server errors
    with exponential backoff.

    Returns:
        Parsed JSON response dict.
    """
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    req = urllib.request.Request(CRUSTDATA_SEARCH_URL, data=body, headers=headers, method="POST")

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            if e.code == 429:
                # Rate limited
                try:
                    retry_after = json.loads(error_body).get("retry_after", 30)
                except (json.JSONDecodeError, AttributeError):
                    retry_after = 30
                print(f"  Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            elif e.code == 413:
                print(f"  ERROR: Payload too large (413). Reduce exclude_profiles list.")
                raise
            elif e.code >= 500 and attempt < retries - 1:
                wait = 4 * (2 ** attempt)
                print(f"  Server error ({e.code}). Retrying in {wait}s... (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
                continue
            else:
                print(f"  CrustData API error ({e.code}): {error_body[:500]}")
                raise
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                wait = 4 * (2 ** attempt)
                print(f"  Connection error: {e}. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise

    print("  ERROR: Max retries exceeded.")
    sys.exit(1)


def preview_search(config, token):
    """Run with preview=true to see total count without fetching profiles.

    Costs 5 credits.
    """
    payload = {
        "filters": config["filters"],
        "preview": True,
    }
    print("\n  Running preview search (5 credits)...")
    result = crustdata_request(payload, token)

    total = int(result.get("total_display_count", 0))
    print(f"\n  Total matching profiles: {total:,}")
    est_pages = min((total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE, MAX_PAGE)
    est_credits = min(total, est_pages * RESULTS_PER_PAGE)
    print(f"  Estimated pages needed: {est_pages}")
    print(f"  Estimated credits (full fetch): {est_credits}")
    return total


# ── Lead Mapping ─────────────────────────────────────────────────

def extract_profile_data(profile):
    """Extract standardized fields from a CrustData People Search profile.

    CrustData's realtime search returns a flat-ish structure. The exact field
    names come from the CSV export and API response schema.
    """
    # CrustData returns various field name patterns depending on the endpoint
    name = (
        profile.get("name")
        or profile.get("Name")
        or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
        or ""
    )

    linkedin_url = (
        profile.get("flagship_profile_url")
        or profile.get("linkedin_flagship_url")
        or profile.get("Person LinkedIn URL")
        or profile.get("linkedin_url")
        or ""
    )
    # Fallback: if flagship not available, try to build from slug
    if not linkedin_url or "/ACwAA" in linkedin_url:
        slugs = profile.get("linkedin_slug_or_urns", [])
        # Pick the human-readable slug (not the URN)
        for slug in slugs:
            if not slug.startswith("ACwAA"):
                linkedin_url = f"https://www.linkedin.com/in/{slug}"
                break

    email = (
        profile.get("email")
        or profile.get("Email")
        or ""
    )
    # Handle email arrays
    if isinstance(email, list):
        email = email[0] if email else ""

    title = (
        profile.get("current_title")
        or profile.get("default_position_title")
        or profile.get("title")
        or profile.get("Title")
        or ""
    )

    # Extract company info from employer array (CrustData realtime format)
    employers = profile.get("employer", [])
    current_employer = employers[0] if employers else {}

    company = (
        current_employer.get("company_name")
        or profile.get("company")
        or profile.get("Company")
        or ""
    )

    company_linkedin_id = (
        current_employer.get("company_linkedin_id")
        or profile.get("default_position_company_linkedin_id")
        or ""
    )
    company_linkedin = ""
    if company_linkedin_id:
        company_linkedin = f"https://www.linkedin.com/company/{company_linkedin_id}"
    if not company_linkedin:
        company_linkedin = profile.get("company_linkedin_url") or profile.get("Company LinkedIn URL") or ""

    # Extract website from profile's websites array
    websites = profile.get("websites", [])
    company_website = ""
    if websites and isinstance(websites, list):
        company_website = websites[0] if isinstance(websites[0], str) else websites[0].get("url", "")
    if not company_website:
        company_website = profile.get("company_website") or profile.get("Company Website") or ""

    company_domain = company_website
    if company_domain:
        company_domain = company_domain.replace("https://", "").replace("http://", "").rstrip("/")

    industry = (
        profile.get("industry")
        or profile.get("Company Industry")
        or ""
    )

    headcount = (
        profile.get("company_headcount")
        or profile.get("Company Headcount")
        or ""
    )

    location = (
        profile.get("location")
        or profile.get("Region")
        or profile.get("region")
        or ""
    )

    headline = (
        profile.get("headline")
        or profile.get("Headline")
        or ""
    )

    yoe = profile.get("years_of_experience") or profile.get("Years of Experience") or None
    connections = profile.get("num_of_connections") or profile.get("Connections") or None

    skills_raw = profile.get("skills") or profile.get("Skills") or ""
    if isinstance(skills_raw, list):
        skills = skills_raw
    elif isinstance(skills_raw, str) and skills_raw:
        skills = [s.strip() for s in skills_raw.split(";") if s.strip()]
    else:
        skills = []

    seniority = profile.get("seniority_level") or profile.get("Seniority Level") or ""
    company_type = profile.get("company_type") or profile.get("Company Type") or ""

    return {
        "name": name,
        "linkedin_url": normalize_linkedin_url(linkedin_url),
        "email": email,
        "email_verified": bool(email),
        "title": title,
        "company": company,
        "company_linkedin_url": company_linkedin,
        "company_domain": company_domain,
        "company_headcount": str(headcount) if headcount else "",
        "industry": industry,
        "location": location,
        "seniority_level": seniority,
        "headline": headline,
        "years_of_experience": int(yoe) if yoe else None,
        "connections": int(connections) if connections else None,
        "skills": skills if skills else None,
        # CSV-only fields (not stored in Supabase)
        "_company_website": company_website,
        "_company_type": company_type,
    }


def map_to_supabase_person(profile_data, config):
    """Map extracted profile data to a Supabase people table row."""
    # Split name into first/last
    name_parts = profile_data["name"].split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    person = {
        "linkedin_url": profile_data["linkedin_url"],
        "name": profile_data["name"],
        "first_name": first_name,
        "last_name": last_name,
        "email": profile_data["email"] or None,
        "email_verified": profile_data["email_verified"],
        "title": profile_data["title"] or None,
        "company_name": profile_data["company"] or None,
        "company_domain": profile_data["company_domain"] or None,
        "company_linkedin_url": profile_data["company_linkedin_url"] or None,
        "company_headcount": profile_data["company_headcount"] or None,
        "industry": profile_data["industry"] or None,
        "location": profile_data["location"] or None,
        "seniority_level": profile_data["seniority_level"] or None,
        "headline": profile_data["headline"] or None,
        "years_of_experience": profile_data["years_of_experience"],
        "connections": profile_data["connections"],
        "skills": profile_data["skills"],
        "source": "crustdata",
        "updated_by": "crustdata-supabase",
        "client_name": config["client_name"],
        "search_config_name": config["search_config_name"],
        "icp_segment": config.get("icp_segment") or None,
        "lead_status": "active",
        "enrichment_status": "complete",
    }

    return person


def map_to_csv_row(profile_data):
    """Map extracted profile data to a CSV row dict."""
    skills_str = "; ".join(profile_data["skills"]) if profile_data["skills"] else ""
    return {
        "Name": profile_data["name"],
        "Title": profile_data["title"],
        "Company": profile_data["company"],
        "Company LinkedIn URL": profile_data["company_linkedin_url"],
        "Company Website": profile_data["_company_website"],
        "Company Industry": profile_data["industry"],
        "Company Headcount": profile_data["company_headcount"],
        "Company Type": profile_data["_company_type"],
        "Person LinkedIn URL": profile_data["linkedin_url"],
        "Region": profile_data["location"],
        "Headline": profile_data["headline"],
        "Years of Experience": profile_data["years_of_experience"] or "",
        "Connections": profile_data["connections"] or "",
        "Skills": skills_str,
        "Email": profile_data["email"],
    }


# ── Main Pipeline ────────────────────────────────────────────────

def run_pipeline(config, env, test_mode=False, dry_run=False, auto_confirm=False):
    """Full prospect search pipeline.

    Returns:
        Dict with summary stats.
    """
    token = env["CRUSTDATA_API_TOKEN"]
    client_name = config["client_name"]

    # Determine mode caps
    if test_mode:
        mode = MODE_CAPS["test"]
    else:
        mode_name = config.get("mode", "standard")
        mode = MODE_CAPS.get(mode_name, MODE_CAPS["standard"])

    max_pages = min(config["max_pages"], mode["max_pages"])

    # ── Step 1: Initialize Supabase ──────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 1: Connect to Supabase")
    print(f"{'='*60}")

    sb = SupabaseClient(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])

    if dry_run:
        print("  [DRY RUN] Skipping Supabase connection test")
        existing_urls = []
    else:
        if not sb.test_connection():
            print("  ERROR: Cannot connect to Supabase. Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
            sys.exit(1)
        print("  Connected successfully")

        total_people = sb.count_people()
        print(f"  Existing people in database: {total_people:,}")

        # ── Step 2: Fetch existing URLs ──────────────────────────
        print(f"\n{'='*60}")
        print(f"Step 2: Fetch Existing LinkedIn URLs for Dedup")
        print(f"{'='*60}")

        existing_urls = sb.get_all_linkedin_urls()
        # Normalize for consistent matching
        existing_urls = [normalize_linkedin_url(u) for u in existing_urls if u]
        print(f"  Loaded {len(existing_urls):,} existing URLs for exclusion")

    # ── Step 3: Build payload and check size ─────────────────────
    print(f"\n{'='*60}")
    print(f"Step 3: Build CrustData Search Payload")
    print(f"{'='*60}")

    payload = build_crustdata_payload(config, existing_urls, page=1)
    payload, was_truncated = check_payload_size(payload)

    exclude_count = len(payload.get("post_processing", {}).get("exclude_profiles", []))
    print(f"  Filters: {len(config['filters'])} filter(s)")
    print(f"  Exclude profiles: {exclude_count:,}")
    print(f"  Mode: {mode['label']}, max pages: {max_pages}")

    if dry_run:
        print(f"\n  [DRY RUN] Would send this payload:")
        # Don't print the full exclude list
        display_payload = dict(payload)
        excludes = display_payload.get("post_processing", {}).get("exclude_profiles", [])
        if len(excludes) > 5:
            display_payload["post_processing"] = dict(display_payload.get("post_processing", {}))
            display_payload["post_processing"]["exclude_profiles"] = (
                excludes[:3] + [f"... ({len(excludes) - 3} more)"]
            )
        print(json.dumps(display_payload, indent=2))
        print("\n  [DRY RUN] No API calls made.")
        return {"dry_run": True}

    # ── Step 4: First page + total count ─────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 4: Search CrustData (Page 1)")
    print(f"{'='*60}")

    result = crustdata_request(payload, token)

    # Extract profiles from response
    # CrustData returns profiles in different wrapper formats
    profiles_raw = []
    if isinstance(result, list):
        profiles_raw = result
    elif isinstance(result, dict):
        profiles_raw = result.get("profiles", result.get("data", result.get("results", [])))
        if not profiles_raw and "linkedin_profile_url" in result:
            profiles_raw = [result]

    total_count = 0
    if isinstance(result, dict):
        total_count = int(result.get("total_display_count", len(profiles_raw)))
    else:
        total_count = len(profiles_raw)

    print(f"  Page 1 returned: {len(profiles_raw)} profiles")
    print(f"  Total matching (total_display_count): {total_count:,}")

    if not profiles_raw:
        print("\n  No new leads found matching filters. All matching profiles may already be in Supabase.")
        return {"new_leads": 0, "total_matching": total_count, "pages_fetched": 1}

    # Calculate pages needed
    total_pages = min(
        (total_count + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE,
        max_pages,
        MAX_PAGE,
    )
    est_credits = min(total_count, total_pages * RESULTS_PER_PAGE)

    print(f"\n  Pages to fetch: {total_pages}")
    print(f"  Estimated credits: ~{est_credits}")

    # Confirm cost
    if not auto_confirm and total_pages > 1:
        answer = input(f"\n  Fetch {total_pages} pages (~{est_credits} credits)? [y/N] ").strip().lower()
        if answer != "y":
            print("  Aborted.")
            return {"aborted": True}

    # ── Step 5: Paginate through results ─────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 5: Fetch Remaining Pages")
    print(f"{'='*60}")

    # Collect all profiles (dedup in-memory by linkedin_url)
    all_profiles = {}
    for profile in profiles_raw:
        data = extract_profile_data(profile)
        if data["linkedin_url"]:
            all_profiles[data["linkedin_url"]] = data

    pages_fetched = 1

    for page in range(2, total_pages + 1):
        print(f"  Page {page}/{total_pages}...", end="", flush=True)
        time.sleep(RATE_LIMIT_DELAY)

        page_payload = build_crustdata_payload(config, existing_urls, page=page)
        # No need to re-check payload size — same exclude list
        try:
            page_result = crustdata_request(page_payload, token)
        except Exception as e:
            print(f" ERROR: {e}")
            print(f"  Stopping pagination. Saving {len(all_profiles)} profiles collected so far.")
            break

        page_profiles = []
        if isinstance(page_result, list):
            page_profiles = page_result
        elif isinstance(page_result, dict):
            page_profiles = page_result.get("profiles", page_result.get("data", page_result.get("results", [])))

        new_on_page = 0
        for profile in page_profiles:
            data = extract_profile_data(profile)
            if data["linkedin_url"] and data["linkedin_url"] not in all_profiles:
                all_profiles[data["linkedin_url"]] = data
                new_on_page += 1

        pages_fetched += 1
        print(f" {len(page_profiles)} returned, {new_on_page} new")

        if len(page_profiles) < RESULTS_PER_PAGE:
            print(f"  Last page reached (partial page).")
            break

    print(f"\n  Total unique profiles collected: {len(all_profiles)}")

    # ── Step 6: Upsert to Supabase ───────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 6: Upsert to Supabase")
    print(f"{'='*60}")

    people = [map_to_supabase_person(data, config) for data in all_profiles.values()]
    upserted = sb.upsert_people(people)
    print(f"  Upserted {upserted} people to Supabase")

    # ── Step 7: Export CSV ───────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 7: Export CSV")
    print(f"{'='*60}")

    csv_rows = [map_to_csv_row(data) for data in all_profiles.values()]
    csv_rows.sort(key=lambda r: r["Name"].lower())

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(script_dir, "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = os.path.join(out_dir, f"{client_name}-{timestamp}.csv")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLS)
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"  CSV exported: {csv_path}")
    print(f"  Total rows: {len(csv_rows)}")

    # ── Summary ──────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Summary")
    print(f"{'='*60}")
    print(f"  Client: {client_name}")
    print(f"  Config: {config['search_config_name']}")
    print(f"  Mode: {mode['label']}")
    print(f"  Pages fetched: {pages_fetched}")
    print(f"  Total matching profiles: {total_count:,}")
    print(f"  Existing leads excluded: {len(existing_urls):,}")
    print(f"  New leads found: {len(all_profiles)}")
    print(f"  Leads upserted to Supabase: {upserted}")
    print(f"  Credits used (est.): ~{len(all_profiles)}")

    with_email = sum(1 for d in all_profiles.values() if d["email"])
    print(f"  Leads with email: {with_email}/{len(all_profiles)}")

    # Show top 10
    if all_profiles:
        print(f"\n  Top 10 leads:")
        print(f"  {'Name':<28} {'Title':<30} {'Company':<20}")
        print(f"  {'-'*78}")
        for data in list(all_profiles.values())[:10]:
            print(f"  {data['name'][:27]:<28} {data['title'][:29]:<30} {data['company'][:19]:<20}")

    print(f"\n  Output: {csv_path}")

    return {
        "new_leads": len(all_profiles),
        "total_matching": total_count,
        "pages_fetched": pages_fetched,
        "existing_excluded": len(existing_urls),
        "upserted": upserted,
        "with_email": with_email,
        "csv_path": csv_path,
    }


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CrustData + Supabase Prospect Search Pipeline"
    )
    parser.add_argument("--config", required=True, help="Path to client config JSON")
    parser.add_argument("--test", action="store_true", help="Test mode: 1 page, 25 results max")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip cost confirmation")
    parser.add_argument("--preview", action="store_true", help="Preview only: show total count (5 credits)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, no API calls")
    args = parser.parse_args()

    config = load_config(args.config)
    env = load_env()

    client_name = config["client_name"]
    mode_label = "TEST" if args.test else config.get("mode", "standard").upper()

    print(f"\n{'='*60}")
    print(f"CrustData + Supabase Prospect Search")
    print(f"{'='*60}")
    print(f"  Client: {client_name}")
    print(f"  Config: {args.config}")
    print(f"  Mode: {mode_label}")
    print(f"  Filters: {len(config['filters'])}")
    if args.dry_run:
        print(f"  DRY RUN — no API calls will be made")

    for i, f in enumerate(config["filters"], 1):
        ftype = f.get("filter_type", "?")
        fval = f.get("value", [])
        fdir = f.get("type", "")
        if isinstance(fval, list) and len(fval) > 3:
            display = ", ".join(str(v) for v in fval[:3]) + f" (+{len(fval)-3} more)"
        elif isinstance(fval, list):
            display = ", ".join(str(v) for v in fval)
        else:
            display = str(fval) if fval else "(boolean)"
        print(f"    {i}. {ftype} {fdir}: {display}")

    if args.preview:
        preview_search(config, env["CRUSTDATA_API_TOKEN"])
        return

    run_pipeline(
        config, env,
        test_mode=args.test,
        dry_run=args.dry_run,
        auto_confirm=args.yes,
    )


if __name__ == "__main__":
    main()
