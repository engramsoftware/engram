#!/bin/bash
# ============================================================
# Engram Docker entrypoint
#
# Runs as root only to prepare the container, then starts Engram as the
# unprivileged "engram" user:
#   1. Secrets (JWT signing key, encryption key for stored API keys) live in
#      /data so they survive rebuilding the container. They used to be
#      generated inside the container, so every rebuild logged everyone out
#      and made saved API keys unreadable.
#   2. /data and the model cache are handed to the engram user.
#   3. Engram runs as that user. If /data can't be written by it (some
#      Windows/macOS folder mounts ignore ownership), it runs as root and
#      says so.
# ============================================================

set -e

APP_DIR="/app"
DATA_DIR="/data"
ENV_FILE="$APP_DIR/.env"
ENV_EXAMPLE="$APP_DIR/.env.example"
SECRETS_FILE="$DATA_DIR/.engram.env"
APP_USER="engram"
CACHE_DIR="${HOME:-/home/engram}/.cache"

# Create data directories
mkdir -p "$DATA_DIR"/chroma/messages "$DATA_DIR"/chroma/memories "$DATA_DIR"/chroma/negative "$DATA_DIR"/chroma/documents
mkdir -p "$DATA_DIR"/mcp "$DATA_DIR"/learning/sessions "$DATA_DIR"/learning/session_links
mkdir -p "$DATA_DIR"/learning/skills "$DATA_DIR"/learning/reflections "$DATA_DIR"/learning/experiments
mkdir -p "$DATA_DIR"/uploads "$DATA_DIR"/crawl_cache "$DATA_DIR"/logs

is_mounted() { grep -q " $1 " /proc/self/mountinfo 2>/dev/null; }

# ── 1. Secrets that survive rebuilds ─────────────────────────
if [ -e "$ENV_FILE" ] && [ ! -L "$ENV_FILE" ]; then
    # A .env you mounted, or one generated inside an older container: use it.
    # Keep a copy of a generated one in /data so the next rebuild reuses it.
    if [ ! -f "$SECRETS_FILE" ] && ! is_mounted "$ENV_FILE"; then
        cp "$ENV_FILE" "$SECRETS_FILE"
        echo "[Engram] Saved this container's secrets to $SECRETS_FILE so rebuilds keep them"
    fi
else
    if [ ! -f "$SECRETS_FILE" ]; then
        echo "[Engram] First run detected. Generating configuration..."
        if [ -f "$ENV_EXAMPLE" ]; then
            cp "$ENV_EXAMPLE" "$SECRETS_FILE"
        else
            touch "$SECRETS_FILE"
        fi

        # Generate secure JWT secret if not set via environment
        if [ -z "$JWT_SECRET_KEY" ] || [ "$JWT_SECRET_KEY" = "change-me-to-a-random-secret-key" ]; then
            JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
            if grep -q "^JWT_SECRET_KEY=" "$SECRETS_FILE"; then
                sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$JWT_SECRET|" "$SECRETS_FILE"
            else
                echo "JWT_SECRET_KEY=$JWT_SECRET" >> "$SECRETS_FILE"
            fi
            echo "[Engram] Generated JWT secret"
        fi

        # Generate secure encryption key if not set via environment
        if [ -z "$ENCRYPTION_KEY" ] || [ "$ENCRYPTION_KEY" = "change-me-to-a-random-32-char-key" ]; then
            ENC_KEY=$(python -c "import secrets; print(secrets.token_hex(16))")
            if grep -q "^ENCRYPTION_KEY=" "$SECRETS_FILE"; then
                sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENC_KEY|" "$SECRETS_FILE"
            else
                echo "ENCRYPTION_KEY=$ENC_KEY" >> "$SECRETS_FILE"
            fi
            echo "[Engram] Generated encryption key"
        fi
        echo "[Engram] Configuration saved to $SECRETS_FILE"
    fi
    ln -sfn "$SECRETS_FILE" "$ENV_FILE"
fi
[ -f "$SECRETS_FILE" ] && chmod 600 "$SECRETS_FILE"

# ── 2 + 3. Drop root ─────────────────────────────────────────
if [ "$(id -u)" = "0" ] && id "$APP_USER" >/dev/null 2>&1 && command -v setpriv >/dev/null 2>&1; then
    APP_UID=$(id -u "$APP_USER")
    APP_GID=$(id -g "$APP_USER")
    # Only touch files that aren't already owned by the app user (fast on restarts)
    for dir in "$DATA_DIR" "$CACHE_DIR"; do
        [ -d "$dir" ] && find "$dir" \! -user "$APP_UID" -exec chown "$APP_UID:$APP_GID" {} + 2>/dev/null || true
    done

    as_app() { setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"; }
    probe="$DATA_DIR/.write-test-$$"
    problem=""
    if ! as_app sh -c "touch '$probe' && rm -f '$probe'" 2>/dev/null; then
        problem="$DATA_DIR isn't writable by the $APP_USER user (the folder mount ignores file ownership)"
    elif [ -e "$DATA_DIR/app.db" ] && ! as_app test -w "$DATA_DIR/app.db"; then
        problem="$DATA_DIR/app.db isn't writable by the $APP_USER user"
    elif [ -e "$ENV_FILE" ] && ! as_app test -r "$ENV_FILE"; then
        problem="$ENV_FILE isn't readable by the $APP_USER user (a mounted .env must be readable by uid $APP_UID)"
    fi
    if [ -z "$problem" ]; then
        echo "[Engram] Starting backend on port ${PORT:-8000} as user $APP_USER..."
        exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups --no-new-privs python main.py
    fi
    echo "[Engram] WARNING: running as root because $problem."
    echo "[Engram]          Fix that (or use a Docker volume for $DATA_DIR) to run Engram unprivileged."
fi

echo "[Engram] Starting backend on port ${PORT:-8000}..."
exec python main.py
