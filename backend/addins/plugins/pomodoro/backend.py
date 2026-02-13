"""
Pomodoro Timer Add-in.
Type 2: GUI Extension for focus timer with work/break cycles.

Tracks completed sessions per user in the database.
"""

import logging
from typing import List, Dict, Any
from datetime import datetime

from addins.addin_interface import GUIAddin

logger = logging.getLogger(__name__)


class PomodoroAddin(GUIAddin):
    """Focus timer with configurable work/break intervals."""

    name = "pomodoro"
    version = "1.0.0"
    description = "Focus timer with 25/5 work-break cycles"
    permissions = ["storage"]

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.work_minutes = self.config.get("work_minutes", 25)
        self.break_minutes = self.config.get("break_minutes", 5)
        self.long_break_minutes = self.config.get("long_break_minutes", 15)
        self.sessions_before_long = self.config.get("sessions_before_long_break", 4)

    async def initialize(self) -> bool:
        """Initialize the pomodoro add-in."""
        return True

    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass

    def get_mount_points(self) -> List[str]:
        """Get UI mount points."""
        return ["sidebar"]

    def get_frontend_component(self) -> str:
        """Get frontend component name."""
        return "PomodoroTimer"

    async def handle_action(
        self, action: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle actions from the frontend."""
        if action == "complete_session":
            return {
                "success": True,
                "message": "Session completed!",
                "timestamp": datetime.utcnow().isoformat(),
            }
        return {"error": f"Unknown action: {action}"}


# Export the add-in class
Addin = PomodoroAddin
