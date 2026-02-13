"""
MCP 3-Database Architecture

DB 1: MongoDB (existing) - Original chat app conversations (DON'T TOUCH)
DB 2: SQLite user_interactions.db - User messages/requests to MCP
DB 3: SQLite ai_reasoning.db - AI thoughts, reasoning, decisions

Search Strategy:
- User DB: keyword search, technology filter, problem type clustering
- AI DB: reasoning pattern search, decision similarity, outcome-based retrieval
- Cross-DB: unified search that finds relevant context from both
"""

import sqlite3
import json
import logging
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from contextlib import contextmanager
from enum import Enum

logger = logging.getLogger(__name__)

# Database paths - centralized under data/mcp/
from config import MCP_DATA_DIR, MCP_USER_INTERACTIONS_DB, MCP_AI_REASONING_DB
USER_DB_PATH = MCP_USER_INTERACTIONS_DB
AI_DB_PATH = MCP_AI_REASONING_DB


class ReasoningType(str, Enum):
    """Types of AI reasoning to categorize thoughts."""
    ANALYSIS = "analysis"           # Understanding a problem
    PLANNING = "planning"           # Creating a plan/approach
    DEBUGGING = "debugging"         # Finding root cause
    DECISION = "decision"           # Choosing between options
    IMPLEMENTATION = "implementation"  # How to build something
    RESEARCH = "research"           # Looking up information
    REFLECTION = "reflection"       # Learning from outcome


class SearchMode(str, Enum):
    """How to search across databases."""
    KEYWORD = "keyword"             # Simple keyword matching
    SEMANTIC = "semantic"           # Meaning-based (uses keywords + context)
    PATTERN = "pattern"             # Find similar reasoning patterns
    OUTCOME = "outcome"             # Find by success/failure


# =============================================================================
# DATABASE 2: User Interactions
# =============================================================================

class UserInteractionsDB:
    """
    Stores user messages and requests made to the MCP.
    
    Search optimized for:
    - Finding similar past requests
    - Filtering by technology/domain
    - Clustering by problem type
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or USER_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    
                    -- User message
                    user_message TEXT NOT NULL,
                    message_type TEXT,  -- question, request, feedback, followup
                    
                    -- Context
                    technologies TEXT,  -- JSON array
                    file_paths TEXT,    -- JSON array of files involved
                    error_messages TEXT, -- JSON array of errors mentioned
                    
                    -- Extracted info for search
                    keywords TEXT,      -- JSON array
                    problem_type TEXT,  -- bug, feature, refactor, question, etc.
                    complexity TEXT,    -- simple, medium, complex
                    
                    -- Outcome
                    was_resolved INTEGER DEFAULT 0,
                    resolution_summary TEXT,
                    ai_reasoning_ids TEXT,  -- JSON array linking to AI reasoning
                    
                    -- Search optimization
                    search_text TEXT,   -- Combined searchable text
                    embedding_hash TEXT -- For deduplication
                )
            """)
            
            # Full-text search index
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS interactions_fts USING fts5(
                    id, user_message, keywords, problem_type, technologies,
                    content='interactions',
                    content_rowid='rowid'
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_type ON interactions(problem_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_tech ON interactions(technologies)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_resolved ON interactions(was_resolved)")
            
            logger.info(f"User Interactions DB initialized at {self.db_path}")
    
    def _extract_info(self, message: str) -> Dict[str, Any]:
        """Extract searchable info from user message."""
        # Keywords
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                      'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                      'could', 'should', 'can', 'to', 'of', 'in', 'for', 'on',
                      'with', 'at', 'by', 'from', 'as', 'and', 'but', 'or', 'not',
                      'this', 'that', 'it', 'i', 'you', 'we', 'they', 'my', 'your',
                      'how', 'what', 'when', 'where', 'why', 'which', 'who', 'please'}
        
        words = re.findall(r'\b[a-zA-Z]{3,}\b', message.lower())
        keywords = [w for w in words if w not in stop_words]
        
        # Technologies (common ones)
        tech_patterns = [
            'python', 'javascript', 'typescript', 'react', 'vue', 'angular',
            'fastapi', 'flask', 'django', 'express', 'node', 'mongodb', 'postgres',
            'sqlite', 'redis', 'docker', 'kubernetes', 'aws', 'gcp', 'azure',
            'git', 'github', 'api', 'rest', 'graphql', 'css', 'html', 'tailwind'
        ]
        technologies = [t for t in tech_patterns if t in message.lower()]
        
        # Error patterns
        error_patterns = re.findall(r'\b\w*(?:Error|Exception|Failed|failure|error|bug|issue|problem|broken)\b', message, re.I)
        
        # Problem type detection
        problem_type = "question"
        if any(w in message.lower() for w in ['error', 'bug', 'fix', 'broken', 'crash', 'fail']):
            problem_type = "bug"
        elif any(w in message.lower() for w in ['add', 'create', 'implement', 'build', 'new']):
            problem_type = "feature"
        elif any(w in message.lower() for w in ['refactor', 'improve', 'optimize', 'clean']):
            problem_type = "refactor"
        elif any(w in message.lower() for w in ['why', 'how', 'what', 'explain', 'understand']):
            problem_type = "question"
        
        # Complexity estimate
        complexity = "simple"
        if len(message) > 500 or len(keywords) > 20:
            complexity = "complex"
        elif len(message) > 200 or len(keywords) > 10:
            complexity = "medium"
        
        return {
            "keywords": list(set(keywords))[:30],
            "technologies": technologies,
            "error_messages": error_patterns,
            "problem_type": problem_type,
            "complexity": complexity
        }
    
    def add_interaction(
        self,
        user_message: str,
        message_type: str = "request",
        file_paths: Optional[List[str]] = None,
        technologies: Optional[List[str]] = None
    ) -> str:
        """Store a user interaction."""
        import uuid
        interaction_id = str(uuid.uuid4())[:24]
        now = datetime.utcnow().isoformat()
        
        extracted = self._extract_info(user_message)
        if technologies:
            extracted["technologies"] = list(set(extracted["technologies"] + technologies))
        
        search_text = f"{user_message} {' '.join(extracted['keywords'])} {' '.join(extracted['technologies'])}"
        embedding_hash = hashlib.md5(user_message.encode()).hexdigest()
        
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO interactions 
                (id, timestamp, user_message, message_type, technologies, file_paths,
                 error_messages, keywords, problem_type, complexity, search_text, embedding_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                interaction_id, now, user_message, message_type,
                json.dumps(extracted["technologies"]),
                json.dumps(file_paths or []),
                json.dumps(extracted["error_messages"]),
                json.dumps(extracted["keywords"]),
                extracted["problem_type"],
                extracted["complexity"],
                search_text,
                embedding_hash
            ))
            
            # Update FTS index
            conn.execute("""
                INSERT INTO interactions_fts (id, user_message, keywords, problem_type, technologies)
                VALUES (?, ?, ?, ?, ?)
            """, (
                interaction_id, user_message,
                ' '.join(extracted["keywords"]),
                extracted["problem_type"],
                ' '.join(extracted["technologies"])
            ))
        
        return interaction_id
    
    def update_resolution(self, interaction_id: str, resolved: bool, 
                          summary: str, reasoning_ids: Optional[List[str]] = None) -> dict:
        """Update interaction with resolution status."""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE interactions SET
                    was_resolved = ?,
                    resolution_summary = ?,
                    ai_reasoning_ids = ?
                WHERE id = ?
            """, (
                1 if resolved else 0,
                summary,
                json.dumps(reasoning_ids or []),
                interaction_id
            ))
    
    def search(
        self,
        query: str,
        mode: SearchMode = SearchMode.KEYWORD,
        problem_type: Optional[str] = None,
        technologies: Optional[List[str]] = None,
        only_resolved: bool = False,
        limit: int = 10
    ) -> List[Dict]:
        """
        Search user interactions.
        
        Modes:
        - KEYWORD: FTS search on message content
        - SEMANTIC: Keyword + technology + problem type matching
        - PATTERN: Find similar problem patterns
        - OUTCOME: Filter by resolution status
        """
        with self._get_conn() as conn:
            if mode == SearchMode.KEYWORD:
                # Full-text search
                rows = conn.execute("""
                    SELECT i.* FROM interactions i
                    JOIN interactions_fts fts ON i.id = fts.id
                    WHERE interactions_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (query, limit)).fetchall()
            
            else:
                # Build dynamic query
                conditions = []
                params = []
                
                if query:
                    extracted = self._extract_info(query)
                    keywords = extracted["keywords"]
                    if keywords:
                        keyword_conditions = " OR ".join(["keywords LIKE ?" for _ in keywords])
                        conditions.append(f"({keyword_conditions})")
                        params.extend([f"%{kw}%" for kw in keywords])
                
                if problem_type:
                    conditions.append("problem_type = ?")
                    params.append(problem_type)
                
                if technologies:
                    tech_conditions = " OR ".join(["technologies LIKE ?" for _ in technologies])
                    conditions.append(f"({tech_conditions})")
                    params.extend([f"%{t}%" for t in technologies])
                
                if only_resolved:
                    conditions.append("was_resolved = 1")
                
                where_clause = " AND ".join(conditions) if conditions else "1=1"
                
                rows = conn.execute(f"""
                    SELECT * FROM interactions
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, params + [limit]).fetchall()
            
            results = []
            for row in rows:
                r = dict(row)
                r["technologies"] = json.loads(r["technologies"] or "[]")
                r["keywords"] = json.loads(r["keywords"] or "[]")
                r["file_paths"] = json.loads(r["file_paths"] or "[]")
                r["error_messages"] = json.loads(r["error_messages"] or "[]")
                r["ai_reasoning_ids"] = json.loads(r["ai_reasoning_ids"] or "[]")
                results.append(r)
            
            return results
    
    def get_stats(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
            resolved = conn.execute("SELECT COUNT(*) FROM interactions WHERE was_resolved = 1").fetchone()[0]
            
            # Problem type breakdown
            types = conn.execute("""
                SELECT problem_type, COUNT(*) as count 
                FROM interactions 
                GROUP BY problem_type
            """).fetchall()
            
            return {
                "total_interactions": total,
                "resolved": resolved,
                "resolution_rate": resolved / total if total > 0 else 0,
                "by_problem_type": {r["problem_type"]: r["count"] for r in types}
            }


# =============================================================================
# DATABASE 3: AI Reasoning
# =============================================================================

class AIReasoningDB:
    """
    Stores AI thoughts, reasoning patterns, and decisions.
    
    This is the AI's "memory" of how it approached problems.
    
    Search optimized for:
    - Finding similar reasoning patterns
    - Learning from past decisions
    - Retrieving relevant approaches for new problems
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or AI_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def _init_db(self):
        with self._get_conn() as conn:
            # Main reasoning table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reasoning (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    
                    -- Context
                    task_context TEXT,      -- What problem was being solved
                    interaction_id TEXT,    -- Link to user interaction
                    
                    -- The reasoning itself
                    reasoning_type TEXT,    -- analysis, planning, debugging, etc.
                    thought_process TEXT,   -- The actual reasoning/thoughts
                    key_insights TEXT,      -- JSON array of key insights
                    
                    -- Decision made
                    decision TEXT,          -- What was decided
                    alternatives_considered TEXT,  -- JSON array of other options
                    decision_rationale TEXT,       -- Why this decision
                    
                    -- Approach taken
                    approach_summary TEXT,  -- High-level approach
                    steps_taken TEXT,       -- JSON array of steps
                    tools_used TEXT,        -- JSON array of tools/methods used
                    
                    -- Outcome
                    outcome TEXT,           -- success, partial, failure
                    outcome_details TEXT,   -- What happened
                    lessons_learned TEXT,   -- JSON array
                    would_do_differently TEXT,  -- Hindsight
                    
                    -- Search optimization
                    keywords TEXT,          -- JSON array
                    technologies TEXT,      -- JSON array
                    patterns TEXT,          -- JSON array of reasoning patterns identified
                    search_embedding TEXT   -- Combined searchable text
                )
            """)
            
            # Reasoning patterns - abstracted learnings
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    id TEXT PRIMARY KEY,
                    pattern_name TEXT,
                    pattern_description TEXT,
                    
                    -- When to apply
                    trigger_conditions TEXT,    -- JSON: when this pattern applies
                    problem_types TEXT,         -- JSON array
                    technologies TEXT,          -- JSON array
                    
                    -- The pattern itself
                    reasoning_template TEXT,    -- How to think about it
                    typical_steps TEXT,         -- JSON array
                    common_pitfalls TEXT,       -- JSON array
                    
                    -- Stats
                    times_used INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    
                    -- Examples
                    example_reasoning_ids TEXT, -- JSON array
                    
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            
            # Full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS reasoning_fts USING fts5(
                    id, task_context, thought_process, decision, approach_summary,
                    keywords, patterns,
                    content='reasoning',
                    content_rowid='rowid'
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reasoning_type ON reasoning(reasoning_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reasoning_outcome ON reasoning(outcome)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reasoning_interaction ON reasoning(interaction_id)")
            
            logger.info(f"AI Reasoning DB initialized at {self.db_path}")
    
    def _extract_patterns(self, thought_process: str, decision: str) -> List[str]:
        """Extract reasoning patterns from thoughts."""
        patterns = []
        
        # Common reasoning patterns
        pattern_indicators = {
            "root_cause_analysis": ["root cause", "underlying", "actual problem", "real issue"],
            "divide_and_conquer": ["break down", "smaller pieces", "step by step", "one at a time"],
            "process_of_elimination": ["rule out", "eliminate", "not the issue", "checked"],
            "hypothesis_testing": ["hypothesis", "test", "verify", "confirm", "assume"],
            "pattern_matching": ["similar to", "reminds me", "like when", "same as"],
            "first_principles": ["fundamentally", "basic", "core concept", "from scratch"],
            "working_backwards": ["end result", "work backwards", "start from", "goal is"],
            "incremental_refinement": ["iterate", "improve", "refine", "adjust"],
        }
        
        combined = f"{thought_process} {decision}".lower()
        for pattern, indicators in pattern_indicators.items():
            if any(ind in combined for ind in indicators):
                patterns.append(pattern)
        
        return patterns
    
    def add_reasoning(
        self,
        task_context: str,
        reasoning_type: ReasoningType,
        thought_process: str,
        decision: str,
        approach_summary: str,
        interaction_id: Optional[str] = None,
        key_insights: Optional[List[str]] = None,
        alternatives_considered: Optional[List[str]] = None,
        decision_rationale: Optional[str] = None,
        steps_taken: Optional[List[str]] = None,
        tools_used: Optional[List[str]] = None,
        outcome: Optional[str] = None,
        outcome_details: Optional[str] = None,
        lessons_learned: Optional[List[str]] = None,
        would_do_differently: Optional[str] = None,
        technologies: Optional[List[str]] = None
    ) -> str:
        """Store AI reasoning for later retrieval."""
        import uuid
        reasoning_id = str(uuid.uuid4())[:24]
        now = datetime.utcnow().isoformat()
        
        # Extract keywords and patterns
        all_text = f"{task_context} {thought_process} {decision} {approach_summary}"
        stop_words = {'the', 'a', 'an', 'is', 'are', 'to', 'of', 'in', 'for', 'on', 'with', 'and', 'but', 'or', 'i'}
        words = re.findall(r'\b[a-zA-Z]{4,}\b', all_text.lower())
        keywords = list(set(w for w in words if w not in stop_words))[:30]
        
        patterns = self._extract_patterns(thought_process, decision)
        
        search_embedding = f"{task_context} {thought_process} {decision} {' '.join(keywords)} {' '.join(patterns)}"
        
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO reasoning
                (id, timestamp, task_context, interaction_id, reasoning_type, thought_process,
                 key_insights, decision, alternatives_considered, decision_rationale,
                 approach_summary, steps_taken, tools_used, outcome, outcome_details,
                 lessons_learned, would_do_differently, keywords, technologies, patterns, search_embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reasoning_id, now, task_context, interaction_id, reasoning_type.value,
                thought_process, json.dumps(key_insights or []), decision,
                json.dumps(alternatives_considered or []), decision_rationale,
                approach_summary, json.dumps(steps_taken or []), json.dumps(tools_used or []),
                outcome, outcome_details, json.dumps(lessons_learned or []),
                would_do_differently, json.dumps(keywords), json.dumps(technologies or []),
                json.dumps(patterns), search_embedding
            ))
            
            # Update FTS
            conn.execute("""
                INSERT INTO reasoning_fts 
                (id, task_context, thought_process, decision, approach_summary, keywords, patterns)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                reasoning_id, task_context, thought_process, decision, approach_summary,
                ' '.join(keywords), ' '.join(patterns)
            ))
        
        return reasoning_id
    
    def update_outcome(
        self,
        reasoning_id: str,
        outcome: str,
        outcome_details: str,
        lessons_learned: Optional[List[str]] = None,
        would_do_differently: Optional[str] = None
    ) -> dict:
        """Update reasoning with outcome after task completion."""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE reasoning SET
                    outcome = ?,
                    outcome_details = ?,
                    lessons_learned = ?,
                    would_do_differently = ?
                WHERE id = ?
            """, (
                outcome, outcome_details,
                json.dumps(lessons_learned or []),
                would_do_differently,
                reasoning_id
            ))
    
    def search(
        self,
        query: str,
        mode: SearchMode = SearchMode.SEMANTIC,
        reasoning_type: Optional[ReasoningType] = None,
        outcome_filter: Optional[str] = None,
        technologies: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Search AI reasoning.
        
        Modes:
        - KEYWORD: FTS on reasoning content
        - SEMANTIC: Combines keywords + patterns + context
        - PATTERN: Find similar reasoning patterns
        - OUTCOME: Filter by success/failure
        """
        with self._get_conn() as conn:
            if mode == SearchMode.KEYWORD:
                rows = conn.execute("""
                    SELECT r.* FROM reasoning r
                    JOIN reasoning_fts fts ON r.id = fts.id
                    WHERE reasoning_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (query, limit)).fetchall()
            
            elif mode == SearchMode.PATTERN:
                # Extract patterns from query and find matching reasoning
                patterns = self._extract_patterns(query, "")
                if patterns:
                    pattern_conditions = " OR ".join(["patterns LIKE ?" for _ in patterns])
                    rows = conn.execute(f"""
                        SELECT * FROM reasoning
                        WHERE {pattern_conditions}
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, [f"%{p}%" for p in patterns] + [limit]).fetchall()
                else:
                    rows = []
            
            else:
                # Semantic search - combine multiple signals
                conditions = []
                params = []
                
                if query:
                    stop_words = {'the', 'a', 'an', 'is', 'are', 'to', 'of', 'in', 'for', 'on'}
                    words = re.findall(r'\b[a-zA-Z]{4,}\b', query.lower())
                    keywords = [w for w in words if w not in stop_words][:10]
                    
                    if keywords:
                        kw_conditions = " OR ".join(["search_embedding LIKE ?" for _ in keywords])
                        conditions.append(f"({kw_conditions})")
                        params.extend([f"%{kw}%" for kw in keywords])
                
                if reasoning_type:
                    conditions.append("reasoning_type = ?")
                    params.append(reasoning_type.value)
                
                if outcome_filter:
                    conditions.append("outcome = ?")
                    params.append(outcome_filter)
                
                if technologies:
                    tech_conditions = " OR ".join(["technologies LIKE ?" for _ in technologies])
                    conditions.append(f"({tech_conditions})")
                    params.extend([f"%{t}%" for t in technologies])
                
                where_clause = " AND ".join(conditions) if conditions else "1=1"
                
                rows = conn.execute(f"""
                    SELECT * FROM reasoning
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, params + [limit]).fetchall()
            
            results = []
            for row in rows:
                r = dict(row)
                r["key_insights"] = json.loads(r["key_insights"] or "[]")
                r["alternatives_considered"] = json.loads(r["alternatives_considered"] or "[]")
                r["steps_taken"] = json.loads(r["steps_taken"] or "[]")
                r["tools_used"] = json.loads(r["tools_used"] or "[]")
                r["lessons_learned"] = json.loads(r["lessons_learned"] or "[]")
                r["keywords"] = json.loads(r["keywords"] or "[]")
                r["technologies"] = json.loads(r["technologies"] or "[]")
                r["patterns"] = json.loads(r["patterns"] or "[]")
                results.append(r)
            
            return results
    
    def get_similar_approaches(self, task_context: str, limit: int = 5) -> List[Dict]:
        """Find similar past approaches for a given task."""
        return self.search(task_context, mode=SearchMode.SEMANTIC, limit=limit)
    
    def get_successful_patterns(self, problem_type: str = None, limit: int = 10) -> List[Dict]:
        """Get reasoning patterns that led to success."""
        return self.search(
            problem_type or "",
            mode=SearchMode.OUTCOME,
            outcome_filter="success",
            limit=limit
        )
    
    def get_stats(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM reasoning").fetchone()[0]
            
            # By type
            types = conn.execute("""
                SELECT reasoning_type, COUNT(*) as count
                FROM reasoning GROUP BY reasoning_type
            """).fetchall()
            
            # By outcome
            outcomes = conn.execute("""
                SELECT outcome, COUNT(*) as count
                FROM reasoning WHERE outcome IS NOT NULL
                GROUP BY outcome
            """).fetchall()
            
            # Most common patterns
            all_patterns = conn.execute("SELECT patterns FROM reasoning").fetchall()
            pattern_counts = {}
            for row in all_patterns:
                for p in json.loads(row["patterns"] or "[]"):
                    pattern_counts[p] = pattern_counts.get(p, 0) + 1
            
            return {
                "total_reasoning_entries": total,
                "by_type": {r["reasoning_type"]: r["count"] for r in types},
                "by_outcome": {r["outcome"]: r["count"] for r in outcomes if r["outcome"]},
                "top_patterns": sorted(pattern_counts.items(), key=lambda x: -x[1])[:10]
            }


# =============================================================================
# UNIFIED SEARCH
# =============================================================================

class UnifiedSearch:
    """
    Search across all databases to find relevant context.
    
    Combines:
    - User interactions (what was asked)
    - AI reasoning (how it was approached)
    - Knowledge DB (solutions and skills)
    """
    
    def __init__(self):
        self.user_db = get_user_interactions_db()
        self.ai_db = get_ai_reasoning_db()
        
        # Lazy load knowledge DB
        self._knowledge_db = None
    
    @property
    def knowledge_db(self) -> dict:
        if self._knowledge_db is None:
            from mcp_knowledge_db import get_mcp_knowledge_db
            self._knowledge_db = get_mcp_knowledge_db()
        return self._knowledge_db
    
    def search_all(
        self,
        query: str,
        include_user: bool = True,
        include_ai: bool = True,
        include_knowledge: bool = True,
        limit_per_source: int = 5
    ) -> Dict[str, List[Dict]]:
        """
        Search across all databases.
        
        Returns results grouped by source.
        """
        results = {}
        
        if include_user:
            results["user_interactions"] = self.user_db.search(
                query, mode=SearchMode.SEMANTIC, limit=limit_per_source
            )
        
        if include_ai:
            results["ai_reasoning"] = self.ai_db.search(
                query, mode=SearchMode.SEMANTIC, limit=limit_per_source
            )
        
        if include_knowledge:
            # Search skills and solutions
            results["skills"] = self.knowledge_db.find_skills(query, limit=limit_per_source)
            results["solutions"] = self.knowledge_db.search_solutions(query, limit=limit_per_source)
            results["memories"] = self.knowledge_db.search_memories(query, limit=limit_per_source)
        
        return results
    
    def find_relevant_context(self, task_description: str) -> str:
        """
        Find relevant context for a new task.
        Returns formatted context string for use in prompts.
        """
        results = self.search_all(task_description, limit_per_source=3)
        
        context_parts = []
        
        # Past similar interactions
        if results.get("user_interactions"):
            context_parts.append("**Similar Past Requests:**")
            for i, interaction in enumerate(results["user_interactions"][:2], 1):
                context_parts.append(f"{i}. {interaction['user_message'][:200]}...")
                if interaction.get("resolution_summary"):
                    context_parts.append(f"   → Resolved: {interaction['resolution_summary'][:100]}")
        
        # Relevant reasoning
        if results.get("ai_reasoning"):
            context_parts.append("\n**Relevant Past Reasoning:**")
            for reasoning in results["ai_reasoning"][:2]:
                context_parts.append(f"- Approach: {reasoning['approach_summary'][:150]}")
                if reasoning.get("lessons_learned"):
                    lessons = reasoning["lessons_learned"][:2]
                    context_parts.append(f"  Lessons: {'; '.join(lessons)}")
        
        # Skills
        if results.get("skills"):
            context_parts.append("\n**Available Skills:**")
            for skill in results["skills"][:3]:
                context_parts.append(f"- {skill['name']}: {skill.get('solution_text', '')[:100]}")
        
        return "\n".join(context_parts) if context_parts else "No relevant context found."


# =============================================================================
# SINGLETONS
# =============================================================================

_user_db: Optional[UserInteractionsDB] = None
_ai_db: Optional[AIReasoningDB] = None
_unified_search: Optional[UnifiedSearch] = None


def get_user_interactions_db() -> UserInteractionsDB:
    global _user_db
    if _user_db is None:
        _user_db = UserInteractionsDB()
    return _user_db


def get_ai_reasoning_db() -> AIReasoningDB:
    global _ai_db
    if _ai_db is None:
        _ai_db = AIReasoningDB()
    return _ai_db


def get_unified_search() -> UnifiedSearch:
    global _unified_search
    if _unified_search is None:
        _unified_search = UnifiedSearch()
    return _unified_search
