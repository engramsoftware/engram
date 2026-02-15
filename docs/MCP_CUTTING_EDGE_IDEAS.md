# Cutting-Edge MCP Ideas (2024–2026)

Research summary: latest Model Context Protocol trends and how they could apply to the Engram MCP.

---

## 1. **Code execution with MCP (token efficiency)**

**Idea:** Instead of the model calling tools directly (and loading all tool definitions + intermediate results into context), the agent **writes and runs code** (e.g. TypeScript/JS in a sandbox) that discovers and invokes tools on demand.

**Benefits:**
- Up to **~98% token reduction** in some workflows (e.g. 150k → 2k tokens).
- **78%+ fewer input tokens** (no full tool schema dump upfront).
- **60% faster** in some scenarios; intermediate data stays in the execution environment instead of the model context.

**Relevance to Engram:** Engram has 37 tools. If Cursor/Claude ever support “code execution with MCP,” we could expose a **tool registry or file-tree** for on-demand discovery and let the agent script batched calls (e.g. `search_all_context` then `find_skill` then `record_outcome`) without blowing context. Today: keep tool descriptions clear and consider a **single “orchestrator” tool** that runs a small script or pipeline to reduce round-trips.

**Refs:** [Anthropic – Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp), [SmartScope – 98.7% token reduction](https://smartscope.blog/en/blog/mcp-code-execution-agent-design/).

---

## 2. **MCP Apps (interactive UI in chat)**

**Idea:** Tools can return **interactive HTML** (dashboards, forms, visualizations) that the host renders in a **sandboxed iframe** inside the conversation. The app and host talk over JSON-RPC; the app can call server tools and receive updates.

**Benefits:**
- Context stays in the thread (no “open this link in a new tab”).
- Reuse existing MCP tools; no separate web app auth/API.
- Security via iframe sandbox and host-controlled capabilities.

**Relevance to Engram:** Add **MCP Apps** for:
- **Insights / stats dashboard:** `get_insights`, `get_reflection_stats`, `get_db_stats` → small charts or tables in-chat.
- **Session browser:** `get_resumable_sessions`, `find_related_sessions` → list + “Resume” with one click.
- **Skill/playbook explorer:** `get_smart_context` / `find_skill` results as a small UI (filter, expand, “Use this playbook”).

Requires: host support (Cursor support TBD); server-side use of `_meta.ui.resourceUri` and a UI resource (e.g. bundled HTML). Official extension: [MCP Apps](https://modelcontextprotocol.io/docs/extensions/apps); SDK: `@modelcontextprotocol/ext-apps`.

---

## 3. **Enterprise / best-practice patterns**

**Controlled autonomy**
- Least-privilege tools; **approval paths for high-impact actions** (e.g. delete skill, clear DB).
- Engram: consider “confirmation” or “dry-run” for tools that mutate a lot (e.g. `store_solution`, bulk deletes).

**Security by design**
- Per-tool authZ, audit logs, no secrets in config.
- Engram: already local/stdio; if we add HTTP or gateway, add auth and audit.

**Stateless by default**
- No hidden in-memory state; use DB/cache with TTL.
- Engram: already stateless (SQLite/Chroma/Neo4j); keep it.

**Bounded toolsets & single responsibility**
- One domain per server; avoid kitchen-sink.
- Engram: 37 tools are one “learning/memory” domain; consider **sub-grouping in descriptions** (e.g. “Reflection”, “Sessions”, “Search”) so clients can filter or show categories.

**MCP Gateway (multi-server)**
- Central auth, routing, rate limits, policy, audit.
- Relevant if Engram is ever deployed alongside other MCP servers in an org; not required for single-user Cursor today.

**Refs:** [MCP Best Practice](https://mcp-best-practice.github.io/mcp-best-practice/best-practice/), [Zeo – MCP server architecture](https://zeo.org/resources/blog/mcp-server-architecture-state-management-security-tool-orchestration).

---

## 4. **Orchestration and workflow patterns**

**Patterns observed in production MCP/agent systems:**
- **Planner/Orchestrator:** One tool or agent that sequences multiple tool calls (e.g. “plan → execute → record_outcome”).
- **Router / intent classifier:** Route user intent to the right subset of tools before calling.
- **Reflection / evaluator:** After a tool run, evaluate success and optionally retry or record outcome.

**Relevance to Engram:** We already encourage “get_smart_context → [follow playbook] → record_outcome.” We could add:
- A **single “run_workflow” tool** that takes a workflow name (e.g. `fix_error`, `start_task`) and runs the recommended sequence (find_skill / get_smart_context, then record_outcome), so the client makes one call instead of three.
- **Prompts** (MCP “prompts”): Predefined prompts like “Fix this error” that tell the model to call `find_skill` then `record_skill_outcome`.

---

## 5. **State management and long-running work**

**Ideas:** Server-side state caching; client-side ephemeral pointers; **async patterns** for long operations (return a handle, provide status/poll tools).

**Relevance to Engram:** Sessions are already “handles” for multi-step work. We could add:
- **Async for slow operations:** If `search_knowledge_graph` or Neo4j is slow, return a job id and a `get_job_status` / `get_job_result` tool.
- **Idempotency keys** for create/update tools (e.g. `store_solution`) to safe retries.

---

## 6. **Observability and governance**

**Ideas:** Curated server catalog, policy-as-code (e.g. OPA), **metrics** (success rate, latency, error classes), **structured audit trails** (who/what/when, with redaction).

**Relevance to Engram:** Add optional **audit logging** for tool calls (tool name, user_id, timestamp, outcome) to a table or file; add a **health/readiness** endpoint if we ever offer HTTP. For Cursor stdio, simple logging to a file or `data/` is enough.

---

## 7. **Spec and ecosystem updates (2025–2026)**

- **MCP** donated to Linux Foundation Agentic AI Foundation; **SEPs** (Specification Enhancement Proposals) as PRs.
- **Spec:** [modelcontextprotocol.io/specification/2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25).
- **MCP Apps** official extension (Jan 2026); supported in ChatGPT, Claude, Goose, VS Code.
- **Adoption:** 97M+ monthly SDK downloads, 10k+ servers; Cursor, Claude, Gemini, etc.

---

## 8. **MCP Prompts (templates for the model)**

**Idea:** Servers can expose **prompt templates** (`prompts/list`, `prompts/get`) so clients (or users via slash commands) request a pre-built message that tells the model exactly what to do.

**How it works:** Each prompt has a name, optional title/description, and **arguments** (e.g. `code`, `error_message`). `prompts/get` returns one or more messages (user/assistant, text/image/audio or embedded resources). The 2025 spec adds **icons** for prompts and supports **embedded resources** (e.g. docs or code samples in the prompt). User interaction is typically via slash commands or a prompt picker.

**Relevance to Engram:** Add prompts such as:
- **"Fix this error"** – argument: `error_message`; messages instruct the model to call `find_skill` with that message, then apply the solution and call `record_skill_outcome`.
- **"Start a task"** – argument: `task_description`; messages instruct the model to call `get_smart_context`, then optionally `create_session`, then follow any playbook returned.

This gives users (and Cursor) a one-click way to run the recommended Engram workflow without the model “forgetting” to use the MCP.

**Refs:** [MCP Concepts – Prompts](https://modelcontextprotocol.io/docs/concepts/prompts), [Spec – Prompts](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts).

---

## 9. **Streamable HTTP (replacing SSE)**

**Idea:** The old **HTTP + SSE** remote transport is deprecated. **Streamable HTTP** (spec 2025-03-26) uses a **single endpoint** (e.g. `/mcp`): POST for requests, GET for streaming when needed. SSE is used only when the server actually streams a response.

**Benefits:** Stateless servers, serverless-friendly, simpler connection handling, no long-lived dual connections. TypeScript SDK 1.10.0+ (April 2025) supports it.

**Relevance to Engram:** Today we use stdio (docker exec). If we ever expose Engram over the network (e.g. for a team or Cursor remote), implement **Streamable HTTP** instead of the legacy HTTP+SSE.

**Refs:** [Why MCP deprecated SSE](https://blog.fka.dev/llm/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/), [RFC #206](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/206).

---

## 10. **Security threats and mitigations**

**Reported threats:**
- **Tool poisoning:** Malicious instructions in tool descriptions to trick the model (e.g. exfiltrate data). Mitigation: treat tool descriptions as untrusted in sensitive hosts; keep Engram’s descriptions factual and short.
- **Rug pulls / silent redefinition:** A tool’s behavior changes after install (e.g. reroute API keys). Mitigation: pin server version; clients should notify users when tool definitions change (Cursor/VS Code are improving this).
- **Tool shadowing:** A malicious server overrides or intercepts another server’s tools (confused deputy). Mitigation: run only trusted servers; avoid overlapping tool names if running multiple MCP servers.
- **Session IDs in URLs:** Spec once mandated session IDs in URLs (logs, history, hijacking risk). Newer transports and best practice avoid this.
- **Registry hijacking:** Public MCP registries may host vulnerable or hijacked servers. Mitigation: vet servers; prefer known sources or self-host.

**Relevance to Engram:** We’re local/stdio and not in a public registry. For safety: (1) keep tool descriptions free of executable instructions, (2) document version pinning, (3) if we add HTTP, use auth and avoid session IDs in URLs.

**Refs:** [Vulnerable MCP Project](https://vulnerablemcp.info/), [Security issues in MCP ecosystem](https://arxiv.org/html/2510.16558v1).

---

## 11. **SDK and client updates (2025)**

- **TypeScript SDK 1.10.0:** Streamable HTTP transport; `McpServer` with protocol negotiation, tools/resources/prompts.
- **Python:** FastMCP-style decorators, Pydantic validation; stdio, HTTP+SSE, and Streamable HTTP.
- **VS Code (May 2025):** “MCP: Add Server” from NPM/PyPI/Docker; **encrypted secret storage** and `.env` support; **tool picker** so users choose which MCP tools the agent can use per session.

**Relevance to Engram:** Stay on a recent SDK for transport and spec alignment. If Cursor gets a tool picker like VS Code, users could enable only “Reflection” or “Sessions” to reduce noise.

---

## 12. **Performance optimization**

**Practices from production MCP servers:**
- **Caching:** Cache tool list and expensive ops (e.g. DB queries, file listings) with TTL; invalidate on change. Can cut response time from ~100ms to ~5ms.
- **Connection pooling:** Reuse DB/HTTP connections instead of creating new ones per request.
- **Parallelism:** Use `Promise.all` / `asyncio.gather` for independent tool logic or batched DB reads (e.g. 300ms → 100ms).
- **Response size:** Paginate list-style responses; use faster JSON (e.g. orjson); stream large outputs when possible.
- **Sampling (MCP-Go):** Servers can request an LLM completion from the client (e.g. for generation or reasoning); requires user approval and clear errors.
- **Tool selection at scale:** “Dynamic ReAct” and similar approaches reduce tool-loading overhead (e.g. ~50%) when hundreds/thousands of tools exist.

**Relevance to Engram:** Add caching for read-heavy tools (`get_db_stats`, `get_smart_context` result shape); ensure DB/Neo4j/Chroma use connection pooling; paginate any tool that returns long lists.

**Refs:** [Tool caching for agents](https://codesignal.com/learn/courses/efficient-mcp-agent-integration-in-typescript/lessons/tool-caching-for-agents), [MCP performance optimization](https://blog.toolboost.dev/mcp-performance-optimization), [Dynamic ReAct (arxiv)](https://arxiv.org/abs/2509.20386).

---

## Which we can apply well — estimated return

| Idea | Apply well? | Effort | Estimated return |
|------|-------------|--------|-------------------|
| **MCP Prompts** ("Fix error", "Start task") | Yes | 1–2 days | **High.** User (or Cursor) picks one prompt → model gets the exact message sequence (call find_skill / get_smart_context, then record_outcome). Fewer wrong workflows; ~1–2 fewer round-trips per task when used. |
| **Single workflow tool** (e.g. `run_workflow`) | Yes | 0.5–1 day | **Medium–high.** One call runs the recommended sequence (e.g. fix_error → find_skill + record_skill_outcome). 30–50% fewer tool round-trips for fix/start flows; more consistent adherence to the guide. |
| **Approval / dry-run for destructive ops** | Yes | ~0.5 day | **Medium (low frequency, high impact).** Add `confirm: true` or `dry_run` for any bulk/delete-style tool. Prevents accidental data loss; payoff when it matters. |
| **Tool categories in descriptions** | Yes | ~0.25 day | **Low–medium.** Add a short prefix like `[Reflection]` or `[Sessions]` to tool descriptions. Better discoverability and filtering when clients support it. |
| **Audit log for tool calls** | Yes | ~0.5 day | **Medium.** Log tool name, user_id, timestamp, outcome to a file or SQLite table. Better debugging, usage insight, and safe history. |
| **Caching for read-heavy tools** | Yes | 0.5–1 day | **Medium.** TTL cache for `get_db_stats`, heavy parts of `get_smart_context` (or list tools). 20–50% faster for repeated calls; helps under load. |
| **Security: pin version, safe descriptions** | Yes | ~0.25 day | **Low–medium.** Document “pin Engram server version” in README; quick pass to keep tool descriptions factual (no executable instructions). Lowers risk in multi-server setups. |
| MCP Apps | No (Cursor support TBD) | — | Defer until host supports. |
| Streamable HTTP | Only if we expose remote | — | Not needed while we stay stdio-only. |
| Async + poll for slow ops | Only if we add slow ops | — | Optional later if Neo4j/Chroma become slow. |
| Code-execution pattern | No (host-dependent) | — | We cannot implement; depends on Cursor/Claude. |

For **prioritized order and file locations**, see **Plan of action** below.

**Rough total:** ~3–5 days for the “apply well” set. Biggest wins: **MCP Prompts** and **single workflow tool** (correctness + fewer round-trips); **caching** and **audit log** (performance and observability).

---

## Plan of action

**Already in place**
- Cursor rule `.cursor/rules/engram-mcp-usage.mdc`: agent is told to use `get_smart_context` first, `find_skill` for errors, `record_outcome` after solving.
- `get_mcp_guide` returns structured workflows (starting task, fixing error, after solving) so the model can follow them.
- Empty-state messages and session-error hints were added in the MCP tools upgrade (branch `feature/mcp-tools-upgrade`).
- No destructive tools (no delete/clear/bulk) in the current 37 tools; dry_run is only for future bulk ops or optional safety on high-impact writes.

**Prioritized actions (in order)**

| Phase | Action | Where | Notes |
|-------|--------|--------|-------|
| 1 | Single workflow tool `run_workflow` | mcp_server.py: new tool + handler in call_tool | Input: workflow (fix_error or start_task), plus error_message or task_description. Handler calls find_skill or get_smart_context and returns instructions/summary; optionally chain record_outcome. |
| 2 | MCP Prompts (Fix this error, Start a task) | mcp_server.py: add prompts API if SDK supports | Check mcp package (>=1.26) for prompts/list and prompts/get. If supported: register two prompts with arguments. If not: document and defer or add a pseudo-prompt tool that returns the same message text. |
| 3 | Tool categories in descriptions | mcp_server.py list_tools() | Add short prefix to each tool, e.g. [Guide], [Search], [Reflection], [Sessions], [Store], [Skills]. Use same tag set as get_mcp_guide categories. |
| 4 | Audit log for tool calls | mcp_server.py: top of call_tool + helper | Log tool name, user_id (from args or default), timestamp, success/fail. Write to data/mcp_audit.log or SQLite in data/. Optional config to disable. |
| 5 | Caching for read-heavy tools | mcp_server.py: get_db_stats, get_smart_context | In-memory TTL cache (e.g. 60s) for get_db_stats; optional short TTL for get_smart_context. Invalidate on write or accept staleness. |
| 6 | Security: pin version, safe descriptions | README or docs/MCP_CURSOR.md | Add line: pin Engram MCP server version. Quick pass on tool descriptions: factual only, no executable instructions. |
| 7 | Approval / dry-run (optional) | mcp_server.py: selected write tools | Add optional dry_run or confirm to high-impact tools (e.g. store_solution, create_playbook). Low priority; no destructive tools today. |

**Dependencies**
- Phase 2 (MCP Prompts) may depend on SDK support; if Python mcp has no prompts API, do Phase 1 first and rely on run_workflow.
- Phases 3–7 can be done in any order after 1–2; 4 and 5 are independent.

**Out of scope for now**
- MCP Apps (wait for Cursor support). Streamable HTTP (only if we expose remote). Async + poll (only if we add slow ops). Code-execution (host-dependent).

---

## Quick checklist for Engram

| Idea | Effort | Impact | Notes |
|------|--------|--------|-------|
| MCP Apps (dashboard / session UI) | Medium | High | Only after Cursor supports MCP Apps |
| MCP Prompts (Fix error, Start task) | Low | High | One-click correct workflow; spec supports args, resources |
| Single workflow tool | Low | Medium | Reduces round-trips; aligns with guide |
| Approval/dry-run for destructive tools | Low | Medium | Safety |
| Tool categories in descriptions | Low | Low | Better discoverability |
| Async + poll for slow searches | Medium | Medium | If Neo4j/Chroma become slow |
| Audit log for tool calls | Low | Medium | Optional file or table |
| Streamable HTTP (if exposing remote) | Medium | Medium | Use instead of deprecated HTTP+SSE |
| Caching and pooling for read-heavy tools | Low | Medium | TTL cache, DB/Chroma pooling, pagination |
| Security: pin version, safe descriptions | Low | Medium | Avoid poisoning; document for users |
| Code-execution pattern | N/A for now | High | Depends on host support |

For **order and concrete steps**, see **Plan of action** above. Research stored in Engram via `store_web_research` (two batches); retrieve with `search_all_context` or `find_skill` (e.g. MCP cutting edge, MCP prompts, Streamable HTTP).
