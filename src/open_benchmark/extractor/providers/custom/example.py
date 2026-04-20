"""
AlManak custom provider — example / template.

═══════════════════════════════════════════════════════════════
HOW TO WRITE A CUSTOM PROVIDER
═══════════════════════════════════════════════════════════════

1. Copy this file to a new .py file in this directory:
       cp example.py my_provider.py

2. Implement matches() and enrich() for your target site.

3. Restart AlManak — it auto-discovers all *.py files here.

No registration, no imports, no configuration needed.

═══════════════════════════════════════════════════════════════
AVAILABLE FIELDS ON result (ExtractionResult)
═══════════════════════════════════════════════════════════════

  result.url            str   — original URL
  result.canonical_url  str   — final URL after redirects
  result.title          str   — page title
  result.description    str   — short description (≤ 500 chars)
  result.content_text   str   — readable article body (trafilatura)
  result.raw_text       str   — raw metadata string (used for indexing)
  result.tags           list  — list of string tags
  result.status         str   — "ok" | "partial" | "failed"

You can read, overwrite, or append to any field.
Always append to result.tags (do not replace the list).
Never raise exceptions — catch them yourself.
"""

from __future__ import annotations


# ── Example: enrich links from a fictional corporate wiki ─────────────────────

def matches(url: str) -> bool:
    """Return True when this provider should activate."""
    # Replace with your domain or URL pattern
    return False  # disabled — change to: return "wiki.mycompany.com" in url


def enrich(url: str, result) -> None:
    """
    Mutate result in-place to add richer metadata.
    Never raise — silently catch any exception.
    """
    # Example: tag all links from a specific domain
    # result.tags.append("internal-wiki")
    #
    # Example: call a private API to get extra metadata
    # try:
    #     resp = requests.get(f"https://api.mycompany.com/page?url={url}", timeout=5)
    #     if resp.ok:
    #         data = resp.json()
    #         result.title = result.title or data.get("title", "")
    #         result.description = result.description or data.get("summary", "")
    # except Exception:
    #     pass
    pass
