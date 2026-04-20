# Contributing to AlManak

Thank you for considering a contribution! This guide will get you up and running quickly.

## Ways to contribute

- 🐛 **Bug reports** — [open an issue](.github/ISSUE_TEMPLATE/bug_report.md)
- 💡 **Feature requests** — [open an issue](.github/ISSUE_TEMPLATE/feature_request.md)
- 🔌 **New providers** — add a file under `src/open_benchmark/extractor/providers/custom/`
- 📖 **Documentation** — improve the README or add examples
- 🔧 **Code** — fix bugs, improve performance, new features

## Development setup

```bash
# Clone
git clone https://github.com/codeurali/almanak
cd almanak

# Install (editable + dev extras)
pip install -e ".[dev]"

# Run tests
pytest

# Run with local SQLite only (no Qdrant needed)
QDRANT_ENABLED=false BENCHMARK_DB_PATH=data/dev.db \
  python -m open_benchmark.ingest.api
```

## Adding a custom provider

Providers are auto-discovered from `src/open_benchmark/extractor/providers/`. See the template:

```
src/open_benchmark/extractor/providers/custom/example.py
```

A provider is a module with a `run(url, result)` function that enriches a `FetchResult` dict. It only runs when its `matches(url)` returns `True`.

## Coding style

- **Python 3.11+** — use modern syntax (`match`, `|` union types, etc.)
- **Max 400 lines per file** — split large files
- **No external formatters required** — but `ruff check` must pass (run `ruff check src/`)
- **Tests** — add a test for any new behaviour in `tests/`
- **No secrets in code** — all config via `.env`

## Pull request checklist

- [ ] Tests pass (`pytest`)
- [ ] Lint passes (`ruff check src/ bot/ scripts/`)
- [ ] No `.env` or `data/` files committed
- [ ] PR description explains the "why", not just the "what"

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
