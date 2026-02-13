"""
Abstract search interface.
Defines the contract for all search implementations.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel


class SearchResult(BaseModel):
    """
    A single search result from chat history.
    Contains message content and metadata for context injection.
    """
    id: str                          # Message ID
    conversation_id: str             # Parent conversation
    content: str                     # Message text
    role: str                        # user/assistant/system
    timestamp: datetime              # When message was sent
    score: float = 0.0               # Relevance score
    metadata: Dict[str, Any] = {}    # Additional context
    
    def to_context_string(self) -> str:
        """
        Format result for injection into system prompt.
        Returns a human-readable string with context.
        """
        date_str = self.timestamp.strftime("%Y-%m-%d %H:%M")
        return f"[{date_str}] ({self.role}): {self.content}"


class SearchFilters(BaseModel):
    """Filters to narrow search scope."""
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    role: Optional[str] = None  # user, assistant, system
    provider: Optional[str] = None
    model: Optional[str] = None


class SearchInterface(ABC):
    """
    Abstract base class for search implementations.
    
    All search implementations must:
    1. Implement search() to find relevant messages
    2. Return results that can be injected into LLM context
    
    The search results are used to provide the LLM with relevant
    context from previous conversations.
    """
    
    @abstractmethod
    async def search(
        self,
        query: str,
        user_id: str,
        filters: Optional[SearchFilters] = None,
        top_k: int = 5
    ) -> List[SearchResult]:
        """
        Search chat history for relevant messages.
        
        Args:
            query: The search query (user's current message)
            user_id: ID of the user to search for
            filters: Optional filters to narrow results
            top_k: Maximum number of results to return
            
        Returns:
            List of SearchResult objects sorted by relevance
        """
        pass
    
    @abstractmethod
    async def index_message(
        self,
        message_id: str,
        conversation_id: str,
        user_id: str,
        content: str,
        role: str,
        timestamp: datetime,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Index a new message for future search.
        
        Args:
            message_id: Unique message identifier
            conversation_id: Parent conversation ID
            user_id: Owner user ID
            content: Message text content
            role: Message role (user/assistant/system)
            timestamp: When message was created
            metadata: Additional searchable metadata
            
        Returns:
            True if indexing successful
        """
        pass
    
    def format_results_for_prompt(
        self,
        results: List[SearchResult],
        max_chars: int = 4000
    ) -> str:
        """
        Format search results for injection into system prompt.
        
        Args:
            results: Search results to format
            max_chars: Maximum characters to include
            
        Returns:
            Formatted string ready for system prompt injection
        """
        if not results:
            return ""
        
        formatted_parts = []
        total_chars = 0
        
        for result in results:
            context_str = result.to_context_string()
            
            # Check if adding this would exceed limit
            if total_chars + len(context_str) > max_chars:
                break
            
            formatted_parts.append(context_str)
            total_chars += len(context_str) + 2  # +2 for newlines
        
        if not formatted_parts:
            return ""
        
        return "\n\n".join(formatted_parts)
