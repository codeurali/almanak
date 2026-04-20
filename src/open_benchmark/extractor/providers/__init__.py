"""
extractor/providers — Provider registry and auto-discovery.

Built-in providers:  extractor/providers/_*.py
User providers:      extractor/providers/custom/*.py  (auto-loaded, never gitignored)

Each provider module must expose two callables:
    matches(url: str) -> bool
    enrich(url: str, result: ExtractionResult) -> None

Providers are discovered once at import time. Errors in individual providers
are logged and silently skipped — a bad plugin never crashes the pipeline.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from open_benchmark.extractor.fetch import ExtractionResult

log = logging.getLogger(__name__)

_PROVIDERS_DIR = Path(__file__).parent


def _load_module(path: Path) -> ModuleType | None:
    """Import a Python file as a module; return None on any error."""
    try:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[arg-type]
        return mod
    except Exception as exc:
        log.warning("AlManak: provider %s failed to load: %s", path.name, exc)
        return None


def _discover() -> list[ModuleType]:
    modules: list[ModuleType] = []

    # Built-in providers: _github.py, _twitter.py, _hn.py, etc. (skip __init__.py itself)
    for path in sorted(_PROVIDERS_DIR.glob("_*.py")):
        if path.name == "__init__.py":
            continue
        mod = _load_module(path)
        if mod is not None:
            modules.append(mod)

    # User custom providers: custom/*.py (skip files starting with _)
    custom_dir = _PROVIDERS_DIR / "custom"
    if custom_dir.is_dir():
        for path in sorted(custom_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            mod = _load_module(path)
            if mod is not None:
                modules.append(mod)

    log.debug("AlManak: loaded %d provider(s)", len(modules))
    return modules


_PROVIDERS: list[ModuleType] = _discover()


def run_providers(url: str, result: "ExtractionResult") -> None:
    """Run all matching providers. Mutates result in-place. Never raises."""
    for mod in _PROVIDERS:
        try:
            matches_fn = getattr(mod, "matches", None)
            enrich_fn = getattr(mod, "enrich", None)
            if callable(matches_fn) and callable(enrich_fn) and matches_fn(url):
                enrich_fn(url, result)
        except Exception as exc:
            name = getattr(mod, "__name__", getattr(mod, "__file__", "?"))
            log.warning("AlManak: provider %s error: %s", name, exc)
