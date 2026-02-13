"""
Schedule router — shared calendar/event system.

Events are shared between ALL users (family/team calendar).
Events can be created manually, by the LLM via [ADD_SCHEDULE] markers,
or imported from Gmail. Each event has a title, datetime, optional
description, recurrence, and source tracking.

Uses SQLite via the standard get_database() accessor.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from database import get_database
from bson import ObjectId
from routers.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Models ────────────────────────────────────────────────────

class ScheduleEventCreate(BaseModel):
    """Create a new schedule event."""
    title: str = Field(..., description="Event title")
    start_time: str = Field(..., description="Start datetime (ISO format)")
    end_time: Optional[str] = Field(default=None, description="End datetime (ISO format, optional)")
    description: Optional[str] = Field(default="", description="Event description or notes")
    location: Optional[str] = Field(default="", description="Location")
    category: str = Field(default="general", description="Category (appointment, reminder, task, etc.)")
    recurring: Optional[str] = Field(default=None, description="Recurrence: daily, weekly, monthly, or null")
    all_day: bool = Field(default=False, description="Whether this is an all-day event")
    source: str = Field(default="manual", description="Source: manual, llm, gmail")


class ScheduleEventUpdate(BaseModel):
    """Update an existing schedule event."""
    title: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    category: Optional[str] = None
    recurring: Optional[str] = None
    all_day: Optional[bool] = None


class ScheduleEventResponse(BaseModel):
    """Schedule event response."""
    id: str
    title: str
    start_time: str
    end_time: Optional[str]
    description: str
    location: str
    category: str
    recurring: Optional[str]
    all_day: bool
    source: str
    created_by: str
    created_at: str


# ── Helpers ───────────────────────────────────────────────────

def _parse_iso(s: str) -> datetime:
    """Parse an ISO datetime string into a datetime object.

    Args:
        s: ISO format datetime string.

    Returns:
        Parsed datetime object.

    Raises:
        ValueError: If the string can't be parsed.
    """
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s}")


def _to_str(val) -> str:
    """Coerce a value to string. Handles datetime objects from SQLite."""
    if val is None:
        return ""
    return val.isoformat() if hasattr(val, "isoformat") else str(val)


def _event_to_response(doc: dict) -> dict:
    """Convert a DB document to a ScheduleEventResponse dict.

    Args:
        doc: Raw database document.

    Returns:
        Dict matching ScheduleEventResponse fields.
    """
    end_raw = doc.get("endTime")
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title", ""),
        "start_time": _to_str(doc.get("startTime", "")),
        "end_time": _to_str(end_raw) if end_raw else None,
        "description": doc.get("description", ""),
        "location": doc.get("location", ""),
        "category": doc.get("category", "general"),
        "recurring": doc.get("recurring"),
        "all_day": doc.get("allDay", False),
        "source": doc.get("source", "manual"),
        "created_by": doc.get("createdBy", ""),
        "created_at": _to_str(doc.get("createdAt", "")),
    }


# ── Endpoints ─────────────────────────────────────────────────

@router.get("")
async def list_events(
    start: Optional[str] = Query(default=None, description="Filter: start date (ISO)"),
    end: Optional[str] = Query(default=None, description="Filter: end date (ISO)"),
    category: Optional[str] = Query(default=None, description="Filter: category"),
    current_user: dict = Depends(get_current_user),
) -> List[dict]:
    """List schedule events (shared — all users see the same calendar).

    Args:
        start: Optional start date filter (ISO format).
        end: Optional end date filter (ISO format).
        category: Optional category filter.
        current_user: Authenticated user (for auth only, events are shared).

    Returns:
        List of schedule events sorted by start_time ascending.
    """
    db = get_database()
    query: dict = {}

    if start:
        query["startTime"] = {"$gte": start}
    if end:
        if "startTime" in query:
            query["startTime"]["$lte"] = end
        else:
            query["startTime"] = {"$lte": end}
    if category:
        query["category"] = category

    events = []
    async for doc in db.schedule_events.find(query).sort("startTime", 1):
        events.append(_event_to_response(doc))

    return events


@router.post("")
async def create_event(
    data: ScheduleEventCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Create a new schedule event (shared between all users).

    Args:
        data: Event details.
        current_user: Authenticated user who created the event.

    Returns:
        Created event with ID.
    """
    db = get_database()

    # Validate datetime
    try:
        parsed_start = _parse_iso(data.start_time)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid start_time: {data.start_time}")

    parsed_end = None
    if data.end_time:
        try:
            parsed_end = _parse_iso(data.end_time)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid end_time: {data.end_time}")

    doc = {
        "title": data.title,
        "startTime": parsed_start.isoformat(),
        "endTime": parsed_end.isoformat() if parsed_end else None,
        "description": data.description or "",
        "location": data.location or "",
        "category": data.category,
        "recurring": data.recurring,
        "allDay": data.all_day,
        "source": data.source,
        "createdBy": current_user["id"],
        "createdAt": datetime.utcnow().isoformat(),
    }

    result = await db.schedule_events.insert_one(doc)
    doc["_id"] = result.inserted_id
    logger.info(f"Schedule event created: '{data.title}' at {data.start_time} by {current_user['id']}")

    return _event_to_response(doc)


@router.put("/{event_id}")
async def update_event(
    event_id: str,
    data: ScheduleEventUpdate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update a schedule event.

    Args:
        event_id: ID of the event to update.
        data: Fields to update.
        current_user: Authenticated user (for auth).

    Returns:
        Updated event.
    """
    db = get_database()

    existing = await db.schedule_events.find_one({"_id": ObjectId(event_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")

    updates = {}
    if data.title is not None:
        updates["title"] = data.title
    if data.start_time is not None:
        try:
            _parse_iso(data.start_time)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid start_time: {data.start_time}")
        updates["startTime"] = data.start_time
    if data.end_time is not None:
        updates["endTime"] = data.end_time
    if data.description is not None:
        updates["description"] = data.description
    if data.location is not None:
        updates["location"] = data.location
    if data.category is not None:
        updates["category"] = data.category
    if data.recurring is not None:
        updates["recurring"] = data.recurring
    if data.all_day is not None:
        updates["allDay"] = data.all_day

    if updates:
        await db.schedule_events.update_one(
            {"_id": ObjectId(event_id)},
            {"$set": updates}
        )

    updated = await db.schedule_events.find_one({"_id": ObjectId(event_id)})
    return _event_to_response(updated)


@router.delete("/{event_id}")
async def delete_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete a schedule event.

    Args:
        event_id: ID of the event to delete.
        current_user: Authenticated user (for auth).

    Returns:
        Deletion confirmation.
    """
    db = get_database()

    existing = await db.schedule_events.find_one({"_id": ObjectId(event_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")

    await db.schedule_events.delete_one({"_id": ObjectId(event_id)})
    logger.info(f"Schedule event deleted: {event_id}")

    return {"deleted": True, "id": event_id}


@router.get("/upcoming")
async def upcoming_events(
    days: int = Query(default=7, description="Number of days to look ahead"),
    current_user: dict = Depends(get_current_user),
) -> List[dict]:
    """Get upcoming events for the next N days.

    Used by the LLM to inject schedule context into conversations.

    Args:
        days: Number of days to look ahead (default 7).
        current_user: Authenticated user (for auth).

    Returns:
        List of upcoming events sorted by start_time.
    """
    db = get_database()
    now = datetime.utcnow()
    end = now + timedelta(days=days)

    events = []
    async for doc in db.schedule_events.find({
        "startTime": {"$gte": now.isoformat(), "$lte": end.isoformat()}
    }).sort("startTime", 1):
        events.append(_event_to_response(doc))

    return events


@router.post("/from-email")
async def create_event_from_email(
    data: ScheduleEventCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Create a schedule event from a Gmail/email import.

    Sets the source to 'gmail' automatically.

    Args:
        data: Event details parsed from email.
        current_user: Authenticated user.

    Returns:
        Created event.
    """
    data.source = "gmail"
    return await create_event(data, current_user)
