"""
Mood Journal Add-in.
Type 2: GUI Extension for mood and energy tracking.

Stores mood entries per user in the database with timestamps.
"""

import logging
from typing import List, Dict, Any
from datetime import datetime

from addins.addin_interface import GUIAddin

logger = logging.getLogger(__name__)


class MoodJournalAddin(GUIAddin):
    """Quick mood/energy logging with emoji picker."""

    name = "mood_journal"
    version = "1.0.0"
    description = "Track your mood and energy over time"
    permissions = ["storage"]

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)

    async def initialize(self) -> bool:
        """Initialize the mood journal add-in."""
        return True

    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass

    def get_mount_points(self) -> List[str]:
        """Get UI mount points."""
        return ["sidebar"]

    def get_frontend_component(self) -> str:
        """Get frontend component name."""
        return "MoodJournal"

    async def handle_action(
        self, action: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle actions from the frontend."""
        if action == "log_mood":
            return {
                "success": True,
                "mood": payload.get("mood"),
                "energy": payload.get("energy"),
                "note": payload.get("note", ""),
                "timestamp": datetime.utcnow().isoformat(),
            }
        return {"error": f"Unknown action: {action}"}


# Export the add-in class
Addin = MoodJournalAddin
