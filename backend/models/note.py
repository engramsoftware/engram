"""
Note model definitions.
Represents a user's notes/knowledge base entries (Obsidian-like).

Notes support:
- Markdown content with rich editing
- Hierarchical folders via parent_id
- Tags for organization
- LLM read/write access (Engram can create and edit notes)
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    """Schema for creating a new note."""
    title: str = "Untitled"
    content: str = ""
    folder: Optional[str] = None
    parent_id: Optional[str] = None
    tags: List[str] = []
    is_folder: bool = False


class Note(BaseModel):
    """
    Full note model as stored in database.
    
    Notes can be either documents (markdown content) or folders
    (containers for other notes). Folders have is_folder=True
    and typically empty content.
    """
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    title: str = "Untitled"
    content: str = ""
    folder: Optional[str] = None
    parent_id: Optional[str] = None
    tags: List[str] = []
    is_folder: bool = False
    is_pinned: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_edited_by: str = "user"


class NoteResponse(BaseModel):
    """Note data returned in API responses."""
    id: str
    user_id: str
    title: str
    content: str
    folder: Optional[str]
    parent_id: Optional[str]
    tags: List[str]
    is_folder: bool
    is_pinned: bool
    created_at: datetime
    updated_at: datetime
    last_edited_by: str
    child_count: int = 0


class NoteUpdate(BaseModel):
    """Schema for updating a note."""
    title: Optional[str] = None
    content: Optional[str] = None
    folder: Optional[str] = None
    parent_id: Optional[str] = None
    tags: Optional[List[str]] = None
    is_pinned: Optional[bool] = None
    last_edited_by: Optional[str] = None
