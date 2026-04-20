.PHONY: help setup token up down logs status index seed

# ── Default target ─────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  AlManak — self-hosted AI memory for the links that matter"
	@echo ""
	@echo "  make setup    — first-time setup: copy .env.example, generate token"
	@echo "  make token    — generate a new Bearer token (print + write to .env)"
	@echo "  make up       — start all services (docker compose)"
	@echo "  make down     — stop all services"
	@echo "  make logs     — tail live logs from MCP server"
	@echo "  make status   — show service health"
	@echo "  make index    — index DB entries into Qdrant"
	@echo "  make seed     — load from data/benchmarks.csv (if present)"
	@echo ""

# ── First-time setup ───────────────────────────────────────────────────────────
setup:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ .env created from .env.example"; \
	else \
		echo "→ .env already exists, skipping"; \
	fi
	@$(MAKE) --no-print-directory _gen_token
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env → set MCP_DOMAIN (your domain or leave empty for IP-only)"
	@echo "  2. Open ports 80 + 443 on your VPS firewall"
	@echo "  3. make up"
	@DOMAIN=$$(grep MCP_DOMAIN .env | cut -d= -f2); TOKEN=$$(grep '^MCP_API_KEY' .env | cut -d= -f2); \
	echo "  4. Your MCP endpoint: https://$$DOMAIN/mcp"; \
	echo "  5. Bearer token: $$TOKEN"
	@echo ""

# ── Token management ───────────────────────────────────────────────────────────
token: _gen_token
	@echo ""
	@echo "Bearer token and URL:"
	@echo "  URL  : https://$$(grep MCP_DOMAIN .env | cut -d= -f2)/mcp"
	@echo "  Token: $$(grep '^MCP_API_KEY' .env | cut -d= -f2)"
	@echo ""
	@echo "VS Code mcp.json snippet:"
	@echo '  {'
	@echo '    "servers": {'
	@echo '      "almanak": {'
	@echo '        "type": "http",'
	@echo "        \"url\": \"https://$$(grep MCP_DOMAIN .env | cut -d= -f2)/mcp\","
	@echo '        "headers": {'
	@echo "          \"Authorization\": \"Bearer $$(grep '^MCP_API_KEY' .env | cut -d= -f2)\""
	@echo '        }'
	@echo '      }'
	@echo '    }'
	@echo '  }'

_gen_token:
	@if [ ! -f .env ]; then echo "Run 'make setup' first."; exit 1; fi
	@NEW_KEY=$$(openssl rand -hex 32); \
	if grep -q '^MCP_API_KEY=$$' .env || ! grep -q '^MCP_API_KEY=' .env; then \
		sed -i "s|^MCP_API_KEY=.*|MCP_API_KEY=$$NEW_KEY|" .env; \
		echo "✓ MCP_API_KEY generated: $$NEW_KEY"; \
	else \
		echo "→ MCP_API_KEY already set (run 'make token' to rotate)"; \
	fi

# ── Docker Compose shortcuts ───────────────────────────────────────────────────
up:
	docker compose up -d
	@echo "✓ Services started"
	@echo "  Endpoint: https://$$(grep MCP_DOMAIN .env | cut -d= -f2)/mcp"

down:
	docker compose down

logs:
	docker compose logs -f mcp

status:
	@echo "Services:"
	@docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
	@echo ""
	@echo "Health:"
	@curl -sf http://localhost:8766/health 2>/dev/null && echo "" || echo "  ingest API: not reachable"
	@echo ""
	@echo "Connection info:"
	@echo "  URL  : https://$$(grep MCP_DOMAIN .env | cut -d= -f2)/mcp"
	@echo "  Token: $$(grep '^MCP_API_KEY' .env | cut -d= -f2)"

# ── Data ───────────────────────────────────────────────────────────────────────
index:
	docker compose exec mcp python scripts/index.py

seed:
	docker compose exec mcp python scripts/seed.py data/benchmarks.csv
