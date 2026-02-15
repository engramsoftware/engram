"""
LLM-Powered Skill Generator - Auto-create skills from successful outcomes.

Uses the LLM to:
1. Analyze successful problem/solution pairs
2. Extract generalizable patterns
3. Generate trigger patterns (regex)
4. Create reusable skills automatically
"""

import logging
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SkillCandidate:
    """A candidate skill to be created."""
    name: str
    description: str
    triggers: List[str]
    solution_text: str
    code_template: Optional[str]
    technologies: List[str]
    confidence: float


SKILL_GENERATION_PROMPT = """Analyze this successful problem/solution pair and create a reusable skill.

PROBLEM:
{problem}

SOLUTION:
{solution}

CODE (if any):
{code}

TECHNOLOGIES: {technologies}

Generate a skill in this exact JSON format:
{{
    "name": "Short descriptive name (3-5 words)",
    "description": "What problem this skill solves (1 sentence)",
    "triggers": ["regex pattern 1", "regex pattern 2"],
    "solution_text": "Step-by-step solution explanation",
    "code_template": "Generic code template if applicable, or null",
    "technologies": ["tech1", "tech2"],
    "generalizability": 0.0-1.0
}}

RULES for triggers:
- Use regex patterns that would match similar problems
- Include error message patterns, keywords, and variations
- Make them specific enough to avoid false positives
- Examples: "TypeError.*NoneType", "CORS|cross.?origin", "import.*error"

RULES for solution_text:
- Make it generic, not specific to this exact case
- Include multiple approaches if applicable
- Explain WHY the solution works

RULES for code_template:
- Use placeholders like <variable_name>, <file_path>
- Include comments explaining each part
- Return null if no code is applicable

Return ONLY valid JSON, no other text."""


class SkillGenerator:
    """Generates skills from successful outcomes using LLM."""
    
    def __init__(self):
        self._llm_provider = None
    
    @staticmethod
    async def _resolve_user_llm_config() -> Optional[Dict[str, Any]]:
        """Fetch the user's LLM provider config from the database (async).

        Reads the first llm_settings document, finds the default (or any
        enabled) provider, decrypts the API key, and returns a dict with
        keys: provider_name, api_key, base_url, model.

        The API keys stored in the DB were encrypted by the FastAPI server
        which runs with CWD=backend/.  The MCP server may run from the
        project root with a *different* .env, so we derive the Fernet key
        from the backend/.env encryption key explicitly to ensure we can
        always decrypt.

        Returns:
            Config dict or None if DB is unreachable or no provider
            is configured.
        """
        try:
            import hashlib
            import base64
            from pathlib import Path
            from cryptography.fernet import Fernet
            from config import get_settings
            from database import get_database

            settings = get_settings()
            db = get_database()
            doc = await db.llm_settings.find_one({})

            if not doc:
                return None

            providers = doc.get("providers", {})
            default_name = doc.get("defaultProvider")

            # Resolve provider: default first, then any enabled
            provider_name = None
            provider_config = None
            if default_name and default_name in providers:
                cfg = providers[default_name]
                if cfg.get("enabled"):
                    provider_name = default_name
                    provider_config = cfg

            if not provider_config:
                for name, cfg in providers.items():
                    if cfg.get("enabled"):
                        provider_name = name
                        provider_config = cfg
                        break

            if not provider_config or not provider_name:
                return None

            # Decrypt API key — use the backend/.env encryption key
            # because that's what the FastAPI server used to encrypt it.
            api_key = None
            encrypted = provider_config.get("apiKey")
            if encrypted:
                # Read encryption key from backend/.env directly
                backend_env = Path(__file__).resolve().parent.parent / ".env"
                enc_key = settings.encryption_key  # default from current .env
                if backend_env.exists():
                    for line in backend_env.read_text().splitlines():
                        line = line.strip()
                        if line.startswith("ENCRYPTION_KEY="):
                            enc_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break

                # Derive Fernet key (same logic as utils/encryption.py)
                key_bytes = hashlib.sha256(enc_key.encode()).digest()
                fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
                api_key = fernet.decrypt(encrypted.encode()).decode()

            # Base URL only for local providers
            base_url = None
            if provider_name in ("lmstudio", "ollama"):
                base_url = provider_config.get("baseUrl")

            model = provider_config.get("defaultModel")

            return {
                "provider_name": provider_name,
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            }
        except Exception as e:
            logger.debug(f"Could not resolve user LLM config from database: {e}")
            return None

    async def _get_llm(self):
        """Get LLM provider lazily.

        Resolution order:
        1. User's configured provider from database (same key the chat uses)
        2. Local providers (LM Studio / Ollama — free, no API key)
        3. .env fallback keys (only if they look valid)

        Returns:
            LLM provider instance or None if none available.
        """
        if self._llm_provider is None:
            try:
                from llm.factory import create_provider
                from config import get_settings
                settings = get_settings()

                # 1. Try the user's configured provider from database
                user_cfg = await self._resolve_user_llm_config()
                if user_cfg and user_cfg.get("provider_name"):
                    try:
                        self._llm_provider = create_provider(
                            user_cfg["provider_name"],
                            api_key=user_cfg.get("api_key"),
                            base_url=user_cfg.get("base_url"),
                        )
                        # Store the model name for generate calls
                        self._user_model = user_cfg.get("model")
                        logger.info(
                            f"Skill generator using user's {user_cfg['provider_name']} "
                            f"provider (model: {self._user_model})"
                        )
                        return self._llm_provider
                    except Exception as e:
                        logger.debug(f"User provider init failed: {e}")

                # 2. Try local providers (free, no API key needed)
                if getattr(settings, "lmstudio_base_url", None):
                    try:
                        self._llm_provider = create_provider(
                            "lmstudio",
                            base_url=settings.lmstudio_base_url,
                        )
                        return self._llm_provider
                    except Exception:
                        pass

                if getattr(settings, "ollama_base_url", None):
                    try:
                        self._llm_provider = create_provider(
                            "ollama",
                            base_url=settings.ollama_base_url,
                        )
                        return self._llm_provider
                    except Exception:
                        pass

                # 3. .env fallback keys — validate before using
                def _key_looks_valid(key: str) -> bool:
                    """Check if an API key looks like a real credential."""
                    if not key or len(key) < 20:
                        return False
                    placeholders = {"your-", "sk-xxx", "placeholder", "changeme", "test"}
                    return not any(p in key.lower() for p in placeholders)

                if _key_looks_valid(getattr(settings, "anthropic_api_key", "")):
                    self._llm_provider = create_provider(
                        "anthropic",
                        api_key=settings.anthropic_api_key,
                        base_url=settings.anthropic_base_url,
                    )
                elif _key_looks_valid(getattr(settings, "openai_api_key", "")):
                    self._llm_provider = create_provider(
                        "openai",
                        api_key=settings.openai_api_key,
                    )
                else:
                    logger.info(
                        "No valid LLM provider for skill generation "
                        "(no user config, no local server, no valid .env keys)"
                    )
            except Exception as e:
                logger.warning(f"Could not initialize LLM for skill generation: {e}")
        return self._llm_provider

    async def generate_skill_from_outcome(
        self,
        problem: str,
        solution: str,
        code: Optional[str] = None,
        technologies: Optional[List[str]] = None
    ) -> Optional[SkillCandidate]:
        """
        Generate a skill candidate from a successful outcome.
        
        Returns None if generation fails or skill isn't generalizable enough.
        """
        llm = await self._get_llm()
        if not llm:
            logger.warning("No LLM available for skill generation")
            return self._generate_skill_heuristically(problem, solution, code, technologies)
        
        prompt = SKILL_GENERATION_PROMPT.format(
            problem=problem,
            solution=solution,
            code=code or "None",
            technologies=", ".join(technologies or [])
        )
        
        try:
            # Use the user's configured model, fall back to provider-specific defaults
            model_name = getattr(self, "_user_model", None)
            if not model_name:
                _FALLBACK_MODELS = {
                    "AnthropicProvider": "claude-sonnet-4-20250514",
                    "OpenAIProvider": "gpt-4o",
                    "LMStudioProvider": "default",
                    "OllamaProvider": "llama3",

                }
                model_name = _FALLBACK_MODELS.get(type(llm).__name__, "claude-sonnet-4-20250514")
            response = await llm.generate(
                messages=[{"role": "user", "content": prompt}],
                model=model_name,
                max_tokens=1000,
                temperature=0.3
            )
            
            # Parse JSON from response
            import json
            content = response.content
            
            # Extract JSON if wrapped in markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json.loads(content.strip())
            
            # Check generalizability threshold
            if data.get("generalizability", 0) < 0.5:
                logger.info("Skill not generalizable enough, skipping")
                return None
            
            return SkillCandidate(
                name=data["name"],
                description=data["description"],
                triggers=data["triggers"],
                solution_text=data["solution_text"],
                code_template=data.get("code_template"),
                technologies=data.get("technologies", technologies or []),
                confidence=data.get("generalizability", 0.7)
            )
            
        except Exception as e:
            logger.error(f"LLM skill generation failed: {e}")
            return self._generate_skill_heuristically(problem, solution, code, technologies)
    
    def _generate_skill_heuristically(
        self,
        problem: str,
        solution: str,
        code: Optional[str] = None,
        technologies: Optional[List[str]] = None
    ) -> Optional[SkillCandidate]:
        """Fallback: Generate skill using heuristics when LLM unavailable."""
        
        # Extract potential error patterns
        triggers = []
        
        # Look for common error patterns
        error_patterns = [
            r"(\w+Error)",  # TypeError, ValueError, etc.
            r"(\w+Exception)",
            r"(cannot|can't|unable to)\s+\w+",
            r"(failed to|error:|warning:)",
        ]
        
        for pattern in error_patterns:
            matches = re.findall(pattern, problem, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                if len(match) > 3:
                    triggers.append(re.escape(match))
        
        # Extract key words
        words = re.findall(r'\b([A-Z][a-z]+[A-Z]\w*|\w{5,})\b', problem)
        for word in words[:3]:
            if word.lower() not in ['error', 'failed', 'cannot']:
                triggers.append(word)
        
        if not triggers:
            return None
        
        # Generate name from first few significant words
        name_words = [w for w in problem.split()[:6] if len(w) > 3]
        name = " ".join(name_words[:4]) + " Fix"
        
        return SkillCandidate(
            name=name[:50],
            description=f"Fix for: {problem[:100]}",
            triggers=triggers[:5],
            solution_text=solution,
            code_template=code,
            technologies=technologies or [],
            confidence=0.5  # Lower confidence for heuristic generation
        )
    
    async def should_generate_skill(
        self,
        problem: str,
        solution: str,
        similar_outcomes_count: int
    ) -> bool:
        """
        Determine if we should generate a skill from this outcome.
        
        Criteria:
        - Problem/solution is substantial enough
        - Similar outcomes have succeeded multiple times
        - No existing skill closely matches
        """
        # Minimum content length
        if len(problem) < 20 or len(solution) < 30:
            return False
        
        # Need at least 2 similar successful outcomes
        if similar_outcomes_count < 2:
            return False
        
        # Check for existing similar skill
        try:
            from skills.skill_system import get_skill_store
            store = get_skill_store()
            matches = await store.find_matching_skills(problem, min_score=0.7)
            if matches:
                # Already have a good skill for this
                return False
        except:
            pass
        
        return True


# Singleton
_skill_generator: Optional[SkillGenerator] = None


def get_skill_generator() -> SkillGenerator:
    """Get or create skill generator singleton."""
    global _skill_generator
    if _skill_generator is None:
        _skill_generator = SkillGenerator()
    return _skill_generator
