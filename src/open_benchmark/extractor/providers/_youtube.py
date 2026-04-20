"""
Built-in provider: YouTube videos.

Uses the official YouTube oEmbed endpoint (no API key required) to enrich
video pages with a structured title, channel name, and tags.

Feature flag: FEATURE_YT_EXTRACT (default: true)
"""

from __future__ import annotations

import re

import requests

from open_benchmark.config import settings

_YT_RE = re.compile(r"https?://(www\.)?(youtube\.com|youtu\.be)/")
_OEMBED_URL = "https://www.youtube.com/oembed"


def matches(url: str) -> bool:
    return bool(_YT_RE.search(url)) and settings.feature_yt_extract


def enrich(url: str, result) -> None:
    try:
        resp = requests.get(
            _OEMBED_URL,
            params={"url": url, "format": "json"},
            timeout=5,
            headers={"User-Agent": settings.fetch_user_agent},
        )
        if resp.status_code != 200:
            return

        data = resp.json()
        title = data.get("title", "")
        author = data.get("author_name", "")

        if not result.title and title:
            result.title = title
        if not result.description and author:
            result.description = f"YouTube video by {author}"

        existing = set(result.tags)
        for tag in ("youtube", "video"):
            if tag not in existing:
                result.tags.append(tag)

        result.raw_text = f"YouTube video: {title}" + (f" by {author}" if author else "")
    except Exception:
        pass
