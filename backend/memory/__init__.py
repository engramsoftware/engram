"""
Memory module for autonomous memory formation.

This module extracts facts, preferences, decisions, and experiences
from conversations and stores them for future retrieval.
"""

from memory.types import Memory, MemoryType, UpdateAction, ConflictResolution
from memory.memory_store import MemoryStore, get_memory_store

__all__ = [
    "Memory",
    "MemoryType", 
    "UpdateAction",
    "ConflictResolution",
    "MemoryStore",
    "get_memory_store"
]
