"""
GooseWorks API routing library.
When GOOSEWORKS_API_KEY is set, routes API calls through GooseWorks proxy.
Otherwise falls back to direct provider API with user's own key.

Usage in skill scripts:
    from lib.gooseworks import apify_config, apollo_config, is_gooseworks
"""
import os

GW_BASE = os.environ.get("GOOSEWORKS_API_BASE", "https://app.gooseworks.ai")


def is_gooseworks() -> bool:
    """Check if running with GooseWorks API key."""
    return bool(os.environ.get("GOOSEWORKS_API_KEY"))


def gw_headers() -> dict:
    """Get GooseWorks authorization headers."""
    return {
        "Authorization": f"Bearer {os.environ['GOOSEWORKS_API_KEY']}",
        "Content-Type": "application/json",
    }


def apify_config() -> dict:
    """
    Get Apify API configuration.
    Returns dict with 'base_url' and 'token'.

    GooseWorks mode: routes through /proxy/apify/v2 (managed API key on server)
    Direct mode: uses user's APIFY_API_TOKEN
    """
    if is_gooseworks():
        return {
            "base_url": f"{GW_BASE}/proxy/apify/v2",
            "token": os.environ["GOOSEWORKS_API_KEY"],
        }
    return {
        "base_url": "https://api.apify.com/v2",
        "token": os.environ.get("APIFY_API_TOKEN", ""),
    }


def apollo_config() -> dict:
    """
    Get Apollo API configuration.
    Returns dict with 'base_url' and 'headers'.

    GooseWorks mode: routes through /proxy/apollo/v1
    Direct mode: uses user's APOLLO_API_KEY
    """
    if is_gooseworks():
        return {
            "base_url": f"{GW_BASE}/proxy/apollo/v1",
            "headers": gw_headers(),
        }
    return {
        "base_url": "https://api.apollo.io/api/v1",
        "headers": {
            "Content-Type": "application/json",
            "x-api-key": os.environ.get("APOLLO_API_KEY", ""),
        },
    }


def crustdata_config() -> dict:
    """
    Get CrustData API configuration.
    Returns dict with 'base_url' and 'headers'.
    """
    if is_gooseworks():
        return {
            "base_url": f"{GW_BASE}/proxy/crustdata",
            "headers": gw_headers(),
        }
    return {
        "base_url": "https://api.crustdata.com",
        "headers": {
            "Authorization": f"Token {os.environ.get('CRUSTDATA_API_KEY', '')}",
            "Content-Type": "application/json",
        },
    }


# --- Named API shortcuts (use GooseWorks REST API directly) ---

def gw_find_email(name: str, company: str) -> dict:
    """Call GooseWorks find-email API. Only works with GOOSEWORKS_API_KEY."""
    import requests
    resp = requests.post(
        f"{GW_BASE}/v1/tools/find-email",
        headers=gw_headers(),
        json={"name": name, "company": company},
    )
    resp.raise_for_status()
    return resp.json()


def gw_search_people(**params) -> dict:
    """Call GooseWorks search-people API."""
    import requests
    resp = requests.post(
        f"{GW_BASE}/v1/tools/search-people",
        headers=gw_headers(),
        json=params,
    )
    resp.raise_for_status()
    return resp.json()


def gw_scrape_twitter(query: str, max_tweets: int = 50, **params) -> dict:
    """Call GooseWorks scrape-twitter API."""
    import requests
    resp = requests.post(
        f"{GW_BASE}/v1/tools/scrape/twitter",
        headers=gw_headers(),
        json={"query": query, "max_tweets": max_tweets, **params},
    )
    resp.raise_for_status()
    return resp.json()
