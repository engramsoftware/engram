"""
Documents router for RAG.

Handles file upload, listing, and deletion of user documents.
Uploaded files are parsed, chunked, and embedded into ChromaDB for
retrieval-augmented generation.

Supported formats: .txt, .md, .pdf, .docx, .csv, .json, .yaml
"""

import logging
import asyncio
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from bson import ObjectId

from database import get_database
from routers.auth import get_current_user
from models.document import DocumentResponse, DocumentUploadResponse
from rag.document_processor import (
    parse_file,
    chunk_text,
    embed_chunks,
    delete_document_chunks,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Max upload size: 20 MB
MAX_FILE_SIZE = 20 * 1024 * 1024

# Keep track of background processing tasks
_bg_tasks: set = set()


@router.post("", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Upload and process a document for RAG.

    The file is parsed, chunked, and embedded into ChromaDB in the background.
    Returns immediately with status='processing'. The document status updates
    to 'ready' or 'error' once processing completes.

    Args:
        file: The uploaded file (multipart form data).
        current_user: Authenticated user from JWT.

    Returns:
        DocumentUploadResponse with document ID and initial status.

    Raises:
        HTTPException: If file is too large or unsupported type.
    """
    db = get_database()
    user_id = current_user["id"]

    # Read file content
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {MAX_FILE_SIZE // (1024*1024)} MB",
        )

    # Validate file type early
    filename = file.filename or "unknown.txt"
    try:
        # Quick parse to validate — will raise ValueError for unsupported types
        text = parse_file(filename, content)
    except (ValueError, ImportError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Save document metadata to MongoDB
    doc = {
        "userId": user_id,
        "filename": filename,
        "fileType": filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt",
        "fileSize": len(content),
        "chunkCount": 0,
        "status": "processing",
        "error": None,
        "tags": [],
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }
    result = await db.documents.insert_one(doc)
    doc_id = str(result.inserted_id)

    # Process in background so upload returns fast
    async def _process():
        try:
            chunks = chunk_text(text)
            embedded = embed_chunks(chunks, user_id, doc_id, filename)

            await db.documents.update_one(
                {"_id": ObjectId(doc_id)},
                {
                    "$set": {
                        "chunkCount": embedded,
                        "status": "ready",
                        "updatedAt": datetime.utcnow(),
                    }
                },
            )
            logger.info(
                f"Document '{filename}' processed: {embedded} chunks (user={user_id})"
            )
        except Exception as e:
            logger.error(f"Document processing failed for '{filename}': {e}")
            await db.documents.update_one(
                {"_id": ObjectId(doc_id)},
                {
                    "$set": {
                        "status": "error",
                        "error": str(e),
                        "updatedAt": datetime.utcnow(),
                    }
                },
            )

    task = asyncio.create_task(_process())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

    return DocumentUploadResponse(
        id=doc_id,
        filename=filename,
        chunks=0,
        status="processing",
    )


@router.get("", response_model=List[DocumentResponse])
async def list_documents(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """List all documents uploaded by the current user.

    Returns:
        List of DocumentResponse sorted by creation date (newest first).
    """
    db = get_database()
    user_id = current_user["id"]

    docs = []
    async for doc in db.documents.find({"userId": user_id}).sort("createdAt", -1):
        docs.append(
            DocumentResponse(
                id=str(doc["_id"]),
                filename=doc["filename"],
                file_type=doc.get("fileType", "txt"),
                file_size=doc.get("fileSize", 0),
                chunk_count=doc.get("chunkCount", 0),
                status=doc.get("status", "ready"),
                error=doc.get("error"),
                tags=doc.get("tags", []),
                created_at=doc["createdAt"].isoformat(),
            )
        )

    return docs


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete a document and its ChromaDB chunks.

    Args:
        document_id: MongoDB document ID.
        current_user: Authenticated user from JWT.

    Returns:
        Success message.

    Raises:
        HTTPException: If document not found or not owned by user.
    """
    db = get_database()
    user_id = current_user["id"]

    doc = await db.documents.find_one({
        "_id": ObjectId(document_id),
        "userId": user_id,
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete chunks from ChromaDB
    delete_document_chunks(document_id)

    # Delete from MongoDB
    await db.documents.delete_one({"_id": ObjectId(document_id)})

    logger.info(f"Deleted document '{doc['filename']}' (user={user_id})")
    return {"message": f"Deleted {doc['filename']}"}
