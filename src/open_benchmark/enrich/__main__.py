"""
enrich/__main__.py — Re-enrichment CLI for existing DB entries.

Usage:
    python -m open_benchmark.enrich [OPTIONS]

Options:
    --filter-type TYPE      Only process entries with this type (e.g. repo, other, social)
    --filter-subject SUBJ   Only process entries with this subject (e.g. unspecified)
    --filter-status STATUS  Only process entries with this status (default: all)
    --ids ID,ID,...         Comma-separated entry IDs to process
    --limit N               Max entries to process (default: all)
    --reclassify-only       Only re-run classify (no HTTP fetch) — fast, offline
    --dry-run               Print changes without writing to DB
    --verbose               Print per-entry detail
    --workers N             Parallel HTTP workers (default: 4)

Exit codes: 0 = success, 1 = partial failures.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from open_benchmark.extractor.classify import classify_subject, classify_type
from open_benchmark.extractor.fetch import extract
from open_benchmark.storage import db as storage
from open_benchmark.storage.db import init_db


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Re-enrich Open Benchmark DB entries")
    p.add_argument("--filter-type", metavar="TYPE")
    p.add_argument("--filter-subject", metavar="SUBJ")
    p.add_argument("--filter-status", metavar="STATUS")
    p.add_argument("--ids", metavar="ID,...")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--reclassify-only", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    return p.parse_args()


def _select_entries(args: argparse.Namespace) -> list[dict]:
    all_entries = storage.list_all()

    if args.ids:
        wanted = {int(i.strip()) for i in args.ids.split(",") if i.strip()}
        all_entries = [e for e in all_entries if e["id"] in wanted]

    if args.filter_type:
        all_entries = [e for e in all_entries if e["type"] == args.filter_type]
    if args.filter_subject:
        all_entries = [e for e in all_entries if e["subject"] == args.filter_subject]
    if args.filter_status:
        all_entries = [e for e in all_entries if e["status"] == args.filter_status]

    if args.limit:
        all_entries = all_entries[: args.limit]

    return all_entries


def _process_entry(entry: dict, reclassify_only: bool) -> dict:
    """Return a dict of fields to update (empty dict = no change needed)."""
    url = entry.get("canonical_url") or entry.get("url") or ""
    if not url:
        return {}

    if reclassify_only:
        title = entry.get("title", "")
        description = entry.get("description", "")
        new_type = classify_type(url, title, description)
        new_subject = classify_subject(url, title, description)
        updates: dict = {}
        if new_type != entry.get("type"):
            updates["btype"] = new_type
        if new_subject != entry.get("subject"):
            updates["subject"] = new_subject
        return updates

    # Full HTTP fetch + re-classify
    result = extract(url)
    if result.status in ("failed", "timeout"):
        return {}

    new_type = classify_type(result.canonical_url, result.title, result.description)
    new_subject = classify_subject(result.canonical_url, result.title, result.description)

    # Merge tags: keep existing user tags + add auto ones
    existing_tags = [t.strip() for t in (entry.get("tags") or "").split(",") if t.strip() and t.strip() != "unspecified"]
    new_auto_tags = result.tags
    merged = list(dict.fromkeys(existing_tags + new_auto_tags))  # dedup, preserve order
    tags_str = ", ".join(merged)

    updates = {}
    if result.title and not entry.get("title"):
        updates["title"] = result.title
    if result.description and not entry.get("description"):
        updates["description"] = result.description
    if result.content_text:
        updates["content_text"] = result.content_text
    if result.canonical_url and result.canonical_url != entry.get("canonical_url"):
        updates["canonical_url"] = result.canonical_url
    if tags_str and tags_str != entry.get("tags", ""):
        updates["tags"] = tags_str
    if result.raw_text:
        updates["raw_text"] = result.raw_text
    if new_type != entry.get("type"):
        updates["btype"] = new_type
    if new_subject != entry.get("subject"):
        updates["subject"] = new_subject
    if result.extraction_confidence > (entry.get("extraction_confidence") or 0):
        updates["extraction_confidence"] = result.extraction_confidence

    return updates


def main() -> int:
    args = _parse_args()
    init_db()

    entries = _select_entries(args)
    if not entries:
        print("No entries match the filter criteria.")
        return 0

    mode = "reclassify-only" if args.reclassify_only else "full fetch"
    print(f"Processing {len(entries)} entries ({mode}){' [DRY RUN]' if args.dry_run else ''}")

    updated = 0
    skipped = 0
    errors = 0
    start = time.time()

    def _worker(entry: dict) -> tuple[int, dict, str | None]:
        try:
            changes = _process_entry(entry, args.reclassify_only)
            return entry["id"], changes, None
        except Exception as exc:
            return entry["id"], {}, str(exc)

    workers = 1 if args.reclassify_only else args.workers

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_worker, e): e for e in entries}
        for fut in as_completed(futures):
            entry = futures[fut]
            eid, changes, err = fut.result()

            if err:
                errors += 1
                if args.verbose:
                    print(f"  [{eid}] ERROR: {err}")
                continue

            if not changes:
                skipped += 1
                if args.verbose:
                    print(f"  [{eid}] no changes")
                continue

            if args.verbose:
                print(f"  [{eid}] {entry.get('url', '')[:60]} → {list(changes.keys())}")

            if not args.dry_run:
                storage.update_entry(eid, **changes)
            updated += 1

    elapsed = time.time() - start
    print(
        f"\nDone in {elapsed:.1f}s — "
        f"updated: {updated}, skipped: {skipped}, errors: {errors}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
