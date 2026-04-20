#!/usr/bin/env python3
"""
scripts/index.py — CLI for indexing benchmarks into Qdrant.

Usage:
  python scripts/index.py               # full reindex
  python scripts/index.py --since 2026-04-01  # incremental
  python scripts/index.py --query "video AI"  # test search
  python scripts/index.py --graph       # rebuild knowledge graph relations
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from open_benchmark.storage.db import init_db
from open_benchmark.indexer import qdrant_index as qdrant
from open_benchmark.graph import relations as graph


def main():
    parser = argparse.ArgumentParser(description="Open Benchmark indexer CLI")
    parser.add_argument("--since", help="ISO date (e.g. 2026-04-01) for incremental index")
    parser.add_argument("--query", help="Test semantic search query")
    parser.add_argument("--top-k", type=int, default=8, help="Results for --query")
    parser.add_argument("--graph", action="store_true", help="Rebuild graph relations")
    args = parser.parse_args()

    init_db()

    if args.query:
        results = qdrant.search(args.query, top_k=args.top_k)
        if not results:
            print("No results (is Qdrant running and indexed?)")
            return
        for r in results:
            print(f"[{r.get('score', '?'):.3f}] #{r['id']} {r['title'][:60]}  {r['url'][:70]}")
        return

    if args.graph:
        print("Rebuilding graph relations…")
        counts = graph.rebuild_all()
        print(f"Done: {counts}")
        return

    print(f"Indexing{' since ' + args.since if args.since else ' (full)'}…")
    n = qdrant.index(since=args.since)
    print(f"Indexed {n} entries.")


if __name__ == "__main__":
    main()
