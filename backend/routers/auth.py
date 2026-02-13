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

from pydantic import BaseModel, EmailStr, Field

from config import get_settings
from database import get_database
from models.user import UserCreate, UserLogin, UserResponse, TokenResponse, User

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
def create_access_token(user_id: str) -> str:
    """Create a JWT access token for a user."""
    settings = get_settings()
    
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_expiration_hours)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Dependency to get current authenticated user from JWT token.
    Raises HTTPException if token is invalid.
    """
    settings = get_settings()
    token = credentials.credentials
    
    try:
        payload = jwt.decode(
            token, 
            settings.jwt_secret_key, 
            algorithms=[settings.jwt_algorithm]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Fetch user from database
    db = get_database()
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "name": user["name"]
    }


# ============================================================
# Endpoints
# ============================================================
@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate) -> TokenResponse:
    """Register a new user account."""
    db = get_database()
    
    # Check if email already exists
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user document
    user_doc = {
        "email": user_data.email,
        "name": user_data.name,
        "passwordHash": hash_password(user_data.password),
        "createdAt": datetime.utcnow(),
        "preferences": {"theme": "dark"}
    }
    
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)
    
    # Generate token
    token = create_access_token(user_id)
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user_id,
            email=user_data.email,
            name=user_data.name,
            created_at=user_doc["createdAt"],
            preferences=user_doc["preferences"]
        )
    )


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
    
    user_id = str(user["_id"])
    token = create_access_token(user_id)
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user_id,
            email=user["email"],
            name=user["name"],
            created_at=user["createdAt"],
            preferences=user.get("preferences", {"theme": "dark"})
        )
    )


class PasswordResetRequest(BaseModel):
    """Schema for password reset (local app — no email verification needed)."""
    email: EmailStr
    new_password: str = Field(..., min_length=8)


@router.post("/reset-password")
async def reset_password(data: PasswordResetRequest) -> dict:
    """Reset a user's password by email.

    Since Engram is a local/LAN-only app (PrivateNetworkMiddleware blocks
    external access), email verification isn't required. The user proves
    ownership by having physical access to the machine.

    Args:
        data: Email and new password.

    Returns:
        Success message.

    Raises:
        HTTPException 404: If no user with that email exists.
    """
    db = get_database()
    user = await db.users.find_one({"email": data.email})

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with that email",
        )

    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"passwordHash": hash_password(data.new_password)}},
    )

    logger.info(f"Password reset for user {data.email}")
    return {"message": "Password reset successfully. You can now log in."}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    """Get current authenticated user's profile."""
    db = get_database()
    user = await db.users.find_one({"_id": ObjectId(current_user["id"])})
    
    return UserResponse(
        id=str(user["_id"]),
        email=user["email"],
        name=user["name"],
        created_at=user["createdAt"],
        preferences=user.get("preferences", {"theme": "dark"})
    )
