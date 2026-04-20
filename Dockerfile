FROM python:3.12-slim

WORKDIR /app

# System deps for trafilatura
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev libxslt-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY bot/ ./bot/

# Pre-download FastEmbed model so it's baked into the image
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warmup']))"

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Default: MCP stdio (override with CMD for HTTP)
CMD ["python", "-m", "open_benchmark.mcp_server.server"]
