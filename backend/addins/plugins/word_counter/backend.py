"""
Word Counter Add-in.
Type 1: LLM-callable tool for text analysis.

Provides word count, character count, sentence count,
reading time estimate, and average word length.
"""

import logging
import re
from typing import List, Dict, Any

from addins.addin_interface import ToolAddin, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


def analyze_text(text: str, wpm: int = 200) -> Dict[str, Any]:
    """Analyze text and return statistics.

    Args:
        text: The text to analyze.
        wpm: Words per minute for reading time estimate.

    Returns:
        Dict with text statistics.
    """
    if not text.strip():
        return {
            "words": 0, "characters": 0, "characters_no_spaces": 0,
            "sentences": 0, "paragraphs": 0, "avg_word_length": 0,
            "reading_time_seconds": 0, "reading_time_display": "0s",
        }

    words = text.split()
    word_count = len(words)
    char_count = len(text)
    char_no_spaces = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))

    # Sentence detection: split on .!? followed by space or end
    sentences = re.split(r'[.!?]+(?:\s|$)', text.strip())
    sentence_count = len([s for s in sentences if s.strip()])

    # Paragraphs: split on double newlines
    paragraphs = re.split(r'\n\s*\n', text.strip())
    para_count = len([p for p in paragraphs if p.strip()])

    # Average word length
    avg_len = round(sum(len(w) for w in words) / word_count, 1) if word_count else 0

    # Reading time
    seconds = int((word_count / wpm) * 60)
    if seconds < 60:
        display = f"{seconds}s"
    else:
        mins = seconds // 60
        secs = seconds % 60
        display = f"{mins}m {secs}s" if secs else f"{mins}m"

    return {
        "words": word_count,
        "characters": char_count,
        "characters_no_spaces": char_no_spaces,
        "sentences": sentence_count,
        "paragraphs": para_count,
        "avg_word_length": avg_len,
        "reading_time_seconds": seconds,
        "reading_time_display": display,
    }


class WordCounterAddin(ToolAddin):
    """Text analysis tool for word/character/sentence counting."""

    name = "word_counter"
    version = "1.0.0"
    description = "Analyze text for word count, reading time, and more"
    permissions = []

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.wpm = self.config.get("words_per_minute", 200)

    async def initialize(self) -> bool:
        """Initialize the word counter add-in."""
        return True

    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Define the analyze_text tool."""
        return [
            ToolDefinition(
                name="analyze_text",
                description=(
                    "Analyze text to get word count, character count, "
                    "sentence count, paragraph count, average word length, "
                    "and estimated reading time."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The text to analyze",
                        }
                    },
                    "required": ["text"],
                },
            )
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> ToolResult:
        """Execute text analysis."""
        if tool_name != "analyze_text":
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

        text = arguments.get("text", "")
        if not text:
            return ToolResult(success=False, error="Text is required")

        try:
            result = analyze_text(text, self.wpm)
            return ToolResult(success=True, result=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# Export the add-in class
Addin = WordCounterAddin
