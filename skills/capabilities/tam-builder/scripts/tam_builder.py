#!/usr/bin/env python3
"""
TAM Builder — Build, Refresh, and Monitor your Total Addressable Market
------------------------------------------------------------------------
Single script with three modes:
  build   — Apollo Company Search → upsert → score → tier → watchlist
  refresh — Re-search → upsert/update → re-score → deprecation → watchlist sync
  status  — Read-only report of current TAM state

Pipeline (build):
  Phase 1: Search Apollo → upsert raw companies → score ICP fit → assign tiers
  Phase 3: Persona Watchlist → pull 2-3 personas per Tier 1-2 company (free)
  Phase 4: People Enrichment → SixtyFour first → Apollo fallback (contact data)

Pipeline (refresh):
  Phase 1: Search Apollo → upsert/update companies → re-score → detect tier changes
  Phase 2: Deprecation check → companies missing 2x → deprecated
  Phase 3: Persona Watchlist → new/promoted companies get personas, deprecated lose them
  Phase 4: People Enrichment → enrich any pending personas

Core functions (build_tam, refresh_tam, get_tam_status) are importable for
trigger.dev automation — CLI main() is a thin wrapper.

Usage:
    python3 skills/capabilities/tam-builder/scripts/tam_builder.py \\
      --config skills/capabilities/tam-builder/configs/{client}.json \\
      --mode {build,refresh,status} \\
      [--test] [--yes] [--dry-run] [--preview] [--skip-watchlist]
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime, timezone

# Import apollo client from the apollo-lead-finder skill
APOLLO_SCRIPTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "apollo-lead-finder", "scripts"
)
sys.path.insert(0, os.path.abspath(APOLLO_SCRIPTS))
from apollo_client import ApolloClient

# Import shared supabase client
SUPABASE_TOOLS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "tools", "supabase"
)
sys.path.insert(0, os.path.abspath(SUPABASE_TOOLS))
from supabase_client import SupabaseClient

# Import SixtyFour client (optional — enrichment fallback)
SIXTYFOUR_TOOLS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "tools", "sixtyfour"
)
sys.path.insert(0, os.path.abspath(SIXTYFOUR_TOOLS))
try:
    from sixtyfour_client import SixtyFourClient
except ImportError:
    SixtyFourClient = None

# ── Constants ────────────────────────────────────────────────────

RESULTS_PER_PAGE = 100  # Apollo max per_page

MODE_CAPS = {
    "test": {"max_pages": 1, "max_companies": 100, "label": "TEST"},
    "standard": {"max_pages": 50, "max_companies": 5000, "label": "STANDARD"},
    "full": {"max_pages": 200, "max_companies": 20000, "label": "FULL"},
}


# ── Config & Env Loading ─────────────────────────────────────────

def load_config(config_path):
    """Load and validate TAM builder config JSON."""
    with open(config_path) as f:
        config = json.load(f)

    required = ["client_name", "company_filters", "scoring"]
    missing = [k for k in required if k not in config]
    if missing:
        print(f"ERROR: Config missing required fields: {missing}")
        sys.exit(1)

    if not isinstance(config["company_filters"], dict) or not config["company_filters"]:
        print("ERROR: 'company_filters' must be a non-empty dict of Apollo org filter params")
        sys.exit(1)

    # Defaults
    config.setdefault("tam_config_name", os.path.splitext(os.path.basename(config_path))[0])
    config.setdefault("max_pages", 50)
    config.setdefault("mode", "standard")
    config.setdefault("watchlist", {"enabled": False})

    return config


def load_env():
    """Walk up from script dir looking for .env, then check cwd."""
    candidates = []
    script_dir = os.path.dirname(os.path.abspath(__file__))
    d = script_dir
    for _ in range(6):
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

    required_keys = ["APOLLO_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [k for k in required_keys if not env.get(k)]
    if missing:
        print(f"ERROR: Missing environment variables: {missing}")
        print("  Add them to your .env file.")
        sys.exit(1)

    # SIXTYFOUR_API_KEY is optional — enables SixtyFour-first enrichment
    # If not present, falls back to Apollo-only enrichment
    return env


# ── Schema Validation ────────────────────────────────────────────

REQUIRED_COLUMNS = {
    "companies": ["sixtyfour_id", "company_type"],
    "people": ["sixtyfour_id"],
}


def validate_schema(sb):
    """Pre-flight check: verify required columns exist in the live database.

    Prevents silent data loss from Supabase rejecting writes that include
    columns missing from the live schema. Catches schema drift early.

    Returns:
        (ok: bool, errors: list[str])
    """
    errors = []
    for table, columns in REQUIRED_COLUMNS.items():
        try:
            row = sb._request("GET", table, params={"limit": "1", "select": ",".join(columns)})
            # If we get here without error, columns exist (even if table is empty)
        except Exception as e:
            error_str = str(e)
            for col in columns:
                if col in error_str:
                    errors.append(
                        f"Column '{col}' missing from '{table}' table. "
                        f"Run: ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} TEXT;"
                    )
            if not any(col in error_str for col in columns):
                errors.append(f"Schema check failed for '{table}': {error_str}")

    return (len(errors) == 0, errors)


# ── Enrichment Helpers ───────────────────────────────────────────

def merge_sixtyfour_data(org_data, sf_result, task_id=None):
    """Merge SixtyFour enrichment result into org_data dict."""
    sd = sf_result.get("structured_data", {})
    org_data["industry"] = sd.get("industry") or org_data.get("industry") or ""
    org_data["employee_count"] = sd.get("employee_count") or org_data.get("employee_count") or 0
    org_data["funding_stage"] = sd.get("funding_stage") or org_data.get("funding_stage") or ""
    org_data["total_funding"] = sd.get("total_funding") or org_data.get("total_funding") or ""
    org_data["founded_year"] = sd.get("founded_year") or org_data.get("founded_year")
    org_data["hq_location"] = sd.get("headquarters") or org_data.get("hq_location") or ""
    org_data["tech_stack"] = sd.get("technologies") or org_data.get("tech_stack") or []

    # Track SixtyFour task_id for selective re-enrichment
    if task_id:
        org_data["sixtyfour_id"] = task_id

    # Store full SixtyFour response in raw_data alongside search data
    search_raw = org_data.get("raw_data") or {}
    org_data["raw_data"] = {
        "_search_data": search_raw.get("_search_data", search_raw),
        "_sixtyfour_data": sf_result,
        **{k: v for k, v in search_raw.items() if k not in ("_search_data", "_sixtyfour_data")},
    }


def merge_apollo_enrichment(org_data, org_enriched):
    """Merge Apollo /organizations/enrich result into org_data dict."""
    org_data["industry"] = org_enriched.get("industry") or org_data.get("industry") or ""
    org_data["employee_count"] = org_enriched.get("estimated_num_employees") or org_data.get("employee_count") or 0
    org_data["funding_stage"] = org_enriched.get("latest_funding_stage") or org_data.get("funding_stage") or ""
    org_data["total_funding"] = org_enriched.get("total_funding_printed") or org_data.get("total_funding") or ""
    org_data["tech_stack"] = org_enriched.get("technology_names") or org_data.get("tech_stack") or []
    org_data["estimated_revenue"] = org_enriched.get("annual_revenue_printed") or org_data.get("estimated_revenue") or ""
    org_data["hq_location"] = ", ".join(
        p for p in [
            org_enriched.get("city") or "",
            org_enriched.get("state") or "",
            org_enriched.get("country") or "",
        ] if p
    ) or org_data.get("hq_location") or ""
    org_data["country"] = org_enriched.get("country") or org_data.get("country") or ""
    org_data["keywords"] = org_enriched.get("keywords") or org_data.get("keywords") or []
    if isinstance(org_data["keywords"], str):
        org_data["keywords"] = [k.strip() for k in org_data["keywords"].split(",") if k.strip()]
    org_data["founded_year"] = org_enriched.get("founded_year") or org_data.get("founded_year")

    # Merge raw_data: search response + enrichment response
    search_raw = org_data.get("raw_data") or {}
    org_data["raw_data"] = {
        **{k: v for k, v in search_raw.items() if not k.startswith("_")},
        **org_enriched,
        "_search_data": search_raw.get("_search_data", search_raw),
    }
    # Preserve SixtyFour data if present (from a prior SixtyFour attempt)
    if "_sixtyfour_data" in search_raw:
        org_data["raw_data"]["_sixtyfour_data"] = search_raw["_sixtyfour_data"]


def merge_sixtyfour_lead_data(person_row, sf_result, task_id):
    """Merge SixtyFour lead enrichment result into a person row dict.

    Maps structured_data fields → people table columns.
    Sets sixtyfour_id and enrichment_status.
    If SixtyFour returns a real LinkedIn URL, replaces synthetic apollo:// URL.
    """
    sd = sf_result.get("structured_data", {})

    person_row["email"] = sd.get("email") or person_row.get("email")
    person_row["phone"] = sd.get("phone") or person_row.get("phone")
    person_row["title"] = sd.get("title") or person_row.get("title")
    person_row["seniority_level"] = sd.get("seniority") or person_row.get("seniority_level")
    person_row["location"] = sd.get("location") or person_row.get("location")
    person_row["headline"] = sd.get("bio") or person_row.get("headline")

    # Skills — SixtyFour returns comma-separated string, we store as text[]
    sf_skills = sd.get("skills")
    if sf_skills:
        if isinstance(sf_skills, str):
            sf_skills = [s.strip() for s in sf_skills.split(",") if s.strip()]
        person_row["skills"] = sf_skills

    # LinkedIn URL — replace synthetic apollo:// URL with real one
    sf_linkedin = sd.get("linkedin_url")
    if sf_linkedin and sf_linkedin.startswith("http"):
        person_row["linkedin_url"] = sf_linkedin

    person_row["sixtyfour_id"] = task_id
    person_row["enrichment_status"] = "complete"

    # Store full response in raw_data
    existing_raw = person_row.get("raw_data") or {}
    if not isinstance(existing_raw, dict):
        existing_raw = {}
    person_row["raw_data"] = {**existing_raw, "_sixtyfour_data": sf_result}


def merge_apollo_person_enrichment(person_row, apollo_person):
    """Merge Apollo person enrichment result into a person row dict.

    Maps Apollo /people/match response → people table columns.
    Sets enrichment_status to 'complete'.
    """
    person_row["email"] = apollo_person.get("email") or person_row.get("email")
    person_row["email_verified"] = apollo_person.get("email_status") == "verified"
    person_row["title"] = apollo_person.get("title") or person_row.get("title")
    person_row["headline"] = apollo_person.get("headline") or person_row.get("headline")
    person_row["seniority_level"] = apollo_person.get("seniority") or person_row.get("seniority_level")

    # LinkedIn URL — replace synthetic apollo:// URL with real one
    apollo_linkedin = apollo_person.get("linkedin_url")
    if apollo_linkedin and apollo_linkedin.startswith("http"):
        person_row["linkedin_url"] = apollo_linkedin

    # Location
    city = apollo_person.get("city") or ""
    state = apollo_person.get("state") or ""
    country = apollo_person.get("country") or ""
    location = ", ".join(p for p in [city, state, country] if p)
    if location:
        person_row["location"] = location

    # Phone — Apollo returns phone_numbers array
    phone_numbers = apollo_person.get("phone_numbers") or []
    if phone_numbers and isinstance(phone_numbers, list):
        # Prefer direct_dial, then mobile, then any
        for ptype in ["direct_dial", "mobile", "work_direct"]:
            match = next((p for p in phone_numbers if p.get("type") == ptype), None)
            if match:
                person_row["phone"] = match.get("sanitized_number") or match.get("number")
                break
        else:
            first = phone_numbers[0]
            person_row["phone"] = first.get("sanitized_number") or first.get("number")

    person_row["enrichment_status"] = "complete"

    # Store Apollo enrichment in raw_data
    existing_raw = person_row.get("raw_data") or {}
    if not isinstance(existing_raw, dict):
        existing_raw = {}
    person_row["raw_data"] = {**existing_raw, "_apollo_enrichment": apollo_person}


def enrich_companies(all_orgs, sb, apollo, env, config, run_id, auto_confirm=False):
    """Two-tier enrichment: SixtyFour first, Apollo fallback.

    If SIXTYFOUR_API_KEY is set and SixtyFourClient is available, enriches via
    SixtyFour batch API first. Companies that fail or return low confidence
    (<5.0) fall back to Apollo. If no SixtyFour key, Apollo-only.

    Mutates org_data dicts in all_orgs in-place. Upserts to Supabase after each.

    Returns:
        dict with enrichment stats.
    """
    sf_key = env.get("SIXTYFOUR_API_KEY")
    use_sixtyfour = sf_key and SixtyFourClient is not None
    confidence_threshold = 5.0

    enriched_count = 0
    sf_enriched = 0
    apollo_enriched = 0
    enrich_failed = 0
    credits_used = 0

    if not auto_confirm and len(all_orgs) > 0:
        if use_sixtyfour:
            prompt_msg = (
                f"\n  Enrich {len(all_orgs)} companies? "
                f"(SixtyFour first → Apollo fallback) [y/N] "
            )
        else:
            prompt_msg = (
                f"\n  Enrich {len(all_orgs)} companies? "
                f"(1 Apollo credit each, {len(all_orgs)} total) [y/N] "
            )
        answer = input(prompt_msg).strip().lower()
        if answer != "y":
            print("  Skipping enrichment. Scoring will use search data only.")
            return {
                "enriched": 0, "sf_enriched": 0, "apollo_enriched": 0,
                "failed": 0, "credits_used": 0, "skipped": True,
            }

    # ── SixtyFour batch enrichment ──────────────────────────────
    apollo_fallback_domains = set()

    if use_sixtyfour:
        sf_client = SixtyFourClient(sf_key)
        companies_list = [
            {"company_name": data["company_name"], "domain": domain}
            for domain, data in all_orgs.items()
        ]

        print(f"\n  SixtyFour: Submitting {len(companies_list)} companies (async batch)...")
        sf_results = sf_client.batch_enrich(
            companies_list, timeout=300, poll_interval=10, return_task_ids=True,
        )

        for domain, (task_id, sf_result) in sf_results.items():
            data = all_orgs.get(domain)
            if not data:
                continue

            if sf_result is None:
                apollo_fallback_domains.add(domain)
                continue

            # Check confidence
            confidence = sf_result.get("confidence", 0)
            if isinstance(confidence, str):
                try:
                    confidence = float(confidence)
                except (ValueError, TypeError):
                    confidence = 0

            if confidence < confidence_threshold:
                print(f"    {domain}: low confidence ({confidence}), → Apollo fallback")
                apollo_fallback_domains.add(domain)
                continue

            merge_sixtyfour_data(data, sf_result, task_id=task_id)
            enriched_row = map_to_supabase_company(data, config, run_id)
            sb.upsert_companies([enriched_row])
            sf_enriched += 1
            enriched_count += 1

            industry = (data.get("industry") or "")[:20]
            emp = data.get("employee_count") or "?"
            print(f"    {domain}: {industry} | {emp} emp | SixtyFour (conf: {confidence})")

        # Any domain not in sf_results at all → fallback
        for domain in all_orgs:
            if domain not in sf_results:
                apollo_fallback_domains.add(domain)

        print(f"\n  SixtyFour enriched: {sf_enriched}")
        print(f"  Apollo fallback needed: {len(apollo_fallback_domains)}")
    else:
        # No SixtyFour key — all companies go to Apollo
        apollo_fallback_domains = set(all_orgs.keys())
        if apollo_fallback_domains:
            print(f"\n  No SixtyFour API key — using Apollo enrichment for all {len(apollo_fallback_domains)} companies")

    # ── Apollo fallback enrichment ──────────────────────────────
    if apollo_fallback_domains:
        fallback_list = sorted(apollo_fallback_domains)
        for i, domain in enumerate(fallback_list):
            data = all_orgs.get(domain)
            if not data:
                continue

            print(f"  [{i+1}/{len(fallback_list)}] {domain}...", end="", flush=True)

            try:
                enrich_result = apollo.enrich_organization(domain=domain)
            except Exception as e:
                print(f" ERROR: {e}")
                enrich_failed += 1
                continue

            if not enrich_result or not enrich_result.get("organization"):
                print(" no data")
                enrich_failed += 1
                continue

            org_enriched = enrich_result["organization"]
            credits_used += 1

            merge_apollo_enrichment(data, org_enriched)
            enriched_row = map_to_supabase_company(data, config, run_id)
            sb.upsert_companies([enriched_row])
            apollo_enriched += 1
            enriched_count += 1

            industry = (data.get("industry") or "")[:20]
            emp = data.get("employee_count") or "?"
            print(f" {industry} | {emp} emp | Apollo")

            time.sleep(0.3)

    print(f"\n  Total enriched: {enriched_count}")
    if use_sixtyfour:
        print(f"    SixtyFour: {sf_enriched}")
        print(f"    Apollo fallback: {apollo_enriched}")
    print(f"  Failed: {enrich_failed}")
    print(f"  Apollo credits used: {credits_used}")

    return {
        "enriched": enriched_count,
        "sf_enriched": sf_enriched,
        "apollo_enriched": apollo_enriched,
        "failed": enrich_failed,
        "credits_used": credits_used,
        "skipped": False,
    }


def enrich_people(sb, apollo, env, config, run_id, auto_confirm=False):
    """Two-tier people enrichment: SixtyFour first, Apollo fallback.

    Enriches people with enrichment_status='pending' and lead_status='monitoring'.
    Skips people who already have sixtyfour_id set (already enriched).

    GUARDRAIL: People enrichment ALWAYS requires explicit user approval,
    even when --yes is passed. This prevents accidental credit spend on
    large batches. The --yes flag only auto-confirms company operations.

    Returns:
        dict with enrichment stats.
    """
    client_name = config["client_name"]
    sf_key = env.get("SIXTYFOUR_API_KEY")
    use_sixtyfour = sf_key and SixtyFourClient is not None

    # Fetch pending people
    pending_people = sb.get_people(
        filters={
            "client_name": f"eq.{client_name}",
            "enrichment_status": "eq.pending",
            "lead_status": "eq.monitoring",
        },
        limit=5000,
    )

    if not pending_people:
        print(f"\n  No pending people to enrich.")
        return {"enriched": 0, "skipped_existing": 0, "failed": 0, "credits_used": 0}

    # Filter out people who already have sixtyfour_id (skip re-enrichment)
    to_enrich = [p for p in pending_people if not p.get("sixtyfour_id")]
    skipped_existing = len(pending_people) - len(to_enrich)

    if skipped_existing > 0:
        print(f"  Skipping {skipped_existing} people with existing sixtyfour_id")

    if not to_enrich:
        print(f"  All pending people already enriched.")
        return {"enriched": 0, "skipped_existing": skipped_existing, "failed": 0, "credits_used": 0}

    print(f"  People to enrich: {len(to_enrich)}")

    # GUARDRAIL: Always require explicit approval for people enrichment.
    # People enrichment costs real credits (SixtyFour or Apollo) and is
    # irreversible. Never auto-confirm, even with --yes.
    if use_sixtyfour:
        prompt_msg = (
            f"\n  ⚠ APPROVAL REQUIRED: Enrich {len(to_enrich)} people? "
            f"(SixtyFour first → Apollo fallback) [y/N] "
        )
    else:
        prompt_msg = (
            f"\n  ⚠ APPROVAL REQUIRED: Enrich {len(to_enrich)} people? "
            f"(1 Apollo credit each, {len(to_enrich)} total) [y/N] "
        )
    answer = input(prompt_msg).strip().lower()
    if answer != "y":
        print("  Skipping people enrichment.")
        return {
            "enriched": 0, "skipped_existing": skipped_existing,
            "failed": 0, "credits_used": 0, "skipped": True,
        }

    sf_enriched = 0
    apollo_enriched = 0
    enrich_failed = 0
    credits_used = 0
    apollo_fallback = []  # people that need Apollo fallback

    # ── SixtyFour batch enrichment ──────────────────────────────
    if use_sixtyfour:
        sf_client = SixtyFourClient(sf_key)

        # Build lead list for SixtyFour
        leads_list = []
        for person in to_enrich:
            linkedin_url = person.get("linkedin_url") or ""
            # Only pass real LinkedIn URLs, not synthetic apollo:// ones
            real_linkedin = linkedin_url if linkedin_url.startswith("http") else None

            leads_list.append({
                "name": person.get("name") or f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                "title": person.get("title"),
                "company": person.get("company_name"),
                "linkedin_url": real_linkedin,
            })

        print(f"\n  SixtyFour: Submitting {len(leads_list)} people (async batch)...")
        sf_results = sf_client.batch_enrich_leads(leads_list, timeout=600, poll_interval=15)

        # Map results back to people rows by dedup key
        for person in to_enrich:
            linkedin_url = person.get("linkedin_url") or ""
            real_linkedin = linkedin_url if linkedin_url.startswith("http") else None

            if real_linkedin:
                dedup_key = real_linkedin
            else:
                name = person.get("name") or f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
                dedup_key = f"{name}|{person.get('company_name') or ''}"

            sf_entry = sf_results.get(dedup_key)
            if not sf_entry:
                apollo_fallback.append(person)
                continue

            task_id, sf_result = sf_entry

            if sf_result is None:
                apollo_fallback.append(person)
                continue

            # Check confidence
            confidence = sf_result.get("confidence", 0)
            if isinstance(confidence, str):
                try:
                    confidence = float(confidence)
                except (ValueError, TypeError):
                    confidence = 0

            if confidence < 5.0:
                print(f"    {person.get('name', '?')}: low confidence ({confidence}), → Apollo fallback")
                apollo_fallback.append(person)
                continue

            # Merge SixtyFour data
            person_update = dict(person)
            old_linkedin = person_update.get("linkedin_url")
            merge_sixtyfour_lead_data(person_update, sf_result, task_id)
            new_linkedin = person_update.get("linkedin_url")

            # If LinkedIn URL changed (synthetic → real), patch by ID to avoid duplicate
            if old_linkedin != new_linkedin and old_linkedin and old_linkedin.startswith("apollo://"):
                sb.patch_person_by_id(person["id"], {
                    k: v for k, v in person_update.items()
                    if k not in ("id", "created_at", "updated_at") and v is not None
                })
            else:
                sb.upsert_people([{
                    k: v for k, v in person_update.items()
                    if k not in ("created_at", "updated_at")
                }])

            sf_enriched += 1
            name = person.get("name") or "?"
            email = person_update.get("email") or "no email"
            print(f"    {name}: {email} | SixtyFour (conf: {confidence})")

        print(f"\n  SixtyFour enriched: {sf_enriched}")
        print(f"  Apollo fallback needed: {len(apollo_fallback)}")
    else:
        # No SixtyFour key — all people go to Apollo
        apollo_fallback = list(to_enrich)
        if apollo_fallback:
            print(f"\n  No SixtyFour API key — using Apollo enrichment for all {len(apollo_fallback)} people")

    # ── Apollo fallback enrichment ──────────────────────────────
    if apollo_fallback:
        for i, person in enumerate(apollo_fallback):
            name = person.get("name") or f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
            print(f"  [{i+1}/{len(apollo_fallback)}] {name}...", end="", flush=True)

            linkedin_url = person.get("linkedin_url") or ""
            # Skip synthetic apollo:// URLs — Apollo won't recognize them
            real_linkedin = linkedin_url if linkedin_url.startswith("http") else None

            try:
                enrich_result = apollo.enrich_person(
                    first_name=person.get("first_name"),
                    last_name=person.get("last_name"),
                    organization_name=person.get("company_name"),
                    linkedin_url=real_linkedin,
                    domain=person.get("company_domain"),
                )
            except Exception as e:
                print(f" ERROR: {e}")
                enrich_failed += 1
                continue

            apollo_person = (enrich_result or {}).get("person")
            if not apollo_person:
                print(" no match")
                # Mark as failed so we don't retry forever
                sb.patch_person_by_id(person["id"], {"enrichment_status": "failed"})
                enrich_failed += 1
                continue

            credits_used += 1

            # Merge Apollo data
            person_update = dict(person)
            old_linkedin = person_update.get("linkedin_url")
            merge_apollo_person_enrichment(person_update, apollo_person)
            new_linkedin = person_update.get("linkedin_url")

            # If LinkedIn URL changed (synthetic → real), patch by ID
            if old_linkedin != new_linkedin and old_linkedin and old_linkedin.startswith("apollo://"):
                sb.patch_person_by_id(person["id"], {
                    k: v for k, v in person_update.items()
                    if k not in ("id", "created_at", "updated_at") and v is not None
                })
            else:
                sb.upsert_people([{
                    k: v for k, v in person_update.items()
                    if k not in ("created_at", "updated_at")
                }])

            apollo_enriched += 1
            email = person_update.get("email") or "no email"
            print(f" {email} | Apollo")

            time.sleep(0.3)

    enriched_count = sf_enriched + apollo_enriched
    print(f"\n  People enrichment complete:")
    print(f"    Total enriched: {enriched_count}")
    if use_sixtyfour:
        print(f"    SixtyFour: {sf_enriched}")
        print(f"    Apollo fallback: {apollo_enriched}")
    print(f"    Failed: {enrich_failed}")
    print(f"    Apollo credits used: {credits_used}")

    return {
        "enriched": enriched_count,
        "sf_enriched": sf_enriched,
        "apollo_enriched": apollo_enriched,
        "failed": enrich_failed,
        "credits_used": credits_used,
        "skipped_existing": skipped_existing,
    }


# ── Data Extraction ──────────────────────────────────────────────

def extract_org_data(org):
    """Normalize Apollo organization fields into a flat dict.

    Apollo's mixed_companies/api_search returns org objects with fields like:
      id, name, primary_domain, industry, estimated_num_employees, etc.

    The full raw Apollo response is preserved in 'raw_data' for future use.
    """
    if not org:
        return None

    domain = org.get("primary_domain") or org.get("website_url") or ""
    if domain:
        domain = domain.replace("https://", "").replace("http://", "").rstrip("/")

    # Location assembly
    city = org.get("city") or ""
    state = org.get("state") or ""
    country = org.get("country") or ""
    location_parts = [p for p in [city, state, country] if p]
    hq_location = ", ".join(location_parts)

    # Keywords from Apollo
    keywords = org.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    # Revenue: try enriched field first, fall back to search-level field
    revenue_str = org.get("annual_revenue_printed") or org.get("organization_revenue_printed") or ""
    revenue_num = org.get("annual_revenue") or org.get("organization_revenue") or 0

    # Headcount growth signals (available from search endpoint)
    hc_growth_6m = org.get("organization_headcount_six_month_growth")
    hc_growth_12m = org.get("organization_headcount_twelve_month_growth")

    # SIC/NAICS codes (available from search endpoint)
    sic_codes = org.get("sic_codes") or []
    naics_codes = org.get("naics_codes") or []

    return {
        "apollo_id": org.get("id") or "",
        "company_name": org.get("name") or "",
        "domain": domain,
        "industry": org.get("industry") or "",
        "employee_count": org.get("estimated_num_employees") or 0,
        "estimated_revenue": revenue_str,
        "revenue_num": revenue_num,
        "hq_location": hq_location,
        "founded_year": org.get("founded_year"),
        "linkedin_url": org.get("linkedin_url") or "",
        "twitter_url": org.get("twitter_url") or "",
        "website_url": org.get("website_url") or "",
        "funding_stage": org.get("latest_funding_stage") or "",
        "total_funding": org.get("total_funding_printed") or "",
        "tech_stack": org.get("technology_names") or [],
        "keywords": keywords,
        "country": country,
        "headcount_growth_6m": hc_growth_6m,
        "headcount_growth_12m": hc_growth_12m,
        "sic_codes": sic_codes,
        "naics_codes": naics_codes,
        "raw_data": org,  # Full Apollo response preserved
    }


# ── Company Type Classification ──────────────────────────────────

_SERVICES_KEYWORDS = frozenset({
    "outsourcing", "staffing", "consulting", "professional services",
    "managed services", "system integration", "systems integration",
    "it services", "digital transformation", "implementation",
    "business process", "bpo", "offshoring", "nearshoring",
    "staff augmentation", "it consulting", "technology consulting",
    "custom software development", "software development services",
    "web development services", "mobile app development",
    "qa testing", "quality assurance", "devops services",
    "cloud migration", "erp implementation", "crm implementation",
    "sap", "oracle", "salesforce", "servicenow", "workday",
    "offshore", "onshore",
})

_AGENCY_KEYWORDS = frozenset({
    "marketing agency", "creative agency", "digital agency",
    "advertising agency", "branding agency", "design agency",
    "pr agency", "public relations", "media agency",
    "social media agency", "content agency", "seo agency",
    "growth agency", "performance marketing", "paid media",
    "demand generation agency", "lead generation agency",
})

_PRODUCT_KEYWORDS = frozenset({
    "saas", "platform", "analytics", "intelligence",
    "automation", "ai-powered", "machine learning",
    "developer tools", "devtools", "api", "sdk",
    "data pipeline", "data platform", "cloud-native",
    "open source", "self-service", "product-led",
    "revenue intelligence", "sales intelligence",
    "conversation intelligence", "notetaking",
    "observability", "monitoring", "security platform",
    "identity", "authentication", "payments",
    "workflow automation", "no-code", "low-code",
    "collaboration", "productivity", "real-time",
})

# Vendor names that only count as services when combined with context words
_VENDOR_NAMES = frozenset({"sap", "oracle", "salesforce", "servicenow", "workday", "microsoft dynamics"})
_VENDOR_CONTEXT = frozenset({"implementation", "consulting", "partner", "integrator", "migration", "services"})


def classify_company_type(org_data):
    """Classify a company as product, services, agency, or unknown.

    Examines keywords, industry, and tech_stack from the org_data dict.
    Conservative — defaults to 'unknown' when signals are mixed.

    Returns:
        str: 'product', 'services', 'agency', or 'unknown'
    """
    keywords = [k.lower().strip() for k in (org_data.get("keywords") or [])]
    industry = (org_data.get("industry") or "").lower()
    tech_stack = [t.lower() for t in (org_data.get("tech_stack") or [])]

    # Combine all text signals for matching
    all_signals = keywords + [industry]

    services_score = 0
    agency_score = 0
    product_score = 0

    # Check keywords against each set
    for kw in all_signals:
        for svc_kw in _SERVICES_KEYWORDS:
            if svc_kw in kw or kw in svc_kw:
                services_score += 1
        for ag_kw in _AGENCY_KEYWORDS:
            if ag_kw in kw or kw in ag_kw:
                agency_score += 1
        for prod_kw in _PRODUCT_KEYWORDS:
            if prod_kw in kw or kw in prod_kw:
                product_score += 1

    # Vendor-name amplifier: SAP/Oracle/Salesforce only count as services
    # when combined with context words like "implementation", "consulting"
    has_vendor = any(v in " ".join(all_signals) for v in _VENDOR_NAMES)
    has_vendor_context = any(c in " ".join(all_signals) for c in _VENDOR_CONTEXT)
    if has_vendor and has_vendor_context:
        services_score += 3

    # Tech stack signal: having a real tech stack suggests product company
    if len(tech_stack) >= 3:
        product_score += 1

    # Industry-level signals
    services_industries = {
        "information technology & services", "computer networking",
        "management consulting", "staffing and recruiting",
    }
    product_industries = {
        "computer software", "internet", "financial technology",
        "computer & network security",
    }
    if industry in services_industries:
        services_score += 1
    if industry in product_industries:
        product_score += 1

    # Decision logic — conservative, defaults to unknown
    total = services_score + agency_score + product_score
    if total == 0:
        return "unknown"

    # Agency check first (most specific)
    if agency_score >= 2 and agency_score > product_score:
        return "agency"

    # Clear winner
    if services_score >= 2 and services_score > product_score * 1.5:
        return "services"
    if product_score >= 2 and product_score > services_score * 1.5:
        return "product"

    # Mixed signals — stay conservative
    if product_score > services_score and product_score >= 2:
        return "product"
    if services_score > product_score and services_score >= 2:
        return "services"

    return "unknown"


# ── ICP Scoring ──────────────────────────────────────────────────

def compute_icp_fit_score(org_data, scoring_config):
    """Pure function: score a company against ICP criteria. Returns 0-100.

    No API calls. Weighted scoring across configurable dimensions.

    Handles two data scenarios:
    1. Enriched data (from /organizations/enrich) — has industry, employee_count,
       funding_stage, keywords. Original scoring logic applies.
    2. Search-only data (from /mixed_companies/search) — missing enrichment fields
       but has revenue, founded_year, headcount_growth. Falls back to search-level
       signals for scoring dimensions that would otherwise score 0.
    """
    weights = scoring_config.get("weights", {})
    total_weight = sum(weights.values()) or 100
    score = 0.0

    # Detect if we have enrichment-level data
    has_enrichment = bool(org_data.get("industry") or org_data.get("employee_count"))

    # 1. Employee count fit
    w = weights.get("employee_count_fit", 0)
    if w > 0:
        emp = org_data.get("employee_count") or 0
        target_ranges = scoring_config.get("target_employee_ranges", [])
        if target_ranges and emp > 0:
            for lo, hi in target_ranges:
                if lo <= emp <= hi:
                    score += w
                    break
            else:
                # Partial credit if close
                min_lo = min(r[0] for r in target_ranges)
                max_hi = max(r[1] for r in target_ranges)
                if emp < min_lo:
                    ratio = emp / min_lo if min_lo > 0 else 0
                    score += w * ratio * 0.5
                elif emp > max_hi:
                    ratio = max_hi / emp if emp > 0 else 0
                    score += w * ratio * 0.5
        elif not has_enrichment:
            # Search endpoint already filtered by employee range — give full credit
            score += w

    # 2. Industry fit
    w = weights.get("industry_fit", 0)
    if w > 0:
        industry = (org_data.get("industry") or "").lower()
        targets = [t.lower() for t in scoring_config.get("target_industries", [])]
        if targets and industry:
            if industry in targets:
                score += w
            elif any(t in industry or industry in t for t in targets):
                score += w * 0.7
        elif not has_enrichment:
            # Search endpoint filtered by keyword tags (proxy for industry) — partial credit
            score += w * 0.5

    # 3. Funding stage fit
    w = weights.get("funding_stage_fit", 0)
    if w > 0:
        stage = (org_data.get("funding_stage") or "").lower()
        targets = [t.lower() for t in scoring_config.get("target_funding_stages", [])]
        if targets and stage:
            if stage in targets:
                score += w
            elif any(t in stage or stage in t for t in targets):
                score += w * 0.5
        elif not stage:
            # Use founded_year as startup signal when funding data is missing
            founded = org_data.get("founded_year")
            if founded and founded >= 2018:
                score += w * 0.7  # Recently founded = likely startup
            elif founded and founded >= 2010:
                score += w * 0.4  # Moderately recent
            else:
                score += w * 0.2  # Unknown or old — minimal credit

    # 4. Geo fit
    w = weights.get("geo_fit", 0)
    if w > 0:
        country = (org_data.get("country") or "").lower()
        hq = (org_data.get("hq_location") or "").lower()
        targets = [t.lower() for t in scoring_config.get("target_geos", [])]
        if targets:
            if any(t in country or t in hq for t in targets):
                score += w

    # 5. Keyword match / growth signals
    w = weights.get("keyword_match", 0)
    if w > 0:
        org_keywords = [k.lower() for k in (org_data.get("keywords") or [])]
        config_keywords = scoring_config.get("config_keywords", [])
        if not config_keywords:
            # Fall back to company_filters keyword tags if no explicit config_keywords
            config_keywords = []
        if org_keywords and config_keywords:
            config_kw_lower = [k.lower() for k in config_keywords]
            matches = sum(
                1 for ok in org_keywords
                if any(ck in ok or ok in ck for ck in config_kw_lower)
            )
            if matches > 0:
                ratio = min(matches / len(config_kw_lower), 1.0)
                score += w * ratio
        elif not org_keywords and not has_enrichment:
            # No keywords available from search — use headcount growth as proxy signal
            hc_6m = org_data.get("headcount_growth_6m")
            hc_12m = org_data.get("headcount_growth_12m")
            if hc_6m is not None and hc_6m > 0.05:
                score += w  # Growing company = strong signal
            elif hc_12m is not None and hc_12m > 0.05:
                score += w * 0.7
            else:
                score += w * 0.3  # Stable/unknown — minimal credit

    # 6. Company type fit
    w = weights.get("company_type_fit", 0)
    if w > 0:
        company_type = org_data.get("_company_type") or classify_company_type(org_data)
        if company_type == "product":
            score += w
        elif company_type == "unknown":
            score += w * 0.5
        # services and agency get 0

    # Normalize to 0-100
    normalized = round((score / total_weight) * 100)
    return max(0, min(100, normalized))


def score_to_tier(score, thresholds):
    """Convert ICP fit score to tier (1, 2, or 3)."""
    t1 = thresholds.get("tier_1_min_score", 75)
    t2 = thresholds.get("tier_2_min_score", 50)
    if score >= t1:
        return 1
    elif score >= t2:
        return 2
    return 3


# ── Row Mappers ──────────────────────────────────────────────────

def map_to_supabase_company(org_data, config, run_id):
    """Map extracted org data to a Supabase companies table row.

    Score and tier are NOT set here — they are applied in a separate pass
    after upsert, supporting the Search → Upsert → Score → Tier flow.

    Data protection: Search flows use insert_companies_ignore_duplicates()
    which skips existing records entirely. Only enrichment flows use
    upsert_companies() which can update existing records — and enrichment
    always provides richer data than what's already stored.
    """
    now = datetime.now(timezone.utc).isoformat()
    company_type = classify_company_type(org_data)
    org_data["_company_type"] = company_type  # Cache for scoring
    return {
        "company_name": org_data["company_name"] or None,
        "domain": org_data["domain"] or None,
        "apollo_id": org_data["apollo_id"] or None,
        "industry": org_data["industry"] or None,
        "employee_count": org_data["employee_count"] or None,
        "estimated_revenue": org_data["estimated_revenue"] or None,
        "hq_location": org_data["hq_location"] or None,
        "founded_year": org_data["founded_year"],
        "linkedin_url": org_data["linkedin_url"] or None,
        "twitter_url": org_data["twitter_url"] or None,
        "website_url": org_data["website_url"] or None,
        "funding_stage": org_data["funding_stage"] or None,
        "total_funding": org_data["total_funding"] or None,
        "tech_stack": org_data["tech_stack"] or [],
        "company_type": company_type,
        "source": "apollo",
        "updated_by": "tam-builder",
        "client_name": config["client_name"],
        "run_id": run_id,
        "last_refreshed_at": now,
        "metadata": {
            "tam_config_name": config.get("tam_config_name", ""),
            "keywords": org_data.get("keywords", []),
            "refresh_miss_count": 0,
        },
        "raw_data": org_data.get("raw_data") or {},
    }


def map_to_supabase_persona(person, company_data, config, run_id):
    """Map an Apollo person search result to a Supabase people row for the watchlist.

    Stores the full raw Apollo person response in raw_data for future enrichment context.
    """
    apollo_id = person.get("id") or ""
    first_name = person.get("first_name") or ""
    last_name = person.get("last_name") or ""
    name = f"{first_name} {last_name}".strip()
    title = person.get("title") or ""
    seniority = person.get("seniority") or ""
    headline = person.get("headline") or ""

    # Location
    city = person.get("city") or ""
    state = person.get("state") or ""
    country = person.get("country") or ""
    location_parts = [p for p in [city, state, country] if p]
    location = ", ".join(location_parts)

    # Synthetic linkedin_url placeholder
    linkedin_url = f"apollo://{apollo_id}" if apollo_id else None

    return {
        "linkedin_url": linkedin_url,
        "apollo_id": apollo_id or None,
        "name": name or None,
        "first_name": first_name or None,
        "last_name": last_name or None,
        "title": title or None,
        "headline": headline or None,
        "seniority_level": seniority or None,
        "location": location or None,
        "company_id": company_data.get("id"),
        "company_name": company_data.get("company_name") or None,
        "company_domain": company_data.get("domain") or None,
        "lead_status": "monitoring",
        "source": "apollo",
        "updated_by": "tam-builder",
        "client_name": config["client_name"],
        "search_config_name": config.get("tam_config_name", ""),
        "run_id": run_id,
        "enrichment_status": "pending",
        "watchlist_added_at": datetime.now(timezone.utc).isoformat(),
        "raw_data": person,  # Full Apollo person response preserved
    }


# ── Build TAM ────────────────────────────────────────────────────

def build_tam(config, env, caps=None, dry_run=False, auto_confirm=False,
              preview_only=False, skip_watchlist=False, sample_only=False):
    """Full TAM build pipeline. Importable — no argparse, no stdin.

    Flow: Search → Upsert → Score → Tier → Watchlist → People Enrichment

    If sample_only=True: Search → Score in-memory → Print summary → Exit.
    No database writes, no enrichment. Used to show the user what results
    look like before committing to a full build.

    Returns:
        dict with summary stats (companies_found, upserted, tier_breakdown, etc.)
    """
    if caps is None:
        caps = MODE_CAPS["standard"]

    apollo = ApolloClient(env["APOLLO_API_KEY"])
    sb = SupabaseClient(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])

    # Pre-flight schema check — abort early if required columns are missing
    if not sample_only:
        schema_ok, schema_errors = validate_schema(sb)
        if not schema_ok:
            print(f"\n{'='*60}")
            print(f"SCHEMA VALIDATION FAILED — aborting to prevent data loss")
            print(f"{'='*60}")
            for err in schema_errors:
                print(f"  ✗ {err}")
            print(f"\n  Fix these in the Supabase SQL Editor, then re-run.")
            return {"error": True, "schema_errors": schema_errors}

    client_name = config["client_name"]
    filters = config["company_filters"]
    scoring_config = config["scoring"]
    thresholds = scoring_config.get("tier_thresholds", {})
    max_pages = min(config.get("max_pages", 50), caps["max_pages"])

    # Inject company_filters keywords into scoring config for keyword_match
    scoring_config["config_keywords"] = filters.get("q_organization_keyword_tags", [])

    # ── Step 1: Apollo Company Search ─────────────────────────────
    print(f"\n{'='*60}")
    print(f"Phase 1: Apollo Company Search")
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
    print(f"  Mode: {caps['label']}, max pages: {max_pages}")

    if dry_run:
        print(f"\n  [DRY RUN] Would search Apollo with these filters.")
        print(f"  [DRY RUN] No API calls made.")
        return {"dry_run": True}

    # First page + total count
    result = apollo.search_organizations(filters, page=1, per_page=RESULTS_PER_PAGE)
    if not result:
        print("  ERROR: No response from Apollo API.")
        return {"error": True, "companies_found": 0}

    orgs_raw = result.get("organizations") or result.get("accounts") or []
    total_entries = result.get("pagination", {}).get("total_entries", len(orgs_raw))

    print(f"  Page 1 returned: {len(orgs_raw)} organizations")
    print(f"  Total matching: {total_entries:,}")

    if preview_only:
        est_pages = min((total_entries + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE, max_pages)
        print(f"\n  Estimated pages needed: {est_pages}")
        print(f"  Estimated companies: {min(total_entries, est_pages * RESULTS_PER_PAGE):,}")
        return {"total_matching": total_entries, "preview": True}

    if not orgs_raw:
        print("\n  No companies found matching filters.")
        return {"companies_found": 0}

    total_pages = min(
        (total_entries + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE,
        max_pages,
    )

    print(f"\n  Pages to fetch: {total_pages}")

    if not auto_confirm and total_pages > 1:
        answer = input(
            f"\n  Fetch {total_pages} pages (~{min(total_entries, total_pages * RESULTS_PER_PAGE):,} companies)? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("  Aborted.")
            return {"aborted": True}

    # Paginate — collect all orgs by domain (dedup)
    all_orgs = {}
    for org in orgs_raw:
        data = extract_org_data(org)
        if data and data["domain"]:
            all_orgs[data["domain"]] = data

    pages_fetched = 1

    for page in range(2, total_pages + 1):
        print(f"  Page {page}/{total_pages}...", end="", flush=True)

        try:
            page_result = apollo.search_organizations(filters, page=page, per_page=RESULTS_PER_PAGE)
        except Exception as e:
            print(f" ERROR: {e}")
            print(f"  Stopping pagination. Collected {len(all_orgs)} companies so far.")
            break

        if not page_result:
            print(" empty response, stopping.")
            break

        page_orgs = page_result.get("organizations") or page_result.get("accounts") or []
        new_on_page = 0

        for org in page_orgs:
            data = extract_org_data(org)
            if data and data["domain"] and data["domain"] not in all_orgs:
                all_orgs[data["domain"]] = data
                new_on_page += 1

        pages_fetched += 1
        print(f" {len(page_orgs)} returned, {new_on_page} new")

        if len(page_orgs) < RESULTS_PER_PAGE:
            print(f"  Last page reached (partial page).")
            break

        # Brief pause between pages
        if page < total_pages:
            time.sleep(0.5)

    print(f"\n  Total unique companies collected: {len(all_orgs)}")

    if not all_orgs:
        print("\n  No companies with domains found.")
        return {"companies_found": 0, "pages_fetched": pages_fetched}

    # ── Sample mode: score in-memory and display, NO DB writes ───
    if sample_only:
        scoring_config_local = config["scoring"].copy()
        scoring_config_local["config_keywords"] = filters.get("q_organization_keyword_tags", [])
        thresholds_local = scoring_config_local.get("tier_thresholds", {})

        tier_counts = {1: 0, 2: 0, 3: 0}
        scored_companies = []

        type_counts = {"product": 0, "services": 0, "agency": 0, "unknown": 0}
        for data in all_orgs.values():
            ctype = classify_company_type(data)
            data["_company_type"] = ctype
            type_counts[ctype] += 1
            score = compute_icp_fit_score(data, scoring_config_local)
            tier = score_to_tier(score, thresholds_local)
            tier_counts[tier] += 1
            scored_companies.append({**data, "_score": score, "_tier": tier, "_company_type": ctype})

        scored_companies.sort(key=lambda x: x["_score"], reverse=True)

        print(f"\n{'='*60}")
        print(f"SAMPLE RESULTS (in-memory only — no database writes)")
        print(f"{'='*60}")
        print(f"\n  Tier distribution:")
        print(f"    Tier 1 (score >= {thresholds_local.get('tier_1_min_score', 75)}): {tier_counts[1]}")
        print(f"    Tier 2 (score >= {thresholds_local.get('tier_2_min_score', 50)}): {tier_counts[2]}")
        print(f"    Tier 3 (below threshold): {tier_counts[3]}")

        print(f"\n  Company type distribution:")
        print(f"    Product: {type_counts['product']}")
        print(f"    Services: {type_counts['services']}")
        print(f"    Agency: {type_counts['agency']}")
        print(f"    Unknown: {type_counts['unknown']}")

        # Show top Tier 1 companies
        tier1 = [c for c in scored_companies if c["_tier"] == 1]
        if tier1:
            print(f"\n  Top Tier 1 companies (showing up to 10):")
            for c in tier1[:10]:
                industry = (c.get("industry") or "N/A")[:25]
                emp = c.get("employee_count") or "?"
                funding = c.get("funding_stage") or "N/A"
                ctype = c.get("_company_type", "?")[:8]
                print(f"    {c['_score']:3d}  {c['company_name'][:35]:<35}  {c['domain'][:30]:<30}  {ctype:<8}  {industry}  {emp} emp  {funding}")

        # Show a few Tier 2 companies
        tier2 = [c for c in scored_companies if c["_tier"] == 2]
        if tier2:
            print(f"\n  Sample Tier 2 companies (showing up to 5):")
            for c in tier2[:5]:
                industry = (c.get("industry") or "N/A")[:25]
                emp = c.get("employee_count") or "?"
                ctype = c.get("_company_type", "?")[:8]
                print(f"    {c['_score']:3d}  {c['company_name'][:35]:<35}  {c['domain'][:30]:<30}  {ctype:<8}  {industry}  {emp} emp")

        print(f"\n  Total in sample: {len(all_orgs)}")
        print(f"  Full TAM estimate: {total_entries:,} companies")
        print(f"\n  ** No data was written to Supabase. **")
        print(f"  Review the results above. If they look good, re-run without --sample to build.")

        return {
            "sample": True,
            "companies_found": len(all_orgs),
            "total_matching": total_entries,
            "tier_breakdown": dict(tier_counts),
            "top_companies": [
                {"name": c["company_name"], "domain": c["domain"],
                 "score": c["_score"], "tier": c["_tier"]}
                for c in scored_companies[:20]
            ],
        }

    # ── Step 2: Connect to Supabase & Create run ──────────────────
    print(f"\n{'='*60}")
    print(f"Phase 1 (cont): Upsert to Supabase")
    print(f"{'='*60}")

    if not sb.test_connection():
        print("  ERROR: Cannot connect to Supabase.")
        return {"error": True, "companies_found": len(all_orgs)}

    print("  Connected to Supabase")

    run = sb.create_run("tam_build", "tam-builder", client_name, config={
        "tam_config_name": config.get("tam_config_name", ""),
        "filters": filters,
        "mode": caps["label"],
    })
    run_id = run["id"] if run else None
    print(f"  Run ID: {run_id}")

    # Map to Supabase rows (raw — no score/tier yet)
    company_rows = []
    for data in all_orgs.values():
        row = map_to_supabase_company(data, config, run_id)
        if row["domain"]:
            company_rows.append(row)

    inserted = sb.insert_companies_ignore_duplicates(company_rows)
    print(f"  Inserted {inserted} new companies to Supabase (existing companies untouched)")

    # ── Step 2.5: Enrich companies (SixtyFour first → Apollo fallback)
    print(f"\n{'='*60}")
    print(f"Phase 1 (cont): Enrich Companies")
    print(f"{'='*60}")

    enrich_stats = enrich_companies(
        all_orgs, sb, apollo, env, config, run_id, auto_confirm=auto_confirm,
    )
    enriched_count = enrich_stats.get("enriched", 0)
    credits_used = enrich_stats.get("credits_used", 0)

    # ── Step 3: Score & Tier ──────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Phase 1 (cont): Score ICP Fit & Assign Tiers")
    print(f"{'='*60}")

    # Fetch the companies we just upserted to get their UUIDs
    existing = sb.get_all_companies(client_name, select="id,domain,metadata")
    domain_to_id = {c["domain"]: c["id"] for c in existing if c.get("domain")}

    tier_counts = {1: 0, 2: 0, 3: 0}
    score_updates = []

    for data in all_orgs.values():
        domain = data["domain"]
        company_id = domain_to_id.get(domain)
        if not company_id:
            continue

        score = compute_icp_fit_score(data, scoring_config)
        tier = score_to_tier(score, thresholds)
        tier_counts[tier] += 1
        score_updates.append((company_id, score, tier))

    # Batch update scores and tiers
    for company_id, score, tier in score_updates:
        sb._request(
            "PATCH",
            "companies",
            params={"id": f"eq.{company_id}"},
            data={"icp_fit_score": score, "tier": tier},
            extra_headers={"Prefer": "return=minimal"},
        )

    print(f"  Scored {len(score_updates)} companies")
    print(f"  Tier 1 (score >= {thresholds.get('tier_1_min_score', 75)}): {tier_counts[1]}")
    print(f"  Tier 2 (score >= {thresholds.get('tier_2_min_score', 50)}): {tier_counts[2]}")
    print(f"  Tier 3 (below threshold): {tier_counts[3]}")

    # Show top 10 by score
    if score_updates:
        top_10 = sorted(score_updates, key=lambda x: x[1], reverse=True)[:10]
        id_to_data = {}
        for data in all_orgs.values():
            cid = domain_to_id.get(data["domain"])
            if cid:
                id_to_data[cid] = data

        print(f"\n  Top 10 companies by ICP fit:")
        print(f"  {'Company':<30} {'Domain':<25} {'Score':>5} {'Tier':>4}")
        print(f"  {'-'*68}")
        for cid, score, tier in top_10:
            d = id_to_data.get(cid, {})
            name = (d.get("company_name") or "")[:29]
            domain = (d.get("domain") or "")[:24]
            print(f"  {name:<30} {domain:<25} {score:>5} {tier:>4}")

    # ── Phase 3: Persona Watchlist ────────────────────────────────
    watchlist_config = config.get("watchlist", {})
    watchlist_enabled = watchlist_config.get("enabled", False)
    watchlist_stats = {}

    if watchlist_enabled and not skip_watchlist:
        tiers_to_watch = watchlist_config.get("tiers_to_watch", [1, 2])

        # Only watch product companies — skip services/agency/unknown
        id_to_type = {}
        for data in all_orgs.values():
            cid = domain_to_id.get(data["domain"])
            if cid:
                id_to_type[cid] = data.get("_company_type") or "unknown"

        all_tier_matches = [
            (cid, score, tier)
            for cid, score, tier in score_updates
            if tier in tiers_to_watch
        ]
        companies_to_watch = [
            (cid, score, tier)
            for cid, score, tier in all_tier_matches
            if id_to_type.get(cid) == "product"
        ]
        skipped_non_product = len(all_tier_matches) - len(companies_to_watch)
        if skipped_non_product:
            print(f"\n  [FILTER] Skipped {skipped_non_product} non-product companies from watchlist")

        # Build lookup for company data
        id_to_company = {}
        for data in all_orgs.values():
            cid = domain_to_id.get(data["domain"])
            if cid:
                id_to_company[cid] = {
                    "id": cid,
                    "company_name": data["company_name"],
                    "domain": data["domain"],
                }

        watchlist_stats = build_watchlist(
            sb, apollo, config, companies_to_watch, id_to_company, run_id
        )
    elif skip_watchlist:
        print(f"\n  [SKIPPED] Persona watchlist (--skip-watchlist)")
    else:
        print(f"\n  [SKIPPED] Persona watchlist (not enabled in config)")

    # ── Phase 4: People Enrichment ────────────────────────────────
    people_enrich_stats = {}

    if watchlist_enabled and not skip_watchlist and watchlist_stats.get("personas_added", 0) > 0:
        print(f"\n{'='*60}")
        print(f"Phase 4: People Enrichment")
        print(f"{'='*60}")

        people_enrich_stats = enrich_people(
            sb, apollo, env, config, run_id, auto_confirm=auto_confirm,
        )

    # ── Complete run ──────────────────────────────────────────────
    summary = {
        "total_matching": total_entries,
        "companies_collected": len(all_orgs),
        "pages_fetched": pages_fetched,
        "new_inserted": inserted,
        "enriched": enriched_count,
        "sf_enriched": enrich_stats.get("sf_enriched", 0),
        "apollo_enriched": enrich_stats.get("apollo_enriched", 0),
        "enrich_credits_used": credits_used,
        "scored": len(score_updates),
        "tier_1": tier_counts[1],
        "tier_2": tier_counts[2],
        "tier_3": tier_counts[3],
        "watchlist": watchlist_stats,
        "people_enrichment": people_enrich_stats,
    }

    if run_id:
        sb.update_run_status(run_id, "completed", summary=summary)

    # Print summary
    print(f"\n{'='*60}")
    print(f"TAM Build Summary")
    print(f"{'='*60}")
    print(f"  Client: {client_name}")
    print(f"  Config: {config.get('tam_config_name', '')}")
    print(f"  Total matching in Apollo: {total_entries:,}")
    print(f"  Companies collected: {len(all_orgs)}")
    print(f"  New companies inserted: {inserted}")
    sf_enriched = enrich_stats.get("sf_enriched", 0)
    apollo_enriched = enrich_stats.get("apollo_enriched", 0)
    if sf_enriched > 0:
        print(f"  Enriched: {enriched_count} (SixtyFour: {sf_enriched}, Apollo: {apollo_enriched}, {credits_used} Apollo credits)")
    else:
        print(f"  Enriched: {enriched_count} ({credits_used} Apollo credits)")
    print(f"  Tier 1: {tier_counts[1]}")
    print(f"  Tier 2: {tier_counts[2]}")
    print(f"  Tier 3: {tier_counts[3]}")
    if watchlist_stats:
        print(f"  Watchlist personas added: {watchlist_stats.get('personas_added', 0)}")
    if people_enrich_stats:
        pe = people_enrich_stats.get("enriched", 0)
        pe_credits = people_enrich_stats.get("credits_used", 0)
        print(f"  People enriched: {pe} ({pe_credits} Apollo credits)")
    print(f"  Run ID: {run_id}")

    return summary


# ── Refresh TAM ──────────────────────────────────────────────────

def refresh_tam(config, env, caps=None, dry_run=False, auto_confirm=False,
                skip_watchlist=False):
    """Refresh existing TAM. Importable — no argparse, no stdin.

    Flow: Search → Upsert/update → Re-score → Deprecation → Watchlist sync → People Enrichment

    Returns:
        dict with summary stats.
    """
    if caps is None:
        caps = MODE_CAPS["standard"]

    apollo = ApolloClient(env["APOLLO_API_KEY"])
    sb = SupabaseClient(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])
    client_name = config["client_name"]
    filters = config["company_filters"]
    scoring_config = config["scoring"]
    thresholds = scoring_config.get("tier_thresholds", {})
    max_pages = min(config.get("max_pages", 50), caps["max_pages"])

    scoring_config["config_keywords"] = filters.get("q_organization_keyword_tags", [])

    if dry_run:
        print(f"\n  [DRY RUN] Would refresh TAM for {client_name}")
        return {"dry_run": True}

    # Connect
    if not sb.test_connection():
        print("  ERROR: Cannot connect to Supabase.")
        return {"error": True}

    # Pre-flight schema check — abort early if required columns are missing
    schema_ok, schema_errors = validate_schema(sb)
    if not schema_ok:
        print(f"\n{'='*60}")
        print(f"SCHEMA VALIDATION FAILED — aborting to prevent data loss")
        print(f"{'='*60}")
        for err in schema_errors:
            print(f"  ✗ {err}")
        print(f"\n  Fix these in the Supabase SQL Editor, then re-run.")
        return {"error": True, "schema_errors": schema_errors}

    # Fetch existing companies
    print(f"\n{'='*60}")
    print(f"Phase 0: Load Existing TAM")
    print(f"{'='*60}")

    existing = sb.get_all_companies(
        client_name,
        select="id,domain,tam_status,tier,icp_fit_score,metadata"
    )
    existing_by_domain = {c["domain"]: c for c in existing if c.get("domain")}
    print(f"  Existing companies: {len(existing_by_domain)}")

    active_count = sum(1 for c in existing if c.get("tam_status") == "active")
    deprecated_count = sum(1 for c in existing if c.get("tam_status") == "deprecated")
    print(f"  Active: {active_count}, Deprecated: {deprecated_count}")

    # Create run
    run = sb.create_run("tam_refresh", "tam-builder", client_name, config={
        "tam_config_name": config.get("tam_config_name", ""),
        "mode": caps["label"],
    })
    run_id = run["id"] if run else None

    # ── Phase 1: Apollo search + upsert + re-score ────────────────
    print(f"\n{'='*60}")
    print(f"Phase 1: Apollo Company Search (Refresh)")
    print(f"{'='*60}")

    # Search Apollo (same as build)
    all_orgs = {}
    pages_fetched = 0

    for page in range(1, max_pages + 1):
        if page == 1:
            print(f"  Page 1...", end="", flush=True)
        else:
            print(f"  Page {page}/{max_pages}...", end="", flush=True)

        try:
            page_result = apollo.search_organizations(filters, page=page, per_page=RESULTS_PER_PAGE)
        except Exception as e:
            print(f" ERROR: {e}")
            break

        if not page_result:
            print(" empty response, stopping.")
            break

        page_orgs = page_result.get("organizations") or page_result.get("accounts") or []

        if page == 1:
            total_entries = page_result.get("pagination", {}).get("total_entries", len(page_orgs))
            print(f" {len(page_orgs)} returned (total: {total_entries:,})")

            if not auto_confirm and total_entries > RESULTS_PER_PAGE:
                total_pages = min((total_entries + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE, max_pages)
                answer = input(f"\n  Fetch {total_pages} pages? [y/N] ").strip().lower()
                if answer != "y":
                    print("  Aborted.")
                    if run_id:
                        sb.update_run_status(run_id, "failed", error_message="Aborted by user")
                    return {"aborted": True}
        else:
            print(f" {len(page_orgs)} returned")

        new_on_page = 0
        for org in page_orgs:
            data = extract_org_data(org)
            if data and data["domain"] and data["domain"] not in all_orgs:
                all_orgs[data["domain"]] = data
                new_on_page += 1

        pages_fetched += 1

        if len(page_orgs) < RESULTS_PER_PAGE:
            break

        if page < max_pages:
            time.sleep(0.5)

    print(f"\n  Companies from search: {len(all_orgs)}")

    # Insert new companies + mark existing as refreshed
    print(f"\n{'='*60}")
    print(f"Phase 1 (cont): Insert New & Mark Refreshed")
    print(f"{'='*60}")

    # Separate new companies from existing ones
    new_company_rows = []
    refreshed_ids = []
    now = datetime.now(timezone.utc).isoformat()

    for data in all_orgs.values():
        domain = data.get("domain")
        if not domain:
            continue
        if domain in existing_by_domain:
            # Existing company — just track its ID for refresh timestamp update
            refreshed_ids.append(existing_by_domain[domain]["id"])
        else:
            # New company — insert it
            row = map_to_supabase_company(data, config, run_id)
            if row["domain"]:
                new_company_rows.append(row)

    # Insert only new companies (existing ones are untouched)
    inserted = 0
    if new_company_rows:
        inserted = sb.insert_companies_ignore_duplicates(new_company_rows)
    print(f"  New companies inserted: {inserted}")
    print(f"  Existing companies found in search: {len(refreshed_ids)}")

    # Patch existing companies with refresh timestamp only (no data overwrite)
    if refreshed_ids:
        sb.patch_companies_by_ids(refreshed_ids, {
            "last_refreshed_at": now,
            "run_id": run_id,
        })
        print(f"  Updated last_refreshed_at on {len(refreshed_ids)} existing companies")

    # ── Enrichment (SixtyFour first → Apollo fallback) ──────────
    print(f"\n{'='*60}")
    print(f"Phase 1 (cont): Enrich Companies")
    print(f"{'='*60}")

    enrich_stats = enrich_companies(
        all_orgs, sb, apollo, env, config, run_id, auto_confirm=auto_confirm,
    )

    # Re-fetch to get UUIDs for scoring
    refreshed = sb.get_all_companies(client_name, select="id,domain,tier,metadata,company_type")
    domain_to_row = {c["domain"]: c for c in refreshed if c.get("domain")}

    # Re-score and detect tier changes
    tier_counts = {1: 0, 2: 0, 3: 0}
    tier_changes = []
    score_updates = []

    for data in all_orgs.values():
        domain = data["domain"]
        row = domain_to_row.get(domain)
        if not row:
            continue

        company_id = row["id"]
        old_tier = row.get("tier")
        score = compute_icp_fit_score(data, scoring_config)
        new_tier = score_to_tier(score, thresholds)
        tier_counts[new_tier] += 1
        score_updates.append((company_id, score, new_tier))

        if old_tier is not None and old_tier != new_tier:
            tier_changes.append({
                "domain": domain,
                "name": data["company_name"],
                "old_tier": old_tier,
                "new_tier": new_tier,
                "score": score,
            })

    # Batch update scores
    for company_id, score, tier in score_updates:
        sb._request(
            "PATCH",
            "companies",
            params={"id": f"eq.{company_id}"},
            data={
                "icp_fit_score": score,
                "tier": tier,
                "metadata": {**domain_to_row.get(
                    next((d for d, r in domain_to_row.items() if r["id"] == company_id), ""),
                    {}
                ).get("metadata", {}), "refresh_miss_count": 0},
            },
            extra_headers={"Prefer": "return=minimal"},
        )

    print(f"  Re-scored {len(score_updates)} companies")
    print(f"  Tier 1: {tier_counts[1]}, Tier 2: {tier_counts[2]}, Tier 3: {tier_counts[3]}")

    if tier_changes:
        print(f"\n  Tier changes detected: {len(tier_changes)}")
        for tc in tier_changes[:10]:
            direction = "promoted" if tc["new_tier"] < tc["old_tier"] else "demoted"
            print(f"    {tc['name'][:30]}: Tier {tc['old_tier']} → {tc['new_tier']} ({direction})")

    # ── Phase 2: Deprecation ──────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Phase 2: Deprecation Check")
    print(f"{'='*60}")

    found_domains = set(all_orgs.keys())
    deprecated_ids = []
    miss_incremented = 0

    for domain, existing_row in existing_by_domain.items():
        if existing_row.get("tam_status") in ("converted", "deprecated"):
            continue

        if domain not in found_domains:
            metadata = existing_row.get("metadata") or {}
            miss_count = metadata.get("refresh_miss_count", 0) + 1
            company_id = existing_row["id"]

            if miss_count >= 2:
                # Deprecate
                deprecated_ids.append(company_id)
                sb._request(
                    "PATCH",
                    "companies",
                    params={"id": f"eq.{company_id}"},
                    data={
                        "tam_status": "deprecated",
                        "metadata": {**metadata, "refresh_miss_count": miss_count, "deprecated_reason": "not_found_2x"},
                    },
                    extra_headers={"Prefer": "return=minimal"},
                )
            else:
                # Increment miss count
                miss_incremented += 1
                sb._request(
                    "PATCH",
                    "companies",
                    params={"id": f"eq.{company_id}"},
                    data={
                        "metadata": {**metadata, "refresh_miss_count": miss_count},
                    },
                    extra_headers={"Prefer": "return=minimal"},
                )

    # Check for zero-employee immediate deprecation
    zero_emp_deprecated = []
    for data in all_orgs.values():
        if (data.get("employee_count") or 0) == 0:
            row = domain_to_row.get(data["domain"])
            if row and row["id"] not in deprecated_ids:
                existing_row = existing_by_domain.get(data["domain"], {})
                if existing_row.get("tam_status") not in ("converted", "deprecated"):
                    zero_emp_deprecated.append(row["id"])
                    sb._request(
                        "PATCH",
                        "companies",
                        params={"id": f"eq.{row['id']}"},
                        data={
                            "tam_status": "deprecated",
                            "metadata": {**(row.get("metadata") or {}), "deprecated_reason": "zero_employees"},
                        },
                        extra_headers={"Prefer": "return=minimal"},
                    )

    all_deprecated_ids = deprecated_ids + zero_emp_deprecated
    print(f"  Companies not found in search: {miss_incremented + len(deprecated_ids)}")
    print(f"  First miss (warning): {miss_incremented}")
    print(f"  Deprecated (2+ misses): {len(deprecated_ids)}")
    print(f"  Deprecated (zero employees): {len(zero_emp_deprecated)}")

    # ── Phase 3: Watchlist sync ───────────────────────────────────
    watchlist_config = config.get("watchlist", {})
    watchlist_enabled = watchlist_config.get("enabled", False)
    watchlist_stats = {}

    if watchlist_enabled and not skip_watchlist:
        tiers_to_watch = watchlist_config.get("tiers_to_watch", [1, 2])

        # Build company_type lookup: all_orgs (current search) + DB (existing)
        id_to_type = {}
        for data in all_orgs.values():
            row = domain_to_row.get(data["domain"])
            if row:
                id_to_type[row["id"]] = data.get("_company_type") or "unknown"
        for row in refreshed:
            if row["id"] not in id_to_type:
                id_to_type[row["id"]] = row.get("company_type") or "unknown"

        # Find new + promoted companies that need personas
        candidates = []
        for tc in tier_changes:
            if tc["new_tier"] in tiers_to_watch and (tc.get("old_tier") not in tiers_to_watch):
                row = domain_to_row.get(tc["domain"])
                if row:
                    candidates.append((row["id"], tc.get("score", 0), tc["new_tier"]))

        # New companies (not in existing) that are Tier 1-2
        for cid, score, tier in score_updates:
            if tier in tiers_to_watch:
                domain = next((d for d, r in domain_to_row.items() if r["id"] == cid), None)
                if domain and domain not in existing_by_domain:
                    candidates.append((cid, score, tier))

        # Only watch product companies — skip services/agency/unknown
        companies_needing_personas = [
            (cid, score, tier) for cid, score, tier in candidates
            if id_to_type.get(cid) == "product"
        ]
        skipped_non_product = len(candidates) - len(companies_needing_personas)
        if skipped_non_product:
            print(f"\n  [FILTER] Skipped {skipped_non_product} non-product companies from watchlist")

        # Build lookup
        id_to_company = {}
        for data in all_orgs.values():
            row = domain_to_row.get(data["domain"])
            if row:
                id_to_company[row["id"]] = {
                    "id": row["id"],
                    "company_name": data["company_name"],
                    "domain": data["domain"],
                }

        watchlist_stats = build_watchlist(
            sb, apollo, config, companies_needing_personas, id_to_company, run_id
        )

        # Disqualify personas at deprecated companies
        if all_deprecated_ids:
            deprecate_watchlist_personas(sb, all_deprecated_ids, client_name)
    elif skip_watchlist:
        print(f"\n  [SKIPPED] Persona watchlist")

    # ── Phase 4: People Enrichment ────────────────────────────────
    people_enrich_stats = {}

    # Enrich any pending people — from this run (new watchlist adds) or prior runs
    pending_count = sb.count_people(filters={
        "client_name": f"eq.{client_name}",
        "enrichment_status": "eq.pending",
        "lead_status": "eq.monitoring",
    })

    if pending_count > 0:
        print(f"\n{'='*60}")
        print(f"Phase 4: People Enrichment ({pending_count} pending)")
        print(f"{'='*60}")

        people_enrich_stats = enrich_people(
            sb, apollo, env, config, run_id, auto_confirm=auto_confirm,
        )

    # ── Complete run ──────────────────────────────────────────────
    summary = {
        "companies_from_search": len(all_orgs),
        "pages_fetched": pages_fetched,
        "new_inserted": inserted,
        "existing_refreshed": len(refreshed_ids),
        "scored": len(score_updates),
        "tier_1": tier_counts[1],
        "tier_2": tier_counts[2],
        "tier_3": tier_counts[3],
        "tier_changes": len(tier_changes),
        "deprecated": len(all_deprecated_ids),
        "miss_warnings": miss_incremented,
        "watchlist": watchlist_stats,
        "people_enrichment": people_enrich_stats,
    }

    if run_id:
        sb.update_run_status(run_id, "completed", summary=summary)

    print(f"\n{'='*60}")
    print(f"TAM Refresh Summary")
    print(f"{'='*60}")
    print(f"  Client: {client_name}")
    print(f"  Companies from search: {len(all_orgs)}")
    print(f"  New inserted: {inserted}")
    print(f"  Existing refreshed: {len(refreshed_ids)}")
    print(f"  Tier 1: {tier_counts[1]}, Tier 2: {tier_counts[2]}, Tier 3: {tier_counts[3]}")
    print(f"  Tier changes: {len(tier_changes)}")
    print(f"  Deprecated: {len(all_deprecated_ids)}")
    if watchlist_stats:
        print(f"  Watchlist personas added: {watchlist_stats.get('personas_added', 0)}")
        print(f"  Watchlist personas disqualified: {watchlist_stats.get('personas_disqualified', 0)}")
    if people_enrich_stats:
        pe = people_enrich_stats.get("enriched", 0)
        pe_credits = people_enrich_stats.get("credits_used", 0)
        print(f"  People enriched: {pe} ({pe_credits} Apollo credits)")
    print(f"  Run ID: {run_id}")

    return summary


# ── Watchlist ────────────────────────────────────────────────────

def build_watchlist(sb, apollo, config, companies_to_watch, id_to_company, run_id):
    """Pull monitoring personas for Tier 1-2 companies using Apollo People Search (free).

    Args:
        sb: SupabaseClient instance
        apollo: ApolloClient instance
        config: Full config dict
        companies_to_watch: List of (company_id, score, tier) tuples
        id_to_company: Dict mapping company_id → {id, company_name, domain}
        run_id: Current run UUID

    Returns:
        dict with watchlist stats.
    """
    watchlist_config = config.get("watchlist", {})
    personas_per_company = watchlist_config.get("personas_per_company", 3)
    person_filters = watchlist_config.get("person_filters", {})

    if not companies_to_watch:
        print(f"\n  No new Tier 1-2 companies need watchlist personas.")
        return {"personas_added": 0, "companies_processed": 0}

    print(f"\n{'='*60}")
    print(f"Phase 3: Persona Watchlist (FREE)")
    print(f"{'='*60}")
    print(f"  Companies to process: {len(companies_to_watch)}")
    print(f"  Personas per company: {personas_per_company}")

    total_personas = 0
    companies_processed = 0

    for company_id, score, tier in companies_to_watch:
        company_data = id_to_company.get(company_id)
        if not company_data:
            continue

        domain = company_data.get("domain", "")
        name = company_data.get("company_name", "")

        # Build Apollo people search filters for this company
        search_filters = dict(person_filters)
        if name:
            search_filters["q_organization_name"] = name

        print(f"  {name[:30]} (Tier {tier})...", end="", flush=True)

        try:
            result = apollo.search_people(search_filters, page=1, per_page=personas_per_company)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        if not result:
            print(" no response")
            continue

        people = result.get("people") or []
        if not people:
            print(" no personas found")
            continue

        # Map to Supabase rows
        persona_rows = []
        for person in people[:personas_per_company]:
            if not person.get("id"):
                continue
            row = map_to_supabase_persona(person, company_data, config, run_id)
            if row.get("linkedin_url"):
                persona_rows.append(row)

        if persona_rows:
            inserted = sb.insert_people_ignore_duplicates(persona_rows)
            total_personas += len(persona_rows)
            print(f" {len(persona_rows)} personas added")
        else:
            print(" no valid personas")

        companies_processed += 1

        # Brief pause
        time.sleep(0.3)

    print(f"\n  Total personas added: {total_personas}")
    print(f"  Companies processed: {companies_processed}")

    return {
        "personas_added": total_personas,
        "companies_processed": companies_processed,
    }


def deprecate_watchlist_personas(sb, deprecated_company_ids, client_name):
    """Disqualify monitoring personas at deprecated companies.

    Only affects lead_status='monitoring' personas — leaves 'active',
    'contacted', etc. untouched.
    """
    if not deprecated_company_ids:
        return {"personas_disqualified": 0}

    print(f"\n  Disqualifying monitoring personas at {len(deprecated_company_ids)} deprecated companies...")

    total_disqualified = 0
    for company_id in deprecated_company_ids:
        personas = sb.get_watchlist_personas(company_id, client_name)
        if personas:
            person_ids = [p["id"] for p in personas]
            sb.update_lead_status(person_ids, "disqualified")
            total_disqualified += len(person_ids)

    print(f"  Disqualified: {total_disqualified} monitoring personas")
    return {"personas_disqualified": total_disqualified}


# ── Status Report ────────────────────────────────────────────────

def get_tam_status(config, env):
    """Read-only TAM status report. Importable — no argparse, no stdin.

    Returns:
        dict with TAM status breakdown.
    """
    sb = SupabaseClient(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])
    client_name = config["client_name"]

    if not sb.test_connection():
        print("  ERROR: Cannot connect to Supabase.")
        return {"error": True}

    print(f"\n{'='*60}")
    print(f"TAM Status Report — {client_name}")
    print(f"{'='*60}")

    # Company counts
    total = sb.count_companies({"client_name": f"eq.{client_name}"})
    active = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.active"})
    deprecated = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.deprecated"})
    converted = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.converted"})

    print(f"\n  Companies:")
    print(f"    Total: {total}")
    print(f"    Active: {active}")
    print(f"    Deprecated: {deprecated}")
    print(f"    Converted: {converted}")

    # Tier breakdown (active only)
    tier1 = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.active", "tier": "eq.1"})
    tier2 = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.active", "tier": "eq.2"})
    tier3 = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.active", "tier": "eq.3"})

    print(f"\n  Active Tier Breakdown:")
    print(f"    Tier 1: {tier1}")
    print(f"    Tier 2: {tier2}")
    print(f"    Tier 3: {tier3}")

    # Company type breakdown
    type_product = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.active", "company_type": "eq.product"})
    type_services = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.active", "company_type": "eq.services"})
    type_agency = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.active", "company_type": "eq.agency"})
    type_unknown = sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.active", "company_type": "is.null"})
    type_unknown += sb.count_companies({"client_name": f"eq.{client_name}", "tam_status": "eq.active", "company_type": "eq.unknown"})

    print(f"\n  Company Type Breakdown (active):")
    print(f"    Product: {type_product}")
    print(f"    Services: {type_services}")
    print(f"    Agency: {type_agency}")
    print(f"    Unknown/unclassified: {type_unknown}")

    # People counts
    total_people = sb.count_people({"client_name": f"eq.{client_name}"})
    monitoring = sb.count_people({"client_name": f"eq.{client_name}", "lead_status": "eq.monitoring"})
    active_people = sb.count_people({"client_name": f"eq.{client_name}", "lead_status": "eq.active"})

    print(f"\n  People:")
    print(f"    Total: {total_people}")
    print(f"    Monitoring (watchlist): {monitoring}")
    print(f"    Active: {active_people}")

    # Recent runs
    recent_runs = sb._request(
        "GET",
        "runs",
        params={
            "client_name": f"eq.{client_name}",
            "skill_name": "eq.tam-builder",
            "order": "created_at.desc",
            "limit": "5",
        },
    ) or []

    if recent_runs:
        print(f"\n  Recent Runs:")
        for r in recent_runs:
            status = r.get("status", "?")
            run_type = r.get("run_type", "?")
            created = (r.get("created_at") or "")[:19]
            print(f"    {created} — {run_type} — {status}")

    # Top 5 Tier 1 companies
    top_companies = sb.get_companies(
        filters={
            "client_name": f"eq.{client_name}",
            "tam_status": "eq.active",
            "tier": "eq.1",
            "order": "icp_fit_score.desc",
        },
        select="company_name,domain,icp_fit_score,tier",
        limit=5,
    )

    if top_companies:
        print(f"\n  Top 5 Tier 1 Companies:")
        print(f"  {'Company':<30} {'Domain':<25} {'Score':>5}")
        print(f"  {'-'*63}")
        for c in top_companies:
            name = (c.get("company_name") or "")[:29]
            domain = (c.get("domain") or "")[:24]
            score = c.get("icp_fit_score", 0)
            print(f"  {name:<30} {domain:<25} {score:>5}")

    return {
        "total_companies": total,
        "active": active,
        "deprecated": deprecated,
        "converted": converted,
        "tier_1": tier1,
        "tier_2": tier2,
        "tier_3": tier3,
        "company_type": {
            "product": type_product,
            "services": type_services,
            "agency": type_agency,
            "unknown": type_unknown,
        },
        "total_people": total_people,
        "monitoring": monitoring,
    }


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TAM Builder — Build, Refresh, and Monitor your Total Addressable Market"
    )
    parser.add_argument("--config", required=True, help="Path to TAM config JSON")
    parser.add_argument("--mode", required=True, choices=["build", "refresh", "status"],
                        help="Mode: build (first-time), refresh (update), status (report)")
    parser.add_argument("--test", action="store_true", help="Test mode: 1 page, 100 companies")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, no API calls")
    parser.add_argument("--preview", action="store_true", help="Preview only: show total count")
    parser.add_argument("--sample", action="store_true",
                        help="Sample mode: search + score in-memory, NO database writes. "
                             "Shows tier distribution and top companies for review.")
    parser.add_argument("--skip-watchlist", action="store_true", help="Skip persona watchlist phase")
    args = parser.parse_args()

    config = load_config(args.config)
    env = load_env()

    client_name = config["client_name"]

    # Determine caps
    if args.test:
        caps = MODE_CAPS["test"]
    else:
        mode_name = config.get("mode", "standard")
        caps = MODE_CAPS.get(mode_name, MODE_CAPS["standard"])

    print(f"\n{'='*60}")
    print(f"TAM Builder")
    print(f"{'='*60}")
    print(f"  Client: {client_name}")
    print(f"  Config: {args.config}")
    print(f"  Mode: {args.mode}")
    print(f"  Caps: {caps['label']}")
    if args.dry_run:
        print(f"  DRY RUN — no API calls will be made")

    if args.sample:
        print(f"  SAMPLE MODE — no database writes")

    if args.mode == "build":
        build_tam(
            config, env, caps=caps,
            dry_run=args.dry_run,
            auto_confirm=args.yes,
            preview_only=args.preview,
            skip_watchlist=args.skip_watchlist,
            sample_only=args.sample,
        )
    elif args.mode == "refresh":
        refresh_tam(
            config, env, caps=caps,
            dry_run=args.dry_run,
            auto_confirm=args.yes,
            skip_watchlist=args.skip_watchlist,
        )
    elif args.mode == "status":
        get_tam_status(config, env)


if __name__ == "__main__":
    main()
