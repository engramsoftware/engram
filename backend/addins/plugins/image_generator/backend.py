"""
Image Generator Add-in.
Type 2: GUI Extension for DALL-E image generation.

Provides a UI panel for generating images from text prompts.
"""

import logging
from typing import List, Dict, Any
import httpx

from addins.addin_interface import GUIAddin

logger = logging.getLogger(__name__)


class ImageGeneratorAddin(GUIAddin):
    """
    Image generation GUI add-in using DALL-E.
    """
    
    name = "image_generator"
    version = "1.0.0"
    description = "Generate images using DALL-E"
    permissions = ["network", "storage"]
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.model = self.config.get("model", "dall-e-3")
        self.size = self.config.get("size", "1024x1024")
        self.quality = self.config.get("quality", "standard")
        self.api_key = self.config.get("openai_api_key", "")
    
    async def initialize(self) -> bool:
        """Initialize the image generator add-in."""
        if not self.api_key:
            logger.warning("OpenAI API key not configured for image generation")
        return True
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass
    
    def get_mount_points(self) -> List[str]:
        """Get UI mount points."""
        return ["toolbar", "sidebar"]
    
    def get_frontend_component(self) -> str:
        """Get frontend component path."""
        return "ImageGenerator.tsx"
    
    async def handle_action(
        self,
        action: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle actions from the frontend component.
        
        Actions:
        - generate: Generate an image from prompt
        - get_history: Get generation history
        """
        if action == "generate":
            return await self._generate_image(payload)
        elif action == "get_history":
            return {"history": []}  # TODO: Implement history
        
        return {"error": f"Unknown action: {action}"}
    
    async def _generate_image(
        self,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate an image using DALL-E.
        
        Args:
            payload: Contains 'prompt', optional 'size', 'quality'
            
        Returns:
            Dict with 'url' of generated image or 'error'
        """
        prompt = payload.get("prompt", "")
        size = payload.get("size", self.size)
        quality = payload.get("quality", self.quality)
        
        if not prompt:
            return {"error": "Prompt is required"}
        
        if not self.api_key:
            return {"error": "OpenAI API key not configured"}
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "n": 1,
                        "size": size,
                        "quality": quality
                    }
                )
                response.raise_for_status()
                data = response.json()
            
            image_url = data["data"][0]["url"]
            revised_prompt = data["data"][0].get("revised_prompt", prompt)
            
            return {
                "success": True,
                "url": image_url,
                "prompt": prompt,
                "revised_prompt": revised_prompt
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"DALL-E API error: {e.response.text}")
            return {"error": f"API error: {e.response.status_code}"}
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return {"error": str(e)}


# Export the add-in class
Addin = ImageGeneratorAddin
