"""
Database connection module — SQLite backend.

Provides connect/disconnect lifecycle and get_database() accessor.
All routers use get_database() to get a collection-style API
(find, insert_one, update_one, etc.) backed by a single SQLite file.

Typical usage:
    from database import get_database
    db = get_database()
    user = await db.users.find_one({"email": "alice@example.com"})
"""

import logging
from typing import Optional

from config import SQLITE_DB_PATH
from sqlite_db import SQLiteDatabase, ObjectId  # noqa: F401 — re-export ObjectId

logger = logging.getLogger(__name__)

# ============================================================
# Global database instance
# ============================================================
_database: Optional[SQLiteDatabase] = None


async def connect_db() -> None:
    """Initialize the SQLite database connection.

    Called once during application startup (main.py lifespan).
    Creates the database file if it doesn't exist.
    """
    global _database

    db_path = str(SQLITE_DB_PATH)
    logger.info(f"Connecting to SQLite database: {db_path}")

    _database = SQLiteDatabase(db_path)
    await _database.connect()

    logger.info("SQLite database connected successfully")


# Backward-compatible aliases (used by main.py and other callers)
connect_to_mongodb = connect_db


async def close_db() -> None:
    """Close the database connection gracefully.

    Called during application shutdown.
    """
    global _database
    if _database:
        await _database.close()
        logger.info("Database connection closed")


# Backward-compatible alias
close_mongodb_connection = close_db


def get_database() -> SQLiteDatabase:
    """Get the database instance.

    Returns:
        SQLiteDatabase with collection-style API (db.users, db.messages, etc.)

    Raises:
        RuntimeError: If connect_db() hasn't been called yet.
    """
    if _database is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")
    return _database


def get_client():
    """Legacy compatibility — returns the database itself."""
    return get_database()
