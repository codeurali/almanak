#!/usr/bin/env python3
"""
bot/telegram_bot.py — Optional Telegram ingestion bot.

Each message with a URL is auto-fetched, classified, deduplication-checked,
and saved to the database. The bot uses the new open_benchmark modules.

Usage:
  export BENCHMARK_BOT_TOKEN="<token>"
  export ALLOWED_USER_ID="519205390"
  python bot/telegram_bot.py

Commands:
  <url> [#tag1 #tag2] [note text]  → save with auto-metadata
  /list [N]        → last N entries (default 10)
  /search <query>  → full-text search
  /tag <id> <tags> → set tags on entry
  /note <id> <text>→ add/update note
  /rm <id>         → delete entry
  /stats           → counts by type & subject
  /export          → send CSV
  /help            → show this help
"""

from __future__ import annotations

import io
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

# Ensure src/ is on the path when run directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from open_benchmark.config import settings
from open_benchmark.extractor.classify import classify_subject, classify_type
from open_benchmark.extractor.fetch import extract
from open_benchmark.graph import relations as graph
from open_benchmark.indexer import qdrant_index as qdrant
from open_benchmark.storage import db as storage
from open_benchmark.storage.db import init_db

# ── Telegram config ────────────────────────────────────────────────────────────

TOKEN = settings.telegram_bot_token
ALLOWED_UID = settings.telegram_allowed_uid

if not TOKEN:
    sys.exit("Error: set BENCHMARK_BOT_TOKEN in .env or environment")
if not ALLOWED_UID:
    sys.exit("Error: set ALLOWED_USER_ID in .env or environment")

API = f"https://api.telegram.org/bot{TOKEN}"
POLL_TIMEOUT = 30

# Commands registered with Telegram — drives /autocomplete and the ☰ menu button
BOT_COMMANDS = [
    {"command": "list",   "description": "Last N saved entries (e.g. /list 20)"},
    {"command": "search", "description": "Full-text search  (e.g. /search RAG)"},
    {"command": "stats",  "description": "Counts by type & subject"},
    {"command": "tag",    "description": "Set tags on an entry  (e.g. /tag 42 llm rag)"},
    {"command": "note",   "description": "Add/update a note  (e.g. /note 42 great read)"},
    {"command": "rm",     "description": "Delete an entry  (e.g. /rm 42)"},
    {"command": "export", "description": "Download all entries as CSV"},
    {"command": "help",   "description": "Show all commands"},
]

URL_RE = re.compile(r"(?:https?://|(?<![\w@])(?=[a-zA-Z0-9][a-zA-Z0-9-]{1,61}[a-zA-Z0-9]\.[a-zA-Z]{2,}))[^\s<>\"']+")
TAG_RE = re.compile(r"#([A-Za-z0-9_\-]+)")


def _normalize_url(url: str) -> str:
    """Add https:// if no scheme is present."""
    if not url.startswith(("http://", "https://")):
        return "https://" + url
    return url

# ── Telegram helpers ───────────────────────────────────────────────────────────


def _tg(method: str, **kwargs) -> dict:
    # Use a longer read timeout for getUpdates (long-poll), 10s for everything else
    req_timeout = POLL_TIMEOUT + 10 if kwargs.get("timeout") else 10
    try:
        r = requests.post(f"{API}/{method}", json=kwargs, timeout=req_timeout)
        return r.json()
    except Exception as exc:
        print(f"[tg] {method} error: {exc}", flush=True)
        return {}


def send(chat_id: int, text: str, parse_mode: str = "HTML") -> None:
    _tg(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
    )


def send_doc(chat_id: int, filename: str, data: bytes, caption: str = "") -> None:
    try:
        requests.post(
            f"{API}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (filename, data, "text/csv")},
            timeout=20,
        )
    except Exception as exc:
        send(chat_id, f"⚠️ Export failed: {exc}")


# ── Formatting ─────────────────────────────────────────────────────────────────

_HELP = (
    "<b>Open Benchmark Bot</b>\n\n"
    "📥 <b>Save a link:</b>\n"
    "<code>https://… [#tag1 #tag2] [optional note]</code>\n\n"
    "📋 <b>Commands:</b>\n"
    "/list [N]        — last N entries (default 10)\n"
    "/search &lt;query&gt; — full-text search\n"
    "/tag &lt;id&gt; &lt;tags&gt;  — set tags on entry\n"
    "/note &lt;id&gt; &lt;text&gt; — add/update note\n"
    "/rm &lt;id&gt;          — delete entry\n"
    "/stats           — counts by type &amp; subject\n"
    "/export          — download as CSV\n"
    "/help            — this message"
)


def _fmt(row: dict) -> str:
    title = row.get("title") or row.get("url") or "(no title)"
    url = row.get("url", "")
    url_part = ""
    if url:
        display = (url[:55] + "…") if len(url) > 55 else url
        url_part = f'\n🔗 <a href="{url}">{display}</a>'
    tags_part = f'  <i>{row["tags"]}</i>' if row.get("tags") else ""
    desc = row.get("description", "")
    desc_part = f"\n<i>{desc[:120]}…</i>" if desc else ""
    notes = row.get("notes", "")
    note_part = f"\n📝 {notes}" if notes else ""
    return (
        f'<b>[{row["id"]}]</b> {row.get("type","")}/{row.get("subject","")}{tags_part}\n'
        f"<b>{title}</b>{url_part}{desc_part}{note_part}"
    )


# ── Command handlers ───────────────────────────────────────────────────────────


def _handle_save(chat_id: int, text: str) -> None:
    urls = URL_RE.findall(text)
    if not urls:
        send(chat_id, "⚠️ No URL detected.")
        return

    url = _normalize_url(urls[0])
    user_tags = ", ".join(TAG_RE.findall(text))
    note_text = TAG_RE.sub("", URL_RE.sub("", text)).strip()

    send(chat_id, "⏳ Fetching metadata…")
    print(f"[bot] extracting {url}", flush=True)
    try:
        result = extract(url)
    except Exception as exc:
        print(f"[bot] extract error: {exc}", flush=True)
        send(chat_id, f"❌ Failed to fetch metadata: {exc}")
        return

    entry_type = classify_type(result.canonical_url, result.title, result.description)
    entry_subject = classify_subject(result.canonical_url, result.title, result.description)

    # Merge tags
    all_tags = list(dict.fromkeys(result.tags + [t for t in user_tags.split(",") if t.strip()]))
    tags_str = ", ".join(all_tags)

    # Dedup check — use same key as insert(): canonical_url or url
    fingerprint = storage.url_fingerprint(result.canonical_url or url)
    existing = storage.get_by_fingerprint(fingerprint)
    if existing:
        send(chat_id, f'⚠️ Already saved as <b>#{existing["id"]}</b> — {_fmt(existing)}')
        return

    entry_id = storage.insert(
        url=url,
        canonical_url=result.canonical_url,
        title=result.title,
        description=result.description,
        content_text=result.content_text,
        btype=entry_type,
        subject=entry_subject,
        tags=tags_str,
        notes=note_text,
        raw_text=result.raw_text,
        extraction_confidence=result.extraction_confidence,
    )

    # INSERT OR IGNORE: -1 means already existed (DB-level dedup caught it)
    if entry_id < 0:
        send(chat_id, "⚠️ Already saved (duplicate URL blocked at DB level).")
        return

    existing_check = storage.get_by_id(entry_id)
    if existing_check and existing_check.get("received_at") != existing_check.get("received_at"):
        # Shouldn't happen, but guard anyway
        pass

    # Index only the newly inserted entry (incremental — avoids OOM on full re-index)
    try:
        qdrant.index(since=entry_id)
    except Exception:
        pass
    if settings.feature_graph:
        try:
            graph.build_tag_relations()
            graph.build_domain_relations()
        except Exception:
            pass

    confidence_note = ""
    if result.extraction_confidence < 0.5:
        confidence_note = f"\n⚠️ Partial metadata (confidence {result.extraction_confidence:.0%})"

    send(
        chat_id,
        f"✅ Saved <b>#{entry_id}</b> — {entry_type}/{entry_subject}\n"
        f"<b>{result.title or '(no title)'}</b>{confidence_note}",
    )


def _handle_list(chat_id: int, args: str) -> None:
    n = int(args.strip()) if args.strip().isdigit() else 10
    rows = storage.list_recent(limit=n)
    if not rows:
        send(chat_id, "📭 No entries yet.")
        return
    msg = "\n\n".join(_fmt(r) for r in rows)
    send(chat_id, msg)


def _handle_search(chat_id: int, query: str) -> None:
    rows = storage.search_fts(query, limit=10)
    if not rows:
        send(chat_id, f"🔍 No results for <i>{query}</i>")
        return
    msg = "\n\n".join(_fmt(r) for r in rows[:5])
    send(chat_id, msg)


def _handle_tag(chat_id: int, args: str) -> None:
    parts = args.strip().split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
        send(chat_id, "Usage: /tag &lt;id&gt; &lt;tags&gt;")
        return
    entry_id, tags = int(parts[0]), parts[1]
    if not storage.get_by_id(entry_id):
        send(chat_id, f"Entry #{entry_id} not found.")
        return
    storage.update_tags(entry_id, tags)
    send(chat_id, f"✅ Tags updated on #{entry_id}")


def _handle_note(chat_id: int, args: str) -> None:
    parts = args.strip().split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
        send(chat_id, "Usage: /note &lt;id&gt; &lt;text&gt;")
        return
    entry_id, note = int(parts[0]), parts[1]
    if not storage.get_by_id(entry_id):
        send(chat_id, f"Entry #{entry_id} not found.")
        return
    storage.update_notes(entry_id, note)
    send(chat_id, f"✅ Note updated on #{entry_id}")


def _handle_rm(chat_id: int, args: str) -> None:
    if not args.strip().isdigit():
        send(chat_id, "Usage: /rm &lt;id&gt;")
        return
    entry_id = int(args.strip())
    if not storage.get_by_id(entry_id):
        send(chat_id, f"Entry #{entry_id} not found.")
        return
    storage.delete(entry_id)
    send(chat_id, f"🗑 Deleted #{entry_id}")


def _handle_stats(chat_id: int) -> None:
    s = storage.stats()
    lines = [f"📊 <b>Total:</b> {s['total']}"]
    if s["by_type"]:
        lines.append("\n<b>By type:</b>")
        lines += [f"  {t}: {n}" for t, n in s["by_type"].items()]
    if s["by_subject"]:
        lines.append("\n<b>By subject:</b>")
        lines += [f"  {t}: {n}" for t, n in s["by_subject"].items()]
    send(chat_id, "\n".join(lines))


def _handle_export(chat_id: int) -> None:
    rows = storage.list_recent(limit=9999)
    if not rows:
        send(chat_id, "📭 Nothing to export.")
        return
    import csv

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "received_at", "url", "title", "summary", "description",
                "type", "subject", "tags", "notes", "status"])
    for r in rows:
        w.writerow([r.get(k, "") for k in
                    ["id", "received_at", "url", "title", "summary", "description",
                     "type", "subject", "tags", "notes", "status"]])
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    send_doc(chat_id, f"benchmarks_{ts}.csv", buf.getvalue().encode("utf-8"))


# ── Main polling loop ──────────────────────────────────────────────────────────


def _dispatch(chat_id: int, text: str) -> None:
    print(f"[bot] dispatch chat={chat_id} text={text[:80]!r}", flush=True)
    text = text.strip()
    if text.startswith("/list"):
        _handle_list(chat_id, text[5:].strip())
    elif text.startswith("/search "):
        _handle_search(chat_id, text[8:].strip())
    elif text.startswith("/tag "):
        _handle_tag(chat_id, text[5:].strip())
    elif text.startswith("/note "):
        _handle_note(chat_id, text[6:].strip())
    elif text.startswith("/rm "):
        _handle_rm(chat_id, text[4:].strip())
    elif text == "/stats":
        _handle_stats(chat_id)
    elif text == "/export":
        _handle_export(chat_id)
    elif text in ("/start", "/help"):
        send(chat_id, _HELP)
    elif URL_RE.search(text):
        _handle_save(chat_id, text)
    else:
        send(chat_id, "⚠️ Send a URL to save it, or /help for commands.")


_OFFSET_FILE = os.path.join(os.path.dirname(__file__), ".tg_offset")


def _load_offset() -> int:
    try:
        return int(open(_OFFSET_FILE).read().strip())
    except Exception:
        return 0


def _save_offset(offset: int) -> None:
    try:
        with open(_OFFSET_FILE, "w") as f:
            f.write(str(offset))
    except Exception as exc:
        print(f"[bot] offset save error: {exc}", flush=True)


def _register_commands() -> None:
    """Push command list to Telegram — enables / autocomplete and ☰ menu button."""
    result = _tg("setMyCommands", commands=BOT_COMMANDS)
    if result.get("result"):
        print("[bot] commands registered", flush=True)
    else:
        print(f"[bot] setMyCommands failed: {result}", flush=True)

    # Set the ☰ menu button to show the command list
    _tg("setChatMenuButton", menu_button={"type": "commands"})


def run() -> None:
    init_db()
    _register_commands()
    offset = _load_offset()
    print(f"[bot] Starting — allowed UID: {ALLOWED_UID}, offset: {offset}", flush=True)
    while True:
        try:
            resp = _tg("getUpdates", offset=offset, timeout=POLL_TIMEOUT)
            for update in resp.get("result", []):
                new_offset = update["update_id"] + 1
                msg = update.get("message")
                if msg:
                    uid = msg.get("from", {}).get("id")
                    if uid == ALLOWED_UID:
                        text = msg.get("text") or msg.get("caption") or ""
                        if text:
                            _dispatch(msg["chat"]["id"], text)
                # Persist offset AFTER processing so we never re-process on restart
                offset = new_offset
                _save_offset(offset)
        except Exception as exc:
            print(f"[bot] poll error: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    run()
