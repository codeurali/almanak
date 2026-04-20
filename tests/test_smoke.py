"""Smoke tests — verify the package imports and core utilities work."""

import os

import pytest

# Ensure no real DB/Qdrant is used during tests
os.environ.setdefault("BENCHMARK_DB_PATH", ":memory:")
os.environ.setdefault("QDRANT_ENABLED", "false")
os.environ.setdefault("MCP_API_KEY", "test-key")
os.environ.setdefault("INGEST_API_KEY", "test-key")


def test_config_loads():
    from open_benchmark.config import settings

    assert settings.mcp_port > 0
    assert settings.ingest_port > 0


def test_classify_type_repo():
    from open_benchmark.extractor.classify import classify_type

    assert classify_type("https://github.com/microsoft/vscode", "", "") == "repo"


def test_classify_type_video():
    from open_benchmark.extractor.classify import classify_type

    assert classify_type("https://www.youtube.com/watch?v=abc", "", "") == "video"


def test_classify_type_article_fallback():
    from open_benchmark.extractor.classify import classify_type

    result = classify_type("https://example.com/blog/post", "Some blog post", "")
    assert result in ("article", "other")


def test_classify_subject_ai():
    from open_benchmark.extractor.classify import classify_subject

    assert classify_subject("LLM fine-tuning benchmark", "", "") == "ai"


def test_classify_subject_devtools():
    from open_benchmark.extractor.classify import classify_subject

    result = classify_subject("pre-commit hooks formatter", "", "")
    assert result == "dev-tools"


def test_ingest_app_starts():
    """FastAPI app can be imported and has the expected routes."""
    from open_benchmark.ingest.api import app

    routes = {r.path for r in app.routes}
    assert "/ingest/links" in routes
    assert "/bookmarklet" in routes
    assert "/add" in routes
    assert "/health" in routes
