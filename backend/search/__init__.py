"""
Search package.
Provides abstract interface and implementations for chat history search.
"""

from search.search_interface import SearchInterface, SearchResult
from search.basic_search import BasicKeywordSearch
from search.hybrid_wrapper import HybridSearchWrapper

__all__ = [
    "SearchInterface",
    "SearchResult",
    "BasicKeywordSearch",
    "HybridSearchWrapper",
]
