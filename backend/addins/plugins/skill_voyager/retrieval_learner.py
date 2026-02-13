"""
Retrieval Learner — Tracks which retrieval sources work best for which query types.

Observes the retrieval pipeline (web search, memory, RAG, graph) and learns
which sources produce the most useful context for different query classifications.
Over time, this enables Skill Voyager to recommend optimal retrieval strategies
instead of always running all sources.

Data is stored in the skill_voyager.db SQLite database alongside skills.
"""

import sqlite3
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from config import DATA_DIR

logger = logging.getLogger(__name__)

SKILL_DB_PATH = DATA_DIR / "learning" / "skill_voyager.db"

# Retrieval sources tracked
RETRIEVAL_SOURCES = ["memory", "graph", "web_search", "rag", "hybrid_search", "notes"]


@dataclass
class RetrievalOutcome:
    """Records whether a retrieval source contributed to a good response."""
    query_type: str         # e.g. "factual/definition"
    source: str             # e.g. "web_search", "memory", "graph"
    was_used: bool          # Was this source activated?
    had_results: bool       # Did it return any results?
    response_score: float   # Overall response quality (from evaluator)
    query_text: str = ""
    timestamp: float = 0.0


class RetrievalLearner:
    """Learns which retrieval sources are most effective per query type.

    Tracks a running average of response quality when each source is
    used vs not used, broken down by query classification. This enables
    data-driven retrieval strategy recommendations.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or SKILL_DB_PATH
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create retrieval learning tables if they don't exist."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retrieval_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    was_used INTEGER NOT NULL DEFAULT 0,
                    had_results INTEGER NOT NULL DEFAULT 0,
                    response_score REAL NOT NULL DEFAULT 0.0,
                    query_text TEXT DEFAULT '',
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retrieval_stats (
                    query_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    times_used INTEGER DEFAULT 0,
                    times_helpful INTEGER DEFAULT 0,
                    avg_score_with REAL DEFAULT 0.0,
                    avg_score_without REAL DEFAULT 0.0,
                    last_updated REAL DEFAULT 0.0,
                    PRIMARY KEY (query_type, source)
                )
            """)
            conn.commit()

    def record_outcome(self, outcome: RetrievalOutcome) -> None:
        """Record a retrieval outcome and update running stats.

        Args:
            outcome: The retrieval outcome to record.
        """
        outcome.timestamp = outcome.timestamp or time.time()

        with sqlite3.connect(str(self.db_path)) as conn:
            # Insert raw outcome
            conn.execute(
                """INSERT INTO retrieval_outcomes
                   (query_type, source, was_used, had_results, response_score, query_text, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (outcome.query_type, outcome.source,
                 int(outcome.was_used), int(outcome.had_results),
                 outcome.response_score, outcome.query_text, outcome.timestamp)
            )

            # Update running stats
            row = conn.execute(
                "SELECT times_used, times_helpful, avg_score_with, avg_score_without FROM retrieval_stats WHERE query_type=? AND source=?",
                (outcome.query_type, outcome.source)
            ).fetchone()

            if row:
                used, helpful, avg_with, avg_without = row
                if outcome.was_used and outcome.had_results:
                    # EMA update for score when source was used
                    new_used = used + 1
                    alpha = 0.3  # Weight for new observations
                    new_avg_with = avg_with * (1 - alpha) + outcome.response_score * alpha
                    new_helpful = helpful + (1 if outcome.response_score >= 3.0 else 0)
                    conn.execute(
                        "UPDATE retrieval_stats SET times_used=?, times_helpful=?, avg_score_with=?, last_updated=? WHERE query_type=? AND source=?",
                        (new_used, new_helpful, new_avg_with, time.time(), outcome.query_type, outcome.source)
                    )
                else:
                    # Track score when source was NOT used
                    alpha = 0.3
                    new_avg_without = avg_without * (1 - alpha) + outcome.response_score * alpha
                    conn.execute(
                        "UPDATE retrieval_stats SET avg_score_without=?, last_updated=? WHERE query_type=? AND source=?",
                        (new_avg_without, time.time(), outcome.query_type, outcome.source)
                    )
            else:
                # First observation for this query_type + source pair
                if outcome.was_used and outcome.had_results:
                    conn.execute(
                        "INSERT INTO retrieval_stats (query_type, source, times_used, times_helpful, avg_score_with, avg_score_without, last_updated) VALUES (?,?,?,?,?,?,?)",
                        (outcome.query_type, outcome.source, 1,
                         1 if outcome.response_score >= 3.0 else 0,
                         outcome.response_score, 0.0, time.time())
                    )
                else:
                    conn.execute(
                        "INSERT INTO retrieval_stats (query_type, source, times_used, times_helpful, avg_score_with, avg_score_without, last_updated) VALUES (?,?,?,?,?,?,?)",
                        (outcome.query_type, outcome.source, 0, 0, 0.0,
                         outcome.response_score, time.time())
                    )
            conn.commit()

    def get_recommended_sources(
        self, query_type: str, min_observations: int = 3
    ) -> Dict[str, float]:
        """Get recommended retrieval sources for a query type.

        Returns a dict of source -> usefulness_score (0-1).
        Sources with score > 0.5 are recommended.

        Args:
            query_type: The query classification (e.g. "factual/definition").
            min_observations: Minimum observations before making recommendations.

        Returns:
            Dict mapping source names to usefulness scores (0.0-1.0).
        """
        recommendations = {}

        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT source, times_used, times_helpful, avg_score_with, avg_score_without FROM retrieval_stats WHERE query_type=?",
                (query_type,)
            ).fetchall()

        for source, used, helpful, avg_with, avg_without in rows:
            if used < min_observations:
                # Not enough data — recommend using it (exploration)
                recommendations[source] = 0.7
                continue

            # Helpfulness ratio
            help_ratio = helpful / max(used, 1)

            # Score improvement when source is used vs not
            improvement = avg_with - avg_without if avg_without > 0 else 0.0

            # Combined score: 60% helpfulness + 40% improvement signal
            score = help_ratio * 0.6 + min(max(improvement / 5.0, 0), 1) * 0.4
            recommendations[source] = round(score, 3)

        return recommendations

    def get_stats_summary(self) -> List[Dict[str, Any]]:
        """Get a summary of all retrieval learning stats.

        Returns:
            List of stat dicts for the dashboard.
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT query_type, source, times_used, times_helpful, avg_score_with, avg_score_without FROM retrieval_stats ORDER BY query_type, source"
            ).fetchall()

        return [
            {
                "query_type": r[0],
                "source": r[1],
                "times_used": r[2],
                "times_helpful": r[3],
                "avg_score_with": round(r[4], 2),
                "avg_score_without": round(r[5], 2),
                "usefulness": round(r[3] / max(r[2], 1), 2),
            }
            for r in rows
        ]

    def get_total_observations(self) -> int:
        """Get total number of retrieval outcomes recorded."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute("SELECT count(*) FROM retrieval_outcomes").fetchone()
        return row[0] if row else 0
