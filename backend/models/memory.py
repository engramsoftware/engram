"""
Manual Memory model definitions.
Allows users to store persistent context for the AI.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    """Schema for creating a new memory entry."""
    content: str = Field(..., min_length=1)
    category: Optional[str] = "general"
    tags: List[str] = Field(default_factory=list)


class Memory(BaseModel):
    """Full memory model as stored in database."""
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    content: str
    category: str = "general"
    tags: List[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


class MemoryResponse(BaseModel):
    """Memory data returned in API responses."""
    id: str
    content: str
    category: str
    tags: List[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime
    source: str = "manual"
    memory_type: str = "fact"
    confidence: float = 1.0
    
    class Config:
        from_attributes = True


class MemoryUpdate(BaseModel):
    """Schema for updating a memory entry."""
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = None
