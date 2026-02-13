"""
Add-in Registry.
Manages installed add-ins and their lifecycle.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Type

from addins.addin_interface import (
    AddinBase,
    ToolAddin,
    InterceptorAddin,
    ToolDefinition,
    ToolResult
)

logger = logging.getLogger(__name__)


class AddinRegistry:
    """
    Central registry for all installed add-ins.
    Handles registration, lookup, and lifecycle management.
    """
    
    def __init__(self):
        # Store add-ins by name
        self._addins: Dict[str, AddinBase] = {}
        
        # Separate indexes by type for quick lookup
        self._tools: Dict[str, ToolAddin] = {}
        self._interceptors: List[InterceptorAddin] = []
        
        # Tool name -> addin mapping for execution
        self._tool_map: Dict[str, ToolAddin] = {}
    
    async def register(self, addin: AddinBase) -> bool:
        """
        Register an add-in with the registry.
        
        Args:
            addin: Add-in instance to register
            
        Returns:
            True if registration successful
        """
        if addin.name in self._addins:
            logger.warning(f"Add-in {addin.name} already registered")
            return False
        
        try:
            # Initialize the add-in
            success = await addin.initialize()
            if not success:
                logger.error(f"Failed to initialize add-in {addin.name}")
                return False
            
            # Store in main registry
            self._addins[addin.name] = addin
            
            # Index by type
            if isinstance(addin, ToolAddin):
                self._tools[addin.name] = addin
                # Map tool names to addin
                for tool_def in addin.get_tool_definitions():
                    self._tool_map[tool_def.name] = addin
                    
            # Index as interceptor if it has before_llm/after_llm hooks.
            # This covers both pure InterceptorAddin AND HYBRID addins
            # (like Skill Voyager) that have interceptor capabilities.
            if isinstance(addin, InterceptorAddin) or (
                hasattr(addin, 'before_llm') and hasattr(addin, 'after_llm')
            ):
                self._interceptors.append(addin)
                logger.info(f"Registered interceptor hooks for: {addin.name}")
            
            logger.info(f"Registered add-in: {addin.name} v{addin.version}")
            return True
            
        except Exception as e:
            logger.error(f"Error registering add-in {addin.name}: {e}")
            return False
    
    async def unregister(self, name: str) -> bool:
        """
        Unregister and cleanup an add-in.
        
        Args:
            name: Name of add-in to unregister
            
        Returns:
            True if unregistration successful
        """
        if name not in self._addins:
            return False
        
        addin = self._addins[name]
        
        try:
            # Cleanup
            await addin.cleanup()
            
            # Remove from indexes
            if isinstance(addin, ToolAddin):
                del self._tools[name]
                # Remove tool mappings
                for tool_def in addin.get_tool_definitions():
                    if tool_def.name in self._tool_map:
                        del self._tool_map[tool_def.name]
            
            # Remove from interceptors (covers InterceptorAddin + HYBRID)
            if addin in self._interceptors:
                self._interceptors.remove(addin)
            
            # Remove from main registry
            del self._addins[name]
            
            logger.info(f"Unregistered add-in: {name}")
            return True
            
        except Exception as e:
            logger.error(f"Error unregistering add-in {name}: {e}")
            return False
    
    def get_addin(self, name: str) -> Optional[AddinBase]:
        """Get an add-in by name."""
        return self._addins.get(name)
    
    def get_all_tool_definitions(self) -> List[ToolDefinition]:
        """Get all tool definitions from registered tool add-ins."""
        definitions = []
        for addin in self._tools.values():
            if addin.enabled:
                definitions.extend(addin.get_tool_definitions())
        return definitions
    
    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict
    ) -> ToolResult:
        """
        Execute a tool by name.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            
        Returns:
            ToolResult from execution
        """
        addin = self._tool_map.get(tool_name)
        
        if not addin:
            return ToolResult(
                success=False,
                error=f"Tool not found: {tool_name}"
            )
        
        if not addin.enabled:
            return ToolResult(
                success=False,
                error=f"Tool add-in is disabled: {addin.name}"
            )
        
        return await addin.execute_tool(tool_name, arguments)
    
    async def run_interceptors_before(
        self,
        messages: List[Dict[str, str]],
        context: Dict
    ) -> List[Dict[str, str]]:
        """Run all enabled before_llm interceptors with a 5s timeout each."""
        result = messages
        
        for interceptor in self._interceptors:
            if not interceptor.enabled:
                continue
            # Check DB-enabled state (addins can be toggled off in the UI)
            _uid = context.get("user_id", "")
            if not await self._is_addin_enabled_in_db(interceptor.name, _uid):
                continue
            try:
                logger.debug(f"Running before_llm: {interceptor.name}")
                result = await asyncio.wait_for(
                    interceptor.before_llm(result, context),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Interceptor {interceptor.name} before_llm timed out (5s)")
            except Exception as e:
                logger.error(f"Interceptor {interceptor.name} before_llm failed: {e}")
        
        return result
    
    async def run_interceptors_after(
        self,
        response: str,
        context: Dict
    ) -> str:
        """Run all enabled after_llm interceptors with a 5s timeout each."""
        result = response
        
        for interceptor in self._interceptors:
            if not interceptor.enabled:
                continue
            _uid = context.get("user_id", "")
            if not await self._is_addin_enabled_in_db(interceptor.name, _uid):
                continue
            try:
                logger.debug(f"Running after_llm: {interceptor.name}")
                result = await asyncio.wait_for(
                    interceptor.after_llm(result, context),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Interceptor {interceptor.name} after_llm timed out (5s)")
            except Exception as e:
                logger.error(f"Interceptor {interceptor.name} after_llm failed: {e}")
        
        return result
    
    async def _is_addin_enabled_in_db(self, addin_name: str, user_id: str = "") -> bool:
        """Check if an addin is enabled in the database for a specific user.
        
        Args:
            addin_name: The addin's manifest ID (e.g. 'skill_voyager').
            user_id: The current user's ID. If empty, checks any user.
            
        Returns:
            True if enabled, False if disabled. Falls back to False if not found
            (addins are seeded as disabled, user must opt-in).
        """
        try:
            from database import get_database
            db = get_database()
            query = {"name": addin_name}
            if user_id:
                query["userId"] = user_id
            doc = await db.addins.find_one(query)
            if doc is None:
                return False  # Not in DB = not installed for this user
            return doc.get("enabled", False)
        except Exception:
            return True  # DB error = assume enabled (graceful degradation)
    
    def list_addins(self) -> List[Dict]:
        """List all registered add-ins."""
        return [addin.get_manifest() for addin in self._addins.values()]


# Global registry instance
_registry: Optional[AddinRegistry] = None


def get_registry() -> AddinRegistry:
    """Get the global add-in registry."""
    global _registry
    if _registry is None:
        _registry = AddinRegistry()
    return _registry
