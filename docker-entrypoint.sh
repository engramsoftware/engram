#!/bin/bash
# ============================================================
# Engram Docker entrypoint
# Handles first-run setup: .env and secrets that persist on /data
# ============================================================

set -e

ENV_FILE="/app/.env"
ENV_EXAMPLE="/app/.env.example"
# Generated secrets live on the /data volume so they survive a new container.
# (They used to live only in /app/.env, which is part of the container layer:
# `docker compose up` after a rebuild, or down/up, generated new ones, logging
# everyone out and making every saved provider API key undecryptable.)
SECRETS_FILE="/data/secrets.env"

# /app/.env is read by every process in the container: the server and
# `docker exec ... python mcp_server.py`. It is rebuilt for each new container.
if [ ! -f "$ENV_FILE" ]; then
    echo "[Engram] Creating $ENV_FILE..."
    if [ -f "$ENV_EXAMPLE" ]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
    else
        touch "$ENV_FILE"
    fi
fi

mkdir -p /data
touch "$SECRETS_FILE"
chmod 600 "$SECRETS_FILE"

# Last KEY=value for KEY in a file ("" if absent). CR is dropped so a file saved
# with Windows line endings doesn't turn "value" into "value\r".
read_var() {
    grep -E "^$1=" "$2" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r' || true
}

# Set KEY=value in a file. No sed: the value stays literal (sed would read & and |),
# and the file is rewritten in place rather than renamed over, which fails on a
# bind-mounted single file. grep re-terminates a last line that had no newline.
set_var() {
    tmp=$(mktemp)
    grep -vE "^$1=" "$3" > "$tmp" || true
    printf '%s=%s\n' "$1" "$2" >> "$tmp"
    cat "$tmp" > "$3"
    rm -f "$tmp"
}

# A missing value or a public placeholder from .env.example both mean "not set"
is_unset() {
    case "$1" in
        ""|change-me*) return 0 ;;
        *) return 1 ;;
    esac
}

# ensure_secret NAME BYTES
ensure_secret() {
    name=$1
    if ! is_unset "$(printenv "$name" || true)"; then
        return  # set in the environment (compose/docker run): that value wins
    fi

    val=$(read_var "$name" "$SECRETS_FILE")
    if is_unset "$val"; then
        # A mounted .env that already has a real secret: keep it
        val=$(read_var "$name" "$ENV_FILE")
        if is_unset "$val"; then
            val=$(python -c "import secrets; print(secrets.token_hex($2))")
            echo "[Engram] Generated $name (saved in $SECRETS_FILE)"
        fi
        set_var "$name" "$val" "$SECRETS_FILE"
    fi

    if [ "$(read_var "$name" "$ENV_FILE")" = "$val" ]; then
        return  # already in place: don't touch the file
    elif [ -w "$ENV_FILE" ]; then
        set_var "$name" "$val" "$ENV_FILE"
    else
        echo "[Engram] WARNING: $ENV_FILE is read-only and its $name differs from $SECRETS_FILE"
    fi
}

ensure_secret JWT_SECRET_KEY 32
ensure_secret ENCRYPTION_KEY 16

# Create data directories
mkdir -p /data/chroma/messages /data/chroma/memories /data/chroma/negative /data/chroma/documents
mkdir -p /data/mcp /data/learning/sessions /data/learning/session_links
mkdir -p /data/learning/skills /data/learning/reflections /data/learning/experiments
mkdir -p /data/uploads /data/crawl_cache /data/logs

echo "[Engram] Starting backend on port ${PORT:-8000}..."
exec python main.py
