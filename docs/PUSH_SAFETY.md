# Push safety — no personal data to GitHub

This repo is set up so **pushing to GitHub does not send secrets or personal data**.

## What is never pushed (ignored by Git)

| Path / pattern | Purpose |
|----------------|--------|
| `.env`, `backend/.env` | API keys, JWT secret, encryption key, DB URLs, **personal paths** (e.g. `HYBRID_SEARCH_PATH`) |
| `data/` | All user data: SQLite DB, uploads, ChromaDB, MCP DBs, logs |
| `*.pem`, `*.key` | SSL certs and private keys |
| `venv/`, `node_modules/` | Dependencies (recreated from lockfiles) |
| `.vscode/`, `.idea/`, `.windsurf/` | Local IDE config |

Only **placeholder** config is in the repo: `backend/.env.example` (no real keys or paths).

## Pre-push hook

A **pre-push hook** (`.git/hooks/pre-push`) runs before every push. It **blocks** the push if any commit being pushed adds or changes:

- `.env` or `backend/.env` (or `backend/.env.*`)
- Anything under `data/`
- `*.pem` or `*.key`

So even if you accidentally stage a secret file, the push will be refused.

## Quick check before pushing

```powershell
git status
```

You should **not** see `.env`, `backend/.env`, or anything under `data/` in “Changes to be committed” or “Untracked files” that you intend to add. If you do, unstage and keep them local:

```powershell
git restore --staged backend/.env
```

Your **personal data stays local**; only code and safe config (e.g. `.env.example`) are pushed.
