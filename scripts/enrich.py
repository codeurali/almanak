#!/usr/bin/env python3
"""
scripts/enrich.py — Re-fetch metadata for entries with missing title/description.

Usage:
  # Enrich a specific entry:
  python scripts/enrich.py --id 160

  # Enrich all entries where title is empty:
  python scripts/enrich.py --empty

  # Dry-run (show what would be updated without saving):
  python scripts/enrich.py --empty --dry-run
"""

from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from open_benchmark.config import settings
from open_benchmark.extractor.classify import classify_subject, classify_type
from open_benchmark.extractor.fetch import extract
from open_benchmark.storage import db as storage
from open_benchmark.storage.db import build_summary


def _enrich_entry(row: dict, dry_run: bool) -> bool:
    """Re-fetch and update a single entry. Returns True if updated."""
    entry_id = row["id"]
    url = row["canonical_url"] or row["url"]

    print(f"[enrich] #{entry_id} — {url}", flush=True)

    result = extract(url)

    if result.status == "failed" and not result.title:
        print(f"  ✗ fetch failed: {result.error}", flush=True)
        return False

    # Build updated fields — keep existing values if re-fetch gives nothing new
    title       = result.title       or row.get("title", "")
    description = result.description or row.get("description", "")
    content_text= result.content_text or row.get("content_text", "")
    canonical   = result.canonical_url or row.get("canonical_url", "") or url
    confidence  = result.extraction_confidence if result.extraction_confidence > 0 else (
        row.get("extraction_confidence") or 0.0
    )

    # Re-classify only if subject was 'unspecified'
    btype   = row.get("type") or classify_type(canonical, title, description)
    subject = row.get("subject", "unspecified")
    if subject == "unspecified":
        subject = classify_subject(canonical, title, description)

    # Merge tags (existing + new from fetch)
    existing_tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
    new_tags      = [t for t in (result.tags or []) if t not in existing_tags]
    tags_str      = ", ".join(existing_tags + new_tags)

    summary = build_summary(title, description, btype, subject)

    print(f"  title      : {title[:80]}", flush=True)
    print(f"  description: {description[:100]}", flush=True)
    print(f"  type/subj  : {btype}/{subject}", flush=True)
    print(f"  tags       : {tags_str}", flush=True)
    print(f"  confidence : {confidence:.0%}", flush=True)

    if dry_run:
        print("  [dry-run] skipping DB update", flush=True)
        return True

    with storage.conn() as c:
        c.execute(
            """UPDATE benchmarks
               SET title=?, description=?, summary=?, content_text=?,
                   canonical_url=?, type=?, subject=?, tags=?,
                   extraction_confidence=?
               WHERE id=?""",
            (title, description, summary, content_text,
             canonical, btype, subject, tags_str,
             confidence, entry_id),
        )
        c.commit()

    print(f"  ✓ updated #{entry_id}", flush=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-enrich benchmark entries")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", type=int, help="Enrich a specific entry by ID")
    group.add_argument("--empty", action="store_true",
                       help="Enrich all entries with empty title")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without saving")
    args = parser.parse_args()

    storage.init_db()

    if args.id:
        row = storage.get_by_id(args.id)
        if not row:
            sys.exit(f"Entry #{args.id} not found.")
        _enrich_entry(row, dry_run=args.dry_run)

    elif args.empty:
        with storage.conn() as c:
            rows = c.execute(
                "SELECT * FROM benchmarks WHERE (title IS NULL OR title='') ORDER BY id DESC"
            ).fetchall()
        rows = [dict(r) for r in rows]
        print(f"[enrich] {len(rows)} entries with empty title", flush=True)
        updated = sum(_enrich_entry(r, dry_run=args.dry_run) for r in rows)
        print(f"[enrich] done — {updated}/{len(rows)} updated", flush=True)


if __name__ == "__main__":
    main()
