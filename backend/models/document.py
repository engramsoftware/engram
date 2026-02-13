"""
Pydantic models for RAG document management.

Documents are user-uploaded files (PDF, TXT, MD, DOCX) that get chunked,
embedded into ChromaDB, and retrieved when relevant to a conversation.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class DocumentUploadResponse(BaseModel):
    """Response after uploading and processing a document.

    Attributes:
        id: MongoDB document ID.
        filename: Original filename.
        chunks: Number of text chunks created.
        status: Processing status (processing, ready, error).
    """
    id: str
    filename: str
    chunks: int
    status: str


class Document(BaseModel):
    """A user-uploaded document stored in MongoDB.

    Attributes:
        id: MongoDB ObjectId as string.
        user_id: Owner's user ID.
        filename: Original filename.
        file_type: MIME type or extension (pdf, txt, md, docx).
        file_size: Size in bytes.
        chunk_count: Number of text chunks created.
        status: Processing status (processing, ready, error).
        error: Error message if processing failed.
        tags: User-assigned tags for organization.
        created_at: Upload timestamp.
        updated_at: Last modification timestamp.
    """
    id: Optional[str] = Field(None, alias="_id")
    user_id: str = Field(..., alias="userId")
    filename: str
    file_type: str = Field(..., alias="fileType")
    file_size: int = Field(0, alias="fileSize")
    chunk_count: int = Field(0, alias="chunkCount")
    status: str = "processing"
    error: Optional[str] = None
    tags: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt")
    updated_at: datetime = Field(default_factory=datetime.utcnow, alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())


class DocumentResponse(BaseModel):
    """API response for a document (camelCase for frontend).

    Attributes:
        id: Document ID.
        filename: Original filename.
        file_type: File extension/type.
        file_size: Size in bytes.
        chunk_count: Number of text chunks.
        status: Processing status.
        error: Error message if failed.
        tags: User-assigned tags.
        created_at: Upload timestamp ISO string.
    """
    id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    status: str
    error: Optional[str] = None
    tags: List[str] = []
    created_at: str
