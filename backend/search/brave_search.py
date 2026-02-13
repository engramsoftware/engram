"""
Brave Search API client.

Provides web search via the Brave Search API (free tier: 1 req/sec, 2000/mo).
Used by the pipeline to give the LLM real-time web context when answering
questions that need current information.

API docs: https://api-dashboard.search.brave.com/documentation/quickstart
"""

import logging
import asyncio
import time
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Brave free tier: max 1 request per second
_MIN_INTERVAL_SECS = 1.05
_last_request_time: float = 0.0
_rate_lock = asyncio.Lock()


class BraveSearchClient:
    """
    Async client for the Brave Web Search API.

    Args:
        api_key: Brave Search subscription token.
    """

    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        """Build request headers with subscription token."""
        return {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }

    async def _rate_limit(self) -> None:
        """Enforce 1-request-per-second rate limit for the free tier."""
        global _last_request_time
        async with _rate_lock:
            now = time.monotonic()
            elapsed = now - _last_request_time
            if elapsed < _MIN_INTERVAL_SECS:
                await asyncio.sleep(_MIN_INTERVAL_SECS - elapsed)
            _last_request_time = time.monotonic()

    async def search(
        self,
        query: str,
        count: int = 5,
        freshness: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search the web via Brave Search API.

        Args:
            query: Search query string.
            count: Number of results to return (max 20 on free tier).
            freshness: Optional freshness filter (e.g. 'pd' for past day,
                       'pw' for past week, 'pm' for past month).

        Returns:
            List of result dicts with keys: title, url, description, age.
        """
        if not self.api_key:
            logger.warning("Brave Search API key not configured")
            return []

        await self._rate_limit()

        params: Dict[str, Any] = {"q": query, "count": min(count, 20)}
        if freshness:
            params["freshness"] = freshness

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    self.BASE_URL,
                    headers=self._headers(),
                    params=params,
                )

                if response.status_code != 200:
                    logger.error(
                        f"Brave Search API error {response.status_code}: "
                        f"{response.text[:300]}"
                    )
                    return []

                data = response.json()
                web_results = data.get("web", {}).get("results", [])

                results = []
                for r in web_results[:count]:
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("description", ""),
                        "age": r.get("age", ""),
                    })

                logger.info(
                    f"Brave Search: '{query}' → {len(results)} results"
                )
                return results

        except httpx.TimeoutException:
            logger.warning(f"Brave Search timed out for query: {query}")
            return []
        except Exception as e:
            logger.error(f"Brave Search error: {e}")
            return []

    async def test_connection(self) -> bool:
        """Test that the API key is valid with a minimal query."""
        if not self.api_key:
            return False
        try:
            results = await self.search("test", count=1)
            return len(results) > 0
        except Exception:
            return False


def format_brave_results_for_context(results: List[Dict[str, Any]]) -> str:
    """
    Format Brave search results into a context string for the LLM.

    Args:
        results: List of search result dicts from BraveSearchClient.search().

    Returns:
        Formatted string suitable for injection into the LLM prompt.
    """
    if not results:
        return ""

    parts = ["## Web Search Results\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        desc = r.get("description", "")
        parts.append(f"{i}. **{title}**\n   {url}\n   {desc}\n")

    return "\n".join(parts)
