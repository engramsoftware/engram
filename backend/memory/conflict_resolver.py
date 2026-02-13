"""
Conflict resolver for memory consolidation.

This module compares new memory candidates against existing memories
and determines the appropriate action (ADD, UPDATE, DELETE, NONE).

Uses vector similarity + LLM reasoning to handle conflicts intelligently.
"""

import logging
import json
from typing import List, Optional
from datetime import datetime

from memory.types import Memory, UpdateAction, ConflictResolution
from llm.factory import create_provider
from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


# Conflict resolution prompt
# Compare old vs new memories and decide action
CONFLICT_RESOLUTION_PROMPT = """You are a memory conflict resolver. Compare the new memory against existing similar memories and decide what action to take.

Actions:
- ADD: The new memory is unique and doesn't conflict with existing memories
- UPDATE: The new memory updates/refines an existing memory (provide the ID and updated content)
- DELETE: The new memory contradicts an existing memory (provide the ID to delete)
- NONE: The new memory is redundant or not useful (do nothing)

New Memory:
{new_memory}

Existing Similar Memories:
{existing_memories}

Analyze the memories and decide:
1. Is the new memory unique enough to ADD?
2. Does it update/refine an existing memory? (UPDATE)
3. Does it contradict an existing memory? (DELETE the old one)
4. Is it redundant or not useful? (NONE)

Return a JSON object with your decision:
{{
  "action": "ADD|UPDATE|DELETE|NONE",
  "target_memory_id": "id of memory to update/delete (if applicable)",
  "updated_content": "new content for UPDATE action (if applicable)",
  "reason": "brief explanation for your decision"
}}

Decision (JSON only):"""


class ConflictResolver:
    """
    Resolves conflicts between new and existing memories.
    
    Uses semantic similarity to find potentially conflicting memories,
    then uses LLM reasoning to determine the appropriate action.
    
    Attributes:
        provider: LLM provider instance for reasoning
        model: Model name to use for conflict resolution
    """
    
    def __init__(
        self,
        provider_name: str = "openai",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize the conflict resolver.
        
        Args:
            provider_name: LLM provider to use (openai, anthropic, etc.)
            model: Model name to use (if None, will use a default)
            api_key: Pre-decrypted API key (from MongoDB user settings).
                     If None, falls back to .env config.
            base_url: Custom base URL for the provider.
                      If None, falls back to .env config.
        """
        self.provider_name = provider_name
        self.model = model
        self.provider = None
        
        # Initialize provider
        self._init_provider(api_key=api_key, base_url=base_url)
    
    def _init_provider(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        """Initialize the LLM provider.

        Uses the explicitly passed api_key/base_url first (from the
        caller who already decrypted the user's stored credentials).
        Falls back to .env config values only when nothing is passed.
        """
        try:
            # Fall back to .env values only if caller didn't provide credentials
            if api_key is None and base_url is None:
                if self.provider_name == "openai":
                    api_key = settings.openai_api_key
                elif self.provider_name == "anthropic":
                    api_key = settings.anthropic_api_key
                elif self.provider_name == "lmstudio":
                    base_url = settings.lmstudio_base_url or "http://host.docker.internal:1234/v1"
                elif self.provider_name == "ollama":
                    base_url = settings.ollama_base_url or "http://host.docker.internal:11434"
            
            self.provider = create_provider(
                self.provider_name,
                api_key=api_key,
                base_url=base_url
            )
            
            if self.provider:
                logger.info(f"Conflict resolver initialized with {self.provider_name}")
            else:
                logger.warning(f"Failed to initialize provider: {self.provider_name}")
                
        except Exception as e:
            logger.error(f"Error initializing conflict resolver: {e}")
            self.provider = None
    
    async def resolve_conflict(
        self,
        new_memory: Memory,
        similar_memories: List[Memory],
        similarity_threshold: float = 0.8
    ) -> ConflictResolution:
        """
        Resolve conflict between new memory and existing similar memories.
        
        Args:
            new_memory: The new memory candidate
            similar_memories: Existing memories with high similarity
            similarity_threshold: Minimum similarity to consider a conflict
            
        Returns:
            ConflictResolution with the determined action
        """
        if not self.provider:
            logger.warning("No LLM provider available, defaulting to ADD")
            return ConflictResolution(
                action=UpdateAction.ADD,
                reason="No LLM provider available for conflict resolution"
            )
        
        # If no similar memories, just ADD
        if not similar_memories:
            return ConflictResolution(
                action=UpdateAction.ADD,
                reason="No similar memories found"
            )
        
        try:
            # Format existing memories for the prompt
            existing_text = "\n\n".join([
                f"ID: {mem.id}\n"
                f"Type: {mem.memory_type}\n"
                f"Content: {mem.content}\n"
                f"Created: {mem.created_at.strftime('%Y-%m-%d')}"
                for mem in similar_memories
            ])
            
            # Format new memory
            new_text = (
                f"Type: {new_memory.memory_type}\n"
                f"Content: {new_memory.content}\n"
                f"Confidence: {new_memory.confidence}"
            )
            
            # Format prompt
            prompt = CONFLICT_RESOLUTION_PROMPT.format(
                new_memory=new_text,
                existing_memories=existing_text
            )
            
            # Call LLM for conflict resolution
            response = await self.provider.generate(
                messages=[{"role": "user", "content": prompt}],
                model=self.model or self._get_default_model(),
                temperature=0.3,  # Low temperature for consistent decisions
                max_tokens=500
            )
            
            # Parse the decision
            resolution = self._parse_resolution(response.content)
            
            logger.info(
                f"Conflict resolution: {resolution.action} - {resolution.reason}"
            )
            return resolution
            
        except Exception as e:
            logger.error(f"Conflict resolution failed: {e}")
            # Default to ADD on error
            return ConflictResolution(
                action=UpdateAction.ADD,
                reason=f"Error during resolution: {str(e)}"
            )
    
    def _parse_resolution(self, response: str) -> ConflictResolution:
        """
        Parse the LLM's JSON response into a ConflictResolution.
        
        Args:
            response: Raw response from LLM
            
        Returns:
            ConflictResolution object
        """
        try:
            # Find JSON object in response
            response = response.strip()
            
            # Find first '{' and last '}'
            start = response.find('{')
            end = response.rfind('}')
            
            if start == -1 or end == -1:
                logger.warning("No JSON object found in resolution response")
                return ConflictResolution(
                    action=UpdateAction.ADD,
                    reason="Failed to parse resolution"
                )
            
            json_str = response[start:end+1]
            data = json.loads(json_str)
            
            # Extract fields
            action_str = data.get("action", "ADD").upper()
            
            # Map to UpdateAction enum
            try:
                action = UpdateAction(action_str.lower())
            except ValueError:
                logger.warning(f"Invalid action '{action_str}', defaulting to ADD")
                action = UpdateAction.ADD
            
            return ConflictResolution(
                action=action,
                target_memory_id=data.get("target_memory_id"),
                updated_content=data.get("updated_content"),
                reason=data.get("reason", "")
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse resolution JSON: {e}")
            return ConflictResolution(
                action=UpdateAction.ADD,
                reason="JSON parse error"
            )
        except Exception as e:
            logger.error(f"Unexpected error parsing resolution: {e}")
            return ConflictResolution(
                action=UpdateAction.ADD,
                reason=f"Parse error: {str(e)}"
            )
    
    def _get_default_model(self) -> str:
        """Get default model name for the provider."""
        defaults = {
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-haiku-20240307",
            "lmstudio": "local-model",
            "ollama": "llama2"
        }
        return defaults.get(self.provider_name, "gpt-4o-mini")


# Module-level singleton for easy access
_conflict_resolver: Optional[ConflictResolver] = None


def get_conflict_resolver(provider_name: str = "openai") -> ConflictResolver:
    """
    Get or create the singleton ConflictResolver instance.
    
    Args:
        provider_name: LLM provider to use
        
    Returns:
        ConflictResolver singleton instance
    """
    global _conflict_resolver
    if _conflict_resolver is None or _conflict_resolver.provider_name != provider_name:
        _conflict_resolver = ConflictResolver(provider_name=provider_name)
    return _conflict_resolver
