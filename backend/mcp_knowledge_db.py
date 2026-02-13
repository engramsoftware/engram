"""
MCP Knowledge Database - Dedicated SQLite database for MCP server.

Separate from the main chat MongoDB database.
Stores: skills, sessions, outcomes, memories, solutions, patterns.

This replaces the need for Neo4j/ChromaDB - works standalone!
"""

import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
from contextlib import contextmanager
import hashlib

logger = logging.getLogger(__name__)

# Database path - centralized under data/mcp/
from config import MCP_KNOWLEDGE_DB
DB_PATH = MCP_KNOWLEDGE_DB


class MCPKnowledgeDB:
    """
    SQLite-based knowledge database for the MCP server.
    
    Stores everything the MCP needs without external dependencies:
    - Skills (reusable solutions)
    - Sessions (task tracking)
    - Outcomes (success/failure history)
    - Memories (context and facts)
    - Solutions (problem->solution pairs)
    - Patterns (learned patterns from outcomes)
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    @contextmanager
    def _get_conn(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Skills table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT DEFAULT 'general',
                    triggers TEXT,  -- JSON array of regex patterns
                    solution_text TEXT,
                    code_template TEXT,
                    technologies TEXT,  -- JSON array
                    confidence REAL DEFAULT 0.5,
                    times_used INTEGER DEFAULT 0,
                    successes INTEGER DEFAULT 0,
                    failures INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    source TEXT DEFAULT 'manual'  -- manual, auto_learned, llm_generated
                )
            """)
            
            # Sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    task_description TEXT,
                    task_goal TEXT,
                    status TEXT DEFAULT 'in_progress',
                    plan_steps TEXT,  -- JSON array
                    current_step INTEGER DEFAULT 0,
                    working_files TEXT,  -- JSON array
                    key_discoveries TEXT,  -- JSON array
                    checkpoints TEXT,  -- JSON array
                    technologies TEXT,  -- JSON array
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            
            # Outcomes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS outcomes (
                    id TEXT PRIMARY KEY,
                    task_description TEXT,
                    solution_applied TEXT,
                    outcome_type TEXT,  -- success, partial_success, failure
                    technologies TEXT,  -- JSON array
                    skills_used TEXT,  -- JSON array of skill IDs
                    error_if_failed TEXT,
                    code_snippet TEXT,
                    created_at TEXT
                )
            """)
            
            # Memories table (replaces ChromaDB)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT DEFAULT 'fact',  -- fact, preference, solution, error, pattern
                    keywords TEXT,  -- JSON array for searching
                    technologies TEXT,  -- JSON array
                    embedding_hash TEXT,  -- For deduplication
                    created_at TEXT,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TEXT
                )
            """)
            
            # Solutions table (replaces Neo4j for problem->solution mapping)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS solutions (
                    id TEXT PRIMARY KEY,
                    problem TEXT NOT NULL,
                    solution TEXT NOT NULL,
                    code_before TEXT,
                    code_after TEXT,
                    technologies TEXT,  -- JSON array
                    keywords TEXT,  -- JSON array for searching
                    success_count INTEGER DEFAULT 1,
                    created_at TEXT
                )
            """)
            
            # Patterns table (for auto-learning)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    id TEXT PRIMARY KEY,
                    pattern_hash TEXT UNIQUE,
                    keywords TEXT,  -- JSON array
                    technologies TEXT,  -- JSON array
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    skill_generated INTEGER DEFAULT 0,
                    skill_id TEXT,
                    first_seen TEXT,
                    last_seen TEXT
                )
            """)
            
            # Chat history import table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id TEXT PRIMARY KEY,
                    role TEXT,  -- user, assistant
                    content TEXT,
                    timestamp TEXT,
                    session_id TEXT,
                    extracted_skills TEXT,  -- JSON array of skill IDs extracted
                    extracted_solutions TEXT  -- JSON array of solution IDs extracted
                )
            """)
            
            # Playbooks table - step-by-step instructions for weak models
            # Generated by smart models, consumed by dumb models
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS playbooks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    task_type TEXT,  -- e.g., 'add-api-endpoint', 'fix-import-error', 'add-component'
                    difficulty TEXT DEFAULT 'medium',  -- easy, medium, hard
                    steps TEXT NOT NULL,  -- JSON array of step objects
                    decision_tree TEXT,  -- JSON object for conditional logic
                    code_templates TEXT,  -- JSON object of named templates
                    prerequisites TEXT,  -- JSON array of required context
                    examples TEXT,  -- JSON array of input/output examples
                    guardrails TEXT,  -- JSON array of "do this, not that" rules
                    technologies TEXT,  -- JSON array
                    keywords TEXT,  -- JSON array for searching
                    generated_by TEXT DEFAULT 'smart_model',  -- smart_model, manual, auto
                    times_used INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0.7,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            
            # Create indexes for fast searching
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_skills_triggers ON skills(triggers)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_skills_tech ON skills(technologies)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_type ON outcomes(outcome_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_keywords ON memories(keywords)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_solutions_keywords ON solutions(keywords)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_patterns_hash ON patterns(pattern_hash)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_playbooks_type ON playbooks(task_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_playbooks_keywords ON playbooks(keywords)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_playbooks_tech ON playbooks(technologies)")
            
            logger.info(f"MCP Knowledge DB initialized at {self.db_path}")
    
    # ==================== SKILLS ====================
    
    def add_skill(self, skill: Dict[str, Any]) -> str:
        """Add a skill to the database."""
        skill_id = skill.get('id') or self._generate_id()
        now = datetime.utcnow().isoformat()
        
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO skills 
                (id, name, description, category, triggers, solution_text, code_template,
                 technologies, confidence, times_used, successes, failures, created_at, updated_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                skill_id,
                skill.get('name', ''),
                skill.get('description', ''),
                skill.get('category', 'general'),
                json.dumps(skill.get('triggers', [])),
                skill.get('solution_text', ''),
                skill.get('code_template'),
                json.dumps(skill.get('technologies', [])),
                skill.get('confidence', 0.5),
                skill.get('times_used', 0),
                skill.get('successes', 0),
                skill.get('failures', 0),
                skill.get('created_at', now),
                now,
                skill.get('source', 'manual')
            ))
        
        return skill_id
    
    def find_skills(self, query: str, limit: int = 5) -> List[Dict]:
        """Find skills matching a query."""
        query_lower = query.lower()
        keywords = self._extract_keywords(query)
        
        with self._get_conn() as conn:
            # Get all skills and score them
            rows = conn.execute("SELECT * FROM skills").fetchall()
            
            scored = []
            for row in rows:
                score = 0
                skill = dict(row)
                
                # Check triggers
                triggers = json.loads(skill['triggers'] or '[]')
                for trigger in triggers:
                    if trigger.lower() in query_lower:
                        score += 0.5
                
                # Check keywords in name/description
                name_desc = f"{skill['name']} {skill['description']}".lower()
                for kw in keywords:
                    if kw in name_desc:
                        score += 0.2
                
                # Check technologies
                techs = json.loads(skill['technologies'] or '[]')
                for tech in techs:
                    if tech.lower() in query_lower:
                        score += 0.3
                
                if score > 0:
                    skill['match_score'] = min(score, 1.0)
                    skill['triggers'] = triggers
                    skill['technologies'] = techs
                    scored.append(skill)
            
            # Sort by score
            scored.sort(key=lambda x: -x['match_score'])
            return scored[:limit]
    
    def update_skill_usage(self, skill_id: str, successful: bool) -> dict:
        """Update skill usage statistics."""
        with self._get_conn() as conn:
            if successful:
                conn.execute("""
                    UPDATE skills SET 
                        times_used = times_used + 1,
                        successes = successes + 1,
                        confidence = MIN(0.95, confidence + 0.05),
                        updated_at = ?
                    WHERE id = ?
                """, (datetime.utcnow().isoformat(), skill_id))
            else:
                conn.execute("""
                    UPDATE skills SET 
                        times_used = times_used + 1,
                        failures = failures + 1,
                        confidence = MAX(0.1, confidence - 0.1),
                        updated_at = ?
                    WHERE id = ?
                """, (datetime.utcnow().isoformat(), skill_id))
    
    # ==================== SESSIONS ====================
    
    def create_session(self, session: Dict[str, Any]) -> str:
        """Create a new session."""
        session_id = session.get('id') or self._generate_id()
        now = datetime.utcnow().isoformat()
        
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO sessions 
                (id, task_description, task_goal, status, plan_steps, current_step,
                 working_files, key_discoveries, checkpoints, technologies, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                session.get('task_description', ''),
                session.get('task_goal', ''),
                session.get('status', 'in_progress'),
                json.dumps(session.get('plan_steps', [])),
                session.get('current_step', 0),
                json.dumps(session.get('working_files', [])),
                json.dumps(session.get('key_discoveries', [])),
                json.dumps(session.get('checkpoints', [])),
                json.dumps(session.get('technologies', [])),
                now,
                now
            ))
        
        return session_id
    
    def get_resumable_sessions(self) -> List[Dict]:
        """Get sessions that can be resumed."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM sessions 
                WHERE status = 'in_progress'
                ORDER BY updated_at DESC
                LIMIT 10
            """).fetchall()
            
            sessions = []
            for row in rows:
                session = dict(row)
                session['plan_steps'] = json.loads(session['plan_steps'] or '[]')
                session['working_files'] = json.loads(session['working_files'] or '[]')
                session['key_discoveries'] = json.loads(session['key_discoveries'] or '[]')
                session['checkpoints'] = json.loads(session['checkpoints'] or '[]')
                session['technologies'] = json.loads(session['technologies'] or '[]')
                
                # Calculate progress
                steps = session['plan_steps']
                if steps:
                    session['progress'] = f"{int((session['current_step'] / len(steps)) * 100)}%"
                else:
                    session['progress'] = "0%"
                
                sessions.append(session)
            
            return sessions
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get a session by ID."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                session = dict(row)
                session['plan_steps'] = json.loads(session['plan_steps'] or '[]')
                session['working_files'] = json.loads(session['working_files'] or '[]')
                session['key_discoveries'] = json.loads(session['key_discoveries'] or '[]')
                session['checkpoints'] = json.loads(session['checkpoints'] or '[]')
                session['technologies'] = json.loads(session['technologies'] or '[]')
                return session
            return None
    
    def update_session(self, session_id: str, updates: Dict[str, Any]) -> dict:
        """Update a session."""
        session = self.get_session(session_id)
        if not session:
            return False
        
        # Merge updates
        for key, value in updates.items():
            if key in session:
                session[key] = value
        
        session['updated_at'] = datetime.utcnow().isoformat()
        
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE sessions SET
                    task_description = ?, task_goal = ?, status = ?,
                    plan_steps = ?, current_step = ?, working_files = ?,
                    key_discoveries = ?, checkpoints = ?, technologies = ?, updated_at = ?
                WHERE id = ?
            """, (
                session['task_description'],
                session['task_goal'],
                session['status'],
                json.dumps(session['plan_steps']),
                session['current_step'],
                json.dumps(session['working_files']),
                json.dumps(session['key_discoveries']),
                json.dumps(session['checkpoints']),
                json.dumps(session['technologies']),
                session['updated_at'],
                session_id
            ))
        
        return True
    
    # ==================== OUTCOMES ====================
    
    def record_outcome(self, outcome: Dict[str, Any]) -> str:
        """Record an outcome."""
        outcome_id = outcome.get('id') or self._generate_id()
        now = datetime.utcnow().isoformat()
        
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO outcomes 
                (id, task_description, solution_applied, outcome_type, technologies,
                 skills_used, error_if_failed, code_snippet, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                outcome_id,
                outcome.get('task_description', ''),
                outcome.get('solution_applied', ''),
                outcome.get('outcome_type', 'unknown'),
                json.dumps(outcome.get('technologies', [])),
                json.dumps(outcome.get('skills_used', [])),
                outcome.get('error_if_failed'),
                outcome.get('code_snippet'),
                now
            ))
        
        return outcome_id
    
    def get_outcome_stats(self) -> Dict[str, Any]:
        """Get outcome statistics."""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
            successes = conn.execute("SELECT COUNT(*) FROM outcomes WHERE outcome_type = 'success'").fetchone()[0]
            failures = conn.execute("SELECT COUNT(*) FROM outcomes WHERE outcome_type = 'failure'").fetchone()[0]
            
            # Technology breakdown
            rows = conn.execute("SELECT technologies FROM outcomes").fetchall()
            tech_stats = {}
            for row in rows:
                techs = json.loads(row['technologies'] or '[]')
                for tech in techs:
                    if tech not in tech_stats:
                        tech_stats[tech] = {'success': 0, 'failure': 0}
            
            # Count by tech
            for row in conn.execute("SELECT technologies, outcome_type FROM outcomes").fetchall():
                techs = json.loads(row['technologies'] or '[]')
                outcome = row['outcome_type']
                for tech in techs:
                    if tech in tech_stats:
                        if outcome == 'success':
                            tech_stats[tech]['success'] += 1
                        elif outcome == 'failure':
                            tech_stats[tech]['failure'] += 1
            
            return {
                'total_outcomes': total,
                'success_count': successes,
                'failure_count': failures,
                'success_rate': successes / total if total > 0 else 0,
                'technology_stats': tech_stats
            }
    
    # ==================== MEMORIES ====================
    
    def store_memory(self, content: str, memory_type: str = 'fact', 
                     technologies: Optional[List[str]] = None) -> str:
        """Store a memory."""
        memory_id = self._generate_id()
        keywords = self._extract_keywords(content)
        embedding_hash = hashlib.md5(content.encode()).hexdigest()
        now = datetime.utcnow().isoformat()
        
        with self._get_conn() as conn:
            # Check for duplicate
            existing = conn.execute(
                "SELECT id FROM memories WHERE embedding_hash = ?", 
                (embedding_hash,)
            ).fetchone()
            
            if existing:
                # Update access count
                conn.execute("""
                    UPDATE memories SET access_count = access_count + 1, last_accessed = ?
                    WHERE id = ?
                """, (now, existing['id']))
                return existing['id']
            
            conn.execute("""
                INSERT INTO memories 
                (id, content, memory_type, keywords, technologies, embedding_hash, 
                 created_at, access_count, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                memory_id,
                content,
                memory_type,
                json.dumps(keywords),
                json.dumps(technologies or []),
                embedding_hash,
                now,
                now
            ))
        
        return memory_id
    
    def search_memories(self, query: str, limit: int = 5) -> List[Dict]:
        """Search memories by keyword matching."""
        keywords = self._extract_keywords(query)
        
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM memories").fetchall()
            
            scored = []
            for row in rows:
                memory = dict(row)
                mem_keywords = json.loads(memory['keywords'] or '[]')
                
                # Score by keyword overlap
                overlap = len(set(keywords) & set(mem_keywords))
                if overlap > 0:
                    memory['match_score'] = overlap / max(len(keywords), 1)
                    memory['keywords'] = mem_keywords
                    memory['technologies'] = json.loads(memory['technologies'] or '[]')
                    scored.append(memory)
            
            scored.sort(key=lambda x: -x['match_score'])
            return scored[:limit]
    
    # ==================== SOLUTIONS ====================
    
    def store_solution(self, problem: str, solution: str, 
                       technologies: Optional[List[str]] = None,
                       code_before: Optional[str] = None,
                       code_after: Optional[str] = None) -> str:
        """Store a problem->solution pair."""
        solution_id = self._generate_id()
        keywords = self._extract_keywords(f"{problem} {solution}")
        now = datetime.utcnow().isoformat()
        
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO solutions 
                (id, problem, solution, code_before, code_after, technologies, keywords, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                solution_id,
                problem,
                solution,
                code_before,
                code_after,
                json.dumps(technologies or []),
                json.dumps(keywords),
                now
            ))
        
        return solution_id
    
    def search_solutions(self, query: str, limit: int = 5) -> List[Dict]:
        """Search for solutions matching a problem."""
        keywords = self._extract_keywords(query)
        query_lower = query.lower()
        
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM solutions").fetchall()
            
            scored = []
            for row in rows:
                sol = dict(row)
                sol_keywords = json.loads(sol['keywords'] or '[]')
                
                # Score by keyword overlap and direct matching
                overlap = len(set(keywords) & set(sol_keywords))
                direct_match = 1 if any(kw in sol['problem'].lower() for kw in keywords) else 0
                
                score = (overlap / max(len(keywords), 1)) * 0.6 + direct_match * 0.4
                
                if score > 0.1:
                    sol['match_score'] = score
                    sol['keywords'] = sol_keywords
                    sol['technologies'] = json.loads(sol['technologies'] or '[]')
                    scored.append(sol)
            
            scored.sort(key=lambda x: -x['match_score'])
            return scored[:limit]
    
    # ==================== PATTERNS ====================
    
    def record_pattern(self, keywords: List[str], technologies: List[str], 
                       success: bool) -> Optional[str]:
        """Record a pattern for auto-learning."""
        pattern_hash = hashlib.md5(
            '|'.join(sorted(keywords[:10]) + sorted(technologies)).encode()
        ).hexdigest()[:12]
        now = datetime.utcnow().isoformat()
        
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT * FROM patterns WHERE pattern_hash = ?",
                (pattern_hash,)
            ).fetchone()
            
            if existing:
                # Update existing pattern
                if success:
                    conn.execute("""
                        UPDATE patterns SET 
                            success_count = success_count + 1,
                            last_seen = ?
                        WHERE pattern_hash = ?
                    """, (now, pattern_hash))
                else:
                    conn.execute("""
                        UPDATE patterns SET 
                            failure_count = failure_count + 1,
                            last_seen = ?
                        WHERE pattern_hash = ?
                    """, (now, pattern_hash))
                return existing['id']
            else:
                # Create new pattern
                pattern_id = self._generate_id()
                conn.execute("""
                    INSERT INTO patterns 
                    (id, pattern_hash, keywords, technologies, success_count, failure_count,
                     first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pattern_id,
                    pattern_hash,
                    json.dumps(keywords),
                    json.dumps(technologies),
                    1 if success else 0,
                    0 if success else 1,
                    now,
                    now
                ))
                return pattern_id
    
    def get_patterns_ready_for_skill(self, min_successes: int = 3, 
                                      min_success_rate: float = 0.7) -> List[Dict]:
        """Get patterns ready to become skills."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM patterns 
                WHERE skill_generated = 0 AND success_count >= ?
            """, (min_successes,)).fetchall()
            
            ready = []
            for row in rows:
                pattern = dict(row)
                total = pattern['success_count'] + pattern['failure_count']
                if total > 0:
                    success_rate = pattern['success_count'] / total
                    if success_rate >= min_success_rate:
                        pattern['success_rate'] = success_rate
                        pattern['keywords'] = json.loads(pattern['keywords'] or '[]')
                        pattern['technologies'] = json.loads(pattern['technologies'] or '[]')
                        ready.append(pattern)
            
            return ready
    
    # ==================== PLAYBOOKS ====================
    
    def add_playbook(self, playbook: Dict[str, Any]) -> str:
        """Add a playbook to the database."""
        playbook_id = playbook.get('id') or self._generate_id()
        now = datetime.utcnow().isoformat()
        
        # Extract keywords from name + description + steps text
        search_text = f"{playbook.get('name', '')} {playbook.get('description', '')} {playbook.get('task_type', '')}"
        keywords = playbook.get('keywords') or self._extract_keywords(search_text)
        
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO playbooks 
                (id, name, description, task_type, difficulty, steps, decision_tree,
                 code_templates, prerequisites, examples, guardrails, technologies,
                 keywords, generated_by, times_used, success_count, failure_count,
                 confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                playbook_id,
                playbook.get('name', ''),
                playbook.get('description', ''),
                playbook.get('task_type', 'general'),
                playbook.get('difficulty', 'medium'),
                json.dumps(playbook.get('steps', [])),
                json.dumps(playbook.get('decision_tree', {})),
                json.dumps(playbook.get('code_templates', {})),
                json.dumps(playbook.get('prerequisites', [])),
                json.dumps(playbook.get('examples', [])),
                json.dumps(playbook.get('guardrails', [])),
                json.dumps(playbook.get('technologies', [])),
                json.dumps(keywords),
                playbook.get('generated_by', 'smart_model'),
                playbook.get('times_used', 0),
                playbook.get('success_count', 0),
                playbook.get('failure_count', 0),
                playbook.get('confidence', 0.7),
                playbook.get('created_at', now),
                now
            ))
        
        return playbook_id
    
    def find_playbooks(self, query: str, limit: int = 3) -> List[Dict]:
        """Find playbooks matching a task description."""
        keywords = self._extract_keywords(query)
        query_lower = query.lower()
        
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM playbooks").fetchall()
            
            scored = []
            for row in rows:
                playbook = dict(row)
                pb_keywords = json.loads(playbook['keywords'] or '[]')
                
                # Score by keyword overlap
                overlap = len(set(keywords) & set(pb_keywords))
                kw_score = overlap / max(len(keywords), 1)
                
                # Score by task_type match
                type_score = 0.5 if playbook['task_type'] and playbook['task_type'].lower() in query_lower else 0
                
                # Score by technology match
                techs = json.loads(playbook['technologies'] or '[]')
                tech_score = sum(0.2 for t in techs if t.lower() in query_lower)
                
                # Confidence boost
                conf_boost = playbook['confidence'] * 0.1
                
                score = kw_score * 0.4 + type_score * 0.3 + min(tech_score, 0.3) + conf_boost
                
                if score > 0.1:
                    playbook['match_score'] = round(min(score, 1.0), 3)
                    playbook['steps'] = json.loads(playbook['steps'] or '[]')
                    playbook['decision_tree'] = json.loads(playbook['decision_tree'] or '{}')
                    playbook['code_templates'] = json.loads(playbook['code_templates'] or '{}')
                    playbook['prerequisites'] = json.loads(playbook['prerequisites'] or '[]')
                    playbook['examples'] = json.loads(playbook['examples'] or '[]')
                    playbook['guardrails'] = json.loads(playbook['guardrails'] or '[]')
                    playbook['technologies'] = techs
                    playbook['keywords'] = pb_keywords
                    scored.append(playbook)
            
            scored.sort(key=lambda x: -x['match_score'])
            return scored[:limit]
    
    def update_playbook_usage(self, playbook_id: str, successful: bool) -> dict:
        """Update playbook usage statistics."""
        with self._get_conn() as conn:
            if successful:
                conn.execute("""
                    UPDATE playbooks SET 
                        times_used = times_used + 1,
                        success_count = success_count + 1,
                        confidence = MIN(0.99, confidence + 0.03),
                        updated_at = ?
                    WHERE id = ?
                """, (datetime.utcnow().isoformat(), playbook_id))
            else:
                conn.execute("""
                    UPDATE playbooks SET 
                        times_used = times_used + 1,
                        failure_count = failure_count + 1,
                        confidence = MAX(0.1, confidence - 0.08),
                        updated_at = ?
                    WHERE id = ?
                """, (datetime.utcnow().isoformat(), playbook_id))
    
    def get_playbook(self, playbook_id: str) -> Optional[Dict]:
        """Get a playbook by ID."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM playbooks WHERE id = ?", (playbook_id,)).fetchone()
            if row:
                pb = dict(row)
                pb['steps'] = json.loads(pb['steps'] or '[]')
                pb['decision_tree'] = json.loads(pb['decision_tree'] or '{}')
                pb['code_templates'] = json.loads(pb['code_templates'] or '{}')
                pb['prerequisites'] = json.loads(pb['prerequisites'] or '[]')
                pb['examples'] = json.loads(pb['examples'] or '[]')
                pb['guardrails'] = json.loads(pb['guardrails'] or '[]')
                pb['technologies'] = json.loads(pb['technologies'] or '[]')
                pb['keywords'] = json.loads(pb['keywords'] or '[]')
                return pb
            return None
    
    # ==================== UTILITIES ====================
    
    def _generate_id(self) -> str:
        """Generate a unique ID."""
        import uuid
        return str(uuid.uuid4())[:24]
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        import re
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'to', 'of', 'in', 'for', 'on',
            'with', 'at', 'by', 'from', 'as', 'into', 'through', 'and', 'but',
            'or', 'not', 'this', 'that', 'it', 'its', 'i', 'you', 'we', 'they',
            'how', 'what', 'when', 'where', 'why', 'which', 'who'
        }
        
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        keywords = [w for w in words if w not in stop_words]
        return list(set(keywords))[:20]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._get_conn() as conn:
            return {
                'skills': conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0],
                'sessions': conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                'outcomes': conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0],
                'memories': conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
                'solutions': conn.execute("SELECT COUNT(*) FROM solutions").fetchone()[0],
                'patterns': conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0],
                'playbooks': conn.execute("SELECT COUNT(*) FROM playbooks").fetchone()[0],
                'db_path': str(self.db_path)
            }


# Singleton
_mcp_db: Optional[MCPKnowledgeDB] = None


def get_mcp_knowledge_db() -> MCPKnowledgeDB:
    """Get or create the MCP knowledge database singleton."""
    global _mcp_db
    if _mcp_db is None:
        _mcp_db = MCPKnowledgeDB()
    return _mcp_db
