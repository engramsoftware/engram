"""
Correction Learner — Learns from user corrections and rejections.

When a user edits a message, regenerates a response, or explicitly rates
a response negatively, this module treats it as negative feedback on
whatever skill was applied. Over time, skills that consistently lead
to corrections get their confidence reduced or deprecated.

Data is stored in the skill_voyager.db SQLite database.
"""

import sqlite3
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from config import DATA_DIR

logger = logging.getLogger(__name__)

SKILL_DB_PATH = DATA_DIR / "learning" / "skill_voyager.db"


@dataclass
class CorrectionEvent:
    """A user correction that implies negative feedback on a skill."""
    correction_type: str    # "edit", "regenerate", "thumbs_down", "explicit"
    conversation_id: str
    message_id: str
    original_response: str  # What the AI said (snippet)
    corrected_text: str     # What the user changed it to (if edit)
    skill_name: str         # Which skill was applied when this response was generated
    skill_id: str
    query_type: str         # Classification of the original query
    timestamp: float = 0.0


class CorrectionLearner:
    """Learns from user corrections to improve skill confidence.

    Tracks correction events and adjusts skill confidence based on
    how often a skill leads to corrections vs successful responses.
    A skill that frequently causes edits/regenerations gets penalized.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or SKILL_DB_PATH
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create correction tracking tables if they don't exist."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    correction_type TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT DEFAULT '',
                    original_snippet TEXT DEFAULT '',
                    corrected_snippet TEXT DEFAULT '',
                    skill_name TEXT DEFAULT '',
                    skill_id TEXT DEFAULT '',
                    query_type TEXT DEFAULT '',
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS correction_stats (
                    skill_id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    times_corrected INTEGER DEFAULT 0,
                    times_edited INTEGER DEFAULT 0,
                    times_regenerated INTEGER DEFAULT 0,
                    times_thumbs_down INTEGER DEFAULT 0,
                    correction_rate REAL DEFAULT 0.0,
                    last_correction REAL DEFAULT 0.0
                )
            """)
            conn.commit()

    def record_correction(
        self,
        event: CorrectionEvent,
        skill_store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Record a correction event and update skill confidence.

        Args:
            event: The correction event details.
            skill_store: Optional SkillStore to update confidence directly.

        Returns:
            Dict with correction_id and any confidence changes applied.
        """
        event.timestamp = event.timestamp or time.time()
        result = {"recorded": True, "confidence_change": 0.0}

        with sqlite3.connect(str(self.db_path)) as conn:
            # Insert correction event
            conn.execute(
                """INSERT INTO corrections
                   (correction_type, conversation_id, message_id,
                    original_snippet, corrected_snippet, skill_name,
                    skill_id, query_type, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event.correction_type, event.conversation_id,
                 event.message_id, event.original_response[:500],
                 event.corrected_text[:500], event.skill_name,
                 event.skill_id, event.query_type, event.timestamp)
            )

            # Update correction stats for this skill
            row = conn.execute(
                "SELECT times_corrected, times_edited, times_regenerated, times_thumbs_down FROM correction_stats WHERE skill_id=?",
                (event.skill_id,)
            ).fetchone()

            if row:
                corrected, edited, regenerated, thumbs = row
                corrected += 1
                if event.correction_type == "edit":
                    edited += 1
                elif event.correction_type == "regenerate":
                    regenerated += 1
                elif event.correction_type == "thumbs_down":
                    thumbs += 1

                conn.execute(
                    """UPDATE correction_stats
                       SET times_corrected=?, times_edited=?, times_regenerated=?,
                           times_thumbs_down=?, last_correction=?
                       WHERE skill_id=?""",
                    (corrected, edited, regenerated, thumbs, event.timestamp, event.skill_id)
                )
            else:
                conn.execute(
                    """INSERT INTO correction_stats
                       (skill_id, skill_name, times_corrected, times_edited,
                        times_regenerated, times_thumbs_down, last_correction)
                       VALUES (?, ?, 1, ?, ?, ?, ?)""",
                    (event.skill_id, event.skill_name,
                     1 if event.correction_type == "edit" else 0,
                     1 if event.correction_type == "regenerate" else 0,
                     1 if event.correction_type == "thumbs_down" else 0,
                     event.timestamp)
                )
            conn.commit()

        # Apply confidence penalty to the skill
        if skill_store and event.skill_id:
            penalty = self._calculate_penalty(event.correction_type)
            result["confidence_change"] = -penalty
            try:
                skill = skill_store.get_skill(event.skill_id)
                if skill:
                    new_confidence = max(0.1, skill.confidence - penalty)
                    skill_store.update_confidence(
                        event.skill_id, new_confidence
                    )
                    logger.info(
                        f"Correction penalty: skill '{event.skill_name}' "
                        f"confidence {skill.confidence:.2f} -> {new_confidence:.2f} "
                        f"(type={event.correction_type})"
                    )
            except Exception as e:
                logger.warning(f"Failed to apply correction penalty: {e}")

        return result

    def _calculate_penalty(self, correction_type: str) -> float:
        """Calculate confidence penalty based on correction severity.

        Args:
            correction_type: Type of correction.

        Returns:
            Penalty to subtract from skill confidence (0.0-0.15).
        """
        penalties = {
            "edit": 0.05,        # Mild — user tweaked the response
            "regenerate": 0.08,  # Medium — user rejected the whole response
            "thumbs_down": 0.10, # Strong — explicit negative feedback
            "explicit": 0.12,    # Strongest — user specifically flagged it
        }
        return penalties.get(correction_type, 0.05)

    def get_correction_stats(self) -> List[Dict[str, Any]]:
        """Get correction stats for all skills.

        Returns:
            List of correction stat dicts for the dashboard.
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                """SELECT skill_id, skill_name, times_corrected, times_edited,
                          times_regenerated, times_thumbs_down, last_correction
                   FROM correction_stats ORDER BY times_corrected DESC"""
            ).fetchall()

        return [
            {
                "skill_id": r[0],
                "skill_name": r[1],
                "times_corrected": r[2],
                "times_edited": r[3],
                "times_regenerated": r[4],
                "times_thumbs_down": r[5],
                "last_correction": r[6],
            }
            for r in rows
        ]

    def get_recent_corrections(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent correction events.

        Args:
            limit: Max number of corrections to return.

        Returns:
            List of recent correction dicts.
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                """SELECT correction_type, skill_name, query_type,
                          original_snippet, corrected_snippet, timestamp
                   FROM corrections ORDER BY timestamp DESC LIMIT ?""",
                (limit,)
            ).fetchall()

        return [
            {
                "type": r[0],
                "skill_name": r[1],
                "query_type": r[2],
                "original": r[3][:100],
                "corrected": r[4][:100],
                "timestamp": r[5],
            }
            for r in rows
        ]

    def get_total_corrections(self) -> int:
        """Get total number of corrections recorded."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute("SELECT count(*) FROM corrections").fetchone()
        return row[0] if row else 0
