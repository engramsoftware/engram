"""
First-run setup endpoints.

Provides a public (no auth required) endpoint to check whether the app
has been set up yet (i.e. at least one user exists). The frontend uses
this to decide whether to show the onboarding wizard or the login page.
"""

import logging
from fastapi import APIRouter

from database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Setup"])


@router.get("/status")
async def setup_status() -> dict:
    """Check if the application has been set up.

    Returns:
        needsSetup: True if no users exist (first run).
        userCount: Number of registered users.
    """
    db = get_database()
    user_count = await db.users.count_documents({})
    return {
        "needsSetup": user_count == 0,
        "userCount": user_count,
    }
