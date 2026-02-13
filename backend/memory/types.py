"""
Memory data models for the autonomous memory system.

These types define the structure of memories extracted from conversations,
including facts, preferences, decisions, and experiences.

Supports conflict resolution when new memories contradict existing ones.
"""

from enum import Enum
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """
    Types of memories that can be extracted from conversations.
    
    FACT: Objective information (e.g., "User works at Google")
    PREFERENCE: User preferences (e.g., "User prefers Python over Java")
    DECISION: Decisions made (e.g., "Decided to use PostgreSQL for the project")
    EXPERIENCE: Past experiences (e.g., "Had issues with Docker networking")
    NEGATIVE: Things that didn't work (e.g., "Tried Redis caching, caused issues")
    """
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    EXPERIENCE = "experience"
    NEGATIVE = "negative"


class UpdateAction(str, Enum):
    """
    Actions that can be taken when processing a new memory candidate.
    ADD: New memory, no conflicts - add to store
    UPDATE: Similar memory exists - update existing memory with new content
    DELETE: Memory is no longer valid - remove from store
    NONE: Duplicate or not useful - take no action
    """
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    NONE = "none"


class Memory(BaseModel):
    """
    A single memory extracted from a conversation.
    
    Memories are stored in both ChromaDB (for vector search) and
    MongoDB (for metadata and full content).
    
    Attributes:
        id: Unique identifier for the memory
        content: The actual memory content (natural language)
        memory_type: Category of memory (fact, preference, etc.)
        user_id: User this memory belongs to
        confidence: How confident we are in this memory (0.0-1.0)
        created_at: When the memory was first created
        updated_at: When the memory was last updated
        invalidated_at: When the memory was invalidated (if applicable)
        source_conversation_id: Conversation this memory came from
        embedding: Optional vector embedding for similarity search
    """
    id: str = Field(default="", description="Unique memory identifier")
    content: str = Field(..., description="The memory content")
    memory_type: MemoryType = Field(..., description="Type of memory")
    user_id: str = Field(..., description="User ID this memory belongs to")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence score")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    invalidated_at: Optional[datetime] = Field(default=None)
    source_conversation_id: str = Field(..., description="Source conversation ID")
    embedding: Optional[List[float]] = Field(default=None, description="Vector embedding")
    
    @property
    def is_active(self) -> bool:
        """Check if memory is still active (not invalidated)."""
        return self.invalidated_at is None
    
    class Config:
        """Pydantic config for MongoDB compatibility."""
        populate_by_name = True


class ConflictResolution(BaseModel):
    """
    Result of conflict resolution between a new memory and existing memories.
    
    Attributes:
        action: What action to take (ADD, UPDATE, DELETE, NONE)
        target_memory_id: ID of existing memory to update or delete
        updated_content: New content if updating
        reason: Explanation for the decision
    """
    action: UpdateAction = Field(..., description="Action to take")
    target_memory_id: Optional[str] = Field(default=None, description="Target memory for update/delete")
    updated_content: Optional[str] = Field(default=None, description="Updated content if applicable")
    reason: str = Field(default="", description="Reason for this decision")


class NegativeKnowledge(BaseModel):
    """
    Negative knowledge: tracking failures and what didn't work.
    
    These are stored separately with priority boosting in retrieval to
    prevent repeated mistakes.
    
    Attributes:
        id: Unique identifier
        what_failed: What was attempted that failed
        why_failed: Reason for the failure
        solution_found: Solution if one was found (optional)
        context: Additional context about the failure
        user_id: User ID this belongs to
        created_at: When this failure was recorded
        related_entities: Entities/technologies involved
    """
    id: str = Field(default="", description="Unique identifier")
    what_failed: str = Field(..., description="What was attempted")
    why_failed: str = Field(..., description="Why it failed")
    solution_found: Optional[str] = Field(default=None, description="Solution if found")
    context: str = Field(default="", description="Additional context")
    user_id: str = Field(..., description="User ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    related_entities: List[str] = Field(default_factory=list, description="Related entities/technologies")
    
    class Config:
        """Pydantic config for MongoDB compatibility."""
        populate_by_name = True

