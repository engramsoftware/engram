# ============================================================
# Engram — Multi-stage Docker build
# Stage 1: Build React frontend with Node.js
# Stage 2: Run FastAPI backend with Python
# ============================================================

# ── Stage 1: Frontend build ──────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python backend ─────────────────────────────────
FROM python:3.11-slim

# System deps for native Python packages (numpy, cryptography, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ML models so first request isn't slow (ChromaDB ONNX + cross-encoder)
RUN python -c "\
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; \
ef = ONNXMiniLM_L6_V2(); \
ef(['warmup']); \
print('ChromaDB ONNX model cached')"
RUN python -c "\
from sentence_transformers import CrossEncoder; \
m = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2'); \
print('Cross-encoder model cached')"

# Copy backend source
COPY backend/ ./

# Copy built frontend into backend/static/ for single-port serving
COPY --from=frontend-build /build/dist/ ./static/

# Copy MCP server (lives at project root)
COPY mcp_server.py /app/mcp_server.py

# Copy license and entrypoint
COPY LICENSE /app/LICENSE
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Data directory — mount a volume here for persistence
# All SQLite, ChromaDB, uploads, crawl cache live under /data
RUN mkdir -p /data

# Environment defaults
ENV HOST=0.0.0.0
ENV PORT=8000
ENV DEBUG=false
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check using the built-in endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
