@echo off
REM Wrapper so Cursor can start the Engram MCP server (stdio) on Windows.
REM Requires: docker compose up (container named "engram" running).
docker exec -i engram python mcp_server.py
