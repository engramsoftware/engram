"""
Compatibility shim — replaces the pymongo bson package.

All existing code that does `from bson import ObjectId` will now
get our SQLite-compatible ObjectId instead of MongoDB's.
"""

from sqlite_db import ObjectId  # noqa: F401

__all__ = ["ObjectId"]
