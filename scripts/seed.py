#!/usr/bin/env python3
"""
scripts/seed.py — Load seed data from a CSV file into the database.

The CSV must have at least a 'url' column. Other columns are optional.
Used to migrate from the old benchmark-bot database or load example data.

Usage:
  python scripts/seed.py data/seed_examples.csv
  python scripts/seed.py /path/to/benchmarks.csv --dry-run
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from open_benchmark.storage.db import init_db, insert, get_by_fingerprint, url_fingerprint


def main():
    parser = argparse.ArgumentParser(description="Seed Open Benchmark database from CSV")
    parser.add_argument("csv_path", help="Path to CSV file")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        sys.exit(f"File not found: {args.csv_path}")

    init_db()

    added = skipped = errors = 0
    with open(args.csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = (row.get("url") or "").strip()
            if not url:
                errors += 1
                continue

            fingerprint = url_fingerprint(url)
            if get_by_fingerprint(fingerprint):
                skipped += 1
                continue

            if not args.dry_run:
                try:
                    insert(
                        url=url,
                        canonical_url=row.get("canonical_url") or url,
                        title=row.get("title", ""),
                        description=row.get("description", ""),
                        content_text=row.get("content_text", ""),
                        btype=row.get("type", "other"),
                        subject=row.get("subject", "unspecified"),
                        tags=row.get("tags", ""),
                        notes=row.get("notes", ""),
                        raw_text=row.get("raw_text", ""),
                    )
                    added += 1
                except Exception as exc:
                    print(f"Error inserting {url}: {exc}", file=sys.stderr)
                    errors += 1
            else:
                added += 1  # count as would-add in dry run

    mode = "DRY RUN — " if args.dry_run else ""
    print(f"{mode}Added: {added}, Skipped (dup): {skipped}, Errors: {errors}")


if __name__ == "__main__":
    main()
