# Skill Voyager — Autonomous Skill Learning Addin

Voyager-style autonomous skill learning system. Observes every conversation, builds a library of verified response strategies, composes simple skills into complex ones, and uses LLM-based self-evaluation.

## How It Works

### Skill Lifecycle
```
candidate → verified (confidence ≥0.6, 2+ successes) → mastered (≥0.85, 5+ successes) → deprecated (<0.2)
```

### Message Pipeline Integration
1. **Before LLM** — Classifies the user's query and injects a matching skill strategy as a system message
2. **After LLM** — Evaluates the response quality, extracts new skills from successful conversations, reflects on failures

### Components
| File | Purpose |
|------|---------|
| `backend.py` | Main entry point. Wires everything together. `before_llm` / `after_llm` hooks. |
| `skill_store.py` | SQLite-backed skill library (`data/learning/skill_voyager.db`). CRUD, search, confidence tracking. |
| `query_classifier.py` | Regex + keyword classifier. Types: factual, research, creative, technical, conversational. |
| `evaluator.py` | Response quality scoring. Uses LLM or heuristic fallback. Updates skill confidence. |
| `skill_extractor.py` | Extracts new skill candidates from successful conversations. |
| `curriculum.py` | Proposes new skills from gaps. Seeds templates, composes verified skills into Level 2+. |
| `self_reflection.py` | Reflects on WHY skills failed. Evolves strategy text in-place. UCB1 exploration bonus. |

## LLM Provider Settings

Skill Voyager uses a **dedicated LLM** for evaluation, reflection, and extraction — independent from the main chat LLM. This keeps costs low (uses cheap/local models) and doesn't interfere with chat.

### Setup (Settings → Addins → Skill Voyager → LLM Provider)

**Option 1: Auto-detect (default)**
- Set Provider to "Auto-detect (LM Studio / Ollama)"
- Start LM Studio on port 1234 or Ollama on port 11434
- Click **Test** to verify connection
- Click **Save**

**Option 2: LM Studio**
- Set Provider to "LM Studio"
- Base URL: `http://localhost:1234` (default)
- Model: leave blank to use whatever model is loaded
- Click **Test** → should show "Connected" with model count
- Click **Save**

**Option 3: Ollama**
- Set Provider to "Ollama"
- Base URL: `http://localhost:11434` (default)
- Model: e.g. `llama3.2` or leave blank
- Click **Test** → **Save**

**Option 4: OpenAI**
- Set Provider to "OpenAI"
- API Key: your `sk-...` key
- Model: `gpt-4o-mini` (recommended — cheap and fast)
- Click **Save**

**Option 5: Anthropic**
- Set Provider to "Anthropic"
- API Key: your `sk-ant-...` key
- Model: `claude-3-haiku-20240307` (recommended — cheapest)
- Click **Save**

### What happens without an LLM?
Everything still works — the evaluator falls back to heuristic scoring (response length, structure, keyword overlap). Skills are still learned, just with less accurate quality signals.

## Learning Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Auto-learn from conversations | ON | Extract skills from every conversation automatically |
| Curriculum engine | ON | Propose new skills from gaps in the library |
| Self-reflection on failures | ON | Analyze why skills failed and evolve strategies |
| Min confidence to apply skill | 0.60 | Only inject skills above this confidence threshold |
| Evaluate every N messages | 1 | How often to run quality evaluation |
| Max skills in library | 200 | Cap to prevent unbounded growth |

## Dashboard (Sidebar → Skill Voyager)

The GUI panel shows:
- **Stats** — Total skills, verified/mastered/deprecated counts, messages processed
- **Skill Library** — Browse, search, filter by state/type, view composition trees
- **Recent Evaluations** — Quality scores for recent conversations
- **Reflections** — Why skills failed and how strategies evolved
- **Exploration Map** — UCB1 exploration bonuses per query type

## API Actions

All actions go through `POST /api/addins/skill_voyager/action`:

| Action | Payload | Description |
|--------|---------|-------------|
| `get_dashboard` | — | Full dashboard data |
| `get_skills` | `{state?, skill_type?}` | Filter skills |
| `get_skill_tree` | `{skill_id}` | Composition tree |
| `add_skill` | `{name, strategy, ...}` | Manually add a skill |
| `delete_skill` | `{skill_id}` | Remove a skill |
| `run_curriculum` | — | Generate skill proposals |
| `test_llm` | `{provider, base_url, ...}` | Test LLM connection |
| `update_settings` | `{key: value, ...}` | Save settings |
| `toggle_auto_learn` | — | Toggle auto-learn |
| `toggle_curriculum` | — | Toggle curriculum |
| `get_exploration_map` | — | UCB1 exploration data |
| `get_reflections` | — | Recent failure reflections |
| `get_revision_history` | `{skill_id}` | Strategy evolution log |
