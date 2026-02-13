"""
Auto Translator Add-in.
Type 3: Message Interceptor for automatic translation.

Hooks into the message pipeline to translate:
- User input to English (before LLM)
- AI output to user's language (after LLM)
"""

import logging
from typing import List, Dict, Any
import httpx

from addins.addin_interface import InterceptorAddin

logger = logging.getLogger(__name__)


class AutoTranslatorAddin(InterceptorAddin):
    """
    Automatic translation interceptor.
    Translates messages before/after LLM processing.
    """
    
    name = "auto_translator"
    version = "1.0.0"
    description = "Automatically translate messages"
    permissions = ["network", "llm.messages"]
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.source_lang = self.config.get("source_language", "auto")
        self.target_lang = self.config.get("target_language", "en")
        self.translate_input = self.config.get("translate_user_input", True)
        self.translate_output = self.config.get("translate_ai_output", False)
        self.detected_lang = None
    
    async def initialize(self) -> bool:
        """Initialize the translator add-in."""
        return True
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass
    
    async def before_llm(
        self,
        messages: List[Dict[str, str]],
        context: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """
        Translate user messages to English before sending to LLM.
        
        Args:
            messages: Conversation messages
            context: Additional context
            
        Returns:
            Messages with user content translated to English
        """
        if not self.translate_input:
            return messages
        
        translated_messages = []
        
        for msg in messages:
            if msg.get("role") == "user":
                # Translate user message to English
                original = msg.get("content", "")
                translated, detected = await self._translate(
                    original,
                    source=self.source_lang,
                    target="en"
                )
                
                # Store detected language for output translation
                if detected and detected != "en":
                    self.detected_lang = detected
                
                translated_messages.append({
                    "role": "user",
                    "content": translated
                })
            else:
                translated_messages.append(msg)
        
        return translated_messages
    
    async def after_llm(
        self,
        response: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Translate AI response back to user's language.
        
        Args:
            response: LLM response text
            context: Additional context
            
        Returns:
            Translated response
        """
        if not self.translate_output:
            return response
        
        # Translate to detected language or configured target
        target = self.detected_lang or self.target_lang
        
        if target == "en":
            return response
        
        translated, _ = await self._translate(
            response,
            source="en",
            target=target
        )
        
        return translated
    
    async def _translate(
        self,
        text: str,
        source: str = "auto",
        target: str = "en"
    ) -> tuple[str, str]:
        """
        Translate text using LibreTranslate API.
        
        Args:
            text: Text to translate
            source: Source language code
            target: Target language code
            
        Returns:
            Tuple of (translated_text, detected_language)
        """
        if not text.strip():
            return text, source
        
        try:
            # Use LibreTranslate (free, self-hostable)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://libretranslate.com/translate",
                    json={
                        "q": text,
                        "source": source,
                        "target": target,
                        "format": "text"
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return (
                        data.get("translatedText", text),
                        data.get("detectedLanguage", {}).get("language", source)
                    )
                
                # Fallback: return original text
                return text, source
                
        except Exception as e:
            logger.warning(f"Translation failed: {e}")
            return text, source


# Export the add-in class
Addin = AutoTranslatorAddin
