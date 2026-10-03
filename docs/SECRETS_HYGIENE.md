# Secrets hygiene — don’t push secrets

(For reporting a security vulnerability, contact the maintainers privately; this page is only about keeping secrets out of the repo.)

**Before every push:** make sure no personal data, API keys, or app passwords are in the repo.

## Never commit

- **`.env` and `backend/.env`** — All secrets live here (JWT secret, encryption key, API keys, Neo4j password). They are in `.gitignore`; never force-add them.
- **GitHub / Git app passwords and tokens** — Use only in:
  - `.env` (for scripts that need them), or
  - System credential manager / GitHub CLI (`gh auth login`), or
  - Cursor/IDE settings that are not synced to the repo.
  Do not put them in config files, docs, or code.
- **SSL keys** — `*.pem`, `*.key` (e.g. for HTTPS). Ignored; keep local only.
- **`data/`** — User data (DBs, Chroma, MCP knowledge). Ignored; never commit.

## Safe to commit

- **`backend/.env.example`** — Template with placeholders only (e.g. `change-me`, `sk-...`). No real keys.
- **`.cursor/mcp.json`** — Only the MCP server command (`docker exec -i -u engram engram python mcp_server.py`). No passwords.

## Quick check before push

```bash
git status
# Ensure no .env, data/, or *.pem appear in the list.

git diff --cached
# Scan for accidental password / api_key / token literals.
```

If you ever pushed a secret: rotate it immediately (new API key, new app password), then remove it from history (e.g. `git filter-branch` or BFG) and force-push only if you understand the impact; otherwise prefer rotating and not rewriting.

## Optional: a local pre-push hook

Git hooks are not versioned, so nothing blocks a push for you by default. If you want a safety net, add a `.git/hooks/pre-push` script that refuses pushes whose commits add `.env`, `backend/.env*`, anything under `data/`, or `*.pem` / `*.key`.
