"""
graph/relations.py — Lightweight knowledge graph derived from metadata.

Relations stored in SQLite `benchmark_relations` table.
No LLM dependency — all relations are deterministically derived.

Relation types:
  same_tag           — entries sharing one or more tags
  same_domain        — entries from the same host domain
  cosine_similar     — Qdrant similarity score >= threshold
  duplicate_candidate — Qdrant similarity score >= duplicate threshold

Public API:
  rebuild_all()        — clear and rebuild all relations
  build_tag_relations()
  build_domain_relations()
  build_similarity_relations()
  get_related(entry_id, relation?)  — query relations for an entry
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from open_benchmark.config import settings
from open_benchmark.storage import db as storage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upsert_relation(
    c,
    source_id: int,
    target_id: int,
    relation: str,
    score: float,
    evidence: str,
) -> None:
    c.execute(
        """INSERT INTO benchmark_relations (source_id, target_id, relation, score, evidence, created_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(source_id, target_id, relation) DO UPDATE SET
               score=excluded.score,
               evidence=excluded.evidence,
               created_at=excluded.created_at""",
        (source_id, target_id, relation, score, evidence, _now()),
    )


def build_tag_relations(db_path: str | None = None) -> int:
    """
    Create same_tag edges between entries sharing at least one non-trivial tag.
    Returns number of edges added/updated.
    """
    with storage.conn(db_path) as c:
        rows = c.execute(
            "SELECT id, tags FROM benchmarks WHERE tags != '' AND tags IS NOT NULL"
        ).fetchall()

    # Build inverted index: tag → [ids]
    tag_index: dict[str, list[int]] = {}
    for row in rows:
        tags = [t.strip().lower() for t in row["tags"].split(",") if t.strip()]
        for tag in tags:
            if len(tag) > 2:  # skip very short/trivial tags
                tag_index.setdefault(tag, []).append(row["id"])

    count = 0
    with storage.conn(db_path) as c:
        for tag, ids in tag_index.items():
            if len(ids) < 2:
                continue
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    src, tgt = min(ids[i], ids[j]), max(ids[i], ids[j])
                    _upsert_relation(c, src, tgt, "same_tag", 1.0, f"tag:{tag}")
                    count += 1
        c.commit()
    return count


def build_domain_relations(db_path: str | None = None) -> int:
    """Create same_domain edges between entries sharing the same registered domain."""
    with storage.conn(db_path) as c:
        rows = c.execute(
            "SELECT id, url FROM benchmarks WHERE url != '' AND url IS NOT NULL"
        ).fetchall()

    # Build inverted index: domain → [ids]
    domain_index: dict[str, list[int]] = {}
    for row in rows:
        try:
            domain = urlparse(row["url"]).netloc.lstrip("www.")
        except Exception:
            continue
        if domain:
            domain_index.setdefault(domain, []).append(row["id"])

    count = 0
    with storage.conn(db_path) as c:
        for domain, ids in domain_index.items():
            if len(ids) < 2:
                continue
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    src, tgt = min(ids[i], ids[j]), max(ids[i], ids[j])
                    _upsert_relation(
                        c, src, tgt, "same_domain", 1.0, f"domain:{domain}"
                    )
                    count += 1
        c.commit()
    return count


def build_similarity_relations(db_path: str | None = None) -> int:
    """
    Build cosine_similar and duplicate_candidate edges using Qdrant.

    Iterates over all entries and queries Qdrant for top-5 neighbours,
    then stores edges above the configured thresholds.
    """
    if not settings.qdrant_enabled or not settings.feature_graph:
        return 0

    try:
        from qdrant_client import QdrantClient  # type: ignore

        client = QdrantClient(url=settings.qdrant_url)
        threshold_similar = settings.graph_similarity_threshold
        threshold_dup = settings.graph_duplicate_threshold

        with storage.conn(db_path) as c:
            ids = [r["id"] for r in c.execute("SELECT id FROM benchmarks").fetchall()]

        count = 0
        with storage.conn(db_path) as c:
            for entry_id in ids:
                try:
                    hits = client.query_points(
                        collection_name=settings.qdrant_collection,
                        query=int(entry_id),
                        limit=6,
                        with_payload=False,
                    ).points
                except Exception:
                    continue

                for hit in hits:
                    if hit.id == entry_id:
                        continue
                    score = hit.score
                    if score < threshold_similar:
                        continue
                    src, tgt = min(entry_id, int(hit.id)), max(entry_id, int(hit.id))
                    relation = (
                        "duplicate_candidate" if score >= threshold_dup else "cosine_similar"
                    )
                    _upsert_relation(
                        c, src, tgt, relation, round(score, 4), f"cosine:{score:.4f}"
                    )
                    count += 1
            c.commit()
        return count
    except Exception:
        return 0


def rebuild_all(db_path: str | None = None) -> dict[str, int]:
    """Clear and rebuild all graph relations. Returns counts per relation type."""
    with storage.conn(db_path) as c:
        c.execute("DELETE FROM benchmark_relations")
        c.commit()

    tag_count = build_tag_relations(db_path)
    domain_count = build_domain_relations(db_path)
    sim_count = build_similarity_relations(db_path)

    return {
        "same_tag": tag_count,
        "same_domain": domain_count,
        "similarity": sim_count,
        "total": tag_count + domain_count + sim_count,
    }


def get_related(
    entry_id: int,
    relation: str | None = None,
    limit: int = 10,
    db_path: str | None = None,
) -> list[dict]:
    """
    Return entries related to entry_id.

    Args:
        relation: filter by relation type (same_tag, same_domain, cosine_similar,
                  duplicate_candidate). None returns all.
        limit:    max results.
    """
    with storage.conn(db_path) as c:
        if relation:
            rows = c.execute(
                """SELECT r.*, b.title, b.url, b.type, b.subject, b.tags
                   FROM benchmark_relations r
                   JOIN benchmarks b ON (
                       CASE WHEN r.source_id = ? THEN r.target_id ELSE r.source_id END = b.id
                   )
                   WHERE (r.source_id = ? OR r.target_id = ?) AND r.relation = ?
                   ORDER BY r.score DESC LIMIT ?""",
                (entry_id, entry_id, entry_id, relation, limit),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT r.*, b.title, b.url, b.type, b.subject, b.tags
                   FROM benchmark_relations r
                   JOIN benchmarks b ON (
                       CASE WHEN r.source_id = ? THEN r.target_id ELSE r.source_id END = b.id
                   )
                   WHERE r.source_id = ? OR r.target_id = ?
                   ORDER BY r.score DESC LIMIT ?""",
                (entry_id, entry_id, entry_id, limit),
            ).fetchall()

    return [dict(r) for r in rows]
