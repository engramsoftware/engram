"""
File upload router.

Handles file uploads for chat messages. Files are stored locally in
data/uploads/ and served via a static file endpoint. The upload returns
a URL that the frontend includes in the message payload.

Supports images (sent to vision models), PDFs, documents, spreadsheets,
and other common file types. Non-image files are extracted to text and
included in the message context.
"""

import logging
import uuid
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import FileResponse

from routers.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

# Storage directory for uploaded images (relative to project root)
UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Allowed file MIME types → extension mapping
ALLOWED_TYPES = {
    # Images
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    # Documents
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    # Spreadsheets
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/csv": ".csv",
    # Text / Code
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/x-python": ".py",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/html": ".html",
    "application/x-yaml": ".yaml",
    "text/yaml": ".yaml",
    # Presentations
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    # Archives (for reference, not extracted)
    "application/zip": ".zip",
}

# Also allow by file extension (browsers sometimes send wrong MIME types)
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv",
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".xml",
    ".html", ".yaml", ".yml", ".log", ".rst",
    ".ppt", ".pptx", ".zip",
}

# Max file size: 20 MB
MAX_FILE_SIZE = 20 * 1024 * 1024


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Upload a file for use in a chat message.

    Supports images, PDFs, documents, spreadsheets, and text files.
    Saves to data/uploads/ with a unique filename and returns the URL.

    Args:
        file: The uploaded file (multipart form data).
        current_user: Authenticated user from JWT.

    Returns:
        Dict with 'url', 'filename', 'size', 'content_type', 'is_image'.

    Raises:
        HTTPException: If file is too large or not an allowed type.
    """
    content_type = file.content_type or ""
    original_name = file.filename or "unknown"
    ext = "." + original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

    # Allow by MIME type or by file extension
    if content_type not in ALLOWED_TYPES and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type} ({ext}). "
                   f"Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {MAX_FILE_SIZE // (1024*1024)} MB",
        )

    # Determine file extension
    if content_type in ALLOWED_TYPES:
        save_ext = ALLOWED_TYPES[content_type]
    elif ext in ALLOWED_EXTENSIONS:
        save_ext = ext
    else:
        save_ext = ext or ".bin"

    unique_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{save_ext}"
    file_path = UPLOAD_DIR / unique_name

    # Save to disk
    file_path.write_bytes(content)
    is_image = content_type.startswith("image/")
    logger.info(f"File uploaded: {unique_name} ({len(content)} bytes, image={is_image}) by user {current_user['id']}")

    return {
        "url": f"/uploads/{unique_name}",
        "filename": original_name,
        "size": len(content),
        "content_type": content_type,
        "is_image": is_image,
    }


@router.get("/{filename}")
async def serve_file(filename: str) -> dict:
    """Serve an uploaded file by filename.

    Files are served without JWT auth because <img> tags and download
    links can't send Authorization headers. Security is provided by:
      1. PrivateNetworkMiddleware blocks all non-LAN/VPN IPs
      2. Filenames are UUID-based and unguessable
      3. Path traversal is prevented below

    Args:
        filename: The unique filename from the upload response.

    Returns:
        The file.

    Raises:
        HTTPException: If file not found or path traversal detected.
    """
    # Only allow alphanumeric, dash, underscore, dot in filenames
    import re
    if not re.match(r'^[\w\-\.]+$', filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = UPLOAD_DIR / filename

    # Security: prevent path traversal
    if not file_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(file_path)
