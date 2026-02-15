# Cursor Rules & MCP: 4x Deeper Ideas

Deep dive from community reports, token economics, Cursor bugs, MCP spec, and crossover with Engram. Actionable ideas with effort/impact.

---

## Part 1: Cursor rules — what actually happens

### 1.1 Token economics (real numbers)

- **200k** token context typical; **~120k** practical before quality drops.
- **Always-apply rules:** ~500–1,000 tokens per 100 lines, **every** prompt, before you type.
- **3 always-apply rules** (e.g. Engram + project + coding) ≈ **1,500–3,000 tokens** burned before the conversation starts.
- Agent exploration: **50k+** tokens on large codebases; 10 messages: **20–40k**.
- **Implication:** Reducing always-apply from 3 to 1–2, or shortening them, directly frees budget for files and history.

**Idea 1 — Token audit prompt (zero code):**  
Use Ask mode once: *"Read all files in @.cursor/rules/ and estimate token count per rule. List alwaysApply: true rules and total always-applied token cost. Suggest which could become glob-scoped or agent-decided without losing effectiveness."*  
Use the output to decide what to convert.

**Idea 2 — Compress project-context to “project one-pager”:**  
Keep `project-context.mdc` always-apply but **under 50 lines**: stack, key dirs, one line each for DB/MCP. Move detailed wiring to a **separate** rule with `description: "Engram backend wiring, SQLite, Chroma, Neo4j. Apply when modifying backend startup, config, or data paths."` and `alwaysApply: false`. Saves ~200–400 tokens per request.

**Idea 3 — Engram rule: keep always, add @-ref:**  
Keep `engram-mcp-usage.mdc` as always-apply (workflow is critical). Add one line: *"Full tool list: @list_tools_compact or get_mcp_guide."* So the rule stays short and points to the MCP for details instead of inlining.

---

### 1.2 Glob bugs and workarounds (2025)

- **Multi-folder workspaces:** Globs like `**/.cursor/rules/*.mdc` or `./.cursor/rules/*.mdc` can report **no matches** even when files exist; single-folder works fine.
- **Spaces in globs:** `**/*.cpp, **/*.h` (space after comma) **fails**; `**/*.cpp,**/*.h` works. We already use no spaces; YAML list form is safer.
- **Glob rules not auto-applying:** Many users report only `alwaysApply: true` rules reliably show as “active”; glob- and description-based rules often **don’t** appear in the Active Rules tooltip and apply inconsistently across models.
- **“Apply to specific files” UI:** In some versions the field doesn’t accept input correctly (click switches to manual). Workaround: edit `.mdc` by hand (we already use YAML list).
- **Subdirectory rules:** `alwaysApply: true` in a rule under `.cursor/rules/some-subdir/` may be **ignored**; root-level rules are more reliable.

**Idea 4 — Don’t rely on globs alone for critical behavior:**  
Anything that *must* happen (e.g. “use Engram at start/end”) should stay in an **always-apply** rule. Use globs for “nice to have” (e.g. frontend/backend conventions) so if they don’t fire, you don’t lose core workflow.

**Idea 5 — Verify glob rules in this project:**  
Open a file matching `frontend/**/*.tsx` and start a chat; check the context gauge / Active Rules. If the frontend rule isn’t listed, mention it in a bug report or fall back to a stronger `description` (Agent Requested) and/or `@frontend` when working on UI.

**Idea 6 — Single-folder workspace for Engram:**  
If you use a multi-root workspace (e.g. monorepo + app), consider opening the **Engram app root only** when working on it, so globs resolve to one root and avoid known multi-folder glob bugs.

---

### 1.3 Rule priority and conflicts

- Cursor has **no explicit priority** (no “rule A overrides rule B”). Precedence is: Team > Project > User > Legacy > AGENTS.md.
- **Within** project rules, order/priority is undefined. With many rules, **alwaysApply can be ignored** in practice; some users see wrong rules applied when they @-mention a specific one.
- “Apply Intelligently” (description-based) is reported as **very unreliable** with many rules.

**Idea 7 — Fewer, sharper project rules:**  
Prefer 5–8 focused rules over 15+. Merge overlapping guidance (e.g. “don’t hardcode paths” lives in one place) so the model gets one clear voice.

**Idea 8 — Critical path in one rule:**  
Keep the **entire** “must do: get_smart_context → work → record_outcome” in a single always-apply rule (`engram-mcp-usage.mdc`) so it’s not split across files and never “loses” in an undefined priority.

---

### 1.4 AGENTS.md reality check

- **Nested AGENTS.md:** Docs say subdirectory AGENTS.md should load when the agent works in that dir; in practice **only root** AGENTS.md is reported to load.
- **Background agents:** GitHub/Slack/Web/Linear agents **do not load AGENTS.md** in some reports.
- Root AGENTS.md can load **unpredictably** (e.g. only when open or when explicitly @’d).

**Idea 9 — AGENTS.md as a short pointer, not the source of truth:**  
If you add AGENTS.md, keep it to 3–5 lines: “This project uses Engram MCP. Follow .cursor/rules/engram-mcp-usage.mdc. Stack: FastAPI + React; see .cursor/rules/project-context.mdc.” Don’t put the full workflow there; rely on `.cursor/rules/` for that so behavior doesn’t depend on AGENTS.md loading.

**Idea 10 — Explicit @AGENTS.md for important chats:**  
When starting a high-stakes or Background Agent task, add “@AGENTS.md” in the first message so the agent definitely has project context even if auto-load failed.

---

### 1.5 Team Rules (enterprise)

- **Team Rules** = cloud-managed, org-wide; recommend or require for all members.
- **Limitation:** No activation criteria (no file-type filter); all enabled rules are always active → more token burn and no “mutually exclusive” options.
- **Relevance to Engram:** If you’re on Team/Enterprise, you could push “Use Engram MCP: get_smart_context first, record_outcome after” as a Team Rule so every dev gets it without per-repo setup. Downside: no globs, so it’s all-or-nothing.

**Idea 11 — Team Rule for Engram (if on Team/Enterprise):**  
One short Team Rule: “When working in repos that use Engram MCP: call get_smart_context at task start and record_outcome at task end.” Complements project-level `.cursor/rules/` and enforces the habit org-wide.

---

### 1.6 Skills vs Rules (Cursor direction)

- **Rules** = passive, loaded up front; shape all behavior (standards, conventions).
- **Skills** = active; agent pulls full content **only when relevant** (progressive disclosure). Stored in `.cursor/skills/`, open standard (agentskills.io). In Cursor nightlies.
- **Commands** = slash-commands, one-off prompts.

**Idea 12 — Move “how to” workflows to Skills when stable:**  
When Cursor Skills are stable in release, consider turning “Fix this error” / “Start a task” into **Skills** (step-by-step procedures). Keep **rules** for “use Engram,” “don’t hardcode secrets,” “stack is FastAPI + React.” Result: rules stay small and stable; detailed workflows live in skills and load only when the agent decides they’re relevant.

**Idea 13 — Align Engram playbooks with Cursor Skills:**  
Engram playbooks (get_smart_context → follow steps) are similar in spirit to Skills. Document that “Engram playbooks = server-side; Cursor Skills = client-side.” Future: a Skill that says “Call get_smart_context and follow the returned playbook” could bridge both.

---

### 1.7 Rule generators and maintenance

- **cursorrules.org**, **cursor-rules.gputil.com**, **cursorrulesgenerator.com**: generate from repo/docs/package.json.
- **rules-gen** (npm): `npx rules-gen` — tech detection, Cursor + Windsurf, .mdc output, 100KB limit.
- **Meta-rule:** A rule that describes “how we write rules” (one concern, frontmatter, examples) so new rules stay consistent.

**Idea 14 — Run rules-gen once:**  
Run `npx rules-gen` in the repo; choose Cursor, pick stack (Python, React, etc.). Compare output to current rules; merge in any useful conventions we don’t have (e.g. testing, imports). Don’t replace Engram-specific rules.

**Idea 15 — Add a meta-rule (optional):**  
Create `.cursor/rules/rule-authoring.mdc` with `alwaysApply: false` and a strong `description`: “Apply when creating or editing Cursor rule files in .cursor/rules/. One concern per file; use YAML list for globs; keep under 500 lines; include concrete examples.” Reduces drift when someone adds a new rule.

---

## Part 2: MCP × Cursor crossover

### 2.1 MCP Prompts vs Cursor rules

- **MCP Prompts:** Server exposes `prompts/list` and `prompts/get` with arguments. In Cursor, **/ in chat** can show MCP prompts. User picks “Fix this error” → model gets the exact message sequence (call find_skill, then record_skill_outcome).
- **Cursor rules** tell the model “when in this project, do X.” **MCP Prompts** hand the model a ready-made user/assistant message set. They’re complementary: rules set the habit; prompts give one-click correct workflow.

**Idea 16 — Implement MCP Prompts on Engram (high impact):**  
Add `prompts/list` and `prompts/get` to the Engram server (if the Python SDK supports it). Two prompts: (1) **“Fix this error”** — argument `error_message`; message instructs: call find_skill with that message, apply solution, call record_skill_outcome. (2) **“Start a task”** — argument `task_description`; message instructs: call get_smart_context, optionally create_session, follow playbook. Then in Cursor, typing **/** surfaces these; user picks one and the model gets the right sequence without relying on the rule being “remembered” mid-chat.

**Idea 17 — Pseudo-prompt tool if SDK lacks prompts API:**  
If the MCP Python package doesn’t expose prompts, add a tool e.g. `get_workflow_prompt(workflow, error_message?, task_description?)` that returns the same instruction text. The rule can say: “For fix/start flows you can call get_workflow_prompt and then follow the returned steps.” Less ideal than native prompts but still improves consistency.

---

### 2.2 MCP tool picker and rule wording

- VS Code (May 2025): **tool picker** so users choose which MCP tools are available per session. Cursor may get similar.
- If users can disable tools, “Reflection” or “Sessions” might be turned off. **Rule** can still say “prefer record_outcome when available” so that when tools are enabled, behavior is correct.

**Idea 18 — Rule mentions optional tool subsets:**  
In `engram-mcp-usage.mdc` add one line: “If your client limits which Engram tools are available, still follow the workflow with whatever tools you have (e.g. get_smart_context, find_skill, record_outcome when available).” Prepares for tool picker without changing server.

---

### 2.3 Resources and rules

- We added **MCP Resources** (engram://playbook/..., engram://skill/...). Clients that support resources can load a playbook without a tool call.
- **Rule** can say: “Playbooks and skills are also available as MCP resources (engram://playbook/<id>). Use list_resources/read_resource when your client supports it.”

**Idea 19 — Document resources in the rule (already partially done):**  
Ensure the Engram rule or project-context briefly mentions that playbooks/skills are exposed as resources so the model knows it can read them via resources when available.

---

### 2.4 Caching and audit (from MCP doc)

- **Caching:** TTL cache for get_db_stats, get_smart_context (we have some). Reduces tokens if the model re-asks for stats/context.
- **Audit log:** Tool name, user_id, timestamp, outcome. Helps debug “why didn’t the model call record_outcome?” and usage patterns.

**Idea 20 — Rule: “After solving, call record_outcome” plus audit:**  
Keep the mandatory checklist in the rule. Add an audit log (if not already) so you can verify post-hoc that record_outcome is being called. If it isn’t, the rule is the place to strengthen wording; the log is the place to see the gap.

---

## Part 3: Windsurf and multi-IDE

- **Windsurf:** Uses flows and `.windsurf/context.md`; different from Cursor’s `.cursor/rules/`.
- **project-context.mdc** already says “Same context as .windsurf/rules/ (Windsurf); full wiring in .windsurf/rules/FEATURES.md.”
- **hiddentao/rules:** CLI to convert between .cursor/rules, .cursorrules, .windsurfrules.

**Idea 21 — Keep one source of truth, convert if needed:**  
Treat `.cursor/rules/` as canonical for Cursor. If you use Windsurf too, either maintain `.windsurf/` in parallel or run a conversion step (e.g. rules CLI) so Engram workflow and stack description stay in sync across IDEs.

**Idea 22 — FEATURES.md as the long-form doc:**  
Keep detailed “how the backend is wired” in `.windsurf/rules/FEATURES.md` (or a single doc referenced by both). Cursor rule “project-context” stays a one-pager that points there; avoids duplicating long content in rules.

---

## Part 4: Prioritized action list

| # | Idea | Effort | Impact | Do when |
|---|------|--------|--------|--------|
| 1 | Token audit prompt (Ask mode) | 0 | High (visibility) | Once, next sprint |
| 2 | Compress project-context; split “wiring” to agent-decided rule | Low | Medium (tokens) | When you touch rules |
| 3 | Engram rule: add @list_tools_compact / get_mcp_guide ref | Trivial | Low | Anytime |
| 4 | Don’t rely on globs for critical behavior | 0 (design) | High | Already done (Engram always-apply) |
| 5 | Verify frontend/backend glob rules in UI | Trivial | Low | Once |
| 6 | Prefer single-folder workspace for Engram | 0 (workflow) | Medium | If using multi-root |
| 7 | Fewer, sharper rules; merge overlap | Low | Medium | When adding new rules |
| 8 | Critical path in one rule (Engram) | 0 | High | Already done |
| 9 | AGENTS.md as short pointer only | Low | Low | If you add AGENTS.md |
| 10 | @AGENTS.md in first message for critical chats | 0 | Low | Optional habit |
| 11 | Team Rule for Engram (Enterprise) | Low | High (org-wide) | If on Team/Enterprise |
| 12 | Move workflows to Cursor Skills when stable | Medium | High (later) | When Skills GA |
| 13 | Document Engram playbooks vs Cursor Skills | Low | Low | Docs only |
| 14 | Run rules-gen, merge useful bits | Low | Medium | Once |
| 15 | Meta-rule for rule authoring | Low | Low | If many people edit rules |
| **16** | **MCP Prompts (Fix error, Start task)** | **1–2 d** | **High** | **Next MCP sprint** |
| 17 | Pseudo-prompt tool if no prompts API | 0.5 d | Medium | If 16 blocked by SDK |
| 18 | Rule line for tool picker / subset tools | Trivial | Low | Anytime |
| 19 | Document resources in rule | Trivial | Low | Anytime |
| 20 | Audit log + rule checklist | 0.5 d | Medium | If not already |
| 21 | Windsurf sync or conversion | Low | Medium | If using Windsurf |
| 22 | FEATURES.md as long-form; rule points to it | Low | Low | When refactoring docs |

---

## Part 5: One-paragraph summary

**Cursor rules:** Token cost of always-apply is real (500–1k per 100 lines per request). Prefer 1–2 always-apply rules (Engram + coding standards); compress project-context and move “wiring” to agent-decided. Glob-based rules are buggy in places; don’t depend on them for must-have behavior. AGENTS.md and nested/Background Agent loading are unreliable; use rules as source of truth and optional @AGENTS.md. Skills (when stable) are a good home for detailed workflows; rules for conventions and “use Engram.” Run a token audit and rules-gen once; add a meta-rule if multiple people edit rules.

**MCP × Cursor:** Biggest win is **MCP Prompts** (“Fix this error”, “Start a task”) so Cursor’s **/** gives the model the exact message sequence; implement if the SDK supports it, else pseudo-prompt tool. Document resources and optional tool subsets in the rule. Audit log helps verify record_outcome is called. Keep one source of truth for project context (e.g. .cursor/rules + FEATURES.md) and sync to Windsurf if needed.

---

---

## Part 6: Token audit (applied 2025-02)

| Rule | alwaysApply | Lines (approx) | Est. tokens/request |
|------|-------------|----------------|----------------------|
| engram-mcp-usage | true | 45 | ~225–450 |
| project-context | true | 22 | ~110–220 |
| coding-standards | true | 27 | ~135–270 |
| project-wiring | false | 12 | 0 (agent-decided) |
| frontend | false (globs) | 17 | 0 unless matching |
| python-backend | false (globs) | 17 | 0 unless matching |
| rule-authoring | false | 15 | 0 (agent-decided) |

**Always-applied total:** ~94 lines → **~470–940 tokens** per request (before: project-context was ~29 lines, so ~98 lines always → ~490–980 tokens). **Savings:** ~10–40 tokens/request by moving DB/wiring to project-wiring (agent-decided). More importantly, project-context is now a short one-pager; detailed wiring loads only when relevant.

**Changes applied:** (1) Compressed project-context; created project-wiring.mdc (agent-decided). (2) Engram rule: added tool picker and resources lines; clarified list_tools_compact/get_mcp_guide. (3) Added rule-authoring.mdc (agent-decided). (4) Globs already in YAML list form (frontend, python-backend).

---

*Sources: design.dev Cursor Rules Guide, Developer Toolkit token management, Cursor forum (globs, alwaysApply, AGENTS.md, Team Rules, Skills vs Rules), MCP_CUTTING_EDGE_IDEAS.md, CURSOR_RULES_COMPARISON.md. Last updated 2025-02.*
