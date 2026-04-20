"""
ingest/api.py — FastAPI ingest endpoint for adding URLs and notes.

Endpoints:
  POST /ingest/links  — fetch + classify + store a URL
  POST /ingest/notes  — add/update a note on an existing entry
  GET  /health        — health check

Run:
  python -m open_benchmark.ingest.api
  uvicorn open_benchmark.ingest.api:app --host 127.0.0.1 --port 8766

Auth: Bearer token in Authorization header (INGEST_API_KEY env var).
"""

from __future__ import annotations

import os
import sys

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, HttpUrl

from open_benchmark.config import settings
from open_benchmark.extractor.classify import classify_subject, classify_type
from open_benchmark.extractor.fetch import extract
from open_benchmark.graph import relations as graph
from open_benchmark.indexer import qdrant_index as qdrant
from open_benchmark.storage import db as storage
from open_benchmark.storage.db import init_db

app = FastAPI(
    title="AlManak Ingest API",
    description="Add and manage curated URL entries.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

# ── Auth ───────────────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


def _check_auth(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    api_key = settings.ingest_api_key
    if not api_key:
        return  # No key configured → open (dev mode)
    if credentials is None or credentials.credentials != api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


# ── Request / Response models ─────────────────────────────────────────────────


class IngestLinkRequest(BaseModel):
    url: str
    tags: str = ""
    notes: str = ""
    visibility: str = "private"
    dry_run: bool = False


class IngestLinkResponse(BaseModel):
    id: int | None
    url: str
    canonical_url: str
    title: str
    description: str
    type: str
    subject: str
    tags: str
    extraction_confidence: float
    status: str
    duplicate: bool
    existing_id: int | None = None
    dry_run: bool


class NoteRequest(BaseModel):
    id: int
    notes: str
    tags: str = ""


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    s = storage.stats()
    return {"status": "ok", "total_entries": s["total"]}


@app.post("/ingest/links", response_model=IngestLinkResponse, dependencies=[Depends(_check_auth)])
def ingest_link(body: IngestLinkRequest):
    """
    Fetch metadata for a URL, classify it, check for duplicates, and store it.

    Set `dry_run=true` to preview extraction without writing to the database.
    """
    result = extract(body.url)

    if result.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Extraction failed: {result.error}",
        )

    entry_type = classify_type(result.canonical_url, result.title, result.description)
    entry_subject = classify_subject(result.canonical_url, result.title, result.description)

    # Merge user-supplied tags with auto-extracted tags
    user_tags = [t.strip() for t in body.tags.split(",") if t.strip()]
    all_tags = list(dict.fromkeys(result.tags + user_tags))  # preserve order, deduplicate
    tags_str = ", ".join(all_tags)

    fingerprint = storage.url_fingerprint(result.canonical_url)
    existing = storage.get_by_fingerprint(fingerprint)

    response_base = IngestLinkResponse(
        id=None,
        url=body.url,
        canonical_url=result.canonical_url,
        title=result.title,
        description=result.description,
        type=entry_type,
        subject=entry_subject,
        tags=tags_str,
        extraction_confidence=result.extraction_confidence,
        status=result.status,
        duplicate=existing is not None,
        existing_id=existing["id"] if existing else None,
        dry_run=body.dry_run,
    )

    if body.dry_run or existing:
        return response_base

    entry_id = storage.insert(
        url=body.url,
        canonical_url=result.canonical_url,
        title=result.title,
        description=result.description,
        content_text=result.content_text,
        btype=entry_type,
        subject=entry_subject,
        tags=tags_str,
        notes=body.notes,
        raw_text=result.raw_text,
        extraction_confidence=result.extraction_confidence,
        visibility=body.visibility,
    )

    # Async-ish: index in background (best-effort)
    try:
        qdrant.index(db_path=None)  # full incremental
    except Exception:
        pass

    # Build graph relations for the new entry (best-effort)
    if settings.feature_graph:
        try:
            graph.build_tag_relations()
            graph.build_domain_relations()
        except Exception:
            pass

    response_base.id = entry_id
    return response_base


@app.post("/ingest/notes", dependencies=[Depends(_check_auth)])
def update_note(body: NoteRequest):
    """Add or replace the note on an existing entry. Optionally update tags."""
    entry = storage.get_by_id(body.id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {body.id} not found")
    storage.update_notes(body.id, body.notes)
    if body.tags:
        storage.update_tags(body.id, body.tags)
    return {"ok": True, "id": body.id}


@app.delete("/ingest/entries/{entry_id}", dependencies=[Depends(_check_auth)])
def delete_entry(entry_id: int):
    """Delete an entry by ID."""
    entry = storage.get_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
    storage.delete(entry_id)
    return {"ok": True, "deleted": entry_id}


# ── Browser bookmarklet endpoints ──────────────────────────────────────────────

def _check_key(key: str) -> bool:
    """Validate the key query param against the configured ingest API key."""
    api_key = settings.ingest_api_key
    if not api_key:
        return True  # dev mode: no auth
    return key == api_key


@app.get("/add", response_class=HTMLResponse)
def add_via_bookmarklet(request: Request, url: str = Query(""), key: str = Query("")):
    """
    One-click URL save from a browser bookmarklet.
    Returns a minimal HTML page (works as a popup or tab).

    Usage: GET /add?url=<encoded-url>&key=<api-key>
    """
    if not _check_key(key):
        return HTMLResponse(_html_page("⛔ Invalid key", "Check your bookmarklet configuration.", ok=False), status_code=401)

    if not url:
        return HTMLResponse(_html_page("⚠️ No URL", "No URL was provided.", ok=False), status_code=400)

    result = extract(url)
    if result.status == "failed":
        return HTMLResponse(_html_page("❌ Failed", f"Could not extract: {result.error}", ok=False), status_code=422)

    entry_type = classify_type(result.canonical_url, result.title, result.description)
    entry_subject = classify_subject(result.canonical_url, result.title, result.description)
    user_tags: list[str] = []
    all_tags = list(dict.fromkeys(result.tags + user_tags))
    tags_str = ", ".join(all_tags)
    fingerprint = storage.url_fingerprint(result.canonical_url)
    existing = storage.get_by_fingerprint(fingerprint)

    if existing:
        return HTMLResponse(_html_page(
            "Already saved",
            f"<b>{result.title or url}</b><br><small>id #{existing['id']} · {entry_type} · {entry_subject}</small>",
            ok=True,
        ))

    entry_id = storage.insert(
        url=url,
        canonical_url=result.canonical_url,
        title=result.title,
        description=result.description,
        content_text=result.content_text,
        btype=entry_type,
        subject=entry_subject,
        tags=tags_str,
        notes="",
        raw_text=result.raw_text,
        extraction_confidence=result.extraction_confidence,
        visibility="private",
    )

    try:
        qdrant.index(db_path=None)
    except Exception:
        pass
    if settings.feature_graph:
        try:
            graph.build_tag_relations()
            graph.build_domain_relations()
        except Exception:
            pass

    return HTMLResponse(_html_page(
        "✅ Saved!",
        f"<b>{result.title or url}</b><br>"
        f"<small>id #{entry_id} · {entry_type} · {entry_subject}"
        + (f" · {tags_str}" if tags_str else "") + "</small>",
        ok=True,
    ))


@app.get("/bookmarklet", response_class=HTMLResponse)
def bookmarklet_setup(request: Request, key: str = Query("")):
    """
    Setup page for the browser bookmarklet.
    Drag the button to your bookmarks bar — done.

    Usage: GET /bookmarklet?key=<api-key>
    """
    if not _check_key(key):
        return HTMLResponse(_html_page("⛔ Invalid key", "Add ?key=YOUR_API_KEY to the URL.", ok=False), status_code=401)

    # Prefer explicit public URL (set INGEST_PUBLIC_URL) so reverse proxies
    # (Tailscale serve, nginx, Caddy) don't cause the bookmarklet to point at
    # 127.0.0.1 instead of the real public hostname.
    base = settings.ingest_public_url.rstrip("/") if settings.ingest_public_url else str(request.base_url).rstrip("/")
    bm_js = (
        f"javascript:(function(){{"
        f"window.open('{base}/add?key={key}&url='+encodeURIComponent(location.href),'_ob','width=400,height=260');"
        f"}})();"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Add to AlManak</title>
<style>
  body{{font-family:system-ui,sans-serif;max-width:520px;margin:60px auto;padding:0 20px;color:#1a1a1a}}
  h1{{font-size:1.3rem;margin-bottom:4px}}
  p{{color:#555;margin:0 0 24px}}
  .bm{{display:inline-block;padding:10px 20px;background:#0070f3;color:#fff;border-radius:8px;
        text-decoration:none;font-weight:600;font-size:1rem;cursor:grab;border:none}}
  .bm:active{{cursor:grabbing}}
  .step{{background:#f5f5f5;border-radius:8px;padding:16px;margin-bottom:16px}}
  .step b{{display:block;margin-bottom:6px}}
  code{{font-size:.8rem;word-break:break-all;color:#333}}
  .mobile{{background:#fffbe6;border:1px solid #f0d060}}
</style>
</head>
<body>
<h1>📎 AlManak bookmarklet</h1>
<p>Save any page to your knowledge base in one click.</p>

<div class="step">
  <b>1. Drag this button to your bookmarks bar:</b>
  <a class="bm" href="{bm_js}">+ Save to AlManak</a>
  <br><br>
  <small>Then click it on any page you want to save.</small>
</div>

<div class="step">
  <b>2. Or copy the bookmarklet code manually:</b>
  <code>{bm_js}</code>
</div>

<div class="step mobile">
  <b>📱 Mobile (iOS / Android):</b>
  Bookmark any page, then edit the bookmark URL and replace it with the code above.
  Tap the bookmark on any page to save.
</div>

<div class="step">
  <b>🔗 Your endpoint:</b>
  <code>{base}/add</code><br>
  <b>🔑 Key:</b> <code>{key[:8]}…</code>
</div>
</body>
</html>"""
    return HTMLResponse(html)


def _html_page(title: str, body: str, ok: bool = True) -> str:
    color = "#0a7c42" if ok else "#b91c1c"
    bg = "#f0fdf4" if ok else "#fef2f2"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body{{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;
       min-height:100vh;margin:0;background:{bg}}}
  .card{{background:#fff;border-radius:12px;padding:28px 32px;max-width:380px;text-align:center;
         box-shadow:0 2px 12px rgba(0,0,0,.08)}}
  h2{{color:{color};margin:0 0 12px;font-size:1.2rem}}
  p{{color:#555;font-size:.9rem;margin:0}}
</style>
<script>setTimeout(()=>window.close(),3000)</script>
</head>
<body>
<div class="card">
  <h2>{title}</h2>
  <p>{body}</p>
</div>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────


def main():
    import uvicorn  # type: ignore

    init_db()
    uvicorn.run(
        "open_benchmark.ingest.api:app",
        host=settings.ingest_host,
        port=settings.ingest_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
