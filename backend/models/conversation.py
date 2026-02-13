"""
Conversation model definitions.
Represents a chat session between user and AI.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class ConversationCreate(BaseModel):
    """Schema for creating a new conversation."""
    model_config = ConfigDict(protected_namespaces=())
    title: Optional[str] = "New Chat"
    model_provider: Optional[str] = None  # e.g., "openai", "anthropic"
    model_name: Optional[str] = None      # e.g., "gpt-4", "claude-3"


class Conversation(BaseModel):
    """
    Full conversation model as stored in database.
    Tracks metadata about the chat session.
    """
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    title: str = "New Chat"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    is_pinned: bool = False
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())


class ConversationResponse(BaseModel):
    """Conversation data returned in API responses."""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    model_provider: Optional[str]
    model_name: Optional[str]
    is_pinned: bool
    message_count: int = 0  # Populated when fetching
    

class ConversationUpdate(BaseModel):
    """Schema for updating conversation metadata."""
    model_config = ConfigDict(protected_namespaces=())
    title: Optional[str] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    is_pinned: Optional[bool] = None
