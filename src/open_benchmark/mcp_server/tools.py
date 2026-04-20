"""
mcp_server/tools.py — Pure tool implementations (no FastMCP decorators here).

These functions are imported by server.py and registered as MCP tools.
Separating business logic from the FastMCP wiring allows unit testing without
spinning up the MCP runtime.
"""

from __future__ import annotations

from typing import Any

from open_benchmark.graph import relations as graph
from open_benchmark.indexer import qdrant_index as qdrant
from open_benchmark.storage import db as storage


def search_benchmarks(
    query: str,
    top_k: int = 8,
    type: str = "",
    subject: str = "",
) -> list[dict[str, Any]]:
    """
    Semantic search over the curated benchmarks knowledge base.

    Tries Qdrant first; falls back to SQLite FTS5 if Qdrant is unavailable.

    Args:
        query:   Natural-language query (e.g. "video generation AI tools")
        top_k:   Max results to return (default 8)
        type:    Optional filter — repo, article, video, social, doc, research, tool, other
        subject: Optional filter — ai, benchmark, power-platform, azure, dev-tools, etc.
    """
    results = qdrant.search(query, top_k=top_k, filter_type=type, filter_subject=subject)
    if results:
        return results

    # Fallback: SQLite FTS5
    rows = storage.search_fts(query, limit=top_k)
    filtered = [
        r for r in rows
        if (not type or r.get("type") == type)
        and (not subject or r.get("subject") == subject)
    ]
    return [
        {
            "score":       None,
            "id":          r["id"],
            "title":       r.get("title", ""),
            "url":         r.get("url", ""),
            "summary":     r.get("summary", ""),
            "description": r.get("description", ""),
            "type":        r.get("type", ""),
            "subject":     r.get("subject", ""),
            "tags":        r.get("tags", ""),
            "notes":       r.get("notes", ""),
            "received_at": r.get("received_at", ""),
        }
        for r in filtered[:top_k]
    ]


def list_benchmarks_stats() -> dict[str, Any]:
    """Return total count and breakdown by type and subject."""
    return storage.stats()


def get_benchmark(id: int) -> dict[str, Any] | None:
    """Retrieve one benchmark entry by its numeric ID."""
    return storage.get_by_id(id)


def get_related_benchmarks(
    id: int,
    relation: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Return entries related to the given entry_id.

    Args:
        id:       Benchmark entry ID.
        relation: Filter by relation type: same_tag, same_domain,
                  cosine_similar, duplicate_candidate. Leave empty for all.
        limit:    Max results (default 10).
    """
    return graph.get_related(id, relation=relation or None, limit=limit)


def list_subjects() -> list[str]:
    """Return all distinct subjects present in the database."""
    import sqlite3
    from open_benchmark.storage.db import conn

    with conn() as c:
        rows = c.execute(
            "SELECT DISTINCT subject FROM benchmarks WHERE subject != '' ORDER BY subject"
        ).fetchall()
    return [r["subject"] for r in rows]


def list_types() -> list[str]:
    """Return all distinct types present in the database."""
    from open_benchmark.storage.db import conn

    with conn() as c:
        rows = c.execute(
            "SELECT DISTINCT type FROM benchmarks WHERE type != '' ORDER BY type"
        ).fetchall()
    return [r["type"] for r in rows]


def list_tags(limit: int = 50) -> list[dict[str, Any]]:
    """
    Return the most common tags with occurrence counts.

    Args:
        limit: Max number of tags to return (default 50).
    """
    from open_benchmark.storage.db import conn

    with conn() as c:
        rows = c.execute(
            "SELECT tags FROM benchmarks WHERE tags != '' AND tags IS NOT NULL"
        ).fetchall()

    tag_counts: dict[str, int] = {}
    for row in rows:
        for tag in row["tags"].split(","):
            tag = tag.strip().lower()
            if tag:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"tag": t, "count": c} for t, c in sorted_tags[:limit]]


def explain_relationships(id: int) -> dict[str, Any]:
    """
    Return a human-readable explanation of all known relationships for an entry.

    Shows counts and examples per relation type.
    """
    entry = storage.get_by_id(id)
    if not entry:
        return {"error": f"Entry {id} not found"}

    all_related = graph.get_related(id, limit=50)
    by_type: dict[str, list[dict]] = {}
    for rel in all_related:
        rel_type = rel.get("relation", "unknown")
        by_type.setdefault(rel_type, []).append(
            {
                "id":    rel.get("target_id") if rel.get("source_id") == id else rel.get("source_id"),
                "title": rel.get("title", ""),
                "url":   rel.get("url", ""),
                "score": rel.get("score"),
                "evidence": rel.get("evidence", ""),
            }
        )

    return {
        "entry": {
            "id":      entry["id"],
            "title":   entry.get("title", ""),
            "url":     entry.get("url", ""),
            "type":    entry.get("type", ""),
            "subject": entry.get("subject", ""),
            "tags":    entry.get("tags", ""),
        },
        "relationships": {
            rel_type: {"count": len(items), "examples": items[:5]}
            for rel_type, items in by_type.items()
        },
        "total_relations": len(all_related),
    }
