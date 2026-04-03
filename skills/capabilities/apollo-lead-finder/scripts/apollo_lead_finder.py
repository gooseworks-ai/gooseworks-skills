#!/usr/bin/env python3
"""
Apollo Lead Finder — Two-Phase Prospecting Pipeline
-----------------------------------------------------
Phase 1 (Search): Free People Search to discover ICP-matching leads.
  Apollo's api_search returns Apollo person IDs + limited preview data
  (first name, title, org name, boolean flags). No LinkedIn URLs or emails.
  Results saved as a local JSON manifest for the enrich phase.

Phase 2 (Enrich): Selectively enrich leads via /people/bulk_match using
  Apollo person IDs. Returns full data (email, phone, LinkedIn URL, etc).
  Deduplicates against Supabase, upserts net-new leads.

Pipeline:
  Search:
    1. Build Apollo search payload from config
    2. Paginate through results (free)
    3. Apply title filters on preview data
    4. Save manifest JSON (Apollo IDs + preview data)
    5. Export search preview CSV

  Enrich:
    1. Load search manifest
    2. Bulk enrich via /people/bulk_match with Apollo IDs (batches of 10)
    3. Post-enrich dedup against Supabase LinkedIn URLs
    4. Upsert net-new leads to Supabase (enrichment_status='complete')
    5. Export enriched CSV

Usage:
    python3 skills/apollo-lead-finder/scripts/apollo_lead_finder.py \\
      --config skills/apollo-lead-finder/configs/{client}.json \\
      --phase {search,enrich,both} \\
      [--test] [--yes] [--dry-run] [--preview] [--limit N]

Flags:
    --config     Path to client config JSON (required)
    --phase      Which phase to run: search, enrich, or both (required)
    --test       Limit to test mode caps
    --yes        Skip confirmation prompts
    --preview    Show total count only (search phase)
    --dry-run    No API calls, show what would happen
    --limit N    Override enrichment limit
"""

import os
import sys
import json
import csv
import time
import argparse
from datetime import datetime, timezone

# Import apollo client from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apollo_client import ApolloClient

# Import shared supabase client from tools/supabase/
SUPABASE_TOOLS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "tools", "supabase"
)
sys.path.insert(0, os.path.abspath(SUPABASE_TOOLS))
from supabase_client import SupabaseClient

# ── Constants ────────────────────────────────────────────────────

RESULTS_PER_PAGE = 100  # Apollo max per_page

SEARCH_CSV_COLS = [
    "Apollo ID",
    "First Name",
    "Title",
    "Company",
    "Has Email",
    "Has Phone",
]

ENRICHED_CSV_COLS = [
    "Name",
    "Title",
    "Company",
    "Company LinkedIn URL",
    "Company Headcount",
    "Industry",
    "Person LinkedIn URL",
    "Location",
    "Headline",
    "Email",
    "Phone",
    "Seniority",
]

MODE_CAPS = {
    "test": {"max_pages": 1, "max_results": 100, "max_enrich": 10, "label": "TEST"},
    "standard": {"max_pages": 50, "max_results": 5000, "max_enrich": 500, "label": "STANDARD"},
    "full": {"max_pages": 500, "max_results": 50000, "max_enrich": 2500, "label": "FULL"},
}


# ── Config Loading ───────────────────────────────────────────────

def load_config(config_path):
    """Load and validate client config JSON."""
    with open(config_path) as f:
        config = json.load(f)

    required = ["client_name", "apollo_filters"]
    missing = [k for k in required if k not in config]
    if missing:
        print(f"ERROR: Config missing required fields: {missing}")
        sys.exit(1)

    if not isinstance(config["apollo_filters"], dict) or not config["apollo_filters"]:
        print("ERROR: 'apollo_filters' must be a non-empty dict of Apollo filter params")
        sys.exit(1)

    # Defaults
    config.setdefault("search_config_name", os.path.splitext(os.path.basename(config_path))[0])
    config.setdefault("icp_segment", "")
    config.setdefault("enrichment_filters", {})
    config.setdefault("apollo_list_name_prefix", config["client_name"])
    config.setdefault("create_apollo_list", True)
    config.setdefault("max_pages", 50)
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
    required_keys = ["APOLLO_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [k for k in required_keys if not env.get(k)]
    if missing:
        print(f"ERROR: Missing environment variables: {missing}")
        print("  Add them to your .env file.")
        sys.exit(1)

    return env


# ── Helpers ──────────────────────────────────────────────────────

def normalize_linkedin_url(url):
    """Normalize LinkedIn URL: lowercase, strip trailing slash and query params."""
    if not url:
        return ""
    url = url.split("?")[0].rstrip("/").lower()
    return url


def extract_search_person(person):
    """Extract preview data from Apollo api_search result.

    The free search endpoint returns limited data:
    - id, first_name, last_name_obfuscated, title
    - has_email, has_city, has_state, has_country, has_direct_phone
    - organization: {name, has_industry, has_phone, ...}
    """
    if not person:
        return None

    return {
        "apollo_id": person.get("id") or "",
        "first_name": person.get("first_name") or "",
        "last_name_obfuscated": person.get("last_name_obfuscated") or "",
        "title": person.get("title") or "",
        "company": (person.get("organization") or {}).get("name") or "",
        "has_email": person.get("has_email", False),
        "has_phone": person.get("has_direct_phone", "No") not in ("No", False, None, ""),
    }


def extract_enriched_person(person):
    """Extract full data from an Apollo enrichment (bulk_match) result."""
    if not person:
        return None

    name = person.get("name") or ""
    first_name = person.get("first_name") or ""
    last_name = person.get("last_name") or ""
    if not name and (first_name or last_name):
        name = f"{first_name} {last_name}".strip()

    linkedin_url = normalize_linkedin_url(person.get("linkedin_url") or "")

    title = person.get("title") or ""
    headline = person.get("headline") or ""
    seniority = person.get("seniority") or ""
    city = person.get("city") or ""
    state = person.get("state") or ""
    country = person.get("country") or ""
    location_parts = [p for p in [city, state, country] if p]
    location = ", ".join(location_parts)

    # Organization data
    org = person.get("organization") or {}
    company = org.get("name") or ""
    company_linkedin = org.get("linkedin_url") or ""
    company_domain = org.get("primary_domain") or org.get("website_url") or ""
    if company_domain:
        company_domain = company_domain.replace("https://", "").replace("http://", "").rstrip("/")
    industry = org.get("industry") or ""
    headcount = org.get("estimated_num_employees") or ""

    email = person.get("email") or ""
    phone = ""
    # bulk_match returns phone at top level for some plans
    if person.get("sanitized_phone"):
        phone = person["sanitized_phone"]
    # Also check organization phone as fallback
    if not phone and org.get("sanitized_phone"):
        phone = org["sanitized_phone"]

    apollo_id = person.get("id") or ""

    return {
        "apollo_id": apollo_id,
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "linkedin_url": linkedin_url,
        "email": email,
        "phone": phone,
        "title": title,
        "headline": headline,
        "seniority": seniority,
        "company": company,
        "company_linkedin_url": company_linkedin,
        "company_domain": company_domain,
        "industry": industry,
        "company_headcount": str(headcount) if headcount else "",
        "location": location,
    }


def apply_title_filters(person_data, enrichment_filters):
    """Apply title-based filters from config. Returns True if person passes."""
    if not enrichment_filters:
        return True

    exclude_titles = enrichment_filters.get("exclude_titles_containing", [])
    if exclude_titles and person_data.get("title"):
        title_lower = person_data["title"].lower()
        for keyword in exclude_titles:
            if keyword.lower() in title_lower:
                return False

    return True


def map_to_supabase_person(person_data, config):
    """Map enriched Apollo person data to a Supabase people table row."""
    person = {
        "linkedin_url": person_data["linkedin_url"],
        "apollo_id": person_data.get("apollo_id") or None,
        "name": person_data["name"],
        "first_name": person_data["first_name"],
        "last_name": person_data["last_name"],
        "email": person_data["email"] or None,
        "phone": person_data.get("phone") or None,
        "email_verified": bool(person_data.get("email")),
        "title": person_data["title"] or None,
        "company_name": person_data["company"] or None,
        "company_domain": person_data["company_domain"] or None,
        "company_linkedin_url": person_data["company_linkedin_url"] or None,
        "company_headcount": person_data["company_headcount"] or None,
        "industry": person_data["industry"] or None,
        "location": person_data["location"] or None,
        "seniority_level": person_data["seniority"] or None,
        "headline": person_data["headline"] or None,
        "source": "apollo",
        "updated_by": "apollo-lead-finder",
        "client_name": config["client_name"],
        "search_config_name": config["search_config_name"],
        "icp_segment": config.get("icp_segment") or None,
        "lead_status": "active",
        "enrichment_status": "complete",
    }

    return person


def export_csv(rows, cols, csv_path):
    """Write rows to CSV file."""
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def get_manifest_path(config):
    """Get path for the search manifest JSON."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(script_dir, "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{config['client_name']}-{config['search_config_name']}-manifest.json")


# ── Search Phase (FREE) ─────────────────────────────────────────

def run_search(config, env, mode, dry_run=False, auto_confirm=False, preview_only=False):
    """Search phase pipeline. FREE — no credits consumed.

    Collects Apollo person IDs + preview data and saves as manifest.
    """
    apollo = ApolloClient(env["APOLLO_API_KEY"])
    client_name = config["client_name"]
    max_pages = min(config["max_pages"], mode["max_pages"])
    filters = config["apollo_filters"]
    enrichment_filters = config.get("enrichment_filters", {})

    # ── Step 1: Build payload ─────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 1: Build Apollo Search Payload")
    print(f"{'='*60}")

    print(f"  Filters:")
    for key, val in filters.items():
        if isinstance(val, list) and len(val) > 3:
            display = ", ".join(str(v) for v in val[:3]) + f" (+{len(val)-3} more)"
        elif isinstance(val, list):
            display = ", ".join(str(v) for v in val)
        else:
            display = str(val)
        print(f"    {key}: {display}")
    print(f"  Mode: {mode['label']}, max pages: {max_pages}")

    if dry_run:
        print(f"\n  [DRY RUN] Would search Apollo with these filters.")
        print(f"  [DRY RUN] No API calls made.")
        return {"dry_run": True}

    # ── Step 2: First page + total count ──────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 2: Search Apollo (Page 1)")
    print(f"{'='*60}")

    result = apollo.search_people(filters, page=1, per_page=RESULTS_PER_PAGE)

    if not result:
        print("  ERROR: No response from Apollo API.")
        return {"new_leads": 0, "error": True}

    people_raw = result.get("people") or []
    total_entries = result.get("total_entries", len(people_raw))

    print(f"  Page 1 returned: {len(people_raw)} people")
    print(f"  Total matching (total_entries): {total_entries:,}")

    if preview_only:
        est_pages = min((total_entries + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE, max_pages)
        print(f"\n  Estimated pages needed: {est_pages}")
        print(f"  Estimated results: {min(total_entries, est_pages * RESULTS_PER_PAGE):,}")
        print(f"  Search cost: FREE")
        return {"total_matching": total_entries, "preview": True}

    if not people_raw:
        print("\n  No leads found matching filters.")
        return {"new_leads": 0, "total_matching": total_entries, "pages_fetched": 1}

    # Calculate pages needed
    total_pages = min(
        (total_entries + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE,
        max_pages,
    )

    print(f"\n  Pages to fetch: {total_pages}")
    print(f"  Search cost: FREE (People Search costs no credits)")

    if not auto_confirm and total_pages > 1:
        answer = input(f"\n  Fetch {total_pages} pages (~{min(total_entries, total_pages * RESULTS_PER_PAGE):,} results)? [y/N] ").strip().lower()
        if answer != "y":
            print("  Aborted.")
            return {"aborted": True}

    # ── Step 3: Paginate through results ──────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 3: Fetch All Pages")
    print(f"{'='*60}")

    # Collect all people by Apollo ID
    all_people = {}
    skipped_filter = 0

    for person in people_raw:
        data = extract_search_person(person)
        if not data or not data["apollo_id"]:
            continue
        if not apply_title_filters(data, enrichment_filters):
            skipped_filter += 1
            continue
        all_people[data["apollo_id"]] = data

    pages_fetched = 1

    for page in range(2, total_pages + 1):
        print(f"  Page {page}/{total_pages}...", end="", flush=True)

        try:
            page_result = apollo.search_people(filters, page=page, per_page=RESULTS_PER_PAGE)
        except Exception as e:
            print(f" ERROR: {e}")
            print(f"  Stopping pagination. Saving {len(all_people)} profiles collected so far.")
            break

        if not page_result:
            print(" empty response, stopping.")
            break

        page_people = page_result.get("people") or []
        new_on_page = 0

        for person in page_people:
            data = extract_search_person(person)
            if not data or not data["apollo_id"]:
                continue
            if not apply_title_filters(data, enrichment_filters):
                skipped_filter += 1
                continue
            if data["apollo_id"] not in all_people:
                all_people[data["apollo_id"]] = data
                new_on_page += 1

        pages_fetched += 1
        print(f" {len(page_people)} returned, {new_on_page} new")

        if len(page_people) < RESULTS_PER_PAGE:
            print(f"  Last page reached (partial page).")
            break

    print(f"\n  Total unique profiles collected: {len(all_people)}")
    if skipped_filter:
        print(f"  Skipped (title filters): {skipped_filter}")

    with_email = sum(1 for d in all_people.values() if d.get("has_email"))
    with_phone = sum(1 for d in all_people.values() if d.get("has_phone"))
    print(f"  Profiles with email available: {with_email}/{len(all_people)}")
    print(f"  Profiles with phone available: {with_phone}/{len(all_people)}")

    if not all_people:
        print("\n  No leads passed filters.")
        return {"new_leads": 0, "total_matching": total_entries, "pages_fetched": pages_fetched}

    # ── Step 4: Save manifest ─────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 4: Save Search Manifest")
    print(f"{'='*60}")

    manifest = {
        "client_name": client_name,
        "search_config_name": config["search_config_name"],
        "icp_segment": config.get("icp_segment", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_matching": total_entries,
        "pages_fetched": pages_fetched,
        "filters": config["apollo_filters"],
        "people": list(all_people.values()),
    }

    manifest_path = get_manifest_path(config)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  Manifest saved: {manifest_path}")
    print(f"  People in manifest: {len(all_people)}")

    # ── Step 5: Export search preview CSV ─────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 5: Export Search Preview CSV")
    print(f"{'='*60}")

    csv_rows = []
    for data in all_people.values():
        csv_rows.append({
            "Apollo ID": data["apollo_id"],
            "First Name": data["first_name"],
            "Title": data["title"],
            "Company": data["company"],
            "Has Email": "Yes" if data.get("has_email") else "No",
            "Has Phone": "Yes" if data.get("has_phone") else "No",
        })
    csv_rows.sort(key=lambda r: r["First Name"].lower())

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(script_dir, "..", "output")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = export_csv(csv_rows, SEARCH_CSV_COLS, os.path.join(out_dir, f"{client_name}-search-{timestamp}.csv"))

    print(f"  CSV exported: {csv_path}")
    print(f"  Total rows: {len(csv_rows)}")

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Search Summary")
    print(f"{'='*60}")
    print(f"  Client: {client_name}")
    print(f"  Config: {config['search_config_name']}")
    print(f"  Mode: {mode['label']}")
    print(f"  Pages fetched: {pages_fetched}")
    print(f"  Total matching profiles: {total_entries:,}")
    print(f"  Profiles collected: {len(all_people)}")
    print(f"  With email available: {with_email}")
    print(f"  Credits used: 0 (search is free)")

    # Show top 10
    if all_people:
        print(f"\n  Top 10 leads (preview — full data after enrichment):")
        print(f"  {'First Name':<18} {'Title':<32} {'Company':<22} {'Email?'}")
        print(f"  {'-'*80}")
        for data in list(all_people.values())[:10]:
            email_flag = "Yes" if data.get("has_email") else "No"
            print(f"  {data['first_name'][:17]:<18} {data['title'][:31]:<32} {data['company'][:21]:<22} {email_flag}")

    print(f"\n  Manifest: {manifest_path}")
    print(f"  CSV: {csv_path}")
    print(f"\n  Next step: Run --phase enrich to reveal emails/phones ({len(all_people)} credits)")

    return {
        "total_matching": total_entries,
        "collected": len(all_people),
        "pages_fetched": pages_fetched,
        "with_email_available": with_email,
        "manifest_path": manifest_path,
        "csv_path": csv_path,
    }


# ── Enrich Phase (COSTS CREDITS) ────────────────────────────────

def run_enrich(config, env, mode, auto_confirm=False, dry_run=False, limit_override=None):
    """Enrich phase pipeline. Costs 1 credit per contact.

    Reads search manifest, bulk-enriches by Apollo ID, deduplicates
    against Supabase, and upserts net-new leads.
    """
    apollo = ApolloClient(env["APOLLO_API_KEY"])
    client_name = config["client_name"]
    max_enrich = limit_override or mode["max_enrich"]

    # ── Step 1: Load search manifest ──────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 1: Load Search Manifest")
    print(f"{'='*60}")

    manifest_path = get_manifest_path(config)
    if not os.path.exists(manifest_path):
        print(f"  ERROR: No search manifest found at {manifest_path}")
        print(f"  Run --phase search first to discover leads.")
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    people = manifest.get("people", [])
    print(f"  Manifest: {manifest_path}")
    print(f"  Search timestamp: {manifest.get('timestamp', 'unknown')}")
    print(f"  People in manifest: {len(people)}")

    if not people:
        print("  No people in manifest. Run --phase search first.")
        return {"enriched": 0}

    # Cap to enrich limit
    people_to_enrich = people[:max_enrich]
    print(f"  Enrichment cap: {max_enrich}")
    print(f"  Will enrich: {len(people_to_enrich)}")

    if dry_run:
        print(f"\n  [DRY RUN] Would enrich {len(people_to_enrich)} leads ({len(people_to_enrich)} credits)")
        print(f"  [DRY RUN] No API calls made.")
        return {"dry_run": True, "would_enrich": len(people_to_enrich)}

    # ── Step 2: Fetch existing URLs for dedup ─────────────────────
    print(f"\n{'='*60}")
    print(f"Step 2: Connect to Supabase & Fetch Existing URLs")
    print(f"{'='*60}")

    sb = SupabaseClient(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])

    if not sb.test_connection():
        print("  ERROR: Cannot connect to Supabase.")
        sys.exit(1)
    print("  Connected successfully")

    raw_urls = sb.get_all_linkedin_urls()
    existing_urls = {normalize_linkedin_url(u) for u in raw_urls if u}
    print(f"  Existing leads in Supabase: {len(existing_urls):,}")

    # ── Step 3: Confirm credit cost ───────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 3: Confirm Enrichment")
    print(f"{'='*60}")

    credit_cost = len(people_to_enrich)
    print(f"  Leads to enrich: {credit_cost}")
    print(f"  Credit cost: {credit_cost} credits (1 per contact)")

    if not auto_confirm:
        answer = input(f"\n  Enrich {credit_cost} leads ({credit_cost} credits)? [y/N] ").strip().lower()
        if answer != "y":
            print("  Aborted.")
            return {"aborted": True}

    # ── Step 4: Bulk enrich ───────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 4: Bulk Enrich via Apollo")
    print(f"{'='*60}")

    enriched_people = []
    failed_count = 0
    batch_size = 10
    credits_consumed = 0

    for i in range(0, len(people_to_enrich), batch_size):
        batch = people_to_enrich[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(people_to_enrich) + batch_size - 1) // batch_size
        print(f"  Batch {batch_num}/{total_batches} ({len(batch)} leads)...", end="", flush=True)

        # Build details for bulk match using Apollo person IDs
        details = [{"id": p["apollo_id"]} for p in batch]

        try:
            result = apollo.bulk_enrich_people(details)
        except Exception as e:
            print(f" ERROR: {e}")
            failed_count += len(batch)
            continue

        if not result:
            print(" empty response")
            failed_count += len(batch)
            continue

        matches = result.get("matches") or []
        batch_credits = result.get("credits_consumed", len(batch))
        credits_consumed += batch_credits
        matched_count = 0

        for match in matches:
            if match:
                person_data = extract_enriched_person(match)
                if person_data and person_data.get("linkedin_url"):
                    enriched_people.append(person_data)
                    matched_count += 1
                else:
                    failed_count += 1
            else:
                failed_count += 1

        print(f" {matched_count} matched, {len(batch) - matched_count} failed")

        # Brief pause between batches
        if i + batch_size < len(people_to_enrich):
            time.sleep(1)

    print(f"\n  Total enriched: {len(enriched_people)}")
    print(f"  Failed to match: {failed_count}")
    print(f"  Credits consumed: {credits_consumed}")

    # ── Step 5: Dedup against Supabase ────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 5: Deduplicate Against Supabase")
    print(f"{'='*60}")

    before_dedup = len(enriched_people)
    net_new = [p for p in enriched_people if p["linkedin_url"] not in existing_urls]
    duplicates_removed = before_dedup - len(net_new)

    print(f"  Enriched leads: {before_dedup}")
    print(f"  Already in Supabase: {duplicates_removed}")
    print(f"  Net-new leads: {len(net_new)}")

    # ── Step 6: Upsert to Supabase ────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 6: Upsert to Supabase")
    print(f"{'='*60}")

    if net_new:
        people = [map_to_supabase_person(data, config) for data in net_new]
        upserted = sb.upsert_people(people)
        print(f"  Upserted {upserted} people to Supabase (source='apollo', enrichment_status='complete')")
    else:
        upserted = 0
        print(f"  No net-new leads to upsert.")

    # ── Step 7: Export enriched CSV ───────────────────────────────
    print(f"\n{'='*60}")
    print(f"Step 7: Export Enriched CSV")
    print(f"{'='*60}")

    csv_rows = []
    for data in net_new:
        csv_rows.append({
            "Name": data["name"],
            "Title": data["title"],
            "Company": data["company"],
            "Company LinkedIn URL": data["company_linkedin_url"],
            "Company Headcount": data["company_headcount"],
            "Industry": data["industry"],
            "Person LinkedIn URL": data["linkedin_url"],
            "Location": data["location"],
            "Headline": data["headline"],
            "Email": data.get("email") or "",
            "Phone": data.get("phone") or "",
            "Seniority": data.get("seniority") or "",
        })
    csv_rows.sort(key=lambda r: r["Name"].lower())

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(script_dir, "..", "output")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = export_csv(csv_rows, ENRICHED_CSV_COLS, os.path.join(out_dir, f"{client_name}-enriched-{timestamp}.csv"))

    print(f"  CSV exported: {csv_path}")
    print(f"  Total rows: {len(csv_rows)}")

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Enrichment Summary")
    print(f"{'='*60}")
    print(f"  Client: {client_name}")
    print(f"  Config: {config['search_config_name']}")
    print(f"  Leads enriched: {len(enriched_people)}")
    print(f"  Duplicates (in Supabase): {duplicates_removed}")
    print(f"  Net-new leads: {len(net_new)}")
    print(f"  Upserted to Supabase: {upserted}")
    print(f"  Credits consumed: {credits_consumed}")

    with_email = sum(1 for d in net_new if d.get("email"))
    with_phone = sum(1 for d in net_new if d.get("phone"))
    print(f"  With email: {with_email}/{len(net_new)}")
    print(f"  With phone: {with_phone}/{len(net_new)}")

    if net_new:
        print(f"\n  Top 10 enriched leads:")
        print(f"  {'Name':<22} {'Title':<22} {'Company':<16} {'Email':<28}")
        print(f"  {'-'*88}")
        for data in net_new[:10]:
            email = data.get("email") or "(none)"
            print(f"  {data['name'][:21]:<22} {data['title'][:21]:<22} {data['company'][:15]:<16} {email[:27]:<28}")

    print(f"\n  Output: {csv_path}")

    # Remove enriched people from manifest (so re-running enrich skips them)
    enriched_ids = {p["apollo_id"] for p in enriched_people}
    remaining = [p for p in manifest.get("people", []) if p["apollo_id"] not in enriched_ids]
    manifest["people"] = remaining
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Manifest updated: {len(remaining)} people remaining for future enrichment")

    return {
        "enriched": len(enriched_people),
        "duplicates_removed": duplicates_removed,
        "net_new": len(net_new),
        "upserted": upserted,
        "with_email": with_email,
        "with_phone": with_phone,
        "credits_consumed": credits_consumed,
        "csv_path": csv_path,
    }


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Apollo Lead Finder — Two-Phase Prospecting Pipeline"
    )
    parser.add_argument("--config", required=True, help="Path to client config JSON")
    parser.add_argument("--phase", required=True, choices=["search", "enrich", "both"],
                        help="Phase to run: search (free), enrich (costs credits), or both")
    parser.add_argument("--test", action="store_true", help="Test mode: reduced caps")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--preview", action="store_true", help="Preview only: show total count (search phase)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, no API calls")
    parser.add_argument("--limit", type=int, help="Override enrichment limit")
    args = parser.parse_args()

    config = load_config(args.config)
    env = load_env()

    client_name = config["client_name"]

    # Determine mode
    if args.test:
        mode = MODE_CAPS["test"]
    else:
        mode_name = config.get("mode", "standard")
        mode = MODE_CAPS.get(mode_name, MODE_CAPS["standard"])

    mode_label = mode["label"]

    print(f"\n{'='*60}")
    print(f"Apollo Lead Finder")
    print(f"{'='*60}")
    print(f"  Client: {client_name}")
    print(f"  Config: {args.config}")
    print(f"  Phase: {args.phase}")
    print(f"  Mode: {mode_label}")
    if args.dry_run:
        print(f"  DRY RUN — no API calls will be made")

    # Display filters
    filters = config["apollo_filters"]
    print(f"\n  Apollo Filters:")
    for key, val in filters.items():
        if isinstance(val, list) and len(val) > 3:
            display = ", ".join(str(v) for v in val[:3]) + f" (+{len(val)-3} more)"
        elif isinstance(val, list):
            display = ", ".join(str(v) for v in val)
        else:
            display = str(val)
        print(f"    {key}: {display}")

    # Run phases
    if args.phase in ("search", "both"):
        run_search(
            config, env, mode,
            dry_run=args.dry_run,
            auto_confirm=args.yes,
            preview_only=args.preview,
        )

    if args.phase in ("enrich", "both"):
        if args.preview:
            print("\n  Skipping enrich phase in preview mode.")
        else:
            run_enrich(
                config, env, mode,
                auto_confirm=args.yes,
                dry_run=args.dry_run,
                limit_override=args.limit,
            )


if __name__ == "__main__":
    main()
