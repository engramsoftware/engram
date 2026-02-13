"""
Negative knowledge extractor for tracking failures.

This module extracts information about what failed, why it failed,
and any solutions found, to prevent repeated mistakes.
"""

import logging
import json
from typing import List, Optional
from datetime import datetime

from memory.types import NegativeKnowledge
from llm.factory import create_provider
from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


# Negative knowledge extraction prompt
NEGATIVE_EXTRACTION_PROMPT = """You are a failure analysis system. Analyze this conversation for things that FAILED or DIDN'T WORK.

Extract failures with:
1. what_failed: What was attempted
2. why_failed: Why it failed (be specific)
3. solution_found: What fixed it (if applicable)
4. context: Additional relevant context
5. related_entities: Technologies/tools involved (list)

Only extract actual failures/problems, not:
- Hypothetical issues
- Questions about potential problems
- General discussions

Return a JSON array. Each entry should have:
{{
  "what_failed": "Description of what was tried",
  "why_failed": "Specific reason for failure",
  "solution_found": "Solution if found, otherwise null",
  "context": "Additional context",
  "related_entities": ["entity1", "entity2"]
}}

If no failures detected, return empty array: []

Conversation:
USER: {user_query}
ASSISTANT: {assistant_response}

Negative knowledge (JSON only):"""


class NegativeKnowledgeExtractor:
    """
    Extracts negative knowledge (failures) from conversations.
    
    Uses LLM to identify:
    - What was attempted that failed
    - Why it failed
    - Solution if one was found
    - Related technologies/entities
    
    Attributes:
        provider: LLM provider instance
        model: Model name to use
    """
    
    def __init__(
        self,
        provider_name: str = "openai",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize the negative knowledge extractor.
        
        Args:
            provider_name: LLM provider to use
            model: Model name (if None, uses default)
            api_key: Pre-decrypted API key (from MongoDB user settings).
                     If None, falls back to .env config.
            base_url: Custom base URL for the provider.
                      If None, falls back to .env config.
        """
        self.provider_name = provider_name
        self.model = model
        self.provider = None
        
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
                logger.info(f"Negative knowledge extractor initialized with {self.provider_name}")
            
        except Exception as e:
            logger.error(f"Error initializing negative knowledge extractor: {e}")
            self.provider = None
    
    async def extract_negative_knowledge(
        self,
        user_query: str,
        assistant_response: str,
        user_id: str
    ) -> List[NegativeKnowledge]:
        """
        Extract negative knowledge from a conversation pair.
        
        Args:
            user_query: User's message
            assistant_response: Assistant's response
            user_id: User ID
            
        Returns:
            List of NegativeKnowledge objects
        """
        if not self.provider:
            logger.warning("No LLM provider for negative knowledge extraction")
            return []
        
        if not user_query.strip() or not assistant_response.strip():
            return []
        
        # Check for failure indicators
        if not self._has_failure_indicators(user_query + " " + assistant_response):
            logger.debug("No failure indicators detected, skipping extraction")
            return []
        
        try:
            # Format prompt
            prompt = NEGATIVE_EXTRACTION_PROMPT.format(
                user_query=user_query,
                assistant_response=assistant_response
            )
            
            # Call LLM
            response = await self.provider.generate(
                messages=[{"role": "user", "content": prompt}],
                model=self.model or self._get_default_model(),
                temperature=0.3,
                max_tokens=1000
            )
            
            # Parse response
            failures_data = self._parse_response(response.content)
            
            # Convert to NegativeKnowledge objects
            failures = []
            for data in failures_data:
                try:
                    failure = NegativeKnowledge(
                        what_failed=data["what_failed"],
                        why_failed=data["why_failed"],
                        solution_found=data.get("solution_found"),
                        context=data.get("context", ""),
                        user_id=user_id,
                        created_at=datetime.utcnow(),
                        related_entities=data.get("related_entities", [])
                    )
                    failures.append(failure)
                except (KeyError, ValueError) as e:
                    logger.warning(f"Failed to parse negative knowledge: {data} - {e}")
                    continue
            
            logger.info(f"Extracted {len(failures)} negative knowledge entries")
            return failures
            
        except Exception as e:
            logger.error(f"Negative knowledge extraction failed: {e}")
            return []
    
    def _has_failure_indicators(self, text: str) -> bool:
        """
        Quick check for failure-related keywords.
        
        Args:
            text: Text to check
            
        Returns:
            True if failure indicators found
        """
        failure_keywords = [
            "error", "failed", "didn't work", "doesn't work", "not working",
            "issue", "problem", "bug", "broken", "crash", "exception",
            "tried", "attempted", "won't", "can't", "couldn't", "unable"
        ]
        
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in failure_keywords)
    
    def _parse_response(self, response: str) -> List[dict]:
        """
        Parse LLM JSON response.
        
        Args:
            response: Raw LLM response
            
        Returns:
            List of failure dictionaries
        """
        try:
            response = response.strip()
            
            # Find JSON array
            start = response.find('[')
            end = response.rfind(']')
            
            if start == -1 or end == -1:
                return []
            
            json_str = response[start:end+1]
            failures = json.loads(json_str)
            
            if not isinstance(failures, list):
                return []
            
            return failures
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse negative knowledge JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error parsing response: {e}")
            return []
    
    def _get_default_model(self) -> str:
        """Get default model for provider."""
        defaults = {
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-haiku-20240307",
            "lmstudio": "local-model",
            "ollama": "llama2"
        }
        return defaults.get(self.provider_name, "gpt-4o-mini")


# Singleton instance
_negative_extractor: Optional[NegativeKnowledgeExtractor] = None


def get_negative_extractor(provider_name: str = "openai") -> NegativeKnowledgeExtractor:
    """
    Get or create singleton NegativeKnowledgeExtractor.
    
    Args:
        provider_name: LLM provider to use
        
    Returns:
        NegativeKnowledgeExtractor instance
    """
    global _negative_extractor
    if _negative_extractor is None or _negative_extractor.provider_name != provider_name:
        _negative_extractor = NegativeKnowledgeExtractor(provider_name=provider_name)
    return _negative_extractor
