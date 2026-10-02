"""
User management router.
Handles listing, updating, creating, and deleting user accounts.

Everyone can update their own profile (changing your password needs the
current one). Listing, creating, editing and deleting other accounts is
admin-only, and Engram always keeps at least one admin.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status
from bson import ObjectId
from pydantic import BaseModel, EmailStr, Field

from database import get_database
from routers.auth import create_access_token, get_current_user, hash_password, require_admin, verify_password
from models.user import UserResponse, user_response

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


class MyProfileUpdate(UserUpdateRequest):
    """Your own profile. Changing your password needs the current one."""
    current_password: Optional[str] = None


class AdminUserUpdate(UserUpdateRequest):
    """An admin editing another account (can also grant or remove admin)."""
    is_admin: Optional[bool] = None


class ProfileUpdateResponse(UserResponse):
    """A password change signs out other sessions; this one gets a new token."""
    access_token: Optional[str] = None


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
    is_admin: bool = False


async def _admin_count(db) -> int:
    return await db.users.count_documents({"isAdmin": True})


# ── Endpoints ────────────────────────────────────────────────

@router.get("/", response_model=List[UserResponse])
async def list_users(current_user: dict = Depends(require_admin)) -> dict:
    """List all accounts (admin only).

    Returns:
        List of user profiles (no password hashes).
    """
    db = get_database()
    users: List[UserResponse] = []
    async for u in db.users.find({"passwordHash": {"$exists": True}}).sort("createdAt", -1):
        users.append(user_response(u))
    return users


@router.put("/me", response_model=ProfileUpdateResponse)
async def update_my_profile(
    data: MyProfileUpdate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update the current user's own profile.

    Changing the password needs the current password. It signs out every
    other session; the response carries a new token for this one.

    Raises:
        400: If the new email is already taken by another user.
        403: If the current password is missing or wrong.
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
        me = await db.users.find_one({"_id": ObjectId(user_id)})
        if not data.current_password or not verify_password(data.current_password, me.get("passwordHash", "")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Current password is incorrect")
        update_fields["passwordHash"] = hash_password(data.password)

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    update: dict = {"$set": update_fields}
    if data.password is not None:
        update["$inc"] = {"tokenVersion": 1}
    await db.users.update_one({"_id": ObjectId(user_id)}, update)

    # Return fresh user doc (and a token for this session after a password change)
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    token = create_access_token(user_id, user.get("tokenVersion", 0)) if data.password is not None else None
    return ProfileUpdateResponse(**user_response(user).model_dump(), access_token=token)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    data: AdminUserUpdate,
    current_user: dict = Depends(require_admin),
) -> dict:
    """Update another account (admin only).

    A new password signs that person out everywhere. The last admin can't
    lose admin rights.

    Raises:
        404: If the user doesn't exist.
        400: If the new email is already taken, or this would leave no admin.
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
    if data.is_admin is not None and data.is_admin != bool(target.get("isAdmin")):
        if not data.is_admin and await _admin_count(db) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Engram needs at least one admin. Make someone else an admin first.",
            )
        update_fields["isAdmin"] = data.is_admin

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    update: dict = {"$set": update_fields}
    if data.password is not None:
        update["$inc"] = {"tokenVersion": 1}
    await db.users.update_one({"_id": ObjectId(user_id)}, update)
    logger.info(f"User {target['email']} updated by {current_user['email']}: {sorted(update_fields)}")

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    return user_response(user)


@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    data: AdminUserCreate,
    current_user: dict = Depends(require_admin),
) -> dict:
    """Create a new user account (admin only).

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
        "isAdmin": data.is_admin,
        "tokenVersion": 0,
    }
    result = await db.users.insert_one(user_doc)
    user_doc["_id"] = str(result.inserted_id)
    logger.info(f"User created: {data.email} (admin={data.is_admin}) by {current_user['email']}")
    return user_response(user_doc)


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    current_user: dict = Depends(require_admin),
) -> dict:
    """Delete a user account (admin only).

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
