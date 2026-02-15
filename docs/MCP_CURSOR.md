# Using Engram MCP with Cursor

The Engram MCP server exposes 37 tools (memory search, knowledge graph, playbooks, skills, etc.) to Cursor. The app and MCP server run in Docker.

## Prerequisites

1. **Container running:** `docker compose up -d`
2. Container name must be `engram` (default in docker-compose).

## Project config (automatic)

If `.cursor/mcp.json` exists in this repo, Cursor should load the **engram** server when you open this project. Config:

```json
{
  "mcpServers": {
    "engram": {
      "command": "docker",
      "args": ["exec", "-i", "engram", "python", "mcp_server.py"]
    }
  }
}
```

## If the agent doesn’t see the tools

1. **Reload Cursor:** **Ctrl+Shift+P** → “Developer: Reload Window”.
2. **Check MCP in Settings:** **Settings → Features → MCP** (or **Tools & MCP**). Confirm **engram** is listed and connected (no error).
3. **Add server manually:** In that same MCP screen, click **+ Add new MCP server**:
   - **Name:** `engram`
   - **Type:** stdio
   - **Command:** `docker`
   - **Args:** `exec`, `-i`, `engram`, `python`, `mcp_server.py`  
   Or use the wrapper: **Command:** full path to `scripts/run-engram-mcp.bat`, **Args:** (empty).
4. **New chat:** After connecting, start a **new** Composer/Agent chat so it gets the updated tool list.
5. **Global fallback:** If project-level config isn’t loaded (known in some Cursor versions), add the same server in the **global** MCP config (e.g. via the same Settings screen; it may write to `%APPDATA%\Cursor\` or similar).

## Getting the agent to use the MCP

The rule **`.cursor/rules/engram-mcp-usage.mdc`** tells the AI to:

- Call **`get_smart_context`** when starting a task (to load playbooks/skills).
- Call **`find_skill`** when the user has an error (to reuse past solutions).
- Call **`record_outcome`** after fixing or completing something (so the system learns).

Keep that rule enabled (it has `alwaysApply: true`). In a new chat, the agent will see the rule and use the tools.

## Verify server in container

```powershell
docker exec -i engram python mcp_server.py
```

You should see “Starting Engram MCP Server…” and the tool list. Cancel with Ctrl+C.
