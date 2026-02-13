"""
Message model definitions.
Represents individual messages in a conversation.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ImageAttachment(BaseModel):
    """An image attached to a chat message.

    Attributes:
        url: Relative URL path to the uploaded image (e.g. /uploads/abc.jpg).
        filename: Original filename for display.
        content_type: MIME type (image/jpeg, image/png, etc.).
    """
    url: str
    filename: str = ""
    content_type: str = "image/jpeg"


class MessageCreate(BaseModel):
    """Schema for creating a new message.
    
    Args:
        conversation_id: ID of the conversation to add the message to.
        content: Message text. Must be 1-100000 characters.
        images: Optional list of image attachments to include.
        is_regeneration: If True, skip saving user message (used by regenerate endpoint).
    """
    conversation_id: str
    content: str = Field(..., min_length=1, max_length=100000)
    images: List[ImageAttachment] = []
    is_regeneration: bool = False


class WebSource(BaseModel):
    """A web search result source attached to an assistant message.

    Attributes:
        title: Page title from search result.
        url: Full URL to the source page.
        description: Snippet/description from search engine.
        age: Optional age string (e.g. '2 hours ago').
    """
    title: str = ""
    url: str = ""
    description: str = ""
    age: Optional[str] = None


class Message(BaseModel):
    """Full message model as stored in database."""
    id: Optional[str] = Field(None, alias="_id")
    conversation_id: str
    user_id: str
    role: str  # "user", "assistant", "system"
    content: str
    images: List[ImageAttachment] = []
    web_sources: List[WebSource] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        populate_by_name = True


class MessageResponse(BaseModel):
    """Message data returned in API responses."""
    id: str
    conversation_id: str
    role: str
    content: str
    images: List[ImageAttachment] = []
    web_sources: List[WebSource] = []
    timestamp: datetime
    metadata: Dict[str, Any] = {}
    
    class Config:
        from_attributes = True
