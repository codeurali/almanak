"""
indexer/qdrant_index.py — Index SQLite benchmarks into Qdrant via FastEmbed.

Public API:
  index(since=None)    — full or incremental upsert to Qdrant
  search(query, ...)   — semantic search (returns list of dicts with score)
  similar(entry_id, k) — find k similar entries by ID
"""

from __future__ import annotations

import sqlite3
from typing import Any

from open_benchmark.config import settings
from open_benchmark.storage import db as storage

BATCH_SIZE = 32

# Lazy singletons
_embedder = None
_qdrant = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding  # type: ignore
        _embedder = TextEmbedding(model_name=settings.embed_model)
    return _embedder


def _get_qdrant():
    global _qdrant
    if _qdrant is None:
        from qdrant_client import QdrantClient  # type: ignore
        _qdrant = QdrantClient(url=settings.qdrant_url)
    return _qdrant


def _build_text(row: sqlite3.Row | dict) -> str:
    """Combine fields into a single string for embedding."""
    if isinstance(row, dict):
        get = row.get
    else:
        get = lambda k, d="": row[k] if row[k] is not None else d  # noqa: E731

    parts = [
        get("title", ""),
        get("summary", ""),
        get("description", ""),
        get("content_text", ""),
        get("tags", ""),
        get("notes", ""),
        get("type", ""),
        get("subject", ""),
        get("url", ""),
    ]
    return " | ".join(p.strip() for p in parts if p.strip())


def _ensure_collection(client, vector_size: int) -> None:
    from qdrant_client.models import Distance, VectorParams  # type: ignore

    existing = {col.name for col in client.get_collections().collections}
    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def index(since: str | None = None, db_path: str | None = None) -> int:
    """
    Upsert benchmarks into Qdrant.

    Args:
        since: ISO timestamp; only process rows with received_at >= since.
        db_path: override for SQLite path.

    Returns:
        Number of rows indexed.
    """
    if not settings.qdrant_enabled:
        return 0

    from qdrant_client.models import PointStruct  # type: ignore

    with storage.conn(db_path) as c:
        if since:
            rows = c.execute(
                "SELECT * FROM benchmarks WHERE received_at >= ? ORDER BY id",
                (since,),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM benchmarks ORDER BY id").fetchall()

    if not rows:
        return 0

    texts = [_build_text(r) for r in rows]
    embedder = _get_embedder()
    vectors = list(embedder.embed(texts))
    vec_size = len(vectors[0])

    client = _get_qdrant()
    _ensure_collection(client, vec_size)

    points = [
        PointStruct(
            id=int(rows[i]["id"]),
            vector=vectors[i].tolist(),
            payload={
                "id":          int(rows[i]["id"]),
                "received_at": rows[i]["received_at"] or "",
                "url":         rows[i]["url"] or "",
                "title":       rows[i]["title"] or "",
                "summary":     rows[i]["summary"] or "",
                "description": rows[i]["description"] or "",
                "type":        rows[i]["type"] or "",
                "subject":     rows[i]["subject"] or "",
                "tags":        rows[i]["tags"] or "",
                "notes":       rows[i]["notes"] or "",
                "status":      rows[i]["status"] or "",
            },
        )
        for i in range(len(rows))
    ]

    for start in range(0, len(points), BATCH_SIZE):
        batch = points[start: start + BATCH_SIZE]
        client.upsert(collection_name=settings.qdrant_collection, points=batch)

    return len(rows)


def search(
    query: str,
    top_k: int = 8,
    filter_type: str = "",
    filter_subject: str = "",
) -> list[dict[str, Any]]:
    """
    Semantic search over Qdrant.  Falls back to empty list if Qdrant is unavailable.
    """
    if not settings.qdrant_enabled:
        return []

    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue  # type: ignore

        embedder = _get_embedder()
        vec = list(embedder.embed([query]))[0].tolist()

        conditions = []
        if filter_type:
            conditions.append(FieldCondition(key="type", match=MatchValue(value=filter_type)))
        if filter_subject:
            conditions.append(
                FieldCondition(key="subject", match=MatchValue(value=filter_subject))
            )
        qdrant_filter = Filter(must=conditions) if conditions else None

        client = _get_qdrant()
        hits = client.query_points(
            collection_name=settings.qdrant_collection,
            query=vec,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        ).points

        return [
            {
                "score":       round(h.score, 3),
                "id":          h.payload.get("id"),
                "title":       h.payload.get("title", ""),
                "url":         h.payload.get("url", ""),
                "summary":     h.payload.get("summary", ""),
                "description": h.payload.get("description", ""),
                "type":        h.payload.get("type", ""),
                "subject":     h.payload.get("subject", ""),
                "tags":        h.payload.get("tags", ""),
                "notes":       h.payload.get("notes", ""),
                "received_at": h.payload.get("received_at", ""),
            }
            for h in hits
        ]
    except Exception:
        return []


def similar(entry_id: int, top_k: int = 5) -> list[dict[str, Any]]:
    """
    Find entries similar to entry_id using Qdrant's recommend/query.
    Returns list of dicts (same schema as search()).
    """
    if not settings.qdrant_enabled:
        return []

    try:
        client = _get_qdrant()
        hits = client.query_points(
            collection_name=settings.qdrant_collection,
            query=entry_id,
            limit=top_k + 1,  # +1 to exclude self
            with_payload=True,
        ).points
        return [
            {
                "score":       round(h.score, 3),
                "id":          h.payload.get("id"),
                "title":       h.payload.get("title", ""),
                "url":         h.payload.get("url", ""),
                "summary":     h.payload.get("summary", ""),
                "type":        h.payload.get("type", ""),
                "subject":     h.payload.get("subject", ""),
                "tags":        h.payload.get("tags", ""),
                "received_at": h.payload.get("received_at", ""),
            }
            for h in hits
            if h.payload.get("id") != entry_id
        ][:top_k]
    except Exception:
        return []
