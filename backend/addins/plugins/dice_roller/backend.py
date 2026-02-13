"""
Dice Roller Add-in.
Type 1: LLM-callable tool for rolling dice.

Supports standard RPG notation: NdS (e.g. 2d6, 1d20, 4d8+3).
"""

import logging
import random
import re
from typing import List, Dict, Any

from addins.addin_interface import ToolAddin, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)

# Pattern: optional count, 'd', sides, optional modifier
DICE_PATTERN = re.compile(
    r"^(\d+)?d(\d+)([+-]\d+)?$", re.IGNORECASE
)


def roll_dice(notation: str) -> Dict[str, Any]:
    """Parse dice notation and roll.

    Args:
        notation: Dice string like '2d6', '1d20+5', 'd100'.

    Returns:
        Dict with rolls, modifier, total, and notation.
    """
    match = DICE_PATTERN.match(notation.strip())
    if not match:
        raise ValueError(f"Invalid dice notation: {notation}. Use format like 2d6, d20, 3d8+2")

    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    modifier = int(match.group(3) or 0)

    if count < 1 or count > 100:
        raise ValueError("Roll 1-100 dice at a time")
    if sides < 2 or sides > 1000:
        raise ValueError("Dice must have 2-1000 sides")

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier

    return {
        "notation": notation,
        "rolls": rolls,
        "modifier": modifier,
        "total": total,
        "min_possible": count + modifier,
        "max_possible": count * sides + modifier,
    }


class DiceRollerAddin(ToolAddin):
    """Dice rolling tool for RPGs and random decisions."""

    name = "dice_roller"
    version = "1.0.0"
    description = "Roll any combination of dice"
    permissions = []

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)

    async def initialize(self) -> bool:
        """Initialize the dice roller add-in."""
        return True

    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Define the roll_dice tool."""
        return [
            ToolDefinition(
                name="roll_dice",
                description=(
                    "Roll dice using standard RPG notation. "
                    "Examples: '2d6' (two six-sided), 'd20' (one twenty-sided), "
                    "'3d8+5' (three eight-sided plus 5). "
                    "Great for games, random decisions, or generating numbers."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "notation": {
                            "type": "string",
                            "description": "Dice notation like '2d6', 'd20', '4d8+3'",
                        }
                    },
                    "required": ["notation"],
                },
            )
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> ToolResult:
        """Execute the dice roll."""
        if tool_name != "roll_dice":
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

        notation = arguments.get("notation", "")
        if not notation:
            return ToolResult(success=False, error="Dice notation is required")

        try:
            result = roll_dice(notation)
            return ToolResult(success=True, result=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# Export the add-in class
Addin = DiceRollerAddin
