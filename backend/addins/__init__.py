"""
Add-ins/Plugin system package.
Supports three plugin types: Tools, GUI, and Interceptors.
"""

from addins.addin_interface import (
    AddinBase,
    ToolAddin,
    GUIAddin,
    InterceptorAddin,
    ToolDefinition,
    ToolResult
)
from addins.registry import AddinRegistry
from addins.loader import AddinLoader

__all__ = [
    "AddinBase",
    "ToolAddin",
    "GUIAddin", 
    "InterceptorAddin",
    "ToolDefinition",
    "ToolResult",
    "AddinRegistry",
    "AddinLoader",
]
