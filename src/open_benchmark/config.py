"""
config.py — central typed configuration via pydantic-settings.

All settings are read from environment variables (and .env file via dotenv).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the project root (two levels up from this file: src/open_benchmark/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Storage ───────────────────────────────────────────────────────────────
    db_path: Path = Field(
        default=_PROJECT_ROOT / "data" / "benchmarks.db",
        validation_alias="BENCHMARK_DB_PATH",
    )
    csv_live_path: Path = Field(
        default=_PROJECT_ROOT / "data" / "benchmarks.csv",
        validation_alias="BENCHMARK_CSV_PATH",
    )

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_url: str = Field(default="http://localhost:6333", validation_alias="QDRANT_URL")
    qdrant_collection: str = Field(default="benchmarks", validation_alias="QDRANT_COLLECTION")
    embed_model: str = Field(
        default="BAAI/bge-small-en-v1.5", validation_alias="EMBED_MODEL"
    )
    qdrant_enabled: bool = Field(default=True, validation_alias="QDRANT_ENABLED")

    # ── MCP HTTP server ───────────────────────────────────────────────────────
    mcp_host: str = Field(default="127.0.0.1", validation_alias="MCP_HOST")
    mcp_port: int = Field(default=8765, validation_alias="MCP_PORT")
    mcp_api_key: str = Field(default="", validation_alias="MCP_API_KEY")

    # ── Ingest REST API ───────────────────────────────────────────────────────
    ingest_host: str = Field(default="127.0.0.1", validation_alias="INGEST_HOST")
    ingest_port: int = Field(default=8766, validation_alias="INGEST_PORT")
    ingest_api_key: str = Field(default="", validation_alias="INGEST_API_KEY")
    # Public-facing base URL (e.g. https://mcp.example.com or Tailscale URL).
    # When set, bookmarklet and /add links use this URL instead of the detected one.
    ingest_public_url: str = Field(default="", validation_alias="INGEST_PUBLIC_URL")

    # ── Telegram bot (optional) ───────────────────────────────────────────────
    telegram_bot_token: str = Field(default="", validation_alias="BENCHMARK_BOT_TOKEN")
    telegram_allowed_uid: int = Field(default=0, validation_alias="ALLOWED_USER_ID")

    # ── Fetcher ───────────────────────────────────────────────────────────────
    fetch_timeout: int = Field(default=10, validation_alias="FETCH_TIMEOUT")
    fetch_user_agent: str = Field(
        default="Mozilla/5.0 (AlManak/1.0; +https://github.com/almanak-app/almanak)",
        validation_alias="FETCH_USER_AGENT",
    )

    # ── Feature flags ─────────────────────────────────────────────────────────
    feature_trafilatura: bool = Field(default=True, validation_alias="FEATURE_TRAFILATURA")
    feature_github_extractor: bool = Field(
        default=True, validation_alias="FEATURE_GITHUB_EXTRACTOR"
    )
    feature_twitter_extract: bool = Field(
        default=True, validation_alias="FEATURE_TWITTER_EXTRACT"
    )
    feature_yt_extract: bool = Field(default=True, validation_alias="FEATURE_YT_EXTRACT")
    feature_hn_context: bool = Field(default=True, validation_alias="FEATURE_HN_CONTEXT")
    hn_min_points: int = Field(default=10, validation_alias="HN_MIN_POINTS")
    feature_graph: bool = Field(default=True, validation_alias="FEATURE_GRAPH")

    # ── Graph ─────────────────────────────────────────────────────────────────
    graph_similarity_threshold: float = Field(
        default=0.80, validation_alias="GRAPH_SIMILARITY_THRESHOLD"
    )
    graph_duplicate_threshold: float = Field(
        default=0.92, validation_alias="GRAPH_DUPLICATE_THRESHOLD"
    )


settings = Settings()
