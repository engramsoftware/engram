"""
Persona model definitions.
Allows users to define custom AI personas for system prompts.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PersonaCreate(BaseModel):
    """Schema for creating a new persona."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    system_prompt: str = Field(..., min_length=1)
    is_default: bool = False


class Persona(BaseModel):
    """Full persona model as stored in database."""
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    name: str
    description: Optional[str] = None
    system_prompt: str
    is_default: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


class PersonaResponse(BaseModel):
    """Persona data returned in API responses."""
    id: str
    name: str
    description: Optional[str]
    system_prompt: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class PersonaUpdate(BaseModel):
    """Schema for updating a persona."""
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    is_default: Optional[bool] = None
