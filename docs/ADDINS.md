# Add-ins Developer Guide

> **Last updated:** 2026-02-12

Add-ins extend Engram with new capabilities without modifying core code. There are three types, and they can be mixed into hybrids.

## Quick Start — Create a New Add-in

```
backend/addins/plugins/
└── my_addin/
    ├── manifest.json    ← metadata, config, permissions
    └── backend.py       ← Python logic (required)
```

### 1. Create `manifest.json`

```json
{
  "id": "my_addin",
  "name": "My Add-in",
  "version": "1.0.0",
  "description": "What it does in one sentence.",
  "author": "Your Name",
  "type": "tool",
  "entrypoint": { "backend": "backend.py" },
  "permissions": [],
  "config": { "some_setting": "default_value" },
  "hooks": { "tools": ["my_tool_name"] }
}
```

### 2. Create `backend.py`

```python
from addins.addin_interface import ToolAddin, ToolDefinition, ToolResult

class MyAddin(ToolAddin):
    name = "my_addin"
    version = "1.0.0"
    description = "What it does"
    permissions = []

    async def initialize(self) -> bool:
        return True

    async def cleanup(self) -> None:
        pass

    def get_tool_definitions(self):
        return [ToolDefinition(
            name="my_tool_name",
            description="What the LLM should know about this tool",
            parameters={"type": "object", "properties": {...}, "required": [...]}
        )]

    async def execute_tool(self, tool_name, arguments):
        # Your logic here
        return ToolResult(success=True, result={"answer": 42})

Addin = MyAddin  # Required: export as 'Addin'
```

### 3. Restart the app

Built-in add-ins are auto-seeded into the database on first load. Users enable them in **Add-ins** tab.

---

## Add-in Types

### Type 1: Tool (`tool`)

LLM-callable functions. The AI invokes them automatically when relevant.

| Field | Description |
|-------|-------------|
| `get_tool_definitions()` | Returns list of `ToolDefinition` (OpenAI function-calling format) |
| `execute_tool(name, args)` | Runs the tool, returns `ToolResult` |

**Examples:** Calculator, Dice Roller, Word Counter, Web Search

### Type 2: GUI (`gui`)

Visual panels that appear as sidebar tabs when enabled.

| Field | Description |
|-------|-------------|
| `get_mount_points()` | Where to render: `["sidebar"]`, `["toolbar"]` |
| `get_frontend_component()` | Name of the React component |
| `handle_action(action, payload)` | Backend handler for frontend actions |

**Manifest extras for GUI addins:**
```json
{
  "ui": {
    "mountPoints": ["sidebar"],
    "icon": "timer",
    "label": "My Panel"
  }
}
```

**Frontend:** Create a panel component in `frontend/src/components/addins/panels/` and register it in `AddinPanelRouter.tsx`:

```tsx
// In AddinPanelRouter.tsx
const MyPanel = lazy(() => import('./MyPanel'))

const PANELS: Record<string, ...> = {
  my_addin: MyPanel,  // key = manifest id
}
```

**Available icons** (from Lucide): `timer`, `smile`, or any — add new ones to `ADDIN_ICONS` in `Sidebar.tsx`.

**Examples:** Pomodoro Timer, Mood Journal, Image Generator

### Type 3: Interceptor (`interceptor`)

Hooks into the message pipeline. Transforms messages before/after the LLM.

| Method | When | Purpose |
|--------|------|---------|
| `before_llm(messages, context)` | Before LLM call | Translate, filter, inject context |
| `after_llm(response, context)` | After LLM response | Translate, filter, post-process |

**Examples:** Auto Translator, Code Improver

### Type 4: Hybrid (`hybrid`)

Combines any of the above. Set `addin_type = AddinType.HYBRID` and implement methods from multiple base classes.

---

## Manifest Reference

```json
{
  "id": "unique_snake_case_id",
  "name": "Display Name",
  "version": "1.0.0",
  "description": "One-line description shown in the Add-ins tab.",
  "author": "System",
  "type": "tool | gui | interceptor | hybrid",
  "entrypoint": {
    "backend": "backend.py",
    "frontend": "ComponentName"
  },
  "permissions": ["network", "storage", "memory", "graph", "search", "llm.messages"],
  "config": {
    "setting_name": "default_value"
  },
  "hooks": {
    "tools": ["tool_name_1"],
    "interceptors": ["before_llm", "after_llm"]
  },
  "ui": {
    "mountPoints": ["sidebar", "toolbar"],
    "icon": "lucide-icon-name",
    "label": "Sidebar Label"
  }
}
```

## Permissions

| Permission | Meaning |
|-----------|---------|
| `network` | Can make HTTP requests |
| `storage` | Can read/write files |
| `memory` | Access the memory system |
| `graph` | Access the knowledge graph |
| `search` | Use the search engine |
| `llm.messages` | Can read/modify messages in the pipeline |

Permissions are displayed to the user in the Add-ins tab. They're informational — enforcement is up to the add-in.

## User Experience

1. **Add-ins tab** shows all installed add-ins with rich cards
2. Users **toggle** add-ins on/off with a switch
3. **GUI addins** automatically appear as sidebar tabs when enabled
4. **Tool addins** become available to the AI when enabled
5. **Interceptor addins** hook into the pipeline when enabled
6. Built-in addins show a **"Built-in"** badge and can't be uninstalled
7. Custom addins can be **uninstalled** via the expand menu

## Built-in Add-ins

| Add-in | Type | Description |
|--------|------|-------------|
| **Calculator** | Tool | Safe math evaluation (AST-based, no eval) |
| **Dice Roller** | Tool | RPG dice notation (2d6, d20+5, etc.) |
| **Word Counter** | Tool | Text analysis: words, sentences, reading time |
| **Web Search** | Tool | Web search via Tavily/SerpAPI |
| **Auto Translator** | Interceptor | Translate messages to/from English |
| **Code Improver** | Interceptor | Enhance coding queries with context |
| **Image Generator** | GUI | DALL-E image generation panel |
| **Pomodoro Timer** | GUI | Focus timer with 25/5 work-break cycles |
| **Mood Journal** | GUI | Mood and energy tracking with emoji picker |

## Architecture

```
backend/addins/
├── addin_interface.py    # Base classes: AddinBase, ToolAddin, GUIAddin, InterceptorAddin
├── registry.py           # Global registry: register, lookup, execute tools, run interceptors
├── loader.py             # Dynamic loader: reads manifest.json, imports backend.py
├── __init__.py           # Package exports
└── plugins/              # Built-in add-ins (one folder each)
    ├── calculator/
    ├── dice_roller/
    ├── word_counter/
    ├── web_search/
    ├── auto_translator/
    ├── code_improver/
    ├── image_generator/
    ├── pomodoro/
    └── mood_journal/

backend/seed_addins.py    # Seeds built-in addins into DB per user
backend/routers/addins.py # REST API: list, install, toggle, config, uninstall

frontend/src/
├── stores/addinsStore.ts                    # Zustand store for enabled addins
├── components/addins/AddinsTab.tsx          # Add-ins management UI
└── components/addins/panels/
    ├── AddinPanelRouter.tsx                 # Maps addin ID → panel component
    ├── PomodoroPanel.tsx                    # Pomodoro Timer panel
    └── MoodPanel.tsx                        # Mood Journal panel
```

## Adding a New Icon for GUI Addins

Edit `frontend/src/components/layout/Sidebar.tsx`:

```tsx
import { Timer, Smile, Sparkles, YourIcon } from 'lucide-react'

const ADDIN_ICONS: Record<string, React.ReactNode> = {
  timer: <Timer size={18} />,
  smile: <Smile size={18} />,
  your_icon: <YourIcon size={18} />,
  default: <Sparkles size={18} />,
}
```

Then set `"icon": "your_icon"` in your manifest's `ui` section.
