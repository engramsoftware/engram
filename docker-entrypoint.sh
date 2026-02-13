#!/bin/bash
# ============================================================
# Engram Docker entrypoint
# Handles first-run setup: .env generation with secure secrets
# ============================================================

set -e

ENV_FILE="/app/.env"
ENV_EXAMPLE="/app/.env.example"

# Generate .env with secure secrets on first run
if [ ! -f "$ENV_FILE" ]; then
    echo "[Engram] First run detected. Generating configuration..."

    if [ -f "$ENV_EXAMPLE" ]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
    else
        touch "$ENV_FILE"
    fi

    # Generate secure JWT secret if not set via environment
    if [ -z "$JWT_SECRET_KEY" ] || [ "$JWT_SECRET_KEY" = "change-me-to-a-random-secret-key" ]; then
        JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
        sed -i "s|JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$JWT_SECRET|" "$ENV_FILE"
        echo "[Engram] Generated JWT secret"
    fi

    # Generate secure encryption key if not set via environment
    if [ -z "$ENCRYPTION_KEY" ] || [ "$ENCRYPTION_KEY" = "change-me-to-a-random-32-char-key" ]; then
        ENC_KEY=$(python -c "import secrets; print(secrets.token_hex(16))")
        sed -i "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENC_KEY|" "$ENV_FILE"
        echo "[Engram] Generated encryption key"
    fi

    echo "[Engram] Configuration saved to $ENV_FILE"
fi

# Create data directories
mkdir -p /data/chroma/messages /data/chroma/memories /data/chroma/negative /data/chroma/documents
mkdir -p /data/mcp /data/learning/sessions /data/learning/session_links
mkdir -p /data/learning/skills /data/learning/reflections /data/learning/experiments
mkdir -p /data/uploads /data/crawl_cache /data/logs

echo "[Engram] Starting backend on port ${PORT:-8000}..."
exec python main.py
