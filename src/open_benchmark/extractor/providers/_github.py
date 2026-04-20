"""
Built-in provider: GitHub repos.

Calls the public GitHub API to enrich repos with stars, topics, language,
and the first ~2 KB of the README for better semantic search.
Falls back gracefully — never raises.

Feature flag: FEATURE_GITHUB_EXTRACTOR (default: true)
"""

from __future__ import annotations

import base64
import re

import requests

from open_benchmark.config import settings

_GH_RE = re.compile(r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$)")
_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": settings.fetch_user_agent,
}
# Strip markdown noise: badges, HTML tags, image links
_MD_CLEAN = re.compile(r"!\[.*?\]\(.*?\)|<[^>]+>|\[!\[.*?\]\(.*?\)\]\(.*?\)", re.DOTALL)


def matches(url: str) -> bool:
    return bool(_GH_RE.match(url)) and settings.feature_github_extractor


def _get(path: str) -> requests.Response | None:
    try:
        resp = requests.get(
            f"https://api.github.com/{path}",
            headers=_HEADERS,
            timeout=settings.fetch_timeout,
        )
        return resp if resp.status_code == 200 else None
    except Exception:
        return None


def _readme_text(repo: str) -> str:
    """Fetch and decode the README, returning up to 3000 chars of clean text."""
    resp = _get(f"repos/{repo}/readme")
    if not resp:
        return ""
    try:
        data = resp.json()
        encoded = data.get("content", "")
        raw = base64.b64decode(encoded).decode("utf-8", errors="replace")
        # Remove noise, then truncate
        clean = _MD_CLEAN.sub("", raw)
        # Collapse whitespace runs
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        return clean[:3000]
    except Exception:
        return ""


def enrich(url: str, result) -> None:
    m = _GH_RE.match(url)
    if not m:
        return
    repo = m.group(1)

    resp = _get(f"repos/{repo}")
    if not resp:
        return

    data = resp.json()

    if not result.description and data.get("description"):
        result.description = data["description"]

    topics: list[str] = data.get("topics", [])
    lang = data.get("language") or ""
    stars: int = data.get("stargazers_count", 0)
    license_name: str = (data.get("license") or {}).get("spdx_id", "")
    archived: bool = data.get("archived", False)

    extra = topics + ([lang.lower()] if lang else []) + ["github", "open-source"]
    if archived:
        extra.append("archived")
    existing = set(result.tags)
    result.tags += [t for t in extra if t not in existing]

    readme = _readme_text(repo)
    result.content_text = readme  # overwrite trafilatura result (GH pages render JS)

    result.raw_text = (
        f"GitHub repo: {repo}. Stars: {stars}. "
        f"Language: {lang}. License: {license_name}. "
        f"Topics: {', '.join(topics)}.\n\n{readme[:1000]}"
    )
