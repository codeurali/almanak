"""
Built-in provider: GitHub repos.

Calls the public GitHub API to enrich repos with stars, topics, language.
Falls back gracefully — never raises.

Feature flag: FEATURE_GITHUB_EXTRACTOR (default: true)
"""

from __future__ import annotations

import re

import requests

from open_benchmark.config import settings

_GH_RE = re.compile(r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$)")


def matches(url: str) -> bool:
    return bool(_GH_RE.match(url)) and settings.feature_github_extractor


def enrich(url: str, result) -> None:
    m = _GH_RE.match(url)
    if not m:
        return
    repo = m.group(1)
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}",
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": settings.fetch_user_agent,
            },
            timeout=settings.fetch_timeout,
        )
        if resp.status_code != 200:
            return
        data = resp.json()

        if not result.description and data.get("description"):
            result.description = data["description"]

        topics: list[str] = data.get("topics", [])
        lang = data.get("language") or ""
        stars: int = data.get("stargazers_count", 0)

        extra = topics + ([lang.lower()] if lang else []) + ["github", "open-source"]
        existing = set(result.tags)
        result.tags += [t for t in extra if t not in existing]

        result.raw_text = (
            f"GitHub repo: {repo}. Stars: {stars}. "
            f"Language: {lang}. Topics: {', '.join(topics)}."
        )
    except Exception:
        pass
