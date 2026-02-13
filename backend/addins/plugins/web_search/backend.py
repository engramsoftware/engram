"""
Web Search Add-in.
Type 1: LLM-callable tool for searching the web.

Supports:
- Tavily API (recommended for AI applications)
- SerpAPI (Google search results)
"""

import logging
from typing import List, Dict, Any
import httpx

from addins.addin_interface import ToolAddin, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class WebSearchAddin(ToolAddin):
    """
    Web search tool that the LLM can call to find information.
    """
    
    name = "web_search"
    version = "1.0.0"
    description = "Search the web for current information"
    permissions = ["network"]
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.provider = self.config.get("provider", "tavily")
        self.api_key = self.config.get("api_key", "")
        self.max_results = self.config.get("max_results", 5)
    
    async def initialize(self) -> bool:
        """Initialize the web search add-in."""
        if not self.api_key:
            logger.warning("Web search API key not configured")
        return True
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass
    
    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Define the web_search tool for LLM function calling."""
        return [
            ToolDefinition(
                name="web_search",
                description="Search the web for current information. Use this when you need up-to-date information or facts you don't know.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "Number of results to return (default 5)",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            )
        ]
    
    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> ToolResult:
        """Execute the web search."""
        if tool_name != "web_search":
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
        
        query = arguments.get("query", "")
        num_results = arguments.get("num_results", self.max_results)
        
        if not query:
            return ToolResult(success=False, error="Query is required")
        
        if not self.api_key:
            return ToolResult(
                success=False,
                error="Web search API key not configured"
            )
        
        try:
            if self.provider == "tavily":
                results = await self._search_tavily(query, num_results)
            else:
                results = await self._search_serpapi(query, num_results)
            
            return ToolResult(success=True, result=results)
            
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return ToolResult(success=False, error=str(e))
    
    async def _search_tavily(
        self,
        query: str,
        num_results: int
    ) -> List[Dict[str, str]]:
        """Search using Tavily API."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": num_results,
                    "include_answer": True
                }
            )
            response.raise_for_status()
            data = response.json()
        
        results = []
        
        # Include AI-generated answer if available
        if data.get("answer"):
            results.append({
                "title": "AI Summary",
                "content": data["answer"],
                "url": ""
            })
        
        # Include search results
        for item in data.get("results", [])[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "url": item.get("url", "")
            })
        
        return results
    
    async def _search_serpapi(
        self,
        query: str,
        num_results: int
    ) -> List[Dict[str, str]]:
        """Search using SerpAPI."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://serpapi.com/search",
                params={
                    "api_key": self.api_key,
                    "q": query,
                    "num": num_results
                }
            )
            response.raise_for_status()
            data = response.json()
        
        results = []
        for item in data.get("organic_results", [])[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "content": item.get("snippet", ""),
                "url": item.get("link", "")
            })
        
        return results


# Export the add-in class
Addin = WebSearchAddin
