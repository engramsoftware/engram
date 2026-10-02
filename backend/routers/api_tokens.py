"""
Personal API tokens for agents and tools that use the OpenAI-compatible
endpoint (/api/v1/chat/completions).

A token acts as the account that created it. Only a SHA-256 hash is stored;
the token itself is shown once, when it is created. Tokens are listed and
revoked in Settings > Account.
"""

import hashlib
import logging
import secrets
from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import get_database
from routers.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

TOKEN_PREFIX = "engram_"
MAX_TOKENS_PER_USER = 20


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class TokenInfo(BaseModel):
    id: str
    name: str
    hint: str  # first characters, so tokens can be told apart
    created_at: datetime
    last_used_at: Optional[datetime] = None


class TokenCreated(TokenInfo):
    token: str  # shown once


def _info(doc: dict) -> TokenInfo:
    return TokenInfo(
        id=str(doc["_id"]),
        name=doc["name"],
        hint=doc["hint"],
        created_at=doc["createdAt"],
        last_used_at=doc.get("lastUsedAt"),
    )


async def user_for_api_token(token: str) -> Optional[dict]:
    """The account an API token belongs to, or None if the token is unknown."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    db = get_database()
    doc = await db.api_tokens.find_one({"tokenHash": _hash(token)})
    if not doc:
        return None
    user = await db.users.find_one({"_id": ObjectId(doc["userId"])})
    if not user:
        return None
    await db.api_tokens.update_one({"_id": ObjectId(str(doc["_id"]))}, {"$set": {"lastUsedAt": datetime.utcnow()}})
    return {"id": str(user["_id"]), "email": user["email"], "name": user["name"], "is_admin": bool(user.get("isAdmin"))}


@router.get("", response_model=List[TokenInfo])
async def list_tokens(current_user: dict = Depends(get_current_user)) -> List[TokenInfo]:
    """Your API tokens (never the token values)."""
    db = get_database()
    return [_info(d) async for d in db.api_tokens.find({"userId": current_user["id"]}).sort("createdAt", -1)]


@router.post("", response_model=TokenCreated, status_code=201)
async def create_token(data: TokenCreate, current_user: dict = Depends(get_current_user)) -> TokenCreated:
    """Create a token. The response is the only time the token is shown."""
    db = get_database()
    if await db.api_tokens.count_documents({"userId": current_user["id"]}) >= MAX_TOKENS_PER_USER:
        raise HTTPException(status_code=400, detail=f"You can have up to {MAX_TOKENS_PER_USER} tokens. Revoke one first.")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    doc = {
        "userId": current_user["id"],
        "name": data.name.strip(),
        "tokenHash": _hash(token),
        "hint": token[: len(TOKEN_PREFIX) + 4],
        "createdAt": datetime.utcnow(),
    }
    result = await db.api_tokens.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    logger.info(f"API token '{doc['name']}' created by {current_user['email']}")
    return TokenCreated(**_info(doc).model_dump(), token=token)


@router.delete("/{token_id}")
async def revoke_token(token_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    """Revoke one of your tokens; agents using it stop working at once."""
    db = get_database()
    result = await db.api_tokens.delete_one({"_id": ObjectId(token_id), "userId": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Token not found")
    logger.info(f"API token {token_id} revoked by {current_user['email']}")
    return {"detail": "Token revoked"}
