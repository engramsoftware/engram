"""
MCP Server - Exposes chat app features to Windsurf/Cascade.

Provides tools for:
- Memory search and evolution
- Knowledge graph queries
- Code entity extraction
- Adaptive context retrieval
- Smart-to-dumb model skill transfer via playbooks

Run with: python mcp_server.py
Then add to Windsurf's MCP configuration.
"""

import asyncio
import json
import sys
import logging
from typing import Any, Dict, List, Optional

# Model capability tiers - used to auto-detect if a model is "smart" or "weak"
# Smart models CREATE playbooks. Weak models CONSUME them.
# Models not in either list default to "unknown" (treated as medium).
SMART_MODELS = {
    "claude-3-opus", "claude-3.5-sonnet", "claude-3.5-haiku", "claude-4",
    "gpt-4", "gpt-4o", "gpt-4-turbo", "gpt-4.1", "gpt-5", "o1", "o3", "o4-mini",
    "gemini-pro", "gemini-ultra", "gemini-2.0", "gemini-2.5-pro",
    "deepseek-v3", "deepseek-r1",
    "codex",
}
WEAK_MODELS = {
    "llama-3", "llama-3.1", "llama-3.2", "llama-3.3", "llama-4",
    "mistral", "mistral-7b", "mistral-small", "mixtral",
    "gemma", "gemma-2", "gemma-3",
    "phi-3", "phi-4", "phi-4-mini",
    "qwen-2.5", "qwen-3",
    "codellama", "starcoder", "starcoder2",
    "tinyllama", "orca-mini",
}

def detect_model_tier(model_name: str) -> str:
    """Detect if a model is smart, weak, or unknown based on its name.
    
    Args:
        model_name: The model identifier string (e.g., 'claude-3.5-sonnet', 'llama-3.1-8b').
        
    Returns:
        'smart', 'weak', or 'unknown'.
    """
    if not model_name:
        return "unknown"
    name_lower = model_name.lower().strip()
    # Check smart models (partial match to handle versions like 'gpt-4o-2024-05-13')
    for smart in SMART_MODELS:
        if smart in name_lower:
            return "smart"
    # Check weak models
    for weak in WEAK_MODELS:
        if weak in name_lower:
            return "weak"
    return "unknown"

# MCP SDK
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("Installing MCP SDK...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "mcp"])
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

# Add backend to path
import os
backend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
sys.path.insert(0, backend_path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize MCP server
server = Server("chatapp-coding-enhancer")

# Lazy-loaded components
_code_extractor = None
_adaptive_retrieval = None
_graph_store = None
_memory_store = None
_skill_store = None
_session_manager = None
_reflection_system = None


def get_code_extractor():
    global _code_extractor
    if _code_extractor is None:
        from knowledge_graph.code_extractor import CodeExtractor
        _code_extractor = CodeExtractor()
    return _code_extractor


def get_adaptive_retrieval():
    global _adaptive_retrieval
    if _adaptive_retrieval is None:
        from pipeline.adaptive_retrieval import AdaptiveRetrieval
        _adaptive_retrieval = AdaptiveRetrieval()
    return _adaptive_retrieval


def get_graph_store():
    """Get Neo4j graph store if configured."""
    global _graph_store
    if _graph_store is None:
        try:
            from knowledge_graph.graph_store import Neo4jGraphStore
            from config import get_settings
            settings = get_settings()
            if settings.neo4j_uri:
                _graph_store = Neo4jGraphStore(
                    uri=settings.neo4j_uri,
                    username=settings.neo4j_username,
                    password=settings.neo4j_password
                )
        except Exception as e:
            logger.warning(f"Graph store not available: {e}")
    return _graph_store


def get_memory_store():
    """Get memory store if configured."""
    global _memory_store
    if _memory_store is None:
        try:
            from memory.memory_store import MemoryStore
            _memory_store = MemoryStore()
        except Exception as e:
            logger.warning(f"Memory store not available: {e}")
    return _memory_store


def get_skill_store():
    """Get skill store."""
    global _skill_store
    if _skill_store is None:
        try:
            from skills.skill_system import get_skill_store as _get_ss
            _skill_store = _get_ss()
        except Exception as e:
            logger.warning(f"Skill store not available: {e}")
    return _skill_store


def get_session_manager():
    """Get session manager."""
    global _session_manager
    if _session_manager is None:
        try:
            from pipeline.session_continuity import get_session_manager as _get_sm
            _session_manager = _get_sm()
        except Exception as e:
            logger.warning(f"Session manager not available: {e}")
    return _session_manager


def get_reflection_system():
    """Get reflection system."""
    global _reflection_system
    if _reflection_system is None:
        try:
            from pipeline.reflection_system import get_reflection_system as _get_rs
            _reflection_system = _get_rs()
        except Exception as e:
            logger.warning(f"Reflection system not available: {e}")
    return _reflection_system


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available tools for Windsurf."""
    return [
        # IMPORTANT: This should be the FIRST tool - helps models understand how to use this MCP
        Tool(
            name="get_mcp_guide",
            description="START HERE! Get a guide on how to use this MCP server effectively. Shows recommended workflows, which tools work without external dependencies, and common use cases. Call this first if you're unsure how to use the Engram coding enhancer.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="extract_code_entities",
            description="Extract functions, classes, errors, and other entities from code. Useful for understanding code structure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The code to analyze"
                    },
                    "language": {
                        "type": "string",
                        "description": "Programming language (python, javascript, typescript). Auto-detected if not provided.",
                        "enum": ["python", "javascript", "typescript", "unknown"]
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="analyze_query_complexity",
            description="Analyze a coding query to determine what context is needed. Helps decide if you need to search for more info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The user's coding question or request"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="summarize_code",
            description="Create a compressed summary of code (functions, classes, imports). Useful for storing code context efficiently.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The code to summarize"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="search_knowledge_graph",
            description="Search the knowledge graph for related entities, past solutions, and connections. Requires Neo4j to be configured.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (technologies, errors, concepts)"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID for filtering (default: 'windsurf')",
                        "default": "windsurf"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="search_memories",
            description="Search past memories for relevant context. Requires ChromaDB to be configured.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID for filtering (default: 'windsurf')",
                        "default": "windsurf"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 5)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_retrieval_strategy",
            description="Get recommended retrieval strategy for a query. Returns which sources to check (memory, graph, search, web).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The user's query"
                    }
                },
                "required": ["query"]
            }
        ),
        # WRITE TOOLS
        Tool(
            name="store_memory",
            description="Store a memory/insight for future retrieval. Use this to remember solutions, patterns, user preferences, or important context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The memory content to store"
                    },
                    "memory_type": {
                        "type": "string",
                        "description": "Type of memory",
                        "enum": ["fact", "preference", "decision", "experience", "negative"],
                        "default": "fact"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID (default: 'windsurf')",
                        "default": "windsurf"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for categorization"
                    }
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="store_code_entity",
            description="Store a code entity (function, class, pattern) in the knowledge graph for relationship tracking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the entity (function name, class name, etc.)"
                    },
                    "entity_type": {
                        "type": "string",
                        "description": "Type of entity",
                        "enum": ["function", "class", "method", "module", "error", "pattern", "library"]
                    },
                    "description": {
                        "type": "string",
                        "description": "What this entity does"
                    },
                    "code_snippet": {
                        "type": "string",
                        "description": "Optional code snippet or signature"
                    },
                    "related_to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of related entities (dependencies, parent class, etc.)"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID (default: 'windsurf')",
                        "default": "windsurf"
                    }
                },
                "required": ["name", "entity_type"]
            }
        ),
        Tool(
            name="store_solution",
            description="Store a complete solution with problem context. Links the error/problem to the solution in the knowledge graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "problem": {
                        "type": "string",
                        "description": "The problem or error that was solved"
                    },
                    "solution": {
                        "type": "string",
                        "description": "The solution that fixed it"
                    },
                    "code_before": {
                        "type": "string",
                        "description": "Optional: code before the fix"
                    },
                    "code_after": {
                        "type": "string",
                        "description": "Optional: code after the fix"
                    },
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Technologies involved (python, react, neo4j, etc.)"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID (default: 'windsurf')",
                        "default": "windsurf"
                    }
                },
                "required": ["problem", "solution"]
            }
        ),
        Tool(
            name="link_entities",
            description="Create a relationship between two entities in the knowledge graph. Supports any semantic label (e.g. 'uses', 'lives_in', 'prefers', 'built_with', 'depends_on').",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_entity": {
                        "type": "string",
                        "description": "Name of the source entity"
                    },
                    "to_entity": {
                        "type": "string",
                        "description": "Name of the target entity"
                    },
                    "relationship": {
                        "type": "string",
                        "description": "Semantic relationship label (e.g. 'uses', 'lives_in', 'prefers', 'built_with', 'depends_on', 'solves', 'causes')"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID (default: 'windsurf')",
                        "default": "windsurf"
                    }
                },
                "required": ["from_entity", "to_entity", "relationship"]
            }
        ),
        # SKILLS SYSTEM
        Tool(
            name="find_skill",
            description="CALL THIS FIRST for any error or problem! Searches all databases for existing solutions. Returns code templates and past approaches. Auto-injects related context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The problem, error message, or task description"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Optional: current file path for context"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="create_skill",
            description="Create a new reusable skill from a successful solution. Use after solving a problem that might recur.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short name for the skill"
                    },
                    "description": {
                        "type": "string",
                        "description": "What problem this skill solves"
                    },
                    "triggers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Regex patterns that should trigger this skill (e.g., 'TypeError', 'CORS')"
                    },
                    "solution_text": {
                        "type": "string",
                        "description": "Explanation of the solution"
                    },
                    "code_template": {
                        "type": "string",
                        "description": "Code template for the fix"
                    },
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Related technologies (python, react, etc.)"
                    }
                },
                "required": ["name", "description", "triggers", "solution_text"]
            }
        ),
        Tool(
            name="record_skill_outcome",
            description="Record whether a skill worked or not. Helps improve skill confidence over time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "ID of the skill that was used"
                    },
                    "successful": {
                        "type": "boolean",
                        "description": "Whether the skill solved the problem"
                    }
                },
                "required": ["skill_id", "successful"]
            }
        ),
        # SESSION CONTINUITY
        Tool(
            name="create_session",
            description="Create a persistent task session that can be resumed later. Use for complex multi-step tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "What you're trying to accomplish"
                    },
                    "task_goal": {
                        "type": "string",
                        "description": "The end goal/success criteria"
                    },
                    "plan_steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Planned steps to complete the task"
                    }
                },
                "required": ["task_description", "task_goal"]
            }
        ),
        Tool(
            name="get_resumable_sessions",
            description="Get list of sessions that can be resumed. Shows in-progress tasks from previous conversations.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="resume_session",
            description="Get full context to resume a previous session. Returns progress, discoveries, and working files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID of the session to resume"
                    }
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="update_session",
            description="Update session progress - advance steps, add discoveries, checkpoint progress.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID"
                    },
                    "advance_step": {
                        "type": "boolean",
                        "description": "Mark current step complete and advance"
                    },
                    "step_summary": {
                        "type": "string",
                        "description": "Summary of what was accomplished in this step"
                    },
                    "add_file": {
                        "type": "string",
                        "description": "Add a file to the working set"
                    },
                    "checkpoint": {
                        "type": "boolean",
                        "description": "Create a checkpoint of current progress"
                    }
                },
                "required": ["session_id"]
            }
        ),
        # REFLECTION SYSTEM
        Tool(
            name="record_outcome",
            description="IMPORTANT: Call this after completing ANY task! Records success/failure to improve future suggestions. Triggers auto-learning and skill generation. Required for the system to learn.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "What was attempted"
                    },
                    "solution_applied": {
                        "type": "string",
                        "description": "The solution that was tried"
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Result of the attempt",
                        "enum": ["success", "partial_success", "failure"]
                    },
                    "error_if_failed": {
                        "type": "string",
                        "description": "Error message if it failed"
                    },
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Technologies involved"
                    },
                    "skills_used": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs of skills that were used"
                    }
                },
                "required": ["task_description", "solution_applied", "outcome"]
            }
        ),
        Tool(
            name="get_insights",
            description="Get learning insights from past outcomes. Shows patterns, anti-patterns, and improvement suggestions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional: filter insights by relevance to query"
                    },
                    "reflect_hours": {
                        "type": "integer",
                        "description": "Hours of history to analyze (default: 24)",
                        "default": 24
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_reflection_stats",
            description="Get statistics on outcomes - success rates, technology breakdown, skills effectiveness.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        # ADVANCED FEATURES
        Tool(
            name="generate_skill_from_outcome",
            description="Use LLM to generate a reusable skill from a successful problem/solution. Creates triggers and code templates automatically.",
            inputSchema={
                "type": "object",
                "properties": {
                    "problem": {
                        "type": "string",
                        "description": "The problem that was solved"
                    },
                    "solution": {
                        "type": "string", 
                        "description": "How it was solved"
                    },
                    "code": {
                        "type": "string",
                        "description": "Code used in the solution (optional)"
                    },
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Technologies involved"
                    }
                },
                "required": ["problem", "solution"]
            }
        ),
        Tool(
            name="find_related_sessions",
            description="Find past sessions related to a task. Useful when starting work to get context from similar past work.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "Description of the current task"
                    },
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Technologies being used"
                    }
                },
                "required": ["task_description"]
            }
        ),
        Tool(
            name="get_experiment_stats",
            description="Get A/B testing statistics for skills. Shows which skills perform better.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_auto_learning_status",
            description="Get status of automatic skill learning. Shows pattern clusters, auto-generated skills, and thresholds.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        # 3-DATABASE SYSTEM TOOLS
        Tool(
            name="store_user_interaction",
            description="Store a user request/message for future reference. Automatically extracts keywords, technologies, and problem type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_message": {
                        "type": "string",
                        "description": "The user's message or request"
                    },
                    "message_type": {
                        "type": "string",
                        "description": "Type: question, request, feedback, followup",
                        "default": "request"
                    },
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Technologies involved"
                    }
                },
                "required": ["user_message"]
            }
        ),
        Tool(
            name="store_ai_reasoning",
            description="Store AI reasoning/thought process for a task. Use this to remember HOW you approached a problem for future reference.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_context": {
                        "type": "string",
                        "description": "What problem was being solved"
                    },
                    "reasoning_type": {
                        "type": "string",
                        "description": "Type: analysis, planning, debugging, decision, implementation, research, reflection",
                        "enum": ["analysis", "planning", "debugging", "decision", "implementation", "research", "reflection"]
                    },
                    "thought_process": {
                        "type": "string",
                        "description": "The actual reasoning/thoughts"
                    },
                    "decision": {
                        "type": "string",
                        "description": "What was decided"
                    },
                    "approach_summary": {
                        "type": "string",
                        "description": "High-level approach taken"
                    },
                    "key_insights": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key insights discovered"
                    },
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Technologies involved"
                    }
                },
                "required": ["task_context", "reasoning_type", "thought_process", "decision", "approach_summary"]
            }
        ),
        Tool(
            name="search_past_reasoning",
            description="Search AI's past reasoning to find how similar problems were approached. Returns relevant thought processes and decisions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for (problem description, keywords, etc.)"
                    },
                    "reasoning_type": {
                        "type": "string",
                        "description": "Filter by type: analysis, planning, debugging, decision, implementation",
                        "enum": ["analysis", "planning", "debugging", "decision", "implementation", "research", "reflection"]
                    },
                    "only_successful": {
                        "type": "boolean",
                        "description": "Only return reasoning that led to success",
                        "default": False
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="search_user_history",
            description="Search past user interactions to find similar requests and how they were resolved.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for"
                    },
                    "problem_type": {
                        "type": "string",
                        "description": "Filter by type: bug, feature, refactor, question"
                    },
                    "only_resolved": {
                        "type": "boolean",
                        "description": "Only return resolved interactions",
                        "default": False
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="search_all_context",
            description="RECOMMENDED: Search ALL databases at once (past requests, AI reasoning, skills, solutions). Call this at the START of complex tasks to find relevant past work and approaches.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_db_stats",
            description="Get statistics from all 3 databases (knowledge, user interactions, AI reasoning).",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        # SMART MODEL → DUMB MODEL SKILL TRANSFER TOOLS
        Tool(
            name="create_playbook",
            description="Create a step-by-step playbook that weaker models can follow mechanically. Smart models should call this after solving complex tasks to teach dumb models how to do it. Includes steps, code templates, decision trees, and guardrails.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short name like 'add-api-endpoint' or 'fix-import-error'"},
                    "description": {"type": "string", "description": "What task this playbook solves"},
                    "task_type": {"type": "string", "description": "Category: add-feature, fix-bug, refactor, setup, test, deploy"},
                    "steps": {
                        "type": "array",
                        "description": "Ordered steps. Each step: {step: number, action: 'what to do', template: 'code template with {{placeholders}}', verify: 'how to check it worked'}",
                        "items": {"type": "object"}
                    },
                    "decision_tree": {
                        "type": "object",
                        "description": "Conditional logic: {'condition_name': {'yes': 'do this', 'no': 'do that'}}"
                    },
                    "code_templates": {
                        "type": "object",
                        "description": "Named code templates: {'template_name': 'code with {{placeholders}}'}"
                    },
                    "guardrails": {
                        "type": "array",
                        "description": "DO/DON'T rules: ['DO: use async/await', 'DON'T: hardcode secrets']",
                        "items": {"type": "string"}
                    },
                    "examples": {
                        "type": "array",
                        "description": "Input/output examples: [{'input': '...', 'output': '...'}]",
                        "items": {"type": "object"}
                    },
                    "technologies": {
                        "type": "array",
                        "description": "Related technologies",
                        "items": {"type": "string"}
                    },
                    "difficulty": {
                        "type": "string",
                        "description": "easy, medium, or hard",
                        "enum": ["easy", "medium", "hard"]
                    }
                },
                "required": ["name", "description", "steps"]
            }
        ),
        Tool(
            name="get_smart_context",
            description="GET HELP FOR YOUR TASK! Returns playbooks, skills, solutions, and guardrails matching your task. Weak/free models should call this FIRST to get step-by-step instructions from smart model sessions. Returns everything needed to complete the task without advanced reasoning.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {"type": "string", "description": "What you're trying to do"},
                    "technologies": {
                        "type": "array",
                        "description": "Technologies involved",
                        "items": {"type": "string"}
                    }
                },
                "required": ["task_description"]
            }
        ),
        Tool(
            name="assess_task_difficulty",
            description="Analyze a task to determine if a weak/free model can handle it or if it needs a smart model. Returns difficulty rating and whether playbooks exist to help.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {"type": "string", "description": "The task to assess"},
                    "current_model": {"type": "string", "description": "Optional: which model is currently running"}
                },
                "required": ["task_description"]
            }
        ),
        Tool(
            name="record_playbook_outcome",
            description="Record whether a playbook worked when used by a model. Helps track which playbooks are reliable for weak models.",
            inputSchema={
                "type": "object",
                "properties": {
                    "playbook_id": {"type": "string", "description": "ID of the playbook used"},
                    "successful": {"type": "boolean", "description": "Whether the playbook led to success"},
                    "model_used": {"type": "string", "description": "Which model used the playbook (e.g., 'llama-3', 'mistral')"}
                },
                "required": ["playbook_id", "successful"]
            }
        ),
        Tool(
            name="list_tools_compact",
            description="Get a minimal list of all available tools with just names and one-line descriptions. Uses far fewer tokens than loading all tool schemas. Ideal for models with small context windows.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="store_web_research",
            description="IMPORTANT: Call this after ANY web research! Saves research findings (URLs, summaries, key takeaways) to the knowledge DB so they can be found later. Prevents re-researching the same topics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "What was being researched (e.g., 'Python docstring best practices')"},
                    "urls": {
                        "type": "array",
                        "description": "URLs that were visited",
                        "items": {"type": "string"}
                    },
                    "findings": {"type": "string", "description": "Summary of what was learned - key takeaways, best practices, code patterns"},
                    "technologies": {
                        "type": "array",
                        "description": "Related technologies",
                        "items": {"type": "string"}
                    },
                    "actionable_items": {
                        "type": "array",
                        "description": "Concrete things to do based on the research",
                        "items": {"type": "string"}
                    }
                },
                "required": ["topic", "findings"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls from Windsurf."""
    
    # Track context for auto-injection
    auto_context = None
    
    try:
        # AUTO-LOG: Store every tool call as a user interaction (except meta tools)
        meta_tools = ("get_mcp_guide", "get_db_stats", "store_user_interaction", "store_ai_reasoning", 
                      "search_all_context", "search_past_reasoning", "search_user_history")
        
        if name not in meta_tools:
            try:
                from mcp_databases import get_user_interactions_db
                user_db = get_user_interactions_db()
                
                # Build interaction message from tool call
                arg_summary = ", ".join(f"{k}={str(v)[:50]}" for k, v in arguments.items())
                interaction_msg = f"Tool: {name}({arg_summary})"
                
                # Extract technologies from arguments
                technologies = arguments.get("technologies", [])
                query_text = arguments.get("query", "") or arguments.get("task_description", "") or arguments.get("problem", "")
                
                if not technologies and query_text:
                    tech_patterns = ['python', 'javascript', 'typescript', 'react', 'fastapi', 'mongodb', 'sqlite', 'vue', 'angular', 'node', 'express', 'django', 'flask']
                    technologies = [t for t in tech_patterns if t in query_text.lower()]
                
                user_db.add_interaction(
                    user_message=interaction_msg,
                    message_type="tool_call",
                    technologies=technologies
                )
                
                # AUTO-CONTEXT: Inject relevant context for problem-solving tools
                problem_tools = ("find_skill", "create_skill", "record_outcome", "generate_skill_from_outcome", 
                                 "store_solution", "create_session")
                if name in problem_tools and query_text:
                    try:
                        from mcp_databases import get_unified_search
                        search = get_unified_search()
                        auto_context = search.find_relevant_context(query_text, max_items=3)
                    except Exception:
                        pass
                        
            except Exception as e:
                logger.debug(f"Auto-log failed: {e}")
        
        # GUIDE - Help dumb models understand how to use this MCP
        if name == "get_mcp_guide":
            guide = {
                "welcome": "Engram Coding Enhancer MCP - 37 tools for AI coding memory, learning & skill transfer",
                "quick_start": [
                    "1. FIRST: Call get_smart_context with your task - get playbooks, skills, and solutions",
                    "2. IF PLAYBOOK FOUND: Follow it step by step - do NOT improvise",
                    "3. FOR ERRORS: Call find_skill with the error message to get solutions",
                    "4. AFTER FIXING: Call record_outcome to help the system learn and auto-generate playbooks",
                    "5. FOR NEW TASKS: Call create_session to track multi-step work"
                ],
                "smart_model_workflow": [
                    "Smart models (Claude, GPT-4) should CREATE knowledge for weaker models:",
                    "1. Solve the task normally",
                    "2. Call create_playbook with step-by-step instructions, code templates, and guardrails",
                    "3. Call record_outcome - this also auto-generates basic playbooks",
                    "4. Future weak model sessions will find and follow these playbooks automatically"
                ],
                "weak_model_workflow": [
                    "Weak/free models (Llama, Mistral, Gemma) should CONSUME knowledge:",
                    "1. Call get_smart_context({task_description: 'your task'}) FIRST",
                    "2. If a playbook is returned, follow each step exactly - do NOT skip or improvise",
                    "3. Call record_playbook_outcome when done",
                    "4. If no playbook exists, call assess_task_difficulty to check if you can handle it",
                    "5. Use list_tools_compact instead of get_mcp_guide to save tokens"
                ],
                "tool_categories": {
                    "guide": ["get_mcp_guide", "list_tools_compact (token-efficient)"],
                    "smart_to_dumb_transfer": [
                        "get_smart_context - GET HELP! Returns playbooks + skills for your task (CALL FIRST)",
                        "create_playbook - Save step-by-step instructions for weak models",
                        "assess_task_difficulty - Check if weak model can handle a task",
                        "record_playbook_outcome - Report if a playbook worked",
                        "list_tools_compact - Minimal tool list (saves tokens)"
                    ],
                    "search": [
                        "find_skill - Find solutions by error/problem",
                        "search_all_context - BEST: unified search across ALL databases",
                        "search_past_reasoning - How AI approached similar problems",
                        "search_user_history - Past user requests and resolutions",
                        "search_knowledge_graph - Solutions database",
                        "search_memories - Stored facts/context"
                    ],
                    "store": [
                        "store_web_research - Save web research findings (CALL AFTER ANY RESEARCH)",
                        "store_solution - Save problem->solution pair",
                        "store_memory - Save facts/context",
                        "store_ai_reasoning - Save HOW you approached a problem",
                        "store_user_interaction - Save user request (AUTO-CALLED)",
                        "store_code_entity - Save code patterns",
                        "link_entities - Create relationships"
                    ],
                    "skills": [
                        "find_skill - Search existing skills",
                        "create_skill - Manually create a skill",
                        "record_skill_outcome - Report if skill worked",
                        "generate_skill_from_outcome - LLM generates skill"
                    ],
                    "sessions": [
                        "create_session - Start multi-step task",
                        "get_resumable_sessions - List incomplete tasks",
                        "resume_session - Continue previous work",
                        "update_session - Update progress",
                        "find_related_sessions - Find similar past work"
                    ],
                    "reflection": [
                        "record_outcome - Log success/failure (triggers auto-learning + auto-playbook)",
                        "get_insights - AI improvement suggestions",
                        "get_reflection_stats - Success rates by technology",
                        "get_experiment_stats - A/B test results",
                        "get_auto_learning_status - Auto-skill generation status"
                    ],
                    "analysis": [
                        "analyze_query_complexity - Adaptive complexity analysis",
                        "get_retrieval_strategy - Smart retrieval recommendations",
                        "extract_code_entities - Parse code structure",
                        "summarize_code - Compress code"
                    ],
                    "stats": [
                        "get_db_stats - All database statistics"
                    ]
                },
                "databases": {
                    "1_knowledge": "data/mcp_knowledge.db - Skills, solutions, memories, playbooks",
                    "2_user_interactions": "data/user_interactions.db - User requests (auto-logged)",
                    "3_ai_reasoning": "data/ai_reasoning.db - AI thought patterns"
                },
                "common_workflows": {
                    "starting_any_task": [
                        "1. get_smart_context({task_description: 'your task'}) - check for playbooks",
                        "2. If playbook found: follow it step by step",
                        "3. If no playbook: search_all_context({query: 'your task'})",
                        "4. If multi-step: create_session({...})"
                    ],
                    "fixing_an_error": [
                        "1. find_skill({query: 'the error message'})",
                        "2. If skill found, apply solution",
                        "3. record_skill_outcome({skill_id: '...', successful: true/false})",
                        "4. If no skill: fix it, then record_outcome({...})"
                    ],
                    "after_solving_anything": [
                        "1. record_outcome({task_description, solution_applied, outcome: 'success'}) - auto-generates playbook",
                        "2. For complex tasks: create_playbook with detailed steps, templates, guardrails",
                        "3. Optionally: store_ai_reasoning to save HOW you solved it"
                    ],
                    "teaching_weak_models": [
                        "1. Solve the task with a smart model",
                        "2. create_playbook({name, description, steps, code_templates, guardrails})",
                        "3. Next time a weak model gets this task, get_smart_context returns the playbook"
                    ]
                },
                "auto_features": [
                    "User interactions are AUTO-LOGGED on every tool call",
                    "Skills auto-generate after 3+ similar successful outcomes",
                    "Playbooks auto-generate from successful record_outcome calls",
                    "Sessions auto-checkpoint every 5 minutes",
                    "Retrieval strategy adapts based on past success rates"
                ]
            }
            return [TextContent(type="text", text=json.dumps(guide, indent=2))]
        
        elif name == "extract_code_entities":
            extractor = get_code_extractor()
            code = arguments.get("code", "")
            language = arguments.get("language")
            
            entities = extractor.extract_entities(code, language)
            
            result = {
                "entities": [
                    {
                        "type": e.entity_type.value,
                        "name": e.name,
                        "signature": e.signature,
                        "docstring": getattr(e, "docstring", "") or "",
                        "line": e.line_number,
                        "parent": e.parent,
                        "dependencies": e.dependencies
                    }
                    for e in entities
                ],
                "count": len(entities),
                "language": language or extractor.detect_language(code)
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "analyze_query_complexity":
            retrieval = get_adaptive_retrieval()
            query = arguments.get("query", "")
            
            plan = retrieval.analyze_query(query)
            
            result = {
                "complexity": plan.complexity.value,
                "retrieval_decision": plan.decision.value,
                "confidence": plan.confidence,
                "reasoning": plan.reasoning,
                "suggested_search_terms": plan.search_queries,
                "max_results": plan.max_results
            }
            if plan.confidence < 0.5:
                result["note"] = "Low confidence in complexity; consider a broader query or get_smart_context for task-specific guidance."
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "summarize_code":
            from knowledge_graph.code_extractor import summarize_code
            code = arguments.get("code", "")
            
            summary = summarize_code(code)
            
            return [TextContent(type="text", text=summary)]
        
        elif name == "search_knowledge_graph":
            # Try Neo4j first, fallback to SQLite
            graph = get_graph_store()
            if graph and graph.is_available:
                query = arguments.get("query", "")
                user_id = arguments.get("user_id", "windsurf")
                results = graph.search_by_query(query, user_id, limit=10)
                formatted = graph.format_context_for_prompt(results)
                if not formatted:
                    return [TextContent(type="text", text=json.dumps({
                        "results": [], "count": 0,
                        "message": "No results found.",
                        "hint": "Try broader keywords or store_solution to add problem-solution pairs."
                    }, indent=2))]
                return [TextContent(type="text", text=formatted)]
            
            # Fallback to SQLite database
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            query = arguments.get("query", "")
            
            # Search solutions (problem->solution pairs)
            solutions = db.search_solutions(query, limit=5)
            
            if solutions:
                result = "Found solutions in knowledge base:\n\n"
                for sol in solutions:
                    result += f"**Problem:** {sol['problem']}\n"
                    result += f"**Solution:** {sol['solution']}\n"
                    result += f"**Technologies:** {', '.join(sol.get('technologies', []))}\n\n"
                return [TextContent(type="text", text=result)]
            
            return [TextContent(type="text", text=json.dumps({
                "results": [], "count": 0,
                "message": "No matching solutions found in knowledge base.",
                "hint": "Try broader keywords or store_solution to add problem-solution pairs."
            }, indent=2))]
        
        elif name == "search_memories":
            # Try ChromaDB first, fallback to SQLite
            memory = get_memory_store()
            if memory and memory.is_available:
                query = arguments.get("query", "")
                user_id = arguments.get("user_id", "windsurf")
                limit = arguments.get("limit", 5)
                memories = memory.search(query, user_id, limit=limit)
            else:
                # Fallback to SQLite database
                from mcp_knowledge_db import get_mcp_knowledge_db
                db = get_mcp_knowledge_db()
                query = arguments.get("query", "")
                limit = arguments.get("limit", 5)
                
                memories = db.search_memories(query, limit=limit)
                
                # SQLite returns dicts
                result = {
                    "memories": [
                        {
                            "content": m.get("content", "") if isinstance(m, dict) else m.content,
                            "type": m.get("memory_type", "unknown") if isinstance(m, dict) else getattr(m, 'memory_type', "unknown"),
                            "match_score": m.get("match_score", 0.8) if isinstance(m, dict) else 0.8
                        }
                        for m in memories
                    ],
                    "count": len(memories),
                    "source": "sqlite"
                }
                if len(memories) == 0:
                    result["message"] = "No memories match this query."
                    result["hint"] = "Use store_memory to add context for future retrieval."
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
            # ChromaDB returns objects
            result = {
                "memories": [
                    {
                        "content": m.content,
                        "type": m.memory_type if hasattr(m, 'memory_type') else "unknown",
                        "confidence": m.confidence if hasattr(m, 'confidence') else 0.8
                    }
                    for m in memories
                ],
                "count": len(memories),
                "source": "chromadb"
            }
            if len(memories) == 0:
                result["message"] = "No memories match this query."
                result["hint"] = "Use store_memory to add context for future retrieval."
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_retrieval_strategy":
            retrieval = get_adaptive_retrieval()
            query = arguments.get("query", "")
            
            plan = retrieval.analyze_query(query)
            sources = retrieval.get_retrieval_sources(plan)
            
            result = {
                "should_retrieve": retrieval.should_retrieve(plan),
                "sources": sources,
                "complexity": plan.complexity.value,
                "reasoning": plan.reasoning
            }
            if not retrieval.should_retrieve(plan):
                result["hint"] = "Retrieval not recommended for this query; use get_smart_context if you need task context."
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # WRITE TOOLS
        elif name == "store_memory":
            content = arguments.get("content", "")
            memory_type = arguments.get("memory_type", "fact")
            user_id = arguments.get("user_id", "windsurf")
            tags = arguments.get("tags", [])
            
            # Try evolved memory first, fall back to basic
            try:
                from memory.memory_evolution import MemoryEvolution
                from memory.memory_store import MemoryStore
                
                memory_store = get_memory_store()
                evolution = MemoryEvolution(memory_store)
                
                note = await evolution.add_memory(
                    content=content,
                    user_id=user_id,
                    source_conversation_id="windsurf-session"
                )
                
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "memory_id": note.id,
                    "keywords": note.keywords,
                    "linked_to": len(note.linked_memories),
                    "message": "Memory stored with evolution and linking"
                }, indent=2))]
                
            except Exception as e:
                logger.warning(f"Evolved memory failed, trying basic: {e}")
                
                # Fallback to basic memory store
                memory = get_memory_store()
                if memory and memory.is_available:
                    from memory.types import Memory, MemoryType
                    from bson import ObjectId
                    
                    # Validate memory_type against actual enum values
                    valid_types = {"fact", "preference", "decision", "experience", "negative"}
                    mem = Memory(
                        id=str(ObjectId()),
                        content=content,
                        memory_type=MemoryType(memory_type) if memory_type in valid_types else MemoryType.FACT,
                        user_id=user_id,
                        source_conversation_id="windsurf-session",
                    )
                    await memory.add(mem)
                    
                    return [TextContent(type="text", text=json.dumps({
                        "success": True,
                        "memory_id": mem.id,
                        "message": "Memory stored (basic mode)"
                    }, indent=2))]
                else:
                    # Fallback to SQLite
                    from mcp_knowledge_db import get_mcp_knowledge_db
                    db = get_mcp_knowledge_db()
                    
                    mem_id = db.store_memory(content, memory_type, tags)
                    
                    return [TextContent(type="text", text=json.dumps({
                        "success": True,
                        "memory_id": mem_id,
                        "message": "Memory stored in SQLite knowledge base",
                        "source": "sqlite"
                    }, indent=2))]
        
        elif name == "store_code_entity":
            graph = get_graph_store()
            if not graph or not graph.is_available:
                # Fallback to SQLite - store as a solution/memory
                from mcp_knowledge_db import get_mcp_knowledge_db
                db = get_mcp_knowledge_db()
                
                name_val = arguments.get("name", "")
                entity_type = arguments.get("entity_type", "function")
                description = arguments.get("description", "")
                code_snippet = arguments.get("code_snippet", "")
                
                # Store as memory
                content = f"{entity_type}: {name_val}\n{description}\n{code_snippet}"
                mem_id = db.store_memory(content, 'pattern', [entity_type])
                
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "entity_id": mem_id,
                    "message": "Code entity stored in SQLite (Neo4j not available)",
                    "source": "sqlite"
                }, indent=2))]
            
            name_val = arguments.get("name", "")
            entity_type = arguments.get("entity_type", "function")
            description = arguments.get("description", "")
            code_snippet = arguments.get("code_snippet", "")
            related_to = arguments.get("related_to", [])
            user_id = arguments.get("user_id", "windsurf")
            
            graph_stored = False
            try:
                from knowledge_graph.types import GraphNode, NodeType
                from datetime import datetime
                
                # Create node in Neo4j
                node = GraphNode(
                    label=NodeType.Entity,
                    name=name_val,
                    node_type=entity_type,
                    properties={
                        "description": description,
                        "code_snippet": code_snippet[:500] if code_snippet else "",
                        "source": "windsurf"
                    },
                    created_at=datetime.utcnow(),
                    last_seen=datetime.utcnow()
                )
                
                graph.add_node(node, user_id)
                
                # Create relationships using dynamic labels (matches chat backend)
                for related in related_to:
                    graph.add_relationship_dynamic(
                        from_node=name_val,
                        to_node=related,
                        rel_label="USES",
                        user_id=user_id,
                        confidence=0.8,
                        source_conversation_id="windsurf-session",
                    )
                graph_stored = True
            except Exception as e:
                logger.warning(f"Graph storage failed for store_code_entity: {e}")
            
            # Always also save to SQLite as backup
            from mcp_knowledge_db import get_mcp_knowledge_db
            sqlite_db = get_mcp_knowledge_db()
            content = f"{entity_type}: {name_val}\n{description}\n{code_snippet}"
            sqlite_db.store_memory(content, 'pattern', [entity_type])
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "entity": name_val,
                "type": entity_type,
                "relationships_created": len(related_to),
                "stored_in": ["neo4j", "sqlite"]
            }, indent=2))]
        
        elif name == "store_solution":
            problem = arguments.get("problem", "")
            solution = arguments.get("solution", "")
            code_before = arguments.get("code_before", "")
            code_after = arguments.get("code_after", "")
            technologies = arguments.get("technologies", [])
            user_id = arguments.get("user_id", "windsurf")
            
            stored_items = []
            
            # Store in memory
            try:
                from memory.memory_evolution import MemoryEvolution
                memory_store = get_memory_store()
                evolution = MemoryEvolution(memory_store)
                
                solution_text = f"Problem: {problem}\nSolution: {solution}"
                if code_after:
                    solution_text += f"\nCode: {code_after[:300]}"
                
                note = await evolution.add_memory(
                    content=solution_text,
                    user_id=user_id,
                    source_conversation_id="windsurf-solution"
                )
                stored_items.append("memory")
            except Exception as e:
                logger.warning(f"Memory storage failed: {e}")
            
            # Store in graph using dynamic relationships (matches chat backend)
            try:
                graph = get_graph_store()
                if graph and graph.is_available:
                    from knowledge_graph.types import GraphNode, NodeType
                    from datetime import datetime
                    
                    # Use hash suffix to avoid name collisions
                    import hashlib as _hl
                    prob_hash = _hl.md5(problem.encode()).hexdigest()[:8]
                    prob_name = f"{problem[:80]}_{prob_hash}"
                    sol_name = f"Solution_{prob_hash}: {problem[:50]}"
                    
                    # Create problem node
                    problem_node = GraphNode(
                        label=NodeType.Entity,
                        name=prob_name,
                        node_type="error",
                        properties={"full_text": problem},
                        created_at=datetime.utcnow(),
                        last_seen=datetime.utcnow()
                    )
                    graph.add_node(problem_node, user_id)
                    
                    # Create solution node
                    solution_node = GraphNode(
                        label=NodeType.Entity,
                        name=sol_name,
                        node_type="solution",
                        properties={
                            "solution_text": solution,
                            "code_after": code_after[:500] if code_after else ""
                        },
                        created_at=datetime.utcnow(),
                        last_seen=datetime.utcnow()
                    )
                    graph.add_node(solution_node, user_id)
                    
                    # Invalidate old SOLVED_BY rels from this problem (temporal conflict resolution)
                    graph.invalidate_relationships(prob_name, "SOLVED_BY", user_id)
                    
                    # Link problem -> solution using dynamic label
                    graph.add_relationship_dynamic(
                        from_node=prob_name,
                        to_node=sol_name,
                        rel_label="SOLVED_BY",
                        user_id=user_id,
                        confidence=0.9,
                        source_conversation_id="windsurf-solution",
                    )
                    
                    # Link technologies using dynamic labels
                    for tech in technologies:
                        tech_node = GraphNode(
                            label=NodeType.Entity,
                            name=tech,
                            node_type="technology",
                            created_at=datetime.utcnow(),
                            last_seen=datetime.utcnow()
                        )
                        graph.add_node(tech_node, user_id)
                        
                        graph.add_relationship_dynamic(
                            from_node=sol_name,
                            to_node=tech,
                            rel_label="USES",
                            user_id=user_id,
                            confidence=0.8,
                            source_conversation_id="windsurf-solution",
                        )
                    
                    stored_items.append("graph")
            except Exception as e:
                logger.warning(f"Graph storage failed for store_solution: {e}")
            
            # Always store in SQLite as backup
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            sol_id = db.store_solution(problem, solution, technologies, code_before, code_after)
            stored_items.append("sqlite")
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "stored_in": stored_items,
                "solution_id": sol_id,
                "problem": problem[:100],
                "technologies": technologies
            }, indent=2))]
        
        elif name == "link_entities":
            graph = get_graph_store()
            if not graph or not graph.is_available:
                # SQLite doesn't support relationships, but we can note the link
                from mcp_knowledge_db import get_mcp_knowledge_db
                db = get_mcp_knowledge_db()
                
                from_entity = arguments.get("from_entity", "")
                to_entity = arguments.get("to_entity", "")
                relationship = arguments.get("relationship", "related_to")
                
                # Store as a memory noting the relationship
                content = f"Relationship: {from_entity} {relationship} {to_entity}"
                mem_id = db.store_memory(content, 'pattern', [])
                
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "message": "Relationship noted in SQLite (Neo4j not available)",
                    "memory_id": mem_id,
                    "source": "sqlite"
                }, indent=2))]
            
            # Neo4j available - use dynamic relationship labels (matches chat backend)
            from_entity = arguments.get("from_entity", "")
            to_entity = arguments.get("to_entity", "")
            relationship = arguments.get("relationship", "related_to")
            user_id = arguments.get("user_id", "windsurf")
            
            # Use add_relationship_dynamic for semantic labels (same as chat backend LLM extractor)
            stored_in = []
            try:
                graph.add_relationship_dynamic(
                    from_node=from_entity,
                    to_node=to_entity,
                    rel_label=relationship,
                    user_id=user_id,
                    confidence=0.8,
                    source_conversation_id="windsurf-session",
                )
                stored_in.append("neo4j")
            except Exception as e:
                logger.warning(f"Graph storage failed for link_entities: {e}")
            
            # Always also save to SQLite as backup
            from mcp_knowledge_db import get_mcp_knowledge_db
            sqlite_db = get_mcp_knowledge_db()
            content = f"Relationship: {from_entity} {relationship} {to_entity}"
            sqlite_db.store_memory(content, 'pattern', [])
            stored_in.append("sqlite")
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "from": from_entity,
                "to": to_entity,
                "relationship": relationship,
                "stored_in": stored_in
            }, indent=2))]
        
        # SKILLS SYSTEM HANDLERS
        elif name == "find_skill":
            query = arguments.get("query", "")
            file_path = arguments.get("file_path")
            
            results = []
            sources = []
            
            # Try MongoDB skill store first
            skill_store = get_skill_store()
            if skill_store:
                matches = await skill_store.find_matching_skills(query, file_path)
                for skill, score in matches:
                    results.append({
                        "id": skill.id,
                        "name": skill.name,
                        "description": skill.description,
                        "match_score": round(score, 2),
                        "confidence": round(skill.confidence, 2),
                        "solution": skill.solution_text,
                        "code_template": skill.code_template,
                        "technologies": skill.technologies,
                        "times_used": skill.times_used,
                        "source": "mongodb"
                    })
                sources.append("mongodb")
            
            # Also search SQLite knowledge DB
            from mcp_knowledge_db import get_mcp_knowledge_db
            sqlite_db = get_mcp_knowledge_db()
            sqlite_skills = sqlite_db.find_skills(query, limit=5)
            for skill in sqlite_skills:
                # Avoid duplicates by checking name
                if not any(r.get("name") == skill.get("name") for r in results):
                    results.append({
                        "id": skill.get("id", ""),
                        "name": skill.get("name", ""),
                        "description": skill.get("description", ""),
                        "match_score": skill.get("match_score", 0.5),
                        "confidence": skill.get("confidence", 0.5),
                        "solution": skill.get("solution_text", ""),
                        "code_template": skill.get("code_template"),
                        "technologies": skill.get("technologies", []),
                        "times_used": skill.get("times_used", 0),
                        "source": "sqlite"
                    })
            sources.append("sqlite")
            
            # Also search solutions in SQLite
            solutions = sqlite_db.search_solutions(query, limit=3)
            for sol in solutions:
                results.append({
                    "id": sol.get("id", ""),
                    "name": f"Solution: {sol.get('problem', '')[:50]}",
                    "description": sol.get("problem", ""),
                    "match_score": sol.get("match_score", 0.5),
                    "confidence": 0.7,
                    "solution": sol.get("solution", ""),
                    "code_template": sol.get("code_after"),
                    "technologies": sol.get("technologies", []),
                    "times_used": sol.get("success_count", 0),
                    "source": "sqlite_solutions"
                })
            
            # Sort by match score
            results.sort(key=lambda x: -x.get("match_score", 0))
            
            if not results:
                response = {
                    "found": False,
                    "message": "No matching skills found",
                    "sources_searched": sources,
                    "suggestion": "Consider creating a skill after solving this problem",
                    "next_action": "After you solve this, call record_outcome({task_description: '...', solution_applied: '...', outcome: 'success'}) to help the system learn"
                }
                if auto_context:
                    response["related_context"] = auto_context
                return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
            response = {
                "found": True,
                "skills": results[:10],
                "sources_searched": sources,
                "reminder": "After applying a skill, call record_skill_outcome({skill_id: '...', successful: true/false})"
            }
            if auto_context:
                response["related_context"] = auto_context
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
        
        elif name == "create_skill":
            skill_name = arguments.get("name", "")
            skill_desc = arguments.get("description", "")
            triggers = arguments.get("triggers", [])
            solution_text = arguments.get("solution_text", "")
            code_template = arguments.get("code_template")
            technologies = arguments.get("technologies", [])
            
            skill_id = None
            source = "sqlite"
            
            # Try MongoDB skill store first
            skill_store = get_skill_store()
            if skill_store:
                try:
                    from skills.skill_system import Skill, SkillCategory
                    from bson import ObjectId
                    
                    skill = Skill(
                        id=str(ObjectId()),
                        name=skill_name,
                        description=skill_desc,
                        category=SkillCategory.ERROR_FIX,
                        triggers=triggers,
                        solution_text=solution_text,
                        code_template=code_template,
                        technologies=technologies,
                        user_id="windsurf"
                    )
                    skill_id = await skill_store.add_skill(skill)
                    source = "mongodb"
                except Exception as e:
                    logger.debug(f"MongoDB skill creation failed: {e}, using SQLite")
            
            # Always save to SQLite as well
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            sqlite_skill_id = db.add_skill({
                "name": skill_name,
                "description": skill_desc,
                "triggers": triggers,
                "solution_text": solution_text,
                "code_template": code_template,
                "technologies": technologies,
                "source": "manual"
            })
            
            if not skill_id:
                skill_id = sqlite_skill_id
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "skill_id": skill_id,
                "name": skill_name,
                "source": source,
                "message": "Skill created and will be suggested for matching problems"
            }, indent=2))]
        
        elif name == "record_skill_outcome":
            skill_id = arguments.get("skill_id", "")
            successful = arguments.get("successful", False)
            new_confidence = 0.5
            source = "sqlite"
            
            # Try MongoDB first
            skill_store = get_skill_store()
            if skill_store:
                try:
                    await skill_store.update_skill_usage(skill_id, successful)
                    skill = await skill_store.get_skill(skill_id)
                    new_confidence = skill.confidence if skill else 0.5
                    source = "mongodb"
                except Exception as e:
                    logger.debug(f"MongoDB skill outcome failed: {e}, using SQLite")
            
            # Always update SQLite as well
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            db.update_skill_usage(skill_id, successful)
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "skill_id": skill_id,
                "outcome": "success" if successful else "failure",
                "new_confidence": round(new_confidence, 2),
                "source": source,
                "next": "Skill confidence is updated; find_skill will rank it differently next time."
            }, indent=2))]
        
        # SESSION CONTINUITY HANDLERS
        elif name == "create_session":
            session_mgr = get_session_manager()
            
            # Try MongoDB first, fall back to SQLite
            if session_mgr:
                try:
                    create_kwargs = {
                        "user_id": "windsurf",
                        "task_description": arguments.get("task_description", ""),
                        "task_goal": arguments.get("task_goal", ""),
                        "plan_steps": arguments.get("plan_steps", []),
                    }
                    # Pass technologies if the session manager supports it
                    if arguments.get("technologies"):
                        create_kwargs["technologies"] = arguments["technologies"]
                    session = await session_mgr.create_session(**create_kwargs)
                    return [TextContent(type="text", text=json.dumps({
                        "success": True,
                        "session_id": session.id,
                        "task": session.task_description,
                        "steps": len(session.plan_steps),
                        "source": "mongodb",
                        "message": "Session created. Use update_session to track progress."
                    }, indent=2))]
                except Exception as e:
                    logger.debug(f"MongoDB session failed: {e}, using SQLite")
            
            # SQLite fallback
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            session_id = db.create_session({
                "task_description": arguments.get("task_description", ""),
                "task_goal": arguments.get("task_goal", ""),
                "plan_steps": arguments.get("plan_steps", []),
                "technologies": arguments.get("technologies", [])
            })
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "session_id": session_id,
                "task": arguments.get("task_description", ""),
                "steps": len(arguments.get("plan_steps", [])),
                "source": "sqlite",
                "message": "Session created. Use update_session to track progress."
            }, indent=2))]
        
        elif name == "get_resumable_sessions":
            session_mgr = get_session_manager()
            sessions = []
            source = "sqlite"
            
            # Try MongoDB first
            if session_mgr:
                try:
                    sessions = await session_mgr.get_resumable_sessions("windsurf")
                    source = "mongodb"
                except Exception as e:
                    logger.debug(f"MongoDB sessions failed: {e}, using SQLite")
            
            # SQLite fallback/addition
            if not sessions:
                from mcp_knowledge_db import get_mcp_knowledge_db
                db = get_mcp_knowledge_db()
                sqlite_sessions = db.get_resumable_sessions()
                for s in sqlite_sessions:
                    sessions.append({
                        "id": s["id"],
                        "task": s["task_description"],
                        "goal": s["task_goal"],
                        "progress": s.get("progress", "0%"),
                        "current_step": s["current_step"],
                        "total_steps": len(s["plan_steps"]),
                        "updated_at": s["updated_at"]
                    })
                source = "sqlite"
            
            payload = {"sessions": sessions, "count": len(sessions), "source": source}
            if len(sessions) == 0:
                payload["message"] = "No resumable sessions."
                payload["hint"] = "Use create_session to start a multi-step task."
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        
        elif name == "resume_session":
            session_id = arguments.get("session_id", "")
            session_mgr = get_session_manager()
            
            # Try MongoDB first
            if session_mgr:
                try:
                    session = await session_mgr.get_session(session_id)
                    if session:
                        context = session.get_resumption_context()
                        return [TextContent(type="text", text=json.dumps({
                            "success": True,
                            "session_id": session.id,
                            "resumption_context": context,
                            "working_files": [f.path for f in session.working_files],
                            "current_step_index": session.current_step_index,
                            "total_steps": len(session.plan_steps),
                            "source": "mongodb"
                        }, indent=2))]
                except Exception as e:
                    logger.debug(f"MongoDB resume failed: {e}, trying SQLite")
            
            # SQLite fallback
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            session = db.get_session(session_id)
            
            if not session:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Session {session_id} not found",
                    "message": "Session not found.",
                    "hint": "Use get_resumable_sessions to list valid session IDs."
                }, indent=2))]
            
            # Build resumption context
            steps = session["plan_steps"]
            current = session["current_step"]
            context = f"Task: {session['task_description']}\nGoal: {session['task_goal']}\n"
            context += f"Progress: Step {current + 1} of {len(steps)}\n"
            if current < len(steps):
                context += f"Current step: {steps[current]}\n"
            if session["key_discoveries"]:
                context += f"Discoveries: {', '.join(session['key_discoveries'][:5])}"
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "session_id": session["id"],
                "resumption_context": context,
                "working_files": session["working_files"],
                "current_step_index": current,
                "total_steps": len(steps),
                "plan_steps": steps,
                "source": "sqlite"
            }, indent=2))]
        
        elif name == "update_session":
            session_id = arguments.get("session_id", "")
            session_mgr = get_session_manager()
            
            # Try MongoDB first
            if session_mgr:
                try:
                    session = await session_mgr.get_session(session_id)
                    if session:
                        updates = []
                        if arguments.get("advance_step"):
                            step_summary = arguments.get("step_summary", "")
                            session.advance_step(step_summary)
                            updates.append(f"Advanced to step {session.current_step_index + 1}")
                        if arguments.get("add_file"):
                            session.add_working_file(arguments["add_file"])
                            updates.append(f"Added file: {arguments['add_file']}")
                        if arguments.get("checkpoint"):
                            from pipeline.session_continuity import CheckpointType
                            checkpoint = session.add_checkpoint("Manual checkpoint", CheckpointType.USER)
                            updates.append(f"Created checkpoint: {checkpoint.id}")
                        await session_mgr.update_session(session)
                        return [TextContent(type="text", text=json.dumps({
                            "success": True,
                            "session_id": session.id,
                            "updates": updates,
                            "progress": f"{session.progress_percent:.0f}%",
                            "status": session.status.value,
                            "source": "mongodb"
                        }, indent=2))]
                except Exception as e:
                    logger.debug(f"MongoDB update failed: {e}, trying SQLite")
            
            # SQLite fallback
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            session = db.get_session(session_id)
            
            if not session:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Session {session_id} not found",
                    "message": "Session not found.",
                    "hint": "Use get_resumable_sessions to list valid session IDs."
                }, indent=2))]
            
            updates = []
            update_dict = {}
            
            if arguments.get("advance_step"):
                new_step = session["current_step"] + 1
                update_dict["current_step"] = new_step
                if arguments.get("step_summary"):
                    discoveries = session["key_discoveries"] or []
                    discoveries.append(arguments["step_summary"])
                    update_dict["key_discoveries"] = discoveries
                updates.append(f"Advanced to step {new_step + 1}")
            
            if arguments.get("add_file"):
                files = session["working_files"] or []
                files.append(arguments["add_file"])
                update_dict["working_files"] = files
                updates.append(f"Added file: {arguments['add_file']}")
            
            if arguments.get("checkpoint"):
                checkpoints = session["checkpoints"] or []
                checkpoints.append({"timestamp": datetime.utcnow().isoformat(), "type": "manual"})
                update_dict["checkpoints"] = checkpoints
                updates.append("Created checkpoint")
            
            db.update_session(session_id, update_dict)
            
            steps = session["plan_steps"]
            current = update_dict.get("current_step", session["current_step"])
            progress = int((current / len(steps)) * 100) if steps else 0
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "session_id": session_id,
                "updates": updates,
                "progress": f"{progress}%",
                "status": "completed" if current >= len(steps) else "in_progress",
                "source": "sqlite"
            }, indent=2))]
        
        # REFLECTION SYSTEM HANDLERS
        elif name == "record_outcome":
            task_desc = arguments.get("task_description", "")
            solution = arguments.get("solution_applied", "")
            outcome_type = arguments.get("outcome", "unknown")
            technologies = arguments.get("technologies", [])
            skills_used = arguments.get("skills_used", [])
            error_msg = arguments.get("error_if_failed")
            
            reflection = get_reflection_system()
            outcome_id = None
            should_create_skill = False
            source = "sqlite"
            
            # Try MongoDB reflection first
            if reflection:
                try:
                    from pipeline.reflection_system import OutcomeType
                    outcome_map = {
                        "success": OutcomeType.SUCCESS,
                        "partial_success": OutcomeType.PARTIAL_SUCCESS,
                        "failure": OutcomeType.FAILURE
                    }
                    outcome = await reflection.record_outcome(
                        task_description=task_desc,
                        solution_applied=solution,
                        outcome_type=outcome_map.get(outcome_type, OutcomeType.UNKNOWN),
                        error_if_failed=error_msg,
                        technologies=technologies,
                        skills_used=skills_used
                    )
                    outcome_id = outcome.id
                    should_create_skill = outcome.should_create_skill
                    source = "mongodb"
                except Exception as e:
                    logger.debug(f"MongoDB reflection failed: {e}, using SQLite")
            
            # Always record in SQLite knowledge DB
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            sqlite_outcome_id = db.record_outcome({
                "task_description": task_desc,
                "solution_applied": solution,
                "outcome_type": outcome_type,
                "technologies": technologies,
                "skills_used": skills_used,
                "error_if_failed": error_msg
            })
            
            if not outcome_id:
                outcome_id = sqlite_outcome_id
            
            # Record pattern for auto-learning
            keywords = db._extract_keywords(f"{task_desc} {solution}")
            is_success = outcome_type == "success"
            db.record_pattern(keywords, technologies, is_success)
            
            # Check if we should create a skill
            patterns_ready = db.get_patterns_ready_for_skill()
            should_create_skill = should_create_skill or len(patterns_ready) > 0
            
            # Wire to adaptive retrieval learning
            try:
                from pipeline.adaptive_retrieval import AdaptiveRetrieval
                retrieval = AdaptiveRetrieval()
                retrieval.record_outcome(
                    query=task_desc,
                    strategy_used="hybrid",  # Default strategy
                    successful=is_success,
                    technologies=technologies
                )
            except Exception as e:
                logger.debug(f"Adaptive retrieval learning failed: {e}")
            
            # Auto-store AI reasoning
            try:
                from mcp_databases import get_ai_reasoning_db, ReasoningType
                ai_db = get_ai_reasoning_db()
                ai_db.add_reasoning(
                    task_context=task_desc,
                    reasoning_type=ReasoningType.REFLECTION,
                    thought_process=f"Applied solution: {solution}",
                    decision=f"Outcome: {outcome_type}",
                    approach_summary=solution[:200] if solution else "",
                    key_insights=[f"Result: {outcome_type}"] + (["Error: " + error_msg] if error_msg else []),
                    technologies=technologies
                )
            except Exception as e:
                logger.debug(f"AI reasoning storage failed: {e}")
            
            # Auto-generate playbook from successful outcomes with substantial solutions
            auto_playbook_id = None
            if is_success and len(solution) > 100:
                try:
                    # Check if a similar playbook already exists
                    existing_playbooks = db.find_playbooks(task_desc, limit=1)
                    if not existing_playbooks or existing_playbooks[0].get("match_score", 0) < 0.5:
                        # Parse solution into steps (split on numbered patterns or newlines)
                        import re as _re
                        solution_lines = [l.strip() for l in solution.split('\n') if l.strip()]
                        
                        # Try to detect numbered steps
                        steps = []
                        step_num = 1
                        for line in solution_lines:
                            # Match patterns like "1.", "1)", "Step 1:", "- "
                            step_match = _re.match(r'^(?:\d+[.)]\s*|step\s*\d+[:.]\s*|-\s*)(.*)', line, _re.IGNORECASE)
                            if step_match:
                                steps.append({
                                    "step": step_num,
                                    "action": step_match.group(1).strip() or line,
                                    "verify": ""
                                })
                                step_num += 1
                            elif not steps:
                                # First line becomes step 1 if no numbered format
                                steps.append({
                                    "step": step_num,
                                    "action": line,
                                    "verify": ""
                                })
                                step_num += 1
                        
                        # If no steps were parsed, create a single-step playbook
                        if not steps:
                            steps = [{"step": 1, "action": solution[:500], "verify": ""}]
                        
                        # Determine difficulty based on step count
                        difficulty = "easy" if len(steps) <= 3 else "medium" if len(steps) <= 7 else "hard"
                        
                        auto_playbook_id = db.add_playbook({
                            "name": f"auto-{'-'.join(keywords[:3])}" if keywords else "auto-playbook",
                            "description": task_desc[:200],
                            "task_type": "auto-generated",
                            "difficulty": difficulty,
                            "steps": steps,
                            "guardrails": [
                                "Follow each step in order",
                                "Do not skip steps",
                                "If a step fails, stop and report the error"
                            ],
                            "technologies": technologies,
                            "generated_by": "auto_from_outcome",
                            "confidence": 0.5  # Lower confidence for auto-generated
                        })
                        logger.info(f"Auto-generated playbook {auto_playbook_id} from outcome")
                except Exception as e:
                    logger.debug(f"Auto-playbook generation failed: {e}")
            
            payload = {
                "success": True,
                "outcome_id": outcome_id,
                "recorded": outcome_type,
                "should_create_skill": should_create_skill,
                "patterns_ready": len(patterns_ready),
                "auto_playbook_id": auto_playbook_id,
                "source": source
            }
            payload["next"] = "Playbooks may be auto-generated when similar outcomes repeat."
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        
        elif name == "get_insights":
            reflection = get_reflection_system()
            insights_list = []
            source = "sqlite"
            
            # Try MongoDB reflection first
            if reflection:
                try:
                    hours = arguments.get("reflect_hours", 24)
                    query = arguments.get("query")
                    new_insights = await reflection.reflect_on_recent(hours)
                    if query:
                        relevant = await reflection.get_relevant_insights(query)
                        insights_list = relevant + [i for i in new_insights if i not in relevant]
                    else:
                        insights_list = new_insights
                    
                    payload = {
                        "insights": [
                            {
                                "type": i.insight_type,
                                "description": i.description,
                                "confidence": round(i.confidence, 2),
                                "suggested_actions": i.suggested_actions
                            }
                            for i in insights_list[:10]
                        ],
                        "count": len(insights_list),
                        "source": "mongodb"
                    }
                    if len(insights_list) == 0:
                        payload["message"] = "No insights yet. Record more outcomes (record_outcome) to get improvement suggestions."
                    return [TextContent(type="text", text=json.dumps(payload, indent=2))]
                except Exception as e:
                    logger.debug(f"MongoDB insights failed: {e}, using SQLite")
            
            # SQLite fallback - generate insights from outcome stats
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            stats = db.get_outcome_stats()
            patterns = db.get_patterns_ready_for_skill()
            
            insights = []
            
            # Success rate insight
            if stats["total_outcomes"] > 0:
                rate = stats["success_rate"]
                insights.append({
                    "type": "success_rate",
                    "description": f"Overall success rate: {rate:.0%} ({stats['success_count']}/{stats['total_outcomes']})",
                    "confidence": 0.9,
                    "suggested_actions": ["Focus on technologies with lower success rates"] if rate < 0.7 else []
                })
            
            # Technology insights
            for tech, tech_stats in stats.get("technology_stats", {}).items():
                total = tech_stats["success"] + tech_stats["failure"]
                if total >= 3:
                    rate = tech_stats["success"] / total
                    if rate < 0.5:
                        insights.append({
                            "type": "technology_issue",
                            "description": f"Low success rate with {tech}: {rate:.0%}",
                            "confidence": 0.8,
                            "suggested_actions": [f"Review {tech} patterns", f"Create skill for common {tech} issues"]
                        })
            
            # Patterns ready insight
            if patterns:
                insights.append({
                    "type": "skill_opportunity",
                    "description": f"{len(patterns)} patterns ready to become skills",
                    "confidence": 0.95,
                    "suggested_actions": ["Run generate_skill_from_outcome to create skills from patterns"]
                })
            
            payload = {
                "insights": insights[:10],
                "count": len(insights),
                "source": "sqlite"
            }
            if len(insights) == 0:
                payload["message"] = "No insights yet. Record more outcomes (record_outcome) to get improvement suggestions."
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        
        elif name == "get_reflection_stats":
            reflection = get_reflection_system()
            
            # Try MongoDB first
            if reflection:
                try:
                    stats = reflection.get_statistics()
                    stats["source"] = "mongodb"
                    return [TextContent(type="text", text=json.dumps(stats, indent=2))]
                except Exception as e:
                    logger.debug(f"MongoDB stats failed: {e}, using SQLite")
            
            # SQLite fallback
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            stats = db.get_outcome_stats()
            stats["source"] = "sqlite"
            if stats.get("total_outcomes", 0) == 0:
                stats["message"] = "No outcomes recorded yet."
                stats["hint"] = "Use record_outcome after completing tasks to see success rates and insights."
            return [TextContent(type="text", text=json.dumps(stats, indent=2))]
        
        # ADVANCED FEATURES HANDLERS
        elif name == "generate_skill_from_outcome":
            problem = arguments.get("problem", "")
            solution_text = arguments.get("solution", "")
            code = arguments.get("code")
            technologies = arguments.get("technologies", [])
            
            candidate = None
            skill_id = None
            source = "sqlite"
            
            # Try LLM-based skill generation first
            try:
                from skills.skill_generator import get_skill_generator
                generator = get_skill_generator()
                
                candidate = await generator.generate_skill_from_outcome(
                    problem=problem,
                    solution=solution_text,
                    code=code,
                    technologies=technologies
                )
            except Exception as e:
                logger.debug(f"LLM skill generation failed: {e}")
            
            if not candidate:
                # Fallback: create a basic skill from the problem/solution directly
                from mcp_knowledge_db import get_mcp_knowledge_db
                db = get_mcp_knowledge_db()
                
                # Extract keywords for triggers
                keywords = db._extract_keywords(f"{problem} {solution_text}")
                triggers = keywords[:5] if keywords else []
                
                skill_id = db.add_skill({
                    "name": f"fix-{'-'.join(triggers[:3])}" if triggers else "auto-generated-fix",
                    "description": problem[:200],
                    "triggers": triggers,
                    "solution_text": solution_text,
                    "code_template": code,
                    "technologies": technologies,
                    "source": "auto_generated"
                })
                
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "skill_id": skill_id,
                    "name": f"fix-{'-'.join(triggers[:3])}" if triggers else "auto-generated-fix",
                    "triggers": triggers,
                    "confidence": 0.5,
                    "source": "sqlite",
                    "message": "Basic skill created from problem/solution (LLM generation unavailable)"
                }, indent=2))]
            
            # LLM generated a candidate - save to MongoDB + SQLite
            skill_store = get_skill_store()
            if skill_store:
                try:
                    from skills.skill_system import Skill, SkillCategory
                    from bson import ObjectId
                    
                    skill = Skill(
                        id=str(ObjectId()),
                        name=candidate.name,
                        description=candidate.description,
                        category=SkillCategory.ERROR_FIX,
                        triggers=candidate.triggers,
                        solution_text=candidate.solution_text,
                        code_template=candidate.code_template,
                        technologies=candidate.technologies,
                        confidence=candidate.confidence,
                        user_id="windsurf"
                    )
                    await skill_store.add_skill(skill)
                    skill_id = skill.id
                    source = "mongodb"
                except Exception as e:
                    logger.debug(f"MongoDB skill save failed: {e}")
            
            # Always save to SQLite as well
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            sqlite_id = db.add_skill({
                "name": candidate.name,
                "description": candidate.description,
                "triggers": candidate.triggers,
                "solution_text": candidate.solution_text,
                "code_template": candidate.code_template,
                "technologies": candidate.technologies,
                "source": "llm_generated"
            })
            
            if not skill_id:
                skill_id = sqlite_id
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "skill_id": skill_id,
                "name": candidate.name,
                "triggers": candidate.triggers,
                "confidence": round(candidate.confidence, 2),
                "source": source,
                "message": "Skill generated and saved"
            }, indent=2))]
        
        elif name == "find_related_sessions":
            task_desc = arguments.get("task_description", "")
            technologies = arguments.get("technologies", [])
            
            # Try MongoDB cross-session learning first
            try:
                from pipeline.cross_session_learning import get_cross_session_learner
                learner = get_cross_session_learner()
                
                related = await learner.find_related_sessions(
                    task_description=task_desc,
                    technologies=technologies
                )
                
                return [TextContent(type="text", text=json.dumps({
                    "related_sessions": related,
                    "count": len(related),
                    "source": "mongodb"
                }, indent=2))]
                
            except Exception as e:
                logger.debug(f"MongoDB cross-session failed: {e}, using SQLite")
            
            # SQLite fallback - search sessions by keyword matching
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            keywords = db._extract_keywords(task_desc)
            
            with db._get_conn() as conn:
                rows = conn.execute("""
                    SELECT * FROM sessions 
                    ORDER BY updated_at DESC 
                    LIMIT 20
                """).fetchall()
                
                scored = []
                for row in rows:
                    session = dict(row)
                    session_text = f"{session['task_description']} {session['task_goal']}".lower()
                    session_techs = json.loads(session['technologies'] or '[]')
                    
                    # Score by keyword overlap + technology match
                    kw_score = sum(1 for kw in keywords if kw in session_text) / max(len(keywords), 1)
                    tech_score = len(set(technologies) & set(session_techs)) / max(len(technologies), 1) if technologies else 0
                    score = kw_score * 0.6 + tech_score * 0.4
                    
                    if score > 0.1:
                        scored.append({
                            "id": session["id"],
                            "task": session["task_description"],
                            "goal": session["task_goal"],
                            "status": session["status"],
                            "relevance": round(score, 2),
                            "technologies": session_techs
                        })
                
                scored.sort(key=lambda x: -x["relevance"])
            
            payload = {"related_sessions": scored[:5], "count": len(scored[:5]), "source": "sqlite"}
            if len(scored) == 0:
                payload["message"] = "No related sessions found."
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        
        elif name == "get_experiment_stats":
            try:
                from skills.skill_ab_testing import get_skill_ab_tester
                tester = get_skill_ab_tester()
                stats = tester.get_experiment_stats()
                stats["source"] = "mongodb"
                
                return [TextContent(type="text", text=json.dumps(stats, indent=2))]
                
            except Exception as e:
                logger.debug(f"A/B testing stats failed: {e}, using SQLite fallback")
                
                # SQLite fallback - derive experiment-like stats from skill outcomes
                from mcp_knowledge_db import get_mcp_knowledge_db
                db = get_mcp_knowledge_db()
                
                with db._get_conn() as conn:
                    skills = conn.execute("""
                        SELECT name, times_used, success_count, confidence 
                        FROM skills WHERE times_used > 0
                        ORDER BY times_used DESC LIMIT 20
                    """).fetchall()
                    
                    experiments = []
                    for s in skills:
                        s = dict(s)
                        experiments.append({
                            "skill": s["name"],
                            "trials": s["times_used"],
                            "successes": s["success_count"],
                            "success_rate": round(s["success_count"] / max(s["times_used"], 1), 2),
                            "confidence": round(s["confidence"], 2)
                        })
                
                payload = {"experiments": experiments, "count": len(experiments), "source": "sqlite"}
                if len(experiments) == 0:
                    payload["message"] = "No experiment data yet."
                    payload["hint"] = "Skill A/B stats appear after record_skill_outcome is used."
                return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        
        elif name == "get_auto_learning_status":
            try:
                from skills.auto_skill_learner import get_auto_skill_learner
                learner = get_auto_skill_learner()
                status = learner.get_learning_status()
                status["source"] = "mongodb"
                
                return [TextContent(type="text", text=json.dumps(status, indent=2))]
                
            except Exception as e:
                logger.debug(f"Auto learning status failed: {e}, using SQLite fallback")
                
                # SQLite fallback - check patterns ready for skill generation
                from mcp_knowledge_db import get_mcp_knowledge_db
                db = get_mcp_knowledge_db()
                patterns = db.get_patterns_ready_for_skill(min_occurrences=3)
                stats = db.get_outcome_stats()
                
                payload = {
                    "auto_learning_active": True,
                    "patterns_detected": len(patterns),
                    "patterns_ready_for_skills": [
                        {"pattern": p.get("pattern_key", ""), "occurrences": p.get("occurrences", 0)}
                        for p in patterns[:10]
                    ],
                    "total_outcomes_tracked": stats.get("total_outcomes", 0),
                    "threshold_for_skill_generation": 3,
                    "source": "sqlite"
                }
                if len(patterns) == 0 and stats.get("total_outcomes", 0) == 0:
                    payload["message"] = "No patterns ready for auto-skills yet."
                    payload["hint"] = "Record 3+ successful outcomes for similar problems to trigger skill generation."
                return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        
        # 3-DATABASE SYSTEM HANDLERS
        elif name == "store_user_interaction":
            from mcp_databases import get_user_interactions_db
            db = get_user_interactions_db()
            
            interaction_id = db.add_interaction(
                user_message=arguments.get("user_message", ""),
                message_type=arguments.get("message_type", "request"),
                technologies=arguments.get("technologies", [])
            )
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "interaction_id": interaction_id,
                "message": "User interaction stored for future reference"
            }, indent=2))]
        
        elif name == "store_ai_reasoning":
            from mcp_databases import get_ai_reasoning_db, ReasoningType
            db = get_ai_reasoning_db()
            
            reasoning_type_map = {
                "analysis": ReasoningType.ANALYSIS,
                "planning": ReasoningType.PLANNING,
                "debugging": ReasoningType.DEBUGGING,
                "decision": ReasoningType.DECISION,
                "implementation": ReasoningType.IMPLEMENTATION,
                "research": ReasoningType.RESEARCH,
                "reflection": ReasoningType.REFLECTION
            }
            
            reasoning_id = db.add_reasoning(
                task_context=arguments.get("task_context", ""),
                reasoning_type=reasoning_type_map.get(arguments.get("reasoning_type", "analysis"), ReasoningType.ANALYSIS),
                thought_process=arguments.get("thought_process", ""),
                decision=arguments.get("decision", ""),
                approach_summary=arguments.get("approach_summary", ""),
                key_insights=arguments.get("key_insights", []),
                technologies=arguments.get("technologies", [])
            )
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "reasoning_id": reasoning_id,
                "message": "AI reasoning stored for future reference"
            }, indent=2))]
        
        elif name == "search_past_reasoning":
            from mcp_databases import get_ai_reasoning_db, SearchMode, ReasoningType
            db = get_ai_reasoning_db()
            
            reasoning_type = None
            if arguments.get("reasoning_type"):
                type_map = {
                    "analysis": ReasoningType.ANALYSIS,
                    "planning": ReasoningType.PLANNING,
                    "debugging": ReasoningType.DEBUGGING,
                    "decision": ReasoningType.DECISION,
                    "implementation": ReasoningType.IMPLEMENTATION,
                    "research": ReasoningType.RESEARCH,
                    "reflection": ReasoningType.REFLECTION
                }
                reasoning_type = type_map.get(arguments.get("reasoning_type"))
            
            outcome_filter = "success" if arguments.get("only_successful") else None
            
            results = db.search(
                query=arguments.get("query", ""),
                mode=SearchMode.SEMANTIC,
                reasoning_type=reasoning_type,
                outcome_filter=outcome_filter,
                limit=10
            )
            
            # Format for readability
            formatted = []
            for r in results:
                formatted.append({
                    "id": r["id"],
                    "task": r["task_context"][:200] if r.get("task_context") else "",
                    "approach": r["approach_summary"][:200] if r.get("approach_summary") else "",
                    "decision": r["decision"][:200] if r.get("decision") else "",
                    "patterns": r.get("patterns", []),
                    "outcome": r.get("outcome"),
                    "lessons": r.get("lessons_learned", [])[:3]
                })
            
            payload = {"results": formatted, "count": len(formatted)}
            if len(formatted) == 0:
                payload["message"] = "No past reasoning found."
                payload["hint"] = "Use store_ai_reasoning when solving problems to build this database."
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        
        elif name == "search_user_history":
            from mcp_databases import get_user_interactions_db, SearchMode
            db = get_user_interactions_db()
            
            results = db.search(
                query=arguments.get("query", ""),
                mode=SearchMode.SEMANTIC,
                problem_type=arguments.get("problem_type"),
                only_resolved=arguments.get("only_resolved", False),
                limit=10
            )
            
            formatted = []
            for r in results:
                formatted.append({
                    "id": r["id"],
                    "message": r["user_message"][:300] if r.get("user_message") else "",
                    "problem_type": r.get("problem_type"),
                    "technologies": r.get("technologies", []),
                    "resolved": bool(r.get("was_resolved")),
                    "resolution": r.get("resolution_summary", "")[:200] if r.get("resolution_summary") else None
                })
            
            payload = {"results": formatted, "count": len(formatted)}
            if len(formatted) == 0:
                payload["message"] = "No matching user history."
                payload["hint"] = "Interactions are auto-logged; try a different query or broader terms."
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        
        elif name == "search_all_context":
            from mcp_databases import get_unified_search
            search = get_unified_search()
            
            results = search.search_all(
                query=arguments.get("query", ""),
                limit_per_source=5
            )
            
            # Summarize results
            summary = {
                "user_interactions": len(results.get("user_interactions", [])),
                "ai_reasoning": len(results.get("ai_reasoning", [])),
                "skills": len(results.get("skills", [])),
                "solutions": len(results.get("solutions", [])),
                "memories": len(results.get("memories", []))
            }
            
            # Get formatted context
            context = search.find_relevant_context(arguments.get("query", ""))
            
            payload = {
                "summary": summary,
                "context": context,
                "raw_results": {
                    "user_interactions": [
                        {"message": r.get("user_message", "")[:150], "resolved": r.get("was_resolved")}
                        for r in results.get("user_interactions", [])[:3]
                    ],
                    "ai_reasoning": [
                        {"task": r.get("task_context", "")[:150], "approach": r.get("approach_summary", "")[:100]}
                        for r in results.get("ai_reasoning", [])[:3]
                    ],
                    "skills": [
                        {"name": s.get("name"), "solution": s.get("solution_text", "")[:100]}
                        for s in results.get("skills", [])[:3]
                    ]
                }
            }
            if sum(summary.values()) == 0:
                payload["message"] = "No context found across any source."
                payload["hint"] = "Record outcomes and store solutions to build retrievable context."
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        
        elif name == "get_db_stats":
            from mcp_databases import get_user_interactions_db, get_ai_reasoning_db
            from mcp_knowledge_db import get_mcp_knowledge_db
            
            user_db = get_user_interactions_db()
            ai_db = get_ai_reasoning_db()
            knowledge_db = get_mcp_knowledge_db()
            
            return [TextContent(type="text", text=json.dumps({
                "databases": {
                    "note": "Main app uses SQLite (data/app.db). MCP uses the 3 DBs below.",
                    "2_user_interactions": user_db.get_stats(),
                    "3_ai_reasoning": ai_db.get_stats(),
                    "4_knowledge": knowledge_db.get_stats()
                }
            }, indent=2))]
        
        # SMART MODEL → DUMB MODEL SKILL TRANSFER HANDLERS
        elif name == "create_playbook":
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            
            playbook_id = db.add_playbook({
                "name": arguments.get("name", ""),
                "description": arguments.get("description", ""),
                "task_type": arguments.get("task_type", "general"),
                "difficulty": arguments.get("difficulty", "medium"),
                "steps": arguments.get("steps", []),
                "decision_tree": arguments.get("decision_tree", {}),
                "code_templates": arguments.get("code_templates", {}),
                "prerequisites": arguments.get("prerequisites", []),
                "examples": arguments.get("examples", []),
                "guardrails": arguments.get("guardrails", []),
                "technologies": arguments.get("technologies", []),
                "generated_by": "smart_model"
            })
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "playbook_id": playbook_id,
                "name": arguments.get("name", ""),
                "steps_count": len(arguments.get("steps", [])),
                "message": "Playbook created! Weak models can now use get_smart_context to find and follow these steps."
            }, indent=2))]
        
        elif name == "get_smart_context":
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            
            task_desc = arguments.get("task_description", "")
            technologies = arguments.get("technologies", [])
            
            context = {
                "playbooks": [],
                "skills": [],
                "solutions": [],
                "guardrails": [],
                "has_playbook": False,
                "recommendation": ""
            }
            
            # 1. Find matching playbooks (most valuable for weak models)
            playbooks = db.find_playbooks(task_desc, limit=3)
            if playbooks:
                context["has_playbook"] = True
                for pb in playbooks:
                    context["playbooks"].append({
                        "id": pb["id"],
                        "name": pb["name"],
                        "description": pb["description"],
                        "difficulty": pb["difficulty"],
                        "match_score": pb["match_score"],
                        "confidence": pb["confidence"],
                        "steps": pb["steps"],
                        "decision_tree": pb["decision_tree"],
                        "code_templates": pb["code_templates"],
                        "guardrails": pb["guardrails"],
                        "examples": pb["examples"]
                    })
                    # Collect all guardrails
                    context["guardrails"].extend(pb.get("guardrails", []))
            
            # 2. Find matching skills
            skills = db.find_skills(task_desc, limit=3)
            for skill in skills:
                context["skills"].append({
                    "id": skill["id"],
                    "name": skill["name"],
                    "solution": skill.get("solution_text", ""),
                    "code_template": skill.get("code_template"),
                    "confidence": skill.get("confidence", 0.5),
                    "match_score": skill.get("match_score", 0)
                })
            
            # 3. Find matching solutions
            solutions = db.search_solutions(task_desc, limit=3)
            for sol in solutions:
                context["solutions"].append({
                    "problem": sol["problem"],
                    "solution": sol["solution"],
                    "code_after": sol.get("code_after", ""),
                    "technologies": sol.get("technologies", [])
                })
            
            # 4. Generate recommendation
            if context["has_playbook"]:
                best = context["playbooks"][0]
                context["recommendation"] = (
                    f"FOLLOW THE PLAYBOOK '{best['name']}' step by step. "
                    f"It has {len(best['steps'])} steps and {best['confidence']:.0%} confidence. "
                    f"Do NOT skip steps. Do NOT improvise. Follow each step exactly."
                )
            elif context["skills"]:
                context["recommendation"] = (
                    "No playbook found, but matching skills exist. "
                    "Apply the skill solution and code template. "
                    "After completing, call record_outcome to help build playbooks for next time."
                )
            else:
                context["recommendation"] = (
                    "No playbooks or skills found for this task. "
                    "This may need a smart model session. "
                    "If you proceed, call record_outcome when done so a playbook can be generated."
                )
                context["message"] = "No playbooks, skills, or solutions found for this task."
            
            # Deduplicate guardrails
            context["guardrails"] = list(set(context["guardrails"]))
            
            return [TextContent(type="text", text=json.dumps(context, indent=2))]
        
        elif name == "assess_task_difficulty":
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            
            task_desc = arguments.get("task_description", "")
            current_model = arguments.get("current_model", "unknown")
            model_tier = detect_model_tier(current_model)
            
            # Check for existing playbooks
            playbooks = db.find_playbooks(task_desc, limit=3)
            skills = db.find_skills(task_desc, limit=3)
            solutions = db.search_solutions(task_desc, limit=3)
            
            # Heuristic difficulty assessment
            difficulty_signals = {
                "easy": 0,
                "medium": 0,
                "hard": 0
            }
            
            # Playbook availability is the strongest signal
            if playbooks and playbooks[0].get("match_score", 0) > 0.3:
                best_pb = playbooks[0]
                if best_pb["difficulty"] == "easy":
                    difficulty_signals["easy"] += 3
                elif best_pb["difficulty"] == "medium":
                    difficulty_signals["medium"] += 2
                    difficulty_signals["easy"] += 1
                else:
                    difficulty_signals["hard"] += 2
                
                # High confidence playbook makes it easier
                if best_pb["confidence"] > 0.8:
                    difficulty_signals["easy"] += 2
            
            # Skills availability helps
            if skills:
                difficulty_signals["easy"] += 1
                difficulty_signals["medium"] += 1
            
            # Solutions availability helps
            if solutions:
                difficulty_signals["easy"] += 1
            
            # Task complexity heuristics
            complex_keywords = ["refactor", "architect", "design", "migrate", "optimize", 
                              "security", "authentication", "deploy", "scale", "debug complex"]
            simple_keywords = ["add", "create", "fix typo", "update", "rename", "style", 
                             "format", "comment", "log", "print"]
            
            task_lower = task_desc.lower()
            for kw in complex_keywords:
                if kw in task_lower:
                    difficulty_signals["hard"] += 1
            for kw in simple_keywords:
                if kw in task_lower:
                    difficulty_signals["easy"] += 1
            
            # No resources found = harder
            if not playbooks and not skills and not solutions:
                difficulty_signals["hard"] += 2
                difficulty_signals["medium"] += 1
            
            # Determine final difficulty
            if difficulty_signals["easy"] > difficulty_signals["medium"] and difficulty_signals["easy"] > difficulty_signals["hard"]:
                difficulty = "easy"
                can_weak_model = True
                recommendation = "A weak/free model can handle this task."
            elif difficulty_signals["hard"] > difficulty_signals["easy"] and difficulty_signals["hard"] > difficulty_signals["medium"]:
                difficulty = "hard"
                can_weak_model = False
                recommendation = "This task likely needs a smart model. Consider switching or creating a playbook first."
            else:
                difficulty = "medium"
                can_weak_model = bool(playbooks or skills)
                recommendation = "A weak model can handle this WITH playbook/skill support." if can_weak_model else "Consider using a smart model for this task."
            
            return [TextContent(type="text", text=json.dumps({
                "difficulty": difficulty,
                "can_weak_model_handle": can_weak_model,
                "model_tier": model_tier,
                "recommendation": recommendation,
                "support_available": {
                    "playbooks": len(playbooks),
                    "skills": len(skills),
                    "solutions": len(solutions)
                },
                "signals": difficulty_signals,
                "suggestion": "Call get_smart_context to get step-by-step instructions" if can_weak_model else "Use a smart model session, then call create_playbook to teach weak models",
                "model_advice": {
                    "smart": "You are a smart model. After solving, call create_playbook to teach weak models.",
                    "weak": "You are a weak model. Always call get_smart_context first and follow playbooks exactly.",
                    "unknown": "Model tier unknown. Call get_smart_context first to check for playbooks."
                }.get(model_tier, "Call get_smart_context first.")
            }, indent=2))]
        
        elif name == "record_playbook_outcome":
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            
            playbook_id = arguments.get("playbook_id", "")
            successful = arguments.get("successful", False)
            model_used = arguments.get("model_used", "unknown")
            
            db.update_playbook_usage(playbook_id, successful)
            
            # Also record as a general outcome for learning
            outcome_id = db.record_outcome({
                "task_description": f"Playbook {playbook_id} used by {model_used}",
                "solution_applied": f"Followed playbook {playbook_id}",
                "outcome_type": "success" if successful else "failure",
                "skills_used": [playbook_id]
            })
            
            playbook = db.get_playbook(playbook_id)
            
            new_confidence = None
            times_used = None
            if playbook:
                new_confidence = round(playbook.get("confidence", 0), 2)
                times_used = playbook.get("times_used")
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "playbook_id": playbook_id,
                "model_used": model_used,
                "outcome": "success" if successful else "failure",
                "new_confidence": new_confidence,
                "times_used": times_used,
                "message": "Playbook outcome recorded. This helps improve playbook quality over time.",
                "next": "This feedback improves playbook ranking for future get_smart_context calls."
            }, indent=2))]
        
        elif name == "store_web_research":
            from mcp_knowledge_db import get_mcp_knowledge_db
            db = get_mcp_knowledge_db()
            
            topic = arguments.get("topic", "")
            urls = arguments.get("urls", [])
            findings = arguments.get("findings", "")
            technologies = arguments.get("technologies", [])
            actionable_items = arguments.get("actionable_items", [])
            
            # Store as a solution (topic = problem, findings = solution)
            solution_id = db.store_solution(
                problem=f"[WEB RESEARCH] {topic}",
                solution=findings,
                technologies=technologies,
                code_before=json.dumps({"urls": urls, "actionable_items": actionable_items}),
                code_after=None
            )
            
            # Also store as a memory for broader search
            urls_text = "\n".join(urls) if urls else "No URLs recorded"
            actions_text = "\n".join(f"- {a}" for a in actionable_items) if actionable_items else ""
            memory_content = (
                f"Web Research: {topic}\n"
                f"Sources:\n{urls_text}\n"
                f"Findings: {findings}\n"
                f"{actions_text}"
            )
            memory_id = db.store_memory(memory_content, "solution", technologies)
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "solution_id": solution_id,
                "memory_id": memory_id,
                "topic": topic,
                "urls_saved": len(urls),
                "message": "Research saved! Use search_all_context or find_skill to find it later."
            }, indent=2))]
        
        elif name == "list_tools_compact":
            # Minimal token-efficient tool listing for weak models
            compact = [
                "get_mcp_guide - Full guide on how to use this MCP server",
                "get_smart_context - GET HELP! Returns playbooks + skills for your task (CALL THIS FIRST)",
                "assess_task_difficulty - Check if weak model can handle a task",
                "create_playbook - Save step-by-step instructions for future use",
                "record_playbook_outcome - Report if a playbook worked",
                "list_tools_compact - This tool (minimal tool list)",
                "find_skill - Search for existing skills/solutions",
                "create_skill - Save a reusable skill",
                "record_skill_outcome - Report if a skill worked",
                "record_outcome - Log task success/failure (CALL AFTER EVERY TASK)",
                "search_all_context - Search all databases at once",
                "store_web_research - Save web research findings (CALL AFTER ANY RESEARCH)",
                "store_solution - Save a problem→solution pair",
                "store_memory - Save a fact or insight",
                "store_code_entity - Save a code entity to knowledge graph",
                "link_entities - Create relationship between entities",
                "search_knowledge_graph - Search the knowledge graph",
                "search_memories - Search stored memories",
                "extract_code_entities - Parse code structure",
                "summarize_code - Compress code to summary",
                "analyze_query_complexity - Check query complexity",
                "get_retrieval_strategy - Get recommended search strategy",
                "create_session - Start a multi-step task session",
                "get_resumable_sessions - List incomplete sessions",
                "resume_session - Continue a previous session",
                "update_session - Update session progress",
                "find_related_sessions - Find similar past sessions",
                "generate_skill_from_outcome - Auto-generate skill from solution",
                "get_insights - Get learning insights",
                "get_reflection_stats - Get outcome statistics",
                "get_experiment_stats - Get A/B testing stats",
                "get_auto_learning_status - Check auto-learning status",
                "store_user_interaction - Log user request",
                "store_ai_reasoning - Log AI thought process",
                "search_past_reasoning - Search AI reasoning history",
                "search_user_history - Search past user requests",
                "get_db_stats - Database statistics"
            ]
            
            return [TextContent(type="text", text=json.dumps({
                "tools": compact,
                "total": len(compact),
                "tip": "For most tasks: 1) Call get_smart_context first, 2) Follow any playbook returned, 3) Call record_outcome when done",
                "weak_model_workflow": [
                    "1. get_smart_context({task_description: 'your task'}) - get instructions",
                    "2. Follow the playbook steps exactly if one is returned",
                    "3. record_playbook_outcome({playbook_id: '...', successful: true/false}) - report result",
                    "4. record_outcome({task_description: '...', solution_applied: '...', outcome: 'success'}) - log for learning"
                ]
            }, indent=2))]
        
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
            
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    """Run the MCP server."""
    logger.info("Starting Engram MCP Server...")
    logger.info("Available tools (37 total):")
    logger.info("  HELP: get_mcp_guide, list_tools_compact (START HERE!)")
    logger.info("  Smart→Dumb Transfer: get_smart_context, create_playbook, assess_task_difficulty, record_playbook_outcome, list_tools_compact")
    logger.info("  Read: extract_code_entities, analyze_query_complexity, summarize_code, search_knowledge_graph, search_memories, get_retrieval_strategy")
    logger.info("  Write: store_memory, store_code_entity, store_solution, link_entities")
    logger.info("  Skills: find_skill, create_skill, record_skill_outcome, generate_skill_from_outcome")
    logger.info("  Sessions: create_session, get_resumable_sessions, resume_session, update_session, find_related_sessions")
    logger.info("  Reflection: record_outcome, get_insights, get_reflection_stats, get_experiment_stats, get_auto_learning_status")
    logger.info("  3-DB System: store_user_interaction, store_ai_reasoning, search_past_reasoning, search_user_history, search_all_context, get_db_stats")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
