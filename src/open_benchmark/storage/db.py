"""
storage/db.py — SQLite schema, connection helpers, and CRUD operations.

Schema (benchmarks table):
  id, received_at, url, canonical_url, title, description, summary,
  content_text, type, subject, tags, notes, raw_text, status,
  fingerprint, extraction_confidence, visibility

Graph extensions (benchmark_relations table):
  source_id, target_id, relation, score, evidence, created_at
"""

from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from open_benchmark.config import settings

# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmarks (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at           TEXT    NOT NULL,
    url                   TEXT,
    canonical_url         TEXT    DEFAULT '',
    title                 TEXT    DEFAULT '',
    description           TEXT    DEFAULT '',
    summary               TEXT    DEFAULT '',
    content_text          TEXT    DEFAULT '',
    type                  TEXT    DEFAULT 'other',
    subject               TEXT    DEFAULT 'unspecified',
    tags                  TEXT    DEFAULT '',
    notes                 TEXT    DEFAULT '',
    raw_text              TEXT    DEFAULT '',
    status                TEXT    DEFAULT 'new',
    fingerprint           TEXT    DEFAULT '',
    extraction_confidence REAL    DEFAULT 0.0,
    visibility            TEXT    DEFAULT 'private'
);

CREATE VIRTUAL TABLE IF NOT EXISTS benchmarks_fts USING fts5(
    title, description, tags, notes, raw_text, content_text,
    content='benchmarks', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS bm_ai AFTER INSERT ON benchmarks BEGIN
    INSERT INTO benchmarks_fts(rowid, title, description, tags, notes, raw_text, content_text)
    VALUES (new.id, new.title, new.description, new.tags, new.notes, new.raw_text, new.content_text);
END;

CREATE TRIGGER IF NOT EXISTS bm_au AFTER UPDATE ON benchmarks BEGIN
    INSERT INTO benchmarks_fts(benchmarks_fts, rowid, title, description, tags, notes, raw_text, content_text)
    VALUES ('delete', old.id, old.title, old.description, old.tags, old.notes, old.raw_text, old.content_text);
    INSERT INTO benchmarks_fts(rowid, title, description, tags, notes, raw_text, content_text)
    VALUES (new.id, new.title, new.description, new.tags, new.notes, new.raw_text, new.content_text);
END;

CREATE TRIGGER IF NOT EXISTS bm_ad AFTER DELETE ON benchmarks BEGIN
    INSERT INTO benchmarks_fts(benchmarks_fts, rowid, title, description, tags, notes, raw_text, content_text)
    VALUES ('delete', old.id, old.title, old.description, old.tags, old.notes, old.raw_text, old.content_text);
END;

CREATE TABLE IF NOT EXISTS benchmark_relations (
    source_id  INTEGER NOT NULL,
    target_id  INTEGER NOT NULL,
    relation   TEXT    NOT NULL,
    score      REAL    DEFAULT 1.0,
    evidence   TEXT    DEFAULT '',
    created_at TEXT    NOT NULL,
    PRIMARY KEY (source_id, target_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_relations_source ON benchmark_relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON benchmark_relations(target_id);
CREATE INDEX IF NOT EXISTS idx_relations_type   ON benchmark_relations(relation);

CREATE UNIQUE INDEX IF NOT EXISTS uq_benchmarks_url ON benchmarks(url);
"""

# Columns that may be missing in databases created before this version
_MIGRATIONS: list[tuple[str, str]] = [
    ("canonical_url",         "ALTER TABLE benchmarks ADD COLUMN canonical_url TEXT DEFAULT ''"),
    ("content_text",          "ALTER TABLE benchmarks ADD COLUMN content_text TEXT DEFAULT ''"),
    ("fingerprint",           "ALTER TABLE benchmarks ADD COLUMN fingerprint TEXT DEFAULT ''"),
    ("extraction_confidence", "ALTER TABLE benchmarks ADD COLUMN extraction_confidence REAL DEFAULT 0.0"),
    ("visibility",            "ALTER TABLE benchmarks ADD COLUMN visibility TEXT DEFAULT 'private'"),
    ("summary",               "ALTER TABLE benchmarks ADD COLUMN summary TEXT DEFAULT ''"),
]


# ── Connection factory ────────────────────────────────────────────────────────

def conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or str(settings.db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def init_db(db_path: str | None = None) -> None:
    """Create schema and apply incremental migrations."""
    with conn(db_path) as c:
        c.executescript(_SCHEMA)
        existing_cols = {
            r[1] for r in c.execute("PRAGMA table_info(benchmarks)").fetchall()
        }
        for col_name, ddl in _MIGRATIONS:
            if col_name not in existing_cols:
                c.execute(ddl)
        c.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def url_fingerprint(url: str) -> str:
    """Stable SHA-256 fingerprint of a canonical URL for dedup."""
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]


def build_summary(title: str, description: str, btype: str, subject: str) -> str:
    parts = []
    if title:
        parts.append(title.strip())
    clean_desc = (description or "").strip()
    if clean_desc and clean_desc.lower() != title.strip().lower():
        parts.append(clean_desc[:250])
    body = " — ".join(parts)
    suffix = f"[{btype}/{subject}]"
    return f"{body}  {suffix}".strip() if body else suffix


# ── CRUD ──────────────────────────────────────────────────────────────────────

def insert(
    *,
    url: str,
    canonical_url: str = "",
    title: str = "",
    description: str = "",
    content_text: str = "",
    btype: str = "other",
    subject: str = "unspecified",
    tags: str = "",
    notes: str = "",
    raw_text: str = "",
    extraction_confidence: float = 0.0,
    visibility: str = "private",
    db_path: str | None = None,
) -> int:
    received_at = datetime.now(timezone.utc).isoformat()
    summary = build_summary(title, description, btype, subject)
    fingerprint = url_fingerprint(canonical_url or url)

    with conn(db_path) as c:
        cur = c.execute(
            """INSERT OR IGNORE INTO benchmarks
               (received_at, url, canonical_url, title, description, summary,
                content_text, type, subject, tags, notes, raw_text,
                fingerprint, extraction_confidence, visibility)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                received_at, url, canonical_url or url, title, description, summary,
                content_text, btype, subject, tags, notes, raw_text,
                fingerprint, extraction_confidence, visibility,
            ),
        )
        if cur.rowcount == 0:
            # URL already exists — return the id of the existing entry
            existing = c.execute(
                "SELECT id FROM benchmarks WHERE url=?", (url,)
            ).fetchone()
            c.commit()
            return existing["id"] if existing else -1
        row_id = cur.lastrowid
        c.commit()
    return row_id


def get_by_id(entry_id: int, db_path: str | None = None) -> dict[str, Any] | None:
    with conn(db_path) as c:
        row = c.execute("SELECT * FROM benchmarks WHERE id=?", (entry_id,)).fetchone()
    return dict(row) if row else None


def get_by_fingerprint(fingerprint: str, db_path: str | None = None) -> dict[str, Any] | None:
    with conn(db_path) as c:
        row = c.execute(
            "SELECT * FROM benchmarks WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
    return dict(row) if row else None


def search_fts(query: str, limit: int = 20, db_path: str | None = None) -> list[dict]:
    with conn(db_path) as c:
        rows = c.execute(
            """SELECT b.* FROM benchmarks b
               JOIN benchmarks_fts f ON b.id = f.rowid
               WHERE benchmarks_fts MATCH ?
               ORDER BY b.id DESC LIMIT ?""",
            (query, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def list_recent(limit: int = 10, db_path: str | None = None) -> list[dict]:
    with conn(db_path) as c:
        rows = c.execute(
            "SELECT * FROM benchmarks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def stats(db_path: str | None = None) -> dict:
    with conn(db_path) as c:
        total = c.execute("SELECT COUNT(*) FROM benchmarks").fetchone()[0]
        by_type = {
            r[0]: r[1]
            for r in c.execute(
                "SELECT type, COUNT(*) n FROM benchmarks GROUP BY type ORDER BY n DESC"
            ).fetchall()
        }
        by_subject = {
            r[0]: r[1]
            for r in c.execute(
                "SELECT subject, COUNT(*) n FROM benchmarks GROUP BY subject ORDER BY n DESC"
            ).fetchall()
        }
    return {"total": total, "by_type": by_type, "by_subject": by_subject}


def update_tags(entry_id: int, tags: str, db_path: str | None = None) -> None:
    with conn(db_path) as c:
        c.execute("UPDATE benchmarks SET tags=? WHERE id=?", (tags, entry_id))
        c.commit()


def update_notes(entry_id: int, notes: str, db_path: str | None = None) -> None:
    with conn(db_path) as c:
        c.execute("UPDATE benchmarks SET notes=? WHERE id=?", (notes, entry_id))
        c.commit()


def delete(entry_id: int, db_path: str | None = None) -> None:
    with conn(db_path) as c:
        c.execute("DELETE FROM benchmarks WHERE id=?", (entry_id,))
        c.commit()


def update_entry(
    entry_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    content_text: str | None = None,
    btype: str | None = None,
    subject: str | None = None,
    tags: str | None = None,
    raw_text: str | None = None,
    canonical_url: str | None = None,
    extraction_confidence: float | None = None,
    status: str | None = None,
    db_path: str | None = None,
) -> None:
    """Partially update an entry — only non-None fields are written."""
    fields: list[str] = []
    values: list[Any] = []
    for col, val in [
        ("title", title),
        ("description", description),
        ("content_text", content_text),
        ("type", btype),
        ("subject", subject),
        ("tags", tags),
        ("raw_text", raw_text),
        ("canonical_url", canonical_url),
        ("extraction_confidence", extraction_confidence),
        ("status", status),
    ]:
        if val is not None:
            fields.append(f"{col}=?")
            values.append(val)
    if not fields:
        return
    # Rebuild summary if title/description/type/subject changed
    if title is not None or description is not None or btype is not None or subject is not None:
        with conn(db_path) as c:
            row = c.execute("SELECT * FROM benchmarks WHERE id=?", (entry_id,)).fetchone()
        if row:
            cur_title = title if title is not None else row["title"]
            cur_desc = description if description is not None else row["description"]
            cur_type = btype if btype is not None else row["type"]
            cur_subj = subject if subject is not None else row["subject"]
            fields.append("summary=?")
            values.append(build_summary(cur_title, cur_desc, cur_type, cur_subj))
    values.append(entry_id)
    with conn(db_path) as c:
        c.execute(f"UPDATE benchmarks SET {', '.join(fields)} WHERE id=?", values)
        c.commit()


def list_all(db_path: str | None = None) -> list[dict]:
    """Return all entries ordered by id."""
    with conn(db_path) as c:
        rows = c.execute("SELECT * FROM benchmarks ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def export_csv(db_path: str | None = None) -> None:
    """Rewrite the live CSV from the current DB."""
    path = str(settings.csv_live_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with conn(db_path) as c:
        rows = c.execute("SELECT * FROM benchmarks ORDER BY id").fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "id", "received_at", "url", "title", "summary",
            "description", "type", "subject", "tags", "notes", "status",
        ])
        for r in rows:
            w.writerow([
                r["id"], r["received_at"], r["url"], r["title"],
                r["summary"], r["description"], r["type"], r["subject"],
                r["tags"], r["notes"], r["status"],
            ])
