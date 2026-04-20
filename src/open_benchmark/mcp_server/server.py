"""
mcp_server/server.py — FastMCP server supporting both stdio and HTTP transports.

Entry points:
  python -m open_benchmark.mcp_server.server              → stdio (for Hermes)
  python -m open_benchmark.mcp_server.server --http       → HTTP on MCP_HOST:MCP_PORT
  python -m open_benchmark.mcp_server.server --http --no-auth  → HTTP without auth (dev)

HTTP endpoint: http://<MCP_HOST>:<MCP_PORT>/mcp
Auth header:   Authorization: Bearer <MCP_API_KEY>
"""

from __future__ import annotations

import argparse
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from open_benchmark.config import settings
from open_benchmark.mcp_server import tools as _tools
from open_benchmark.storage.db import init_db

# ── FastMCP instance ───────────────────────────────────────────────────────────

mcp = FastMCP(
    "almanak",
    # Disable DNS-rebinding protection: Bearer auth already secures the endpoint,
    # and the server is accessed via Tailscale IP / remote hosts.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    instructions=(
        "Curated knowledge base of tools, repos, articles, and resources. "
        "Use search_benchmarks for semantic search, get_benchmark for a specific entry, "
        "get_related_benchmarks for similar/related entries, "
        "and list_benchmarks_stats for overview counts."
    ),
)

# ── Tool registrations ─────────────────────────────────────────────────────────


@mcp.tool()
def search_benchmarks(
    query: str,
    top_k: int = 8,
    type: str = "",
    subject: str = "",
) -> list[dict]:
    """
    Semantic search over the curated benchmarks knowledge base.

    Falls back to FTS5 full-text search if vector index is unavailable.

    Args:
        query:   Natural-language query (e.g. "video generation AI tools")
        top_k:   Max results to return (default 8)
        type:    Optional filter — repo, article, video, social, doc, research, tool, other
        subject: Optional filter — ai, benchmark, power-platform, azure, dev-tools, etc.
    """
    return _tools.search_benchmarks(query, top_k=top_k, type=type, subject=subject)


@mcp.tool()
def list_benchmarks_stats() -> dict:
    """Return total count and breakdown by type and subject."""
    return _tools.list_benchmarks_stats()


@mcp.tool()
def get_benchmark(id: int) -> dict | None:
    """
    Retrieve one benchmark entry by its numeric ID.

    Returns full entry (title, url, summary, description, tags, notes) or None.
    """
    return _tools.get_benchmark(id)


@mcp.tool()
def get_related_benchmarks(id: int, relation: str = "", limit: int = 10) -> list[dict]:
    """
    Return entries related to the given entry_id.

    Args:
        id:       Benchmark entry ID.
        relation: Filter by: same_tag, same_domain, cosine_similar,
                  duplicate_candidate. Leave empty for all.
        limit:    Max results (default 10).
    """
    return _tools.get_related_benchmarks(id, relation=relation, limit=limit)


@mcp.tool()
def list_subjects() -> list[str]:
    """Return all distinct subjects present in the database."""
    return _tools.list_subjects()


@mcp.tool()
def list_types() -> list[str]:
    """Return all distinct entry types present in the database."""
    return _tools.list_types()


@mcp.tool()
def list_tags(limit: int = 50) -> list[dict]:
    """Return the most common tags with occurrence counts."""
    return _tools.list_tags(limit=limit)


@mcp.tool()
def explain_relationships(id: int) -> dict:
    """
    Return a human-readable explanation of all known relationships for an entry.
    Shows counts and examples per relation type (same_tag, same_domain, etc.).
    """
    return _tools.explain_relationships(id)


# ── HTTP auth middleware ───────────────────────────────────────────────────────


def _make_secured_app(api_key: str):
    """
    Wrap the FastMCP ASGI app with a pure-ASGI Bearer token middleware.

    Pure ASGI (not Starlette BaseHTTPMiddleware) so that the inner app's
    lifespan scope is forwarded correctly — avoids the "Task group not
    initialized" error that occurs when wrapping with a new Starlette app.
    """
    mcp_app = mcp.streamable_http_app()

    class BearerAuthMiddleware:
        def __init__(self, app):
            self.app = app
            self._key = api_key

        async def __call__(self, scope, receive, send):
            # Pass lifespan and websocket scopes straight through
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            auth = headers.get(b"authorization", b"").decode()
            if not (auth.startswith("Bearer ") and auth[7:] == self._key):
                async def _send_401(send):
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [[b"content-type", b"application/json"]]})
                    await send({"type": "http.response.body",
                                "body": b'{"error":"Unauthorized"}', "more_body": False})
                await _send_401(send)
                return

            await self.app(scope, receive, send)

    return BearerAuthMiddleware(mcp_app)


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    init_db()

    parser = argparse.ArgumentParser(description="AlManak MCP server")
    parser.add_argument("--http",    action="store_true", help="Run HTTP transport")
    parser.add_argument("--no-auth", action="store_true", help="Disable Bearer auth (dev only)")
    parser.add_argument("--host",    default=settings.mcp_host)
    parser.add_argument("--port",    type=int, default=settings.mcp_port)
    args = parser.parse_args()

    if args.http:
        import uvicorn  # type: ignore

        api_key = settings.mcp_api_key
        if api_key and not args.no_auth:
            app = _make_secured_app(api_key)
            print(
                f"[mcp] HTTP server on http://{args.host}:{args.port}/mcp  (auth: Bearer)",
                file=sys.stderr,
            )
        else:
            app = mcp.streamable_http_app()
            if not api_key:
                print(
                    "[mcp] WARNING: MCP_API_KEY not set — running without authentication",
                    file=sys.stderr,
                )
            print(
                f"[mcp] HTTP server on http://{args.host}:{args.port}/mcp  (no auth)",
                file=sys.stderr,
            )
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    else:
        print("[mcp] stdio transport", file=sys.stderr)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
