"""
Notification management router.

CRUD endpoints for email notifications — list (with filters), cancel
pending, mark as read, retry failed, and delete. All notifications are
scoped to the authenticated user.
"""

import logging
from datetime import datetime
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_database
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _serialize_notification(doc: dict) -> dict:
    """Convert a MongoDB notification document to an API-friendly dict.

    Args:
        doc: Raw MongoDB document with ObjectId and camelCase keys.

    Returns:
        Dict with string id and snake_case keys for the frontend.
    """
    return {
        "id": str(doc["_id"]),
        "subject": doc.get("subject", ""),
        "body": doc.get("body", ""),
        "status": doc.get("status", "pending"),
        "scheduled_at": doc.get("scheduledAt"),
        "sent_at": doc.get("sentAt"),
        "created_at": doc.get("createdAt"),
        "conversation_id": doc.get("conversationId"),
        "error": doc.get("error"),
        "read": doc.get("read", False),
    }


@router.get("/")
async def list_notifications(
    status: Optional[str] = Query(None, description="Filter by status: pending, sent, failed, cancelled"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """List notifications for the current user.

    Returns newest first. Optionally filter by status.

    Args:
        status: Filter by notification status.
        limit: Max results to return (default 50).
        skip: Number of results to skip (for pagination).

    Returns:
        Dict with notifications list, total count, and unread count.
    """
    db = get_database()
    user_id = current_user["id"]

    query = {"userId": user_id}
    if status:
        query["status"] = status

    total = await db.notifications.count_documents(query)
    unread = await db.notifications.count_documents({
        "userId": user_id,
        "read": False,
    })

    cursor = db.notifications.find(query).sort("createdAt", -1).skip(skip).limit(limit)
    notifications = []
    async for doc in cursor:
        notifications.append(_serialize_notification(doc))

    return {
        "notifications": notifications,
        "total": total,
        "unread": unread,
    }


@router.get("/unread-count")
async def get_unread_count(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get the count of unread notifications.

    Returns:
        Dict with unread count and pending (scheduled) count.
    """
    db = get_database()
    user_id = current_user["id"]

    unread = await db.notifications.count_documents({
        "userId": user_id,
        "read": False,
    })
    pending = await db.notifications.count_documents({
        "userId": user_id,
        "status": "pending",
    })

    return {"unread": unread, "pending": pending}


@router.put("/{notification_id}/read")
async def mark_as_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Mark a notification as read.

    Args:
        notification_id: The notification's MongoDB ObjectId.

    Returns:
        Dict with success status.
    """
    db = get_database()
    user_id = current_user["id"]

    result = await db.notifications.update_one(
        {"_id": ObjectId(notification_id), "userId": user_id},
        {"$set": {"read": True}},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")

    return {"success": True}


@router.put("/read-all")
async def mark_all_as_read(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Mark all notifications as read for the current user.

    Returns:
        Dict with count of notifications marked as read.
    """
    db = get_database()
    user_id = current_user["id"]

    result = await db.notifications.update_many(
        {"userId": user_id, "read": False},
        {"$set": {"read": True}},
    )

    return {"success": True, "marked": result.modified_count}


@router.put("/{notification_id}/cancel")
async def cancel_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Cancel a pending (scheduled) notification before it sends.

    Args:
        notification_id: The notification's MongoDB ObjectId.

    Returns:
        Dict with success status.

    Raises:
        HTTPException: If notification not found or not in pending status.
    """
    db = get_database()
    user_id = current_user["id"]

    result = await db.notifications.update_one(
        {
            "_id": ObjectId(notification_id),
            "userId": user_id,
            "status": "pending",
        },
        {"$set": {"status": "cancelled"}},
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Notification not found or not in pending status",
        )

    logger.info(f"Notification {notification_id} cancelled by user {user_id}")
    return {"success": True}


@router.put("/{notification_id}/retry")
async def retry_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Retry a failed notification by resetting it to pending.

    The scheduler will pick it up on its next cycle.

    Args:
        notification_id: The notification's MongoDB ObjectId.

    Returns:
        Dict with success status.

    Raises:
        HTTPException: If notification not found or not in failed status.
    """
    db = get_database()
    user_id = current_user["id"]

    result = await db.notifications.update_one(
        {
            "_id": ObjectId(notification_id),
            "userId": user_id,
            "status": "failed",
        },
        {"$set": {
            "status": "pending",
            "error": None,
            "scheduledAt": datetime.utcnow(),
        }},
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Notification not found or not in failed status",
        )

    logger.info(f"Notification {notification_id} retried by user {user_id}")
    return {"success": True}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete a notification permanently.

    Args:
        notification_id: The notification's MongoDB ObjectId.

    Returns:
        Dict with success status.

    Raises:
        HTTPException: If notification not found.
    """
    db = get_database()
    user_id = current_user["id"]

    result = await db.notifications.delete_one(
        {"_id": ObjectId(notification_id), "userId": user_id},
    )

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")

    return {"success": True}
