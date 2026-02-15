# Cursor Rules: Latest Best Practice vs This Project

Quick comparison of current best practice (2024–2025) and our `.cursor/rules/` setup.

---

## Sources

- [Cursor Rules Guide (design.dev)](https://design.dev/guides/cursor-rules/) — modern `.mdc` system, activation modes, best practices
- [Cursor docs – Rules for AI](https://docs.cursor.com/context/rules-for-ai) — hierarchy, AGENTS.md
- Community: glob format (YAML list vs comma-separated), description quality, token usage

---

## 1. Rule system and format

| Practice | Recommendation | Our project |
|----------|----------------|-------------|
| **System** | Use `.cursor/rules/` with `.mdc` files (not legacy `.cursorrules`) | ✅ We use `.cursor/rules/*.mdc` |
| **Frontmatter** | YAML: `description`, `globs`, `alwaysApply` | ✅ All 5 rules have frontmatter |
| **One concern per file** | One topic per rule; split if >500 lines | ✅ Focused rules, all short |
| **Filenames** | kebab-case; filename = `@rule-name` for mentions | ✅ e.g. `engram-mcp-usage.mdc` → `@engram-mcp-usage` |

**Verdict:** Aligned.

---

## 2. Activation modes

Cursor supports four modes:

| Mode | When it applies | Our usage |
|------|-----------------|-----------|
| **Always Apply** | Every conversation | `engram-mcp-usage`, `project-context`, `coding-standards` (3 rules) |
| **Auto Attached** | When referenced files match `globs` | `frontend.mdc`, `python-backend.mdc` (2 rules) |
| **Agent Requested** | AI includes rule when `description` matches context | We use `description` on all; globs override for 2 |
| **Manual** | Only when user does `@rule-name` | None explicitly |

**Best practice:** Use Always Apply sparingly to save context tokens; prefer globs or a strong `description` where possible.

**Our tradeoff:** We use Always Apply for (1) Engram MCP workflow, (2) project architecture, (3) coding standards so the agent consistently sees stack, security, and “use Engram / don’t dumb down.” Reducing these could save tokens but risks the agent forgetting. Optional: move `project-context` to Agent Requested (richer `description`) and keep only `engram-mcp-usage` + `coding-standards` as Always Apply.

**Verdict:** Reasonable; optional to trim Always Apply if token budget is tight.

---

## 3. Globs format

| Practice | Recommendation | Our project |
|----------|----------------|-------------|
| **Format** | Prefer YAML list with hyphens; avoid comma-separated string (parser quirks) | We use comma-separated: `globs: frontend/**/*.ts,frontend/**/*.tsx,...` |
| **No spaces after commas** | Avoid `"*.ts, *.tsx"` | ✅ We have no spaces |
| **Recursive** | Use `**` for subdirs: `src/**/*.ts` | ✅ We use `frontend/**/*.ts`, `backend/**/*.py` |

**Recommendation:** Switch to YAML list for robustness, e.g.:

```yaml
globs:
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
  - "frontend/**/*.css"
```

**Verdict:** Small improvement available (use list form).

---

## 4. Description quality

| Practice | Recommendation | Our project |
|----------|----------------|-------------|
| **Specificity** | Specific descriptions → higher activation when Agent Requested | Descriptions are clear and specific |
| **Purpose** | AI uses `description` to decide relevance | All rules have a `description` |

**Verdict:** Good.

---

## 5. Content best practices

| Practice | Recommendation | Our project |
|----------|----------------|-------------|
| **Concrete, actionable** | Clear “do this / don’t do that” with examples | ✅ Checklists and bullet lists |
| **Reference files** | Point to canonical files instead of pasting long code | We don’t reference specific files (e.g. “follow `backend/sqlite_db.py`”) |
| **Avoid duplication** | Don’t repeat what’s already in code or linters | ✅ Rules are short, no style-guide dumps |

**Optional:** Add 1–2 references in `python-backend.mdc` and `frontend.mdc` (e.g. “Follow pattern in `backend/sqlite_db.py`” or “See `frontend/src/services/` for API layer”).

**Verdict:** Solid; optional to add file references.

---

## 6. AGENTS.md and hierarchy

| Practice | Recommendation | Our project |
|----------|----------------|-------------|
| **Hierarchy** | Team > Project (`.cursor/rules/`) > User > Legacy (`.cursorrules`) > AGENTS.md | We use only project rules |
| **AGENTS.md** | Simple always-on instructions in project root; no frontmatter | We don’t have AGENTS.md |

**Optional:** Add a short `AGENTS.md` in the repo root: 2–3 sentences on “This project uses Engram MCP; follow `.cursor/rules/engram-mcp-usage.mdc`. Stack: FastAPI + React; see `.cursor/rules/project-context.mdc`.” Gives a single “start here” for any agent that reads the root.

**Verdict:** Not required; AGENTS.md is a nice optional addition.

---

## 7. Organization and version control

| Practice | Recommendation | Our project |
|----------|----------------|-------------|
| **Version control** | Commit `.cursor/rules/` | ✅ In repo |
| **Subdirectories** | Optional: e.g. `rules/frontend/`, `rules/backend/` | Flat list of 5 files |

**Verdict:** Fine as-is; subdirs are optional.

---

## 8. Summary

| Area | Status | Action |
|------|--------|--------|
| Rule system & format | ✅ Aligned | None |
| Activation modes | ✅ Reasonable | Optional: reduce Always Apply if needed |
| Globs | ⚠️ Minor | Prefer YAML list for `globs` in frontend/backend rules |
| Descriptions | ✅ Good | None |
| Content | ✅ Good | Optional: add 1–2 file references |
| AGENTS.md | Optional | Add short root AGENTS.md if desired |
| Version control / layout | ✅ Good | None |

---

## 9. Cutting-edge / extra ideas

- **Rule generator:** Cursor has “New Cursor Rule” / rule generators; we can add or refine rules when we see repeated mistakes.
- **Cursor 2.0 glob bug:** Some users report glob-based rules not auto-loading in 2.0; if a rule doesn’t fire, try `@rule-name` or tighten `description` for Agent Requested.
- **Skills vs rules:** Rules = project conventions; Skills = task-specific workflows (e.g. SKILL.md). We use both (rules + Engram MCP / playbooks); no change needed.
- **Meta-rule:** A “how to write rules” rule can help keep new rules consistent (description, globs, one concern). Optional.

---

*Last updated: 2025-02; re-check Cursor docs and design.dev for later changes.*
