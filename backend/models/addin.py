"""
Add-in/Plugin model definitions.
Supports three plugin types: tools, gui, interceptors.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


class AddinType(str, Enum):
    """Types of add-ins supported."""
    TOOL = "tool"           # LLM-callable backend functions
    GUI = "gui"             # React UI components
    INTERCEPTOR = "interceptor"  # Message pipeline hooks
    HYBRID = "hybrid"       # Combination of types


class AddinConfig(BaseModel):
    """User-configurable settings for an add-in."""
    settings: Dict[str, Any] = Field(default_factory=dict)


class AddinCreate(BaseModel):
    """Schema for installing a new add-in."""
    name: str
    description: Optional[str] = None
    addin_type: AddinType
    config: AddinConfig = Field(default_factory=AddinConfig)
    manifest_path: Optional[str] = None


class Addin(BaseModel):
    """Full add-in model as stored in database."""
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    name: str
    description: Optional[str] = None
    addin_type: AddinType
    enabled: bool = True
    config: AddinConfig = Field(default_factory=AddinConfig)
    installed_at: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"
    permissions: List[str] = Field(default_factory=list)
    
    class Config:
        populate_by_name = True


class AddinResponse(BaseModel):
    """Add-in data returned in API responses."""
    id: str
    name: str
    internal_name: str = ""  # Manifest ID used for routing (e.g. 'skill_voyager')
    description: Optional[str]
    addin_type: AddinType
    enabled: bool
    config: AddinConfig
    installed_at: str
    version: str
    permissions: List[str]
    built_in: bool = False
    
    class Config:
        from_attributes = True


class AddinManifest(BaseModel):
    """
    Plugin manifest.json structure.
    Defines plugin metadata, entry points, and permissions.
    """
    id: str
    name: str
    version: str
    description: Optional[str] = None
    author: Optional[str] = None
    addin_type: AddinType
    entrypoint: Dict[str, str] = Field(default_factory=dict)
    permissions: List[str] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)
    hooks: Dict[str, Any] = Field(default_factory=dict)
    ui: Dict[str, Any] = Field(default_factory=dict)
