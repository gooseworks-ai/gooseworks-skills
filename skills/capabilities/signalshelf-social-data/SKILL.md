---
name: signalshelf-social-data
description: Pull public social and web data (Instagram, TikTok, YouTube, X, Reddit, Meta Ad Library, Google Maps, link-in-bio pages) as JSON through the SignalShelf API. Use when a GTM task needs creator or competitor profiles, recent posts, keyword search across platforms, a creator's other social accounts, local business listings, or competitor ads.
argument-hint: [topic or @handle]
---

# SignalShelf Social Data

Fetch public profile, post, search and ad data from one REST API with one key. Every call is a synchronous GET that returns JSON.

## Setup

1. Create a free account at https://signalshelf.dev (1,000 free credits after email verification, no card).
2. Copy an API key from the dashboard and set it as `SIGNALSHELF_API_KEY`.

Send every request to `https://signalshelf.dev<path>` with the key in the `x-api-key` header. Never print or store the key.

```bash
curl -s "https://signalshelf.dev/v1/instagram/profile?handle=nike" \
  -H "x-api-key: $SIGNALSHELF_API_KEY"
```

If the key is missing, ask the user to create one. Do not invent data when a call cannot run.

## Endpoints

| Need | Path | Main parameters |
|---|---|---|
| Instagram profile | `/v1/instagram/profile` | `handle` |
| Instagram recent posts | `/v2/instagram/user/posts` | `handle`, `cursor` |
| Instagram account search | `/v1/instagram/search` | `query` |
| TikTok profile | `/v1/tiktok/profile` | `handle` |
| TikTok profile videos | `/v3/tiktok/profile/videos` | `handle`, `sort_by`, `max_cursor` |
| TikTok user search | `/v1/tiktok/search/users` | `query` |
| YouTube channel | `/v1/youtube/channel` | `handle` |
| YouTube search | `/v1/youtube/search` | `query`, `uploadDate`, `sortBy` |
| X profile | `/v1/twitter/profile` | `handle` |
| A creator's other social accounts | `/v1/find-social-profiles` | `platform` (instagram, tiktok, youtube, x, facebook), `handle` |
| Link-in-bio page | `/v1/linktree` | `url` |
| Reddit search | `/v1/reddit/search` | `query`, `sort`, `timeframe` |
| Meta Ad Library search | `/v1/facebook/adLibrary/search/ads` | `query`, `country` |
| Google Maps businesses | `/v1/google-maps/search` | `query`, `location`, `limit` |

Full reference with every endpoint and parameter: https://signalshelf.dev/docs

## Credits

- Most calls cost 1 credit; search and ad-library calls cost 2 to 3. Each response includes `credits_charged` and `credits_remaining`.
- Failed calls cost nothing.
- Add `cache_max_age` (for example `1d`) on endpoints that support it to accept a recent cached copy for free.
- A `404` means the profile or post does not exist or is not public. Do not retry it.

## Workflow

1. Confirm the platforms, handles or keywords, and how many results the user needs.
2. Make one small call first and check the response shape before paging.
3. Follow the returned cursor only until the requested sample size is reached.
4. Keep the platform, handle, source URL and date with every item, and remove duplicates by URL or ID.
5. Report what the API returned separately from your own conclusions. Follower count alone does not show audience fit.

## Example: creator discovery

1. Search candidates with `/v1/tiktok/search/users` and `/v1/instagram/search`.
2. Pull each shortlisted profile with the matching profile endpoint for follower counts and bio.
3. Use `/v1/find-social-profiles` to find each creator's accounts on other platforms.
4. Return a table: creator, platforms with links, followers per platform, and a one-line content focus.
