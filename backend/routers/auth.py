"""
Authentication router.
Handles user registration, login, and token management.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import bcrypt
from jose import JWTError, jwt
from bson import ObjectId


from config import get_settings
from database import get_database
from models.user import UserCreate, UserLogin, UserResponse, TokenResponse, User, user_response

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================================
# Password Hashing
# ============================================================
security = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    # Stored as a UTF-8 string like: "$2b$12$..."
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ============================================================
# JWT Token Management
# ============================================================
def create_access_token(user_id: str, version: int = 0) -> str:
    """Create a JWT access token for a user.

    ``ver`` is the user's tokenVersion when the token was issued. Bumping
    tokenVersion (password change, "sign out everywhere", admin reset)
    invalidates every token issued before it.
    """
    settings = get_settings()
    
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_expiration_hours)
    payload = {
        "sub": user_id,
        "ver": version,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# Real accounts have a password hash (the old "anonymous-agent" record has none)
REAL_USERS = {"passwordHash": {"$exists": True}}


async def count_real_users(db) -> int:
    """Number of accounts that can sign in."""
    return await db.users.count_documents(REAL_USERS)


async def ensure_admin_exists(db) -> None:
    """Make the earliest account an admin if no admin exists yet.

    Installs from before roles existed have no admin; the person who set
    Engram up (the first account) becomes it.
    """
    if await db.users.count_documents({"isAdmin": True}) > 0:
        return
    first = await db.users.find(REAL_USERS).sort("createdAt", 1).limit(1).to_list(1)
    if first:
        await db.users.update_one({"_id": ObjectId(str(first[0]["_id"]))}, {"$set": {"isAdmin": True}})
        logger.info(f"No admin found; made the first account an admin: {first[0]['email']}")


async def user_for_session_token(token: str) -> Optional[dict]:
    """The account a login token belongs to, or None if the token is invalid,
    expired, or from a session that has been ended."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = await get_database().users.find_one({"_id": ObjectId(user_id)})
    # Tokens issued before a password change or "sign out everywhere" are void
    if not user or payload.get("ver", 0) != user.get("tokenVersion", 0):
        return None
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "name": user["name"],
        "is_admin": bool(user.get("isAdmin")),
    }


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Dependency to get current authenticated user from JWT token.
    Raises HTTPException if token is invalid.
    """
    user = await user_for_session_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Your session has ended. Please sign in again.")
    return user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency for endpoints only an admin may use."""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Only an admin can do this")
    return current_user


# ============================================================
# Endpoints
# ============================================================
@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate) -> TokenResponse:
    """Create the first account, which becomes the admin.

    Sign-up is closed once an account exists: admins add everyone else in
    Settings > Users.
    """
    db = get_database()

    if await count_real_users(db) > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign-up is closed. Ask an admin to add you in Settings › Users.",
        )

    # Create user document
    user_doc = {
        "email": user_data.email,
        "name": user_data.name,
        "passwordHash": hash_password(user_data.password),
        "createdAt": datetime.utcnow(),
        "preferences": {"theme": "dark"},
        "isAdmin": True,
        "tokenVersion": 0,
    }
    
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)
    user_doc["_id"] = user_id
    logger.info(f"First account created (admin): {user_data.email}")

    return TokenResponse(access_token=create_access_token(user_id), user=user_response(user_doc))


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin) -> TokenResponse:
    """Login with email and password."""
    db = get_database()
    
    # Find user by email
    user = await db.users.find_one({"email": credentials.email})
    
    if not user or not verify_password(credentials.password, user["passwordHash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    await ensure_admin_exists(db)
    user = await db.users.find_one({"_id": ObjectId(str(user["_id"]))})

    user_id = str(user["_id"])
    token = create_access_token(user_id, user.get("tokenVersion", 0))
    return TokenResponse(access_token=token, user=user_response(user))


# Password reset: there is no self-service reset (it let anyone on the network
# take over an account by typing its email). Admins reset passwords in
# Settings > Users; a locked-out sole admin runs `python reset_password.py` on
# the server.


@router.post("/logout-all")
async def logout_everywhere(current_user: dict = Depends(get_current_user)) -> dict:
    """Sign out every session of the current user, including this one."""
    db = get_database()
    await db.users.update_one({"_id": ObjectId(current_user["id"])}, {"$inc": {"tokenVersion": 1}})
    logger.info(f"Signed out everywhere: {current_user['email']}")
    return {"detail": "Signed out everywhere"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    """Get current authenticated user's profile."""
    db = get_database()
    user = await db.users.find_one({"_id": ObjectId(current_user["id"])})
    return user_response(user)
