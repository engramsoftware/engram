"""
API routers package.
Each router handles a specific domain of endpoints.
"""

from routers import auth, conversations, messages, search, settings, addins, personas, memories, notes, documents, uploads

__all__ = [
    "auth",
    "conversations", 
    "messages",
    "search",
    "settings",
    "addins",
    "personas",
    "memories",
    "notes",
    "documents",
    "uploads",
]
