"""
User model definitions.
Handles user authentication and profile data.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field


class UserPreferences(BaseModel):
    """User preferences for UI and behavior."""
    theme: str = "dark"
    default_provider: Optional[str] = None
    default_model: Optional[str] = None


class UserCreate(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8)


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


class User(BaseModel):
    """
    Full user model as stored in database.
    Password hash is never exposed in responses.
    """
    id: Optional[str] = Field(None, alias="_id")
    email: EmailStr
    name: str
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    
    class Config:
        populate_by_name = True


class UserResponse(BaseModel):
    """
    User data returned in API responses.
    Excludes sensitive fields like password_hash.
    """
    id: str
    email: EmailStr
    name: str
    created_at: datetime
    preferences: UserPreferences
    
    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """JWT token response after successful login."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
