"""
extractor/fetch.py — Generic multi-layer URL metadata + content extractor.

Layer 1: HTTP GET (redirect-following, canonical URL resolution)
Layer 2: HTML meta extraction (og:*, twitter:*, <title>, <meta description>)
Layer 3: Readable content extraction via trafilatura (optional, feature-flagged)
Layer 4: Per-domain providers — GitHub, Twitter/X, YouTube, HN context, + custom plugins
         (extractor/providers/). Each provider targets specific URL patterns and enriches
         the result with API data, structured metadata, and auto-tags.

Returns an ExtractionResult dataclass. Never raises; errors captured as status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from open_benchmark.config import settings
from open_benchmark.extractor.providers import run_providers

# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    url: str
    canonical_url: str = ""
    title: str = ""
    description: str = ""
    content_text: str = ""
    raw_text: str = ""
    tags: list[str] = field(default_factory=list)
    extraction_confidence: float = 0.0
    status: str = "ok"           # ok | partial | failed | non_html | timeout
    error: str = ""


# ── HTML meta tag parser ───────────────────────────────────────────────────────

class _MetaParser(HTMLParser):
    """Extract <title>, og:*, twitter:*, and meta description from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str = ""
        self.description: str = ""
        self.og_title: str = ""
        self.og_description: str = ""
        self.twitter_title: str = ""
        self.twitter_description: str = ""
        self.canonical_url: str = ""
        self._in_title = False
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        a = dict(attrs)
        tag_l = tag.lower()

        if tag_l == "title":
            self._in_title = True

        elif tag_l == "meta":
            prop = (a.get("property") or "").lower()
            name = (a.get("name") or "").lower()
            content = a.get("content") or ""

            if prop == "og:title":
                self.og_title = content
            elif prop == "og:description":
                self.og_description = content
            elif name == "twitter:title":
                self.twitter_title = content
            elif name == "twitter:description":
                self.twitter_description = content
            elif name == "description":
                self.description = content

        elif tag_l == "link":
            if (a.get("rel") or "").lower() == "canonical":
                self.canonical_url = a.get("href") or ""

        elif tag_l == "body":
            self._done = True  # Stop after head

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def best_title(self) -> str:
        return (self.og_title or self.twitter_title or self.title or "").strip()

    def best_description(self) -> str:
        return (
            self.og_description or self.twitter_description or self.description or ""
        ).strip()[:500]


# ── Content extraction (trafilatura) ─────────────────────────────────────────

def _extract_content(html: str) -> str:
    """Return main readable text from HTML using trafilatura."""
    try:
        import trafilatura  # type: ignore

        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        return (text or "").strip()[:4000]
    except ImportError:
        return ""
    except Exception:
        return ""


# ── Main entry point ──────────────────────────────────────────────────────────

def extract(url: str) -> ExtractionResult:
    """
    Fetch a URL and extract structured metadata + content.

    Returns ExtractionResult regardless of errors (never raises).
    """
    result = ExtractionResult(url=url, canonical_url=url)

    # Layer 1 — HTTP fetch
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": settings.fetch_user_agent},
            timeout=settings.fetch_timeout,
            allow_redirects=True,
        )
        result.canonical_url = resp.url  # resolved after redirects
        content_type = resp.headers.get("content-type", "").lower()

        if resp.status_code >= 400:
            result.status = "failed"
            result.error = f"HTTP {resp.status_code}"
            return result

        if "text/html" not in content_type:
            result.status = "non_html"
            result.error = f"content-type: {content_type}"
            return result

        html = resp.text

    except requests.Timeout:
        result.status = "timeout"
        result.error = "request timed out"
        return result
    except Exception as exc:
        result.status = "failed"
        result.error = str(exc)
        return result

    # Layer 2 — HTML meta extraction
    parser = _MetaParser()
    try:
        parser.feed(html[:60_000])  # limit parse to first 60 KB
    except Exception:
        pass

    result.title = parser.best_title()
    result.description = parser.best_description()
    if parser.canonical_url:
        result.canonical_url = parser.canonical_url

    # Layer 3 — Readable content
    if settings.feature_trafilatura:
        result.content_text = _extract_content(html)

    # Layer 4 — Provider enrichment (GitHub, Twitter/X, YouTube, HN, custom plugins)
    run_providers(url, result)

    # Confidence scoring
    filled = sum([
        bool(result.title),
        bool(result.description),
        bool(result.content_text),
        bool(result.tags),
    ])
    result.extraction_confidence = filled / 4.0

    if result.extraction_confidence < 0.25:
        result.status = "partial"
    
    return result
