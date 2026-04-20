"""
Built-in provider: Hacker News discussion context.

For ANY non-HN URL, queries the HN Algolia API to check whether this page
was ever discussed on Hacker News. If found with meaningful engagement,
adds HN discussion metadata to raw_text (used for semantic indexing) and
appends the "hn-discussed" tag.

This enrichment gives the AI agent useful social-signal context:
  "This paper was discussed on HN with 847 points and 230 comments."

Feature flag: FEATURE_HN_CONTEXT (default: true)
Minimum points threshold: HN_MIN_POINTS (default: 10)
"""

from __future__ import annotations

import re

import requests

from open_benchmark.config import settings

_HN_RE = re.compile(r"news\.ycombinator\.com")


def matches(url: str) -> bool:
    # Run on any URL that is NOT itself a HN page
    return not _HN_RE.search(url) and settings.feature_hn_context


def enrich(url: str, result) -> None:
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "query": url,
                "restrictSearchableAttributes": "url",
                "hitsPerPage": 5,
            },
            timeout=4,
            headers={"User-Agent": settings.fetch_user_agent},
        )
        if resp.status_code != 200:
            return

        hits = resp.json().get("hits", [])
        if not hits:
            return

        best = max(hits, key=lambda h: h.get("points") or 0)
        points: int = best.get("points") or 0

        if points < settings.hn_min_points:
            return

        comments: int = best.get("num_comments") or 0
        hn_id: str = best.get("objectID", "")
        hn_title: str = best.get("title", result.title or url)
        hn_link = f"https://news.ycombinator.com/item?id={hn_id}"

        if "hn-discussed" not in result.tags:
            result.tags.append("hn-discussed")

        hn_note = (
            f"\n\nHN: \"{hn_title}\" — "
            f"{points} pts, {comments} comments → {hn_link}"
        )
        result.raw_text = (result.raw_text or "") + hn_note
    except Exception:
        pass
