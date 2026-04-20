<div align="center">

# AlManak

**Self-hosted AI memory for the links that matter.**

[![CI](https://github.com/codeurali/almanak/actions/workflows/ci.yml/badge.svg)](https://github.com/codeurali/almanak/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)](docker-compose.yml)
[![MCP](https://img.shields.io/badge/MCP-compatible-blueviolet)](https://modelcontextprotocol.io/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](CONTRIBUTING.md)

Send a link → get AI-searchable memory. Works from Telegram, browser bookmarklet, or any HTTP client.
Everything runs on a **$5 VPS** you control. No subscription. No data sent to third parties.

[Quick Start](#quick-start) · [Features](#features) · [MCP Integration](#mcp-integration-ai-agents) · [Roadmap](#roadmap) · [Contributing](#contributing)

</div>

---

## Why AlManak?

| | Pocket / Raindrop | Readwise | AlManak |
|---|---|---|---|
| **Self-hosted** | ❌ | ❌ | ✅ |
| **Your data only** | ❌ | ❌ | ✅ |
| **AI agent (MCP)** | ❌ | ❌ | ✅ |
| **Semantic search** | ❌ | ✅ | ✅ |
| **Telegram bot** | ❌ | ❌ | ✅ |
| **Free forever** | ❌ | ❌ | ✅ |
| **Open source** | ❌ | ❌ | ✅ |

AlManak turns your saved links into a **queryable knowledge base** that your AI agent (Claude, VS Code Copilot, Hermes, any MCP client) can search in natural language — all without your data leaving your machine.

---

## How it works

```
You find a link  ──→  Telegram bot   ──┐
anywhere                               │
                  Bookmarklet        ──┼──→  AlManak (VPS)  ──→  MCP  ──→  AI agent
                  API / CSV          ──┘       │
                                               └──→  SQLite + Qdrant
```

1. **Capture** — send a URL to your Telegram bot, click the bookmarklet, or POST to the API
2. **Enrich** — AlManak fetches title, description, content, auto-classifies type & subject, deduplicates
3. **Index** — stored in SQLite + vectorized in Qdrant
4. **Retrieve** — any MCP client (VS Code, Claude Desktop, Hermes…) can semantic-search your KB

---

## Features

| | |
|---|---|
| 📱 **Telegram bot** | Send links from your phone as naturally as messaging a friend |
| 🔖 **Bookmarklet** | One-click save from any browser, including iOS Safari |
| 🤖 **MCP HTTP + stdio** | Connects to any MCP-compatible AI agent (VS Code, Claude, Hermes…) |
| 🔍 **Semantic search** | Qdrant + FastEmbed (`BAAI/bge-small-en-v1.5`) — CPU only, no GPU needed |
| 💾 **FTS fallback** | SQLite FTS5 full-text search when Qdrant is unavailable |
| 🕸️ **Knowledge graph** | Tag co-occurrence, same-domain, cosine similarity links |
| 🏷️ **Auto-classification** | Detects type (repo, article, video, model…) and subject (ai, dev-tools…) |
| 🔁 **Deduplication** | URL fingerprinting — no duplicate entries |
| 🔐 **Bearer auth** | All HTTP endpoints protected by API key |
| 🔒 **Auto-HTTPS** | Caddy handles Let's Encrypt automatically |
| 🐳 **Docker Compose** | One-command deploy on any VPS |

---

## Quick Start

```bash
git clone https://github.com/almanak-app/almanak
cd almanak
make setup          # creates .env, generates API key
# → edit .env: set MCP_DOMAIN=mcp.example.com  (or leave for IP-only)
make up             # starts everything (Qdrant + MCP + Ingest + Caddy)
make token          # prints your URL + VS Code config snippet
```

**Prerequisites**: Docker + Docker Compose. That's it.

---

## Sending links

### Option 1 — Telegram bot (recommended for mobile)

The Telegram bot is your "buddy that remembers everything". Send it a URL from anywhere — it replies with the extracted title, type, and subject in seconds.

#### Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token
2. Find your Telegram user ID: message [@userinfobot](https://t.me/userinfobot)
3. Set in `.env`:
   ```
   BENCHMARK_BOT_TOKEN=123456789:AAF...your_token...
   ALLOWED_USER_ID=123456789
   ```
4. Add to `docker-compose.yml` (see below) and `docker compose up bot -d`

#### Usage

Just send a URL — the bot does the rest:

```
You:    https://github.com/microsoft/markitdown
Bot:    ✅ Saved #847
        📌 MarkItDown — Microsoft
        Convert files and office documents to Markdown
        🏷  repo · dev-tools · python, markdown, office
```

You can also add tags and a note inline:

```
You:    https://arxiv.org/abs/2307.09288 #llm #research worth reading
Bot:    ✅ Saved #848
        📌 LLaMA 2: Open Foundation and Fine-Tuned Chat Models
        🏷  research · ai · llm, research
```

#### Bot commands

| Command | Description |
|---------|-------------|
| `<url> [#tag1 #tag2] [note]` | Save URL with optional tags and note |
| `/list [N]` | Last N entries (default 10) |
| `/search <query>` | Full-text search |
| `/tag <id> <tags>` | Set tags on an entry |
| `/note <id> <text>` | Add or update a note |
| `/rm <id>` | Delete an entry |
| `/stats` | Counts by type and subject |
| `/export` | Receive a CSV of all entries |
| `/help` | Show help |

#### Add bot service to docker-compose.yml

```yaml
  bot:
    build: .
    command: ["python", "bot/telegram_bot.py"]
    env_file: .env
    volumes:
      - ./data:/app/data
    depends_on:
      - qdrant
    restart: unless-stopped
```

---

### Option 2 — Bookmarklet (works everywhere, including iOS Safari)

1. Visit `https://mcp.example.com/bookmarklet?key=YOUR_INGEST_API_KEY`
2. Drag **"+ Save to AlManak"** to your bookmarks bar
3. On any page, click it → popup confirms → closes in 3 seconds

---

### Option 3 — REST API

For integrations (Raycast, Alfred, n8n, iOS Shortcuts, scripts — anything that can make an HTTP request):

```bash
curl -X POST https://mcp.example.com/ingest/links \
  -H "Authorization: Bearer YOUR_INGEST_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "tags": "ai, research", "notes": "great paper"}'
```

---

## MCP Integration (AI agents)

### VS Code (any PC, any network)

```jsonc
// .vscode/mcp.json  OR  VS Code settings.json → "mcp.servers"
{
  "servers": {
    "almanak": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_API_KEY"
      }
    }
  }
}
```

### Hermes / Claude Desktop

```yaml
mcp_servers:
  almanak:
    transport: http
    url: https://mcp.example.com/mcp
    headers:
      Authorization: "Bearer YOUR_MCP_API_KEY"
```

### Local stdio (same machine as AlManak)

```yaml
mcp_servers:
  almanak:
    command: python3
    args: [-m, open_benchmark.mcp_server.server]
    env:
      BENCHMARK_DB_PATH: /abs/path/to/data/benchmarks.db
      QDRANT_URL: http://localhost:6333
```

### MCP tools

| Tool | Description |
|------|-------------|
| `search_benchmarks` | Semantic search (Qdrant or FTS fallback) |
| `get_benchmark` | Retrieve entry by ID |
| `list_benchmarks_stats` | Counts by type and subject |
| `get_related_benchmarks` | Entries linked by tag, domain, or similarity |
| `list_subjects` | All subjects in DB |
| `list_types` | All types in DB |
| `list_tags` | Most common tags with counts |
| `explain_relationships` | Human-readable relation summary for an entry |

---

## Remote Access

Caddy is included in docker-compose and handles HTTPS automatically.

### With a domain (recommended)

1. DNS A record: `mcp.example.com → <vps-ip>`
2. `.env`: `MCP_DOMAIN=mcp.example.com`
3. VPS firewall: open ports 80 + 443
4. `make up` — cert issued automatically

### IP-only VPS

1. Leave `MCP_DOMAIN` unset
2. Open port 443
3. `make up`
4. Add `"allowInsecureCertificate": true` in VS Code MCP config

---

## Architecture

```
almanak/
  src/open_benchmark/       # Python package
    config.py               # Typed env config (pydantic-settings)
    storage/db.py           # SQLite schema, CRUD, graph tables
    extractor/              # URL fetch, classify, GitHub enrichment
    indexer/                # Qdrant upsert + semantic search
    graph/                  # Tag/domain/cosine similarity graph
    mcp_server/             # FastMCP (stdio + HTTP)
    ingest/                 # FastAPI ingest + bookmarklet endpoints
  bot/
    telegram_bot.py         # Telegram ingestion bot
  scripts/                  # index.py, seed.py
  data/                     # .gitignored — SQLite + CSV
  Caddyfile                 # Auto-HTTPS config
  docker-compose.yml
  Makefile
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCHMARK_DB_PATH` | `data/benchmarks.db` | SQLite path |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint |
| `QDRANT_ENABLED` | `true` | Disable for FTS-only mode |
| `MCP_API_KEY` | `` | Bearer token for MCP |
| `MCP_DOMAIN` | `localhost` | Domain for auto-HTTPS |
| `INGEST_API_KEY` | `` | Bearer token for ingest API + bookmarklet |
| `BENCHMARK_BOT_TOKEN` | `` | Telegram bot token (from @BotFather) |
| `ALLOWED_USER_ID` | `` | Your Telegram user ID |
| `FEATURE_TRAFILATURA` | `true` | Readable content extraction |
| `FEATURE_GRAPH` | `true` | Knowledge graph building |

---

---

## Roadmap

- [ ] **Web UI** — browse, search and annotate links from a browser dashboard
- [ ] **LLM enrichment** — optional GPT/Ollama pass to improve classification & summaries
- [ ] **Browser extension** — Chrome/Firefox, replaces the bookmarklet
- [ ] **iOS Shortcuts template** — pre-made `.shortcut` file for one-tap save from Safari Share Sheet (the REST API already works manually)
- [ ] **RSS ingestion** — automatically ingest feeds into your KB
- [ ] **Duplicate clustering** — group near-duplicate URLs across sources
- [ ] **Export** — Markdown, JSON, Obsidian vault

> Have a feature request? [Open an issue](https://github.com/codeurali/almanak/issues) — PRs are very welcome.

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

```bash
git clone https://github.com/codeurali/almanak
cd almanak
pip install -e ".[dev]"
pytest
```

---

## ⭐ Support the project

If AlManak saves you time or helps your workflow, **leaving a star is the best way to support it** and help others discover it.

---

## License

MIT
