"""
Add-in interface definitions.
Base classes for all three plugin types.

Plugin Types:
1. ToolAddin - LLM-callable functions (web_search, calculator)
2. GUIAddin - React UI components (image generator panel)
3. InterceptorAddin - Message pipeline hooks (auto-translator)
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from enum import Enum


class AddinType(str, Enum):
    """Types of add-ins supported."""
    TOOL = "tool"
    GUI = "gui"
    INTERCEPTOR = "interceptor"
    HYBRID = "hybrid"


class ToolDefinition(BaseModel):
    """
    Definition of a tool that can be called by the LLM.
    Follows OpenAI function calling format.
    """
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema for parameters
    
    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


class ToolResult(BaseModel):
    """Result from executing a tool."""
    success: bool
    result: Any = None
    error: Optional[str] = None


class AddinBase(ABC):
    """
    Base class for all add-ins.
    All plugins must implement these core methods.
    """
    
    # Metadata - override in subclass
    name: str = "base_addin"
    version: str = "1.0.0"
    description: str = ""
    addin_type: AddinType = AddinType.TOOL
    permissions: List[str] = []
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize add-in with configuration.
        
        Args:
            config: User-provided configuration settings
        """
        self.config = config or {}
        self.enabled = True
    
    @abstractmethod
    async def initialize(self) -> bool:
        """
        Initialize the add-in.
        Called when the add-in is first loaded.
        
        Returns:
            True if initialization successful
        """
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """
        Cleanup resources when add-in is unloaded.
        """
        pass
    
    def get_manifest(self) -> Dict[str, Any]:
        """Get add-in manifest for registration."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "type": self.addin_type.value,
            "permissions": self.permissions
        }

    def get_settings_schema(self) -> Dict[str, Any]:
        """
        Return the settings schema for dynamic frontend rendering.

        Override this in subclasses to declare settings that appear
        in the Settings > Add-ins panel. The frontend reads the schema
        and renders controls (toggles, selects, LLM provider cards, etc.)
        without any hardcoded addin-specific UI.

        Returns:
            Schema dict with addin_id, addin_name, and sections list.
            Each section has fields with type, label, default, etc.
        """
        return {
            "addin_id": self.name,
            "addin_name": self.name,
            "sections": [],
        }


class ToolAddin(AddinBase):
    """
    Type 1: Backend Tools (LLM-callable functions).
    
    These plugins register as tools that the LLM can call
    via function calling when needed.
    
    Example: web_search, calculator, code_executor
    """
    
    addin_type = AddinType.TOOL
    
    @abstractmethod
    def get_tool_definitions(self) -> List[ToolDefinition]:
        """
        Get list of tools this add-in provides.
        
        Returns:
            List of ToolDefinition objects
        """
        pass
    
    @abstractmethod
    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> ToolResult:
        """
        Execute a tool with given arguments.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments from LLM
            
        Returns:
            ToolResult with execution outcome
        """
        pass


class GUIAddin(AddinBase):
    """
    Type 2: GUI Extensions (React components).
    
    These plugins add UI elements to the interface.
    User-triggered via buttons/menus.
    
    Example: image_generator panel, file_uploader
    """
    
    addin_type = AddinType.GUI
    
    @abstractmethod
    def get_mount_points(self) -> List[str]:
        """
        Get UI mount points where this add-in can be rendered.
        
        Valid mount points:
        - "sidebar" - Sidebar panel
        - "toolbar" - Chat toolbar
        - "message_actions" - Actions on messages
        - "settings" - Settings panel
        
        Returns:
            List of mount point identifiers
        """
        pass
    
    @abstractmethod
    def get_frontend_component(self) -> str:
        """
        Get the frontend component path/name.
        
        Returns:
            Path to the React component file
        """
        pass
    
    async def handle_action(
        self,
        action: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle an action from the frontend component.
        
        Args:
            action: Action identifier
            payload: Action payload data
            
        Returns:
            Response data for the frontend
        """
        return {"status": "ok"}


class InterceptorAddin(AddinBase):
    """
    Type 3: Message Interceptors.
    
    These plugins hook into the message pipeline
    and run before/after LLM processing.
    
    Example: auto_translator, context_injector, content_filter
    """
    
    addin_type = AddinType.INTERCEPTOR
    
    @abstractmethod
    async def before_llm(
        self,
        messages: List[Dict[str, str]],
        context: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """
        Process messages before sending to LLM.
        
        Args:
            messages: Conversation messages
            context: Additional context (user_id, conversation_id, etc.)
            
        Returns:
            Modified messages list
        """
        pass
    
    @abstractmethod
    async def after_llm(
        self,
        response: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Process LLM response before returning to user.
        
        Args:
            response: LLM response text
            context: Additional context
            
        Returns:
            Modified response text
        """
        pass
