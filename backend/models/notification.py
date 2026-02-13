"""
Notification data models.

Represents email notifications that Engram can send immediately or schedule
for a future time. Stored in MongoDB for history/audit and scheduling.

Typical usage:
    notif = NotificationCreate(
        subject="Meeting Reminder",
        body="You have a meeting at 3pm",
        scheduled_at=datetime(2026, 2, 8, 15, 0),
    )
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class NotificationCreate(BaseModel):
    """Request to create a new notification.

    Args:
        subject: Email subject line.
        body: Plain text email body.
        scheduled_at: When to send (None = immediate).
        conversation_id: Conversation that triggered this notification.
    """
    subject: str
    body: str
    scheduled_at: Optional[datetime] = None
    conversation_id: Optional[str] = None


class NotificationResponse(BaseModel):
    """Notification as returned by the API.

    Args:
        id: MongoDB document ID.
        subject: Email subject line.
        body: Plain text email body.
        status: pending | sent | failed | cancelled.
        scheduled_at: When it's scheduled to send (None = was immediate).
        sent_at: When it was actually sent (None = not yet sent).
        created_at: When the notification was created.
        conversation_id: Conversation that triggered this.
        error: Error message if status is 'failed'.
        read: Whether the user has seen this in the notification panel.
    """
    id: str
    subject: str
    body: str
    status: str = "pending"
    scheduled_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    conversation_id: Optional[str] = None
    error: Optional[str] = None
    read: bool = False


# MongoDB document schema (camelCase for Mongo, snake_case in Python)
# {
#   "userId": str,
#   "subject": str,
#   "body": str,
#   "status": "pending" | "sent" | "failed" | "cancelled",
#   "scheduledAt": datetime | null,
#   "sentAt": datetime | null,
#   "createdAt": datetime,
#   "conversationId": str | null,
#   "error": str | null,
#   "read": bool,
# }
