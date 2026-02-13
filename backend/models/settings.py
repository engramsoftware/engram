"""
LLM Settings model definitions.
Stores provider configurations and API keys (encrypted).
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""
    enabled: bool = False
    api_key: Optional[str] = None  # Stored encrypted
    base_url: Optional[str] = None
    default_model: Optional[str] = None
    available_models: List[str] = Field(default_factory=list)


class LLMSettingsCreate(BaseModel):
    """Schema for creating/updating LLM settings."""
    providers: Dict[str, ProviderConfig] = Field(default_factory=dict)
    default_provider: Optional[str] = None
    default_model: Optional[str] = None


class LLMSettings(BaseModel):
    """Full LLM settings as stored in database."""
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    providers: Dict[str, ProviderConfig] = Field(default_factory=dict)
    default_provider: Optional[str] = None
    default_model: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


class LLMSettingsResponse(BaseModel):
    """LLM settings returned in API responses."""
    user_id: str
    providers: Dict[str, ProviderConfig]
    default_provider: Optional[str]
    default_model: Optional[str]
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ModelInfo(BaseModel):
    """Information about an available model."""
    id: str
    name: str
    provider: str
    context_length: Optional[int] = None
    supports_streaming: bool = True
    supports_functions: bool = False
