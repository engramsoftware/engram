"""
Memory extractor for autonomous memory formation.

This module analyzes conversations and extracts salient facts, preferences,
decisions, and experiences using the configured LLM provider.

Uses LLM-based extraction with customizable prompts.
"""

import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime

from memory.types import Memory, MemoryType
from llm.factory import create_provider
from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


# Extraction prompt for the LLM
# Analyze conversation pairs to extract salient information
EXTRACTION_PROMPT = """You are a memory extraction system. Analyze the conversation and extract important information worth remembering.

Extract the following types of memories:
1. FACTS: Objective information (e.g., "User works at Google", "Project uses PostgreSQL")
2. PREFERENCES: User likes/dislikes (e.g., "Prefers Python over Java", "Likes verbose comments")
3. DECISIONS: Choices made (e.g., "Decided to use Docker for deployment")
4. EXPERIENCES: Past events (e.g., "Had issues with Redis caching last month")
5. NEGATIVE: Things that didn't work (e.g., "Tried async processing, caused race conditions")

Guidelines:
- Only extract memories that are useful for future conversations
- Be specific and include context
- Each memory should be a single, clear statement
- Skip casual chatter, greetings, or temporary topics
- Assign a confidence score (0.0-1.0) based on how certain you are

IMPORTANT: You MUST respond with ONLY a valid JSON array. No explanations, no markdown, just the JSON.

Format:
[
  {{"content": "The memory statement", "memory_type": "fact", "confidence": 0.9}},
  {{"content": "Another memory", "memory_type": "preference", "confidence": 0.8}}
]

Valid memory_type values: fact, preference, decision, experience, negative

If no memories are worth extracting, return exactly: []

Conversation:
USER: {user_query}
ASSISTANT: {assistant_response}

JSON array:"""


class MemoryExtractor:
    """
    Extracts memories from conversation pairs.
    
    Uses the configured LLM provider to analyze query-response pairs
    and extract salient information worth remembering.
    
    Attributes:
        provider: LLM provider instance for extraction
        model: Model name to use for extraction
    """
    
    def __init__(
        self,
        provider_name: str = "openai",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize the memory extractor.
        
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
                logger.info(f"Memory extractor initialized with {self.provider_name}")
            else:
                logger.warning(f"Failed to initialize provider: {self.provider_name}")
                
        except Exception as e:
            logger.error(f"Error initializing memory extractor: {e}")
            self.provider = None
    
    async def extract_memories(
        self,
        user_query: str,
        assistant_response: str,
        user_id: str,
        conversation_id: str
    ) -> List[Memory]:
        """
        Extract memories from a conversation pair.
        
        Args:
            user_query: The user's query/message
            assistant_response: The assistant's response
            user_id: User ID these memories belong to
            conversation_id: Conversation ID for source tracking
            
        Returns:
            List of Memory objects extracted from the conversation
        """
        if not self.provider:
            logger.warning("No LLM provider available for memory extraction")
            return []
        
        if not user_query.strip() or not assistant_response.strip():
            logger.debug("Empty query or response, skipping extraction")
            return []
        
        try:
            # Format the extraction prompt
            prompt = EXTRACTION_PROMPT.format(
                user_query=user_query,
                assistant_response=assistant_response
            )
            
            # Call LLM to extract memories
            # Use low temperature for more consistent extraction
            response = await self.provider.generate(
                messages=[{"role": "user", "content": prompt}],
                model=self.model or self._get_default_model(),
                temperature=0.3,  # Low temperature for consistent extraction
                max_tokens=1000
            )
            
            # Parse JSON response
            memories_data = self._parse_extraction_response(response.content)
            
            # Convert to Memory objects
            memories = []
            for mem_data in memories_data:
                try:
                    memory = Memory(
                        id="",  # Will be set by memory store
                        content=mem_data["content"],
                        memory_type=MemoryType(mem_data["memory_type"]),
                        user_id=user_id,
                        confidence=float(mem_data.get("confidence", 0.8)),
                        source_conversation_id=conversation_id,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    memories.append(memory)
                except (KeyError, ValueError) as e:
                    logger.warning(f"Failed to parse memory: {mem_data} - {e}")
                    continue
            
            logger.info(f"Extracted {len(memories)} memories from conversation")
            return memories
            
        except Exception as e:
            logger.error(f"Memory extraction failed: {e}")
            return []
    
    def _parse_extraction_response(self, response: str) -> List[Dict[str, Any]]:
        """
        Parse the LLM's JSON response into memory data.

        Handles various formats and gracefully falls back to empty list.

        Args:
            response: Raw response from LLM

        Returns:
            List of memory dictionaries
        """
        try:
            # Try to find JSON array in response
            # LLMs sometimes add explanations before/after the JSON
            response = response.strip()

            # Find first '[' and last ']'
            start = response.find('[')
            end = response.rfind(']')

            if start != -1 and end != -1 and end > start:
                # Found an array
                json_str = response[start:end+1]
                memories = json.loads(json_str)

                if isinstance(memories, list):
                    return memories

            # Try to find a single object { } (LLM sometimes returns one object instead of array)
            obj_start = response.find('{')
            obj_end = response.rfind('}')

            if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
                json_str = response[obj_start:obj_end+1]
                memory = json.loads(json_str)

                if isinstance(memory, dict) and "content" in memory:
                    logger.debug("Parsed single memory object, wrapping in list")
                    return [memory]

            # Try parsing entire response as JSON
            try:
                parsed = json.loads(response)
                if isinstance(parsed, list):
                    return parsed
                elif isinstance(parsed, dict) and "content" in parsed:
                    return [parsed]
            except json.JSONDecodeError:
                pass

            logger.debug("No valid JSON found in extraction response")
            return []

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse extraction JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error parsing extraction: {e}")
            return []
    
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
_memory_extractor: Optional[MemoryExtractor] = None


def get_memory_extractor(provider_name: str = "openai") -> MemoryExtractor:
    """
    Get or create the singleton MemoryExtractor instance.
    
    Args:
        provider_name: LLM provider to use
        
    Returns:
        MemoryExtractor singleton instance
    """
    global _memory_extractor
    if _memory_extractor is None or _memory_extractor.provider_name != provider_name:
        _memory_extractor = MemoryExtractor(provider_name=provider_name)
    return _memory_extractor
