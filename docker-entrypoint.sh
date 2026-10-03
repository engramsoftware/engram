#!/bin/bash
# ============================================================
# Engram Docker entrypoint
#
# Runs as root only to prepare the container, then starts Engram as the
# unprivileged "engram" user:
#   1. /app/.env is rebuilt for each new container. The generated secrets
#      (JWT signing key, key that encrypts saved API keys) live on the /data
#      volume in /data/secrets.env, so a rebuild or down/up keeps them.
#   2. /data, the model cache and /app/.env are handed to the engram user.
#   3. Engram runs as that user. If /data can't be written by it (some
#      Windows/macOS folder mounts ignore ownership), it runs as root and
#      says so.
# ============================================================

set -e

APP_DIR="${ENGRAM_APP_DIR:-/app}"      # overridable for tests only
DATA_DIR="${ENGRAM_DATA_DIR:-/data}"
ENV_FILE="$APP_DIR/.env"
ENV_EXAMPLE="$APP_DIR/.env.example"
SECRETS_FILE="$DATA_DIR/secrets.env"
# Written by a pre-release build (branch claude/mcp-access-w11k3y), where
# /app/.env was a symlink to it. Read so those installs keep their secrets
# and settings; never written.
LEGACY_ENV_FILE="$DATA_DIR/.engram.env"
APP_USER="engram"
CACHE_DIR="${HOME:-/home/engram}/.cache"

is_mounted() { grep -q " $1 " /proc/self/mountinfo 2>/dev/null; }

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

# Create data directories
mkdir -p "$DATA_DIR"/chroma/messages "$DATA_DIR"/chroma/memories "$DATA_DIR"/chroma/negative "$DATA_DIR"/chroma/documents
mkdir -p "$DATA_DIR"/mcp "$DATA_DIR"/learning/sessions "$DATA_DIR"/learning/session_links
mkdir -p "$DATA_DIR"/learning/skills "$DATA_DIR"/learning/reflections "$DATA_DIR"/learning/experiments
mkdir -p "$DATA_DIR"/uploads "$DATA_DIR"/crawl_cache "$DATA_DIR"/logs

# ── 1. .env and secrets that survive rebuilds ────────────────
# /data belongs to the engram user, and this part runs as root: never follow a
# symlink planted there (it could point root's reads/writes at any file)
for f in "$SECRETS_FILE" "$LEGACY_ENV_FILE"; do
    if [ -L "$f" ]; then
        echo "[Engram] ERROR: $f is a symlink; replace it with a regular file" >&2
        exit 1
    fi
done
# A dangling or leftover symlink from the pre-release layout: replace it
[ -L "$ENV_FILE" ] && rm -f "$ENV_FILE"
if [ ! -e "$ENV_FILE" ]; then
    echo "[Engram] Creating $ENV_FILE..."
    if [ -f "$LEGACY_ENV_FILE" ]; then
        # Keep the settings a pre-release install had there (CR dropped)
        tr -d '\r' < "$LEGACY_ENV_FILE" > "$ENV_FILE"
    elif [ -f "$ENV_EXAMPLE" ]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
    else
        : > "$ENV_FILE"
    fi
fi

touch "$SECRETS_FILE"
chmod 600 "$SECRETS_FILE" 2>/dev/null || true

# ensure_secret NAME BYTES
ensure_secret() {
    name=$1
    if ! is_unset "$(printenv "$name" || true)"; then
        return  # set in the environment (compose/docker run): that value wins
    fi

    val=$(read_var "$name" "$SECRETS_FILE")
    if is_unset "$val"; then
        # A mounted .env, or one left in this container by an older image
        val=$(read_var "$name" "$ENV_FILE")
        if is_unset "$val"; then
            val=$(read_var "$name" "$LEGACY_ENV_FILE")
        fi
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

# ── 2 + 3. Drop root ─────────────────────────────────────────
if [ "$(id -u)" = "0" ] && id "$APP_USER" >/dev/null 2>&1 && command -v setpriv >/dev/null 2>&1; then
    APP_UID=$(id -u "$APP_USER")
    APP_GID=$(id -g "$APP_USER")
    # Only touch files that aren't already owned by the app user (fast on restarts)
    for dir in "$DATA_DIR" "$CACHE_DIR"; do
        [ -d "$dir" ] && find "$dir" \! -user "$APP_UID" -exec chown -h "$APP_UID:$APP_GID" {} + 2>/dev/null || true
    done
    # The generated .env holds the secrets: readable by Engram (and by
    # `docker exec -u engram ... mcp_server.py`) only. A mounted .env is the
    # host's file: leave its owner and mode alone.
    if ! is_mounted "$ENV_FILE"; then
        chown "$APP_UID:$APP_GID" "$ENV_FILE" 2>/dev/null || true
        chmod 600 "$ENV_FILE" 2>/dev/null || true
    fi

    as_app() { setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"; }
    probe="$DATA_DIR/.write-test-$$"
    problem=""
    if ! as_app sh -c "touch '$probe' && rm -f '$probe'" 2>/dev/null; then
        problem="$DATA_DIR isn't writable by the $APP_USER user (the folder mount ignores file ownership)"
    elif [ -e "$DATA_DIR/app.db" ] && ! as_app test -w "$DATA_DIR/app.db"; then
        problem="$DATA_DIR/app.db isn't writable by the $APP_USER user"
    elif ! as_app test -r "$ENV_FILE"; then
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
