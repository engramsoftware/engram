"""
User management router.
Handles listing, updating, creating, and deleting user accounts.

All endpoints require authentication. Any authenticated user can
update their own profile; listing and creating users is available
to all authenticated users (LAN-only app, no admin role needed).
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status
from bson import ObjectId
from pydantic import BaseModel, EmailStr, Field

from database import get_database
from routers.auth import get_current_user, hash_password
from models.user import UserResponse

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response Models ────────────────────────────────

class UserUpdateRequest(BaseModel):
    """Schema for updating a user's profile.

    All fields are optional — only provided fields are updated.

    Args:
        name: New display name (1-100 chars).
        email: New email address.
        password: New password (min 8 chars, re-hashed on save).
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8)


class AdminUserCreate(BaseModel):
    """Schema for creating a new user from the Users tab.

    Args:
        email: Email address (must be unique).
        name: Display name.
        password: Initial password (min 8 chars).
    """
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8)


# ── Endpoints ────────────────────────────────────────────────

@router.get("/", response_model=List[UserResponse])
async def list_users(current_user: dict = Depends(get_current_user)) -> dict:
    """List all users in the system.

    Returns:
        List of user profiles (no password hashes).
    """
    db = get_database()
    users: List[UserResponse] = []
    async for u in db.users.find().sort("createdAt", -1):
        users.append(UserResponse(
            id=str(u["_id"]),
            email=u["email"],
            name=u["name"],
            created_at=u["createdAt"],
            preferences=u.get("preferences", {"theme": "dark"}),
        ))
    return users


@router.put("/me", response_model=UserResponse)
async def update_my_profile(
    data: UserUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update the current user's own profile.

    Args:
        data: Fields to update (name, email, password).

    Returns:
        Updated user profile.

    Raises:
        400: If the new email is already taken by another user.
    """
    db = get_database()
    user_id = current_user["id"]

    update_fields: dict = {}
    if data.name is not None:
        update_fields["name"] = data.name
    if data.email is not None:
        # Check uniqueness
        existing = await db.users.find_one({
            "email": data.email,
            "_id": {"$ne": ObjectId(user_id)},
        })
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use by another account",
            )
        update_fields["email"] = data.email
    if data.password is not None:
        update_fields["passwordHash"] = hash_password(data.password)

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_fields},
    )

    # Return fresh user doc
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    return UserResponse(
        id=str(user["_id"]),
        email=user["email"],
        name=user["name"],
        created_at=user["createdAt"],
        preferences=user.get("preferences", {"theme": "dark"}),
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    data: UserUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update any user's profile (LAN app — no admin role required).

    Args:
        user_id: Target user's ID.
        data: Fields to update.

    Returns:
        Updated user profile.

    Raises:
        404: If the user doesn't exist.
        400: If the new email is already taken.
    """
    db = get_database()

    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    update_fields: dict = {}
    if data.name is not None:
        update_fields["name"] = data.name
    if data.email is not None:
        existing = await db.users.find_one({
            "email": data.email,
            "_id": {"$ne": ObjectId(user_id)},
        })
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use by another account",
            )
        update_fields["email"] = data.email
    if data.password is not None:
        update_fields["passwordHash"] = hash_password(data.password)

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_fields},
    )

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    return UserResponse(
        id=str(user["_id"]),
        email=user["email"],
        name=user["name"],
        created_at=user["createdAt"],
        preferences=user.get("preferences", {"theme": "dark"}),
    )


@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    data: AdminUserCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Create a new user account.

    Args:
        data: New user's email, name, and password.

    Returns:
        Created user profile.

    Raises:
        400: If the email is already registered.
    """
    db = get_database()

    existing = await db.users.find_one({"email": data.email})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user_doc = {
        "email": data.email,
        "name": data.name,
        "passwordHash": hash_password(data.password),
        "createdAt": datetime.utcnow(),
        "preferences": {"theme": "dark"},
    }
    result = await db.users.insert_one(user_doc)
    logger.info(f"User created: {data.email} by {current_user['email']}")

    return UserResponse(
        id=str(result.inserted_id),
        email=data.email,
        name=data.name,
        created_at=user_doc["createdAt"],
        preferences=user_doc["preferences"],
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete a user account.

    Cannot delete your own account (safety measure).

    Args:
        user_id: ID of the user to delete.

    Raises:
        400: If trying to delete yourself.
        404: If the user doesn't exist.
    """
    if user_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    db = get_database()
    result = await db.users.delete_one({"_id": ObjectId(user_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(f"User {user_id} deleted by {current_user['email']}")
    return {"detail": "User deleted"}
