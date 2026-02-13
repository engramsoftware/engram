"""
Skill Store — SQLite-backed persistent storage for the Voyager skill library.

Each skill is a verified response strategy that the system learned from
observing successful conversations. Skills have:
- A query pattern (what triggers them)
- A strategy (instructions injected before the LLM)
- Confidence scores that evolve with feedback
- Composition chains (parent skills that combine into this skill)

Inspired by Voyager's executable skill library, but adapted for a
conversational AI system rather than Minecraft.
"""

import sqlite3
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

from config import DATA_DIR

logger = logging.getLogger(__name__)

# Store skills alongside other data
SKILL_DB_PATH = DATA_DIR / "learning" / "skill_voyager.db"


@dataclass
class Skill:
    """A single learned skill in the library."""
    id: str
    name: str
    skill_type: str  # search_strategy, response_format, retrieval_combo, conversation_pattern, error_recovery
    description: str
    # The actual strategy text injected into system prompt when skill activates
    strategy: str
    # Query classification patterns that trigger this skill
    trigger_patterns: List[str] = field(default_factory=list)
    # Confidence: starts at 0.5, grows with success, decays with failure
    confidence: float = 0.5
    # Usage tracking
    times_used: int = 0
    times_succeeded: int = 0
    times_failed: int = 0
    # Composition: IDs of parent skills this was composed from
    parent_skill_ids: List[str] = field(default_factory=list)
    # Composition: IDs of child skills derived from this
    child_skill_ids: List[str] = field(default_factory=list)
    # Lifecycle state: candidate -> verified -> mastered -> deprecated
    state: str = "candidate"
    # Source: how this skill was created
    source: str = "observed"  # observed, composed, curriculum, manual
    # Timestamps
    created_at: float = 0.0
    last_used_at: float = 0.0
    last_evaluated_at: float = 0.0


@dataclass
class SkillEvaluation:
    """Result of evaluating a response where a skill was applied."""
    id: str
    skill_id: str
    message_id: str
    conversation_id: str
    score: float  # 1-5 scale
    reasoning: str
    query_text: str
    response_snippet: str
    evaluated_at: float = 0.0


class SkillStore:
    """
    SQLite-backed skill library with CRUD, search, and analytics.

    Schema:
    - skills: The skill definitions and metadata
    - evaluations: Per-message evaluation results
    - composition_log: Track how skills get composed
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or SKILL_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    skill_type TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    strategy TEXT NOT NULL,
                    trigger_patterns TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    times_used INTEGER NOT NULL DEFAULT 0,
                    times_succeeded INTEGER NOT NULL DEFAULT 0,
                    times_failed INTEGER NOT NULL DEFAULT 0,
                    parent_skill_ids TEXT NOT NULL DEFAULT '[]',
                    child_skill_ids TEXT NOT NULL DEFAULT '[]',
                    state TEXT NOT NULL DEFAULT 'candidate',
                    source TEXT NOT NULL DEFAULT 'observed',
                    created_at REAL NOT NULL,
                    last_used_at REAL NOT NULL DEFAULT 0,
                    last_evaluated_at REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    reasoning TEXT NOT NULL DEFAULT '',
                    query_text TEXT NOT NULL DEFAULT '',
                    response_snippet TEXT NOT NULL DEFAULT '',
                    evaluated_at REAL NOT NULL,
                    FOREIGN KEY (skill_id) REFERENCES skills(id)
                );

                CREATE TABLE IF NOT EXISTS composition_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_ids TEXT NOT NULL,
                    child_id TEXT NOT NULL,
                    method TEXT NOT NULL DEFAULT 'auto',
                    reasoning TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_skills_type ON skills(skill_type);
                CREATE INDEX IF NOT EXISTS idx_skills_state ON skills(state);
                CREATE INDEX IF NOT EXISTS idx_skills_confidence ON skills(confidence DESC);
                CREATE INDEX IF NOT EXISTS idx_evals_skill ON evaluations(skill_id);
            """)
        logger.info(f"Skill store initialized at {self.db_path}")

    # ── CRUD ──────────────────────────────────────────────────

    def add_skill(self, skill: Skill) -> bool:
        """Add a new skill to the library."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """INSERT INTO skills (id, name, skill_type, description, strategy,
                       trigger_patterns, confidence, times_used, times_succeeded, times_failed,
                       parent_skill_ids, child_skill_ids, state, source, created_at,
                       last_used_at, last_evaluated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (skill.id, skill.name, skill.skill_type, skill.description,
                     skill.strategy, json.dumps(skill.trigger_patterns),
                     skill.confidence, skill.times_used, skill.times_succeeded,
                     skill.times_failed, json.dumps(skill.parent_skill_ids),
                     json.dumps(skill.child_skill_ids), skill.state, skill.source,
                     skill.created_at or time.time(), skill.last_used_at,
                     skill.last_evaluated_at)
                )
            logger.info(f"Added skill: {skill.name} ({skill.id})")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"Skill already exists: {skill.id}")
            return False
        except Exception as e:
            logger.error(f"Failed to add skill: {e}")
            return False

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get a single skill by ID."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
            if row:
                return self._row_to_skill(row)
        return None

    def update_skill(self, skill: Skill) -> bool:
        """Update an existing skill."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """UPDATE skills SET name=?, skill_type=?, description=?, strategy=?,
                       trigger_patterns=?, confidence=?, times_used=?, times_succeeded=?,
                       times_failed=?, parent_skill_ids=?, child_skill_ids=?, state=?,
                       source=?, last_used_at=?, last_evaluated_at=?
                       WHERE id=?""",
                    (skill.name, skill.skill_type, skill.description, skill.strategy,
                     json.dumps(skill.trigger_patterns), skill.confidence,
                     skill.times_used, skill.times_succeeded, skill.times_failed,
                     json.dumps(skill.parent_skill_ids), json.dumps(skill.child_skill_ids),
                     skill.state, skill.source, skill.last_used_at,
                     skill.last_evaluated_at, skill.id)
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update skill {skill.id}: {e}")
            return False

    def delete_skill(self, skill_id: str) -> bool:
        """Remove a skill from the library."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
                conn.execute("DELETE FROM evaluations WHERE skill_id = ?", (skill_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to delete skill {skill_id}: {e}")
            return False

    # ── Search & Retrieval ────────────────────────────────────

    def find_matching_skills(
        self,
        query: str,
        min_confidence: float = 0.4,
        limit: int = 3
    ) -> List[Skill]:
        """
        Find skills whose trigger patterns match the query.
        Uses keyword overlap scoring, ordered by confidence * match_score.

        Args:
            query: The user's message text.
            min_confidence: Minimum confidence threshold.
            limit: Maximum skills to return.

        Returns:
            List of matching skills, best first.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM skills
                   WHERE confidence >= ? AND state IN ('candidate', 'verified', 'mastered')
                   ORDER BY confidence DESC""",
                (min_confidence,)
            ).fetchall()

        scored = []
        for row in rows:
            skill = self._row_to_skill(row)
            match_score = self._compute_match_score(query_lower, query_words, skill)
            if match_score > 0.1:
                scored.append((skill, match_score * skill.confidence))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored[:limit]]

    def get_all_skills(
        self,
        state: Optional[str] = None,
        skill_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Skill]:
        """Get all skills, optionally filtered by state or type."""
        clauses = []
        params: List[Any] = []

        if state:
            clauses.append("state = ?")
            params.append(state)
        if skill_type:
            clauses.append("skill_type = ?")
            params.append(skill_type)

        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM skills WHERE {where} ORDER BY confidence DESC LIMIT ?",
                params
            ).fetchall()

        return [self._row_to_skill(r) for r in rows]

    def get_skill_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics about the skill library."""
        with sqlite3.connect(str(self.db_path)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
            by_state = dict(conn.execute(
                "SELECT state, COUNT(*) FROM skills GROUP BY state"
            ).fetchall())
            by_type = dict(conn.execute(
                "SELECT skill_type, COUNT(*) FROM skills GROUP BY skill_type"
            ).fetchall())
            avg_confidence = conn.execute(
                "SELECT AVG(confidence) FROM skills WHERE state != 'deprecated'"
            ).fetchone()[0] or 0.0
            total_evals = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
            avg_eval = conn.execute(
                "SELECT AVG(score) FROM evaluations"
            ).fetchone()[0] or 0.0

        return {
            "total_skills": total,
            "by_state": by_state,
            "by_type": by_type,
            "avg_confidence": round(avg_confidence, 3),
            "total_evaluations": total_evals,
            "avg_evaluation_score": round(avg_eval, 2),
        }

    # ── Evaluation Tracking ───────────────────────────────────

    def record_evaluation(self, evaluation: SkillEvaluation) -> bool:
        """Record a response evaluation for a skill."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """INSERT INTO evaluations
                       (id, skill_id, message_id, conversation_id, score,
                        reasoning, query_text, response_snippet, evaluated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (evaluation.id, evaluation.skill_id, evaluation.message_id,
                     evaluation.conversation_id, evaluation.score,
                     evaluation.reasoning, evaluation.query_text,
                     evaluation.response_snippet,
                     evaluation.evaluated_at or time.time())
                )
            return True
        except Exception as e:
            logger.error(f"Failed to record evaluation: {e}")
            return False

    def get_recent_evaluations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent evaluations with skill names."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT e.*, s.name as skill_name, s.skill_type
                   FROM evaluations e
                   LEFT JOIN skills s ON e.skill_id = s.id
                   ORDER BY e.evaluated_at DESC LIMIT ?""",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Confidence Evolution ──────────────────────────────────

    def update_confidence(self, skill_id: str, success: bool) -> Optional[float]:
        """
        Update skill confidence based on evaluation outcome.
        Uses exponential moving average with asymmetric learning rates:
        - Success: slower growth (trust must be earned)
        - Failure: faster decay (one bad result weighs more)

        Also promotes/demotes skill state based on confidence thresholds.

        Args:
            skill_id: Skill to update.
            success: Whether the skill application was successful.

        Returns:
            New confidence value, or None if skill not found.
        """
        skill = self.get_skill(skill_id)
        if not skill:
            return None

        # Asymmetric EMA: success grows slowly, failure decays faster
        alpha_success = 0.1  # ~10 successes to go 0.5 → 0.85
        alpha_failure = 0.2  # ~5 failures to go 0.85 → 0.5
        alpha = alpha_success if success else alpha_failure
        target = 1.0 if success else 0.0

        skill.confidence = skill.confidence * (1 - alpha) + target * alpha
        skill.confidence = max(0.05, min(0.99, skill.confidence))

        if success:
            skill.times_succeeded += 1
        else:
            skill.times_failed += 1
        skill.times_used += 1
        skill.last_used_at = time.time()
        skill.last_evaluated_at = time.time()

        # State transitions based on confidence
        if skill.confidence >= 0.85 and skill.times_succeeded >= 5:
            skill.state = "mastered"
        elif skill.confidence >= 0.6 and skill.times_succeeded >= 2:
            skill.state = "verified"
        elif skill.confidence < 0.2:
            skill.state = "deprecated"

        self.update_skill(skill)
        return skill.confidence

    # ── Composition ───────────────────────────────────────────

    def log_composition(
        self,
        parent_ids: List[str],
        child_id: str,
        method: str,
        reasoning: str
    ) -> None:
        """Log a skill composition event."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """INSERT INTO composition_log
                       (parent_ids, child_id, method, reasoning, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (json.dumps(parent_ids), child_id, method, reasoning, time.time())
                )
        except Exception as e:
            logger.error(f"Failed to log composition: {e}")

    def get_composition_tree(self, skill_id: str) -> Dict[str, Any]:
        """Get the full composition tree for a skill (parents and children)."""
        skill = self.get_skill(skill_id)
        if not skill:
            return {}

        parents = [self.get_skill(pid) for pid in skill.parent_skill_ids]
        children = [self.get_skill(cid) for cid in skill.child_skill_ids]

        return {
            "skill": asdict(skill),
            "parents": [asdict(p) for p in parents if p],
            "children": [asdict(c) for c in children if c],
        }

    # ── Internal Helpers ──────────────────────────────────────

    def _row_to_skill(self, row: sqlite3.Row) -> Skill:
        """Convert a database row to a Skill dataclass."""
        return Skill(
            id=row["id"],
            name=row["name"],
            skill_type=row["skill_type"],
            description=row["description"],
            strategy=row["strategy"],
            trigger_patterns=json.loads(row["trigger_patterns"]),
            confidence=row["confidence"],
            times_used=row["times_used"],
            times_succeeded=row["times_succeeded"],
            times_failed=row["times_failed"],
            parent_skill_ids=json.loads(row["parent_skill_ids"]),
            child_skill_ids=json.loads(row["child_skill_ids"]),
            state=row["state"],
            source=row["source"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            last_evaluated_at=row["last_evaluated_at"],
        )

    @staticmethod
    def _compute_match_score(
        query_lower: str,
        query_words: set,
        skill: Skill
    ) -> float:
        """
        Score how well a query matches a skill's trigger patterns.
        Combines keyword overlap with substring matching.
        """
        if not skill.trigger_patterns:
            return 0.0

        best_score = 0.0
        for pattern in skill.trigger_patterns:
            pattern_lower = pattern.lower()
            pattern_words = set(pattern_lower.split())

            # Keyword overlap (Jaccard-ish)
            if pattern_words:
                overlap = len(query_words & pattern_words)
                kw_score = overlap / max(len(pattern_words), 1)
            else:
                kw_score = 0.0

            # Substring containment bonus
            substr_bonus = 0.3 if pattern_lower in query_lower else 0.0

            best_score = max(best_score, kw_score + substr_bonus)

        return min(best_score, 1.0)
