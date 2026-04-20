"""
Built-in provider: X.com / Twitter.

X pages are JS-rendered — a plain HTTP GET returns almost nothing useful.
Strategy:
  1. Extract username + tweet ID from the URL (always works, no API key needed)
  2. Try fxtwitter.com API (community-maintained, no auth) for tweet text
  3. Fall back to a synthetic title using URL structure alone

Feature flag: FEATURE_TWITTER_EXTRACT (default: true)
"""

from __future__ import annotations

import re

import requests

from open_benchmark.config import settings

_TWITTER_RE = re.compile(r"https?://(twitter|x)\.com/(@?[\w]+)/status/(\d+)")
# fxtwitter returns structured JSON for any tweet ID, no auth required
_FXTWITTER_API = "https://api.fxtwitter.com/{username}/status/{tweet_id}"


def matches(url: str) -> bool:
    return bool(_TWITTER_RE.search(url)) and settings.feature_twitter_extract


def enrich(url: str, result) -> None:
    m = _TWITTER_RE.search(url)
    if not m:
        return

    username = m.group(2).lstrip("@")
    tweet_id = m.group(3)

    # Step 1 — always tag as social/twitter and build synthetic baseline
    existing = set(result.tags)
    for tag in ("twitter", "social", "x"):
        if tag not in existing:
            result.tags.append(tag)

    synthetic_title = f"@{username} on X"
    if not result.title:
        result.title = synthetic_title

    # Step 2 — try fxtwitter for richer content
    try:
        resp = requests.get(
            _FXTWITTER_API.format(username=username, tweet_id=tweet_id),
            timeout=5,
            headers={"User-Agent": settings.fetch_user_agent},
        )
        if resp.status_code == 200:
            data = resp.json()
            tweet = data.get("tweet") or {}
            text: str = tweet.get("text", "")
            author: str = tweet.get("author", {}).get("name", "") or username
            screen_name: str = tweet.get("author", {}).get("screen_name", "") or username

            if text:
                result.title = f"@{screen_name} on X"
                if not result.description:
                    result.description = text[:500]
                result.raw_text = (
                    f"Tweet by @{screen_name} ({author}): {text}"
                )
    except Exception:
        pass
