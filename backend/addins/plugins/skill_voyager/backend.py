"""
Skill Voyager — Hybrid Addin (Interceptor + GUI).

This is the main entry point loaded by the AddinLoader.
It wires together:
- SkillStore (persistent skill library)
- QueryClassifier (categorize incoming queries)
- ResponseEvaluator (score responses, update confidence)
- SkillExtractor (learn new skills from successful conversations)
- CurriculumEngine (propose skills to fill gaps)

Pipeline hooks:
- before_llm: Classify query → find matching skill → inject strategy into system prompt
- after_llm: Evaluate response → update skill confidence → maybe extract new skill

GUI endpoints (via handle_action):
- get_dashboard: Skill library stats + recent evaluations
- get_skills: Full skill list with filters
- get_skill_tree: Composition tree for a skill
- run_curriculum: Manually trigger curriculum proposals
- add_skill: Manually add a skill
- delete_skill: Remove a skill
"""

import asyncio
import logging
import time
from typing import List, Dict, Any, Optional

from addins.addin_interface import (
    AddinBase, AddinType, GUIAddin, InterceptorAddin,
    ToolDefinition, ToolResult,
)

from .skill_store import SkillStore, Skill
from .query_classifier import QueryClassifier, QueryClassification
from .evaluator import ResponseEvaluator
from .skill_extractor import SkillExtractor
from .curriculum import CurriculumEngine
from .self_reflection import SelfReflectionEngine
from .retrieval_learner import RetrievalLearner, RetrievalOutcome
from .correction_learner import CorrectionLearner, CorrectionEvent

logger = logging.getLogger(__name__)


class Addin(AddinBase):
    """
    Skill Voyager — Voyager-style autonomous skill learning.

    Hybrid addin that acts as both:
    1. InterceptorAddin — hooks into message pipeline (before_llm / after_llm)
    2. GUIAddin — provides a dashboard panel in the sidebar

    The addin observes every conversation, builds a skill library of
    verified response strategies, composes simple skills into complex ones,
    and uses local LLM (or heuristics) for self-evaluation.
    """

    name = "skill_voyager"
    version = "1.0.0"
    description = "Voyager-style autonomous skill learning"
    addin_type = AddinType.HYBRID
    permissions = ["read_messages", "write_context", "local_llm"]

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)

        # Core components — initialized in initialize()
        self.skill_store: Optional[SkillStore] = None
        self.classifier: Optional[QueryClassifier] = None
        self.evaluator: Optional[ResponseEvaluator] = None
        self.extractor: Optional[SkillExtractor] = None
        self.curriculum: Optional[CurriculumEngine] = None
        self.reflection: Optional[SelfReflectionEngine] = None
        self.retrieval_learner: Optional[RetrievalLearner] = None
        self.correction_learner: Optional[CorrectionLearner] = None

        # Runtime state
        self._last_classification: Optional[QueryClassification] = None
        self._last_skill_applied: Optional[Skill] = None
        self._last_query: str = ""
        self._message_count: int = 0

        # Config
        settings = (config or {}).get("settings", {})
        self.auto_learn = settings.get("auto_learn", True)
        self.curriculum_enabled = settings.get("curriculum_enabled", True)
        self.min_confidence = settings.get("min_confidence_to_apply", 0.45)
        self.eval_every_n = settings.get("eval_after_every_n", 1)

    async def initialize(self) -> bool:
        """Initialize all sub-components."""
        try:
            self.skill_store = SkillStore()
            self.classifier = QueryClassifier()
            self.evaluator = ResponseEvaluator(self.skill_store)
            self.extractor = SkillExtractor(self.skill_store, self.classifier)
            self.curriculum = CurriculumEngine(self.skill_store, self.classifier)
            self.reflection = SelfReflectionEngine(self.skill_store)
            self.retrieval_learner = RetrievalLearner()
            self.correction_learner = CorrectionLearner()

            # Try to detect local LLM (LM Studio default)
            await self._detect_local_llm()

            # Bootstrap: seed basic skills if library is empty
            stats = self.skill_store.get_skill_stats()
            if stats["total_skills"] == 0:
                seeded = await self.curriculum.auto_seed(max_seeds=8)
                logger.info(f"Bootstrapped skill library with {seeded} seed skills")

            logger.info(
                f"Skill Voyager initialized — "
                f"{stats['total_skills']} skills in library, "
                f"auto_learn={self.auto_learn}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Skill Voyager: {e}")
            return False

    async def cleanup(self) -> None:
        """Cleanup resources."""
        logger.info("Skill Voyager shutting down")

    # ── Interceptor: before_llm ───────────────────────────────

    async def before_llm(
        self,
        messages: List[Dict[str, str]],
        context: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """
        Pre-LLM hook: classify query and inject matching skill strategy.

        Steps:
        1. Extract the latest user message
        2. Classify it (factual/research/creative/technical/conversational)
        3. Search skill library for a matching verified strategy
        4. If found: inject the strategy as a system message
        5. Track which skill was applied for post-evaluation

        Args:
            messages: The conversation messages about to be sent to LLM.
            context: Pipeline context (user_id, conversation_id, etc.)

        Returns:
            Modified messages list (with skill injection if applicable).
        """
        if not self.enabled or not self.classifier or not self.skill_store:
            return messages

        # Find the latest user message
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break

        if not user_msg:
            return messages

        self._last_query = user_msg
        self._last_skill_applied = None

        # Classify the query
        history = [m for m in messages if m.get("role") in ("user", "assistant")]
        self._last_classification = self.classifier.classify(user_msg, history[-6:])

        logger.debug(
            f"Query classified: {self._last_classification.primary_type}/"
            f"{self._last_classification.sub_type} "
            f"(confidence={self._last_classification.confidence})"
        )

        # Search for matching skills
        matching_skills = self.skill_store.find_matching_skills(
            user_msg, min_confidence=self.min_confidence, limit=2
        )

        if matching_skills:
            best_skill = matching_skills[0]
            self._last_skill_applied = best_skill

            # Inject skill strategy as a system message
            skill_injection = (
                f"[SKILL: {best_skill.name}] "
                f"Apply this response strategy: {best_skill.strategy}"
            )

            # Insert as a system message near the end (before the last user message)
            # This ensures it's in the LLM's recent context window
            injection_msg = {"role": "system", "content": skill_injection}

            # Find the position just before the last user message
            insert_idx = len(messages) - 1
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    insert_idx = i
                    break

            messages = messages[:insert_idx] + [injection_msg] + messages[insert_idx:]

            logger.info(
                f"Applied skill '{best_skill.name}' "
                f"(confidence={best_skill.confidence:.2f}) "
                f"to {self._last_classification.primary_type}/{self._last_classification.sub_type} query"
            )

        return messages

    # ── Interceptor: after_llm ────────────────────────────────

    async def after_llm(
        self,
        response: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Post-LLM hook: evaluate response and maybe learn a new skill.

        Steps:
        1. If a skill was applied → evaluate the response quality
        2. Update skill confidence based on evaluation
        3. If NO skill was applied → try to extract a new skill candidate
        4. Periodically run curriculum engine

        Args:
            response: The LLM's response text.
            context: Pipeline context.

        Returns:
            Unmodified response (evaluation is a side-effect).
        """
        if not self.enabled or not self.auto_learn:
            return response

        self._message_count += 1
        message_id = context.get("message_id", "")
        conversation_id = context.get("conversation_id", "")

        # Run evaluation and extraction in the background
        # Don't block the response to the user
        asyncio.create_task(
            self._background_learn(
                response, message_id, conversation_id
            )
        )

        # Periodically run curriculum engine
        if self.curriculum_enabled and self.curriculum and self.curriculum.should_run():
            asyncio.create_task(self._background_curriculum())

        return response

    async def _background_learn(
        self,
        response: str,
        message_id: str,
        conversation_id: str,
    ) -> None:
        """Background task: evaluate, reflect on failures, evolve, or extract."""
        try:
            # Track exploration coverage
            if self._last_classification and self.reflection:
                self.reflection.record_query_type(
                    self._last_classification.primary_type,
                    self._last_classification.sub_type,
                    success=self._last_skill_applied is not None,
                )

            if self._last_skill_applied and self.evaluator:
                # A skill was applied — evaluate how it went
                if self._message_count % self.eval_every_n == 0:
                    evaluation = await self.evaluator.evaluate(
                        query=self._last_query,
                        response=response,
                        skill=self._last_skill_applied,
                        message_id=message_id,
                        conversation_id=conversation_id,
                    )

                    # Self-reflection: if evaluation failed, reflect and evolve
                    if evaluation.score < 3.0 and self.reflection:
                        reflection = await self.reflection.reflect_on_failure(
                            skill=self._last_skill_applied,
                            evaluation=evaluation,
                            query=self._last_query,
                            response=response,
                        )
                        if reflection and reflection.confidence_in_fix >= 0.4:
                            self.reflection.evolve_skill(
                                self._last_skill_applied, reflection
                            )

            elif self._last_classification and self.extractor:
                # No skill applied — try to learn from this exchange
                await self.extractor.maybe_extract(
                    query=self._last_query,
                    response=response,
                    classification=self._last_classification,
                    skill_was_applied=False,
                    message_id=message_id,
                    conversation_id=conversation_id,
                )

            # Record retrieval learning outcomes if we have an evaluation
            if self._last_classification and self.retrieval_learner:
                query_type = f"{self._last_classification.primary_type}/{self._last_classification.sub_type}"
                # Estimate response quality from evaluation or heuristic
                score = 3.0  # Default neutral score
                if self._last_skill_applied and self.evaluator:
                    try:
                        score = evaluation.score if 'evaluation' in dir() else 3.0
                    except NameError:
                        score = 3.0

                # Record outcomes for common retrieval sources
                # The context dict from the interceptor tells us what source was used
                for source in ["memory", "graph", "web_search", "hybrid_search"]:
                    self.retrieval_learner.record_outcome(RetrievalOutcome(
                        query_type=query_type,
                        source=source,
                        was_used=True,   # Conservatively assume all sources ran
                        had_results=True,
                        response_score=score,
                        query_text=self._last_query[:100],
                    ))

        except Exception as e:
            logger.error(f"Background learning failed: {e}")

    async def _background_curriculum(self) -> None:
        """Background task: run curriculum engine to propose new skills."""
        try:
            proposals = await self.curriculum.generate_proposals()
            # Auto-add Level 1 proposals with high priority
            for proposal in proposals:
                if proposal.level <= 1 and proposal.priority >= 0.7:
                    self.skill_store.add_skill(proposal.skill)
                    logger.info(f"Curriculum auto-added: {proposal.skill.name}")
        except Exception as e:
            logger.error(f"Curriculum engine failed: {e}")

    # ── GUI: mount points ─────────────────────────────────────

    def get_mount_points(self) -> List[str]:
        """This addin mounts in the sidebar."""
        return ["sidebar"]

    def get_frontend_component(self) -> str:
        """Frontend component path."""
        return "SkillVoyagerPanel"

    # ── GUI: action handler ───────────────────────────────────

    async def handle_action(
        self,
        action: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle frontend actions for the skill dashboard.

        Supported actions:
        - get_dashboard: Overview stats + recent evaluations
        - get_skills: Full skill list with optional filters
        - get_skill_tree: Composition tree for a specific skill
        - run_curriculum: Manually trigger curriculum proposals
        - add_skill: Manually create a skill
        - delete_skill: Remove a skill
        - toggle_auto_learn: Enable/disable auto-learning
        """
        if not self.skill_store:
            return {"error": "Skill store not initialized"}

        if action == "get_dashboard":
            stats = self.skill_store.get_skill_stats()
            recent_evals = self.skill_store.get_recent_evaluations(limit=10)
            skills = self.skill_store.get_all_skills(limit=50)
            reflections = self.reflection.get_recent_reflections(5) if self.reflection else []
            exploration = self.reflection.get_exploration_map() if self.reflection else {}
            # Retrieval learning stats
            retrieval_stats = []
            retrieval_total = 0
            if self.retrieval_learner:
                retrieval_stats = self.retrieval_learner.get_stats_summary()
                retrieval_total = self.retrieval_learner.get_total_observations()

            # Correction stats
            correction_stats = []
            correction_total = 0
            if self.correction_learner:
                correction_stats = self.correction_learner.get_correction_stats()
                correction_total = self.correction_learner.get_total_corrections()

            return {
                "stats": stats,
                "recent_evaluations": recent_evals,
                "skills": [self._skill_to_dict(s) for s in skills],
                "recent_reflections": reflections,
                "exploration_map": exploration,
                "auto_learn": self.auto_learn,
                "curriculum_enabled": self.curriculum_enabled,
                "messages_processed": self._message_count,
                # New: retrieval + correction learning
                "retrieval_stats": retrieval_stats,
                "retrieval_observations": retrieval_total,
                "correction_stats": correction_stats,
                "total_corrections": correction_total,
                "learning_sources": [
                    "chat (/api/messages)",
                    "code agents (/v1/chat/completions)",
                    "retrieval optimization",
                    "user corrections",
                ],
            }

        elif action == "get_skills":
            state = payload.get("state")
            skill_type = payload.get("skill_type")
            skills = self.skill_store.get_all_skills(
                state=state, skill_type=skill_type, limit=200
            )
            return {"skills": [self._skill_to_dict(s) for s in skills]}

        elif action == "get_skill_tree":
            skill_id = payload.get("skill_id", "")
            tree = self.skill_store.get_composition_tree(skill_id)
            return tree

        elif action == "run_curriculum":
            if not self.curriculum:
                return {"error": "Curriculum engine not available"}
            proposals = await self.curriculum.generate_proposals()
            return {
                "proposals": [
                    {
                        "skill_name": p.skill.name,
                        "reason": p.reason,
                        "priority": p.priority,
                        "level": p.level,
                        "skill_type": p.skill.skill_type,
                    }
                    for p in proposals
                ]
            }

        elif action == "add_skill":
            import uuid as _uuid
            skill = Skill(
                id=str(_uuid.uuid4()),
                name=payload.get("name", "unnamed_skill"),
                skill_type=payload.get("skill_type", "search_strategy"),
                description=payload.get("description", ""),
                strategy=payload.get("strategy", ""),
                trigger_patterns=payload.get("trigger_patterns", []),
                confidence=0.5,
                state="candidate",
                source="manual",
                created_at=time.time(),
            )
            success = self.skill_store.add_skill(skill)
            return {"success": success, "skill_id": skill.id}

        elif action == "delete_skill":
            skill_id = payload.get("skill_id", "")
            success = self.skill_store.delete_skill(skill_id)
            return {"success": success}

        elif action == "toggle_auto_learn":
            self.auto_learn = not self.auto_learn
            return {"auto_learn": self.auto_learn}

        elif action == "toggle_curriculum":
            self.curriculum_enabled = not self.curriculum_enabled
            return {"curriculum_enabled": self.curriculum_enabled}

        elif action == "get_exploration_map":
            if not self.reflection:
                return {"exploration_map": {}}
            return {"exploration_map": self.reflection.get_exploration_map()}

        elif action == "get_reflections":
            if not self.reflection:
                return {"reflections": []}
            return {"reflections": self.reflection.get_recent_reflections(20)}

        elif action == "get_revision_history":
            skill_id = payload.get("skill_id", "")
            if not self.reflection:
                return {"revisions": []}
            return {"revisions": self.reflection.get_revision_history(skill_id)}

        elif action == "get_settings_schema":
            return self.get_settings_schema()

        elif action == "update_settings":
            return await self._apply_settings(payload)

        elif action == "test_llm":
            return await self._test_llm_connection(payload)

        elif action == "list_models":
            return await self._list_models(payload)

        # ── Correction feedback actions ─────────────────────────
        elif action == "record_correction":
            # Called when user edits, regenerates, or thumbs-down a response
            if not self.correction_learner:
                return {"error": "Correction learner not initialized"}
            event = CorrectionEvent(
                correction_type=payload.get("type", "edit"),
                conversation_id=payload.get("conversation_id", ""),
                message_id=payload.get("message_id", ""),
                original_response=payload.get("original_response", ""),
                corrected_text=payload.get("corrected_text", ""),
                skill_name=payload.get("skill_name", ""),
                skill_id=payload.get("skill_id", ""),
                query_type=payload.get("query_type", ""),
            )
            result = self.correction_learner.record_correction(
                event, skill_store=self.skill_store
            )
            return result

        elif action == "get_correction_stats":
            if not self.correction_learner:
                return {"corrections": [], "total": 0}
            return {
                "corrections": self.correction_learner.get_correction_stats(),
                "recent": self.correction_learner.get_recent_corrections(10),
                "total": self.correction_learner.get_total_corrections(),
            }

        # ── Retrieval learning actions ─────────────────────────
        elif action == "get_retrieval_stats":
            if not self.retrieval_learner:
                return {"stats": [], "total": 0}
            return {
                "stats": self.retrieval_learner.get_stats_summary(),
                "total": self.retrieval_learner.get_total_observations(),
            }

        elif action == "get_retrieval_recommendations":
            if not self.retrieval_learner:
                return {"recommendations": {}}
            query_type = payload.get("query_type", "factual/definition")
            return {
                "query_type": query_type,
                "recommendations": self.retrieval_learner.get_recommended_sources(query_type),
            }

        return {"error": f"Unknown action: {action}"}

    # ── Internal Helpers ──────────────────────────────────────

    async def _test_llm_connection(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Test the LLM connection with the given settings.
        Called by the frontend Test button.

        For local providers (lmstudio, ollama, auto): hits /v1/models endpoint.
        For cloud providers (openai, anthropic): verifies API key format.

        Args:
            payload: Dict with provider, base_url, api_key, model keys.

        Returns:
            Dict with success bool and message string.
        """
        import httpx

        provider = payload.get("provider", "auto")
        base_url = payload.get("base_url", "").rstrip("/")
        api_key = payload.get("api_key", "")

        # Build URL list: user-provided first, then Docker-reachable defaults
        if provider in ("auto", "lmstudio", "ollama"):
            urls_to_try = []
            if base_url:
                urls_to_try.append(base_url.rstrip("/"))
            if provider in ("auto", "lmstudio"):
                urls_to_try.append("http://host.docker.internal:1234/v1")
            if provider in ("auto", "ollama"):
                urls_to_try.append("http://host.docker.internal:11434")

            for url in urls_to_try:
                try:
                    models_url = f"{url}/v1/models" if "/v1" not in url else f"{url}/models"
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(models_url)
                        if resp.status_code == 200:
                            data = resp.json()
                            models = data.get("data", [])
                            model_names = [m.get("id", "?") for m in models[:5]]
                            return {
                                "success": True,
                                "message": f"Connected to {url} — {len(models)} model(s): {', '.join(model_names)}",
                            }
                except Exception:
                    continue

            return {"success": False, "message": "No local LLM server found. Start LM Studio or Ollama first."}

        # Cloud providers — validate key format
        if provider == "openai":
            if not api_key or not api_key.startswith("sk-"):
                return {"success": False, "message": "Invalid OpenAI API key (should start with sk-)"}
            return {"success": True, "message": "OpenAI API key format valid"}

        if provider == "anthropic":
            if not api_key or not api_key.startswith("sk-ant-"):
                return {"success": False, "message": "Invalid Anthropic API key (should start with sk-ant-)"}
            return {"success": True, "message": "Anthropic API key format valid"}

        return {"success": False, "message": f"Unknown provider: {provider}"}

    async def _list_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        List available models from a provider endpoint.
        Called by the frontend Refresh Models button.

        Args:
            payload: Dict with provider, base_url, api_key.

        Returns:
            Dict with models list (list of model ID strings).
        """
        import httpx

        provider = payload.get("provider", "lmstudio")
        base_url = payload.get("base_url", "").rstrip("/")

        if provider in ("lmstudio", "ollama"):
            url = base_url or (
                "http://host.docker.internal:1234/v1" if provider == "lmstudio"
                else "http://host.docker.internal:11434"
            )
            try:
                models_url = f"{url}/v1/models" if "/v1" not in url else f"{url}/models"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(models_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        model_ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                        return {"models": model_ids}
            except Exception as e:
                logger.warning(f"Failed to list models from {url}: {e}")
                return {"models": [], "error": str(e)}

        # Cloud providers — return common models
        if provider == "openai":
            return {"models": ["gpt-4o-mini", "gpt-4o", "gpt-4", "gpt-3.5-turbo"]}
        if provider == "anthropic":
            return {"models": ["claude-3-haiku-20240307", "claude-3-sonnet-20240229", "claude-3-opus-20240229"]}

        return {"models": []}

    async def _detect_local_llm(self) -> None:
        """Try to detect a running local LLM server, or use configured endpoint."""
        import httpx

        # Check if user configured a specific LLM endpoint
        settings = (self.config or {}).get("settings", {})
        configured_url = settings.get("llm_base_url", "")
        if configured_url:
            endpoints = [configured_url]
        else:
            endpoints = [
                "http://host.docker.internal:1234",   # LM Studio (Docker-reachable)
                "http://host.docker.internal:11434",  # Ollama (Docker-reachable)
            ]

        for url in endpoints:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"{url}/v1/models")
                    if resp.status_code == 200:
                        self.evaluator.set_llm_endpoint(url)
                        self.extractor.set_llm_endpoint(url)
                        if self.reflection:
                            self.reflection.set_llm_endpoint(url)
                        logger.info(f"Detected local LLM at {url}")
                        return
            except Exception:
                continue

        logger.info("No local LLM detected — using heuristic evaluation")

    def get_settings_schema(self) -> Dict[str, Any]:
        """
        Return the settings schema for dynamic rendering in the frontend.

        Addins declare their own settings via this method.
        The frontend reads the schema and renders appropriate controls
        (toggles, text inputs, selects, LLM provider cards, etc.)
        WITHOUT hardcoding anything in the Settings page.
        """
        settings = (self.config or {}).get("settings", {})
        return {
            "addin_id": "skill_voyager",
            "addin_name": "Skill Voyager",
            "sections": [
                {
                    "id": "llm",
                    "title": "LLM Provider",
                    "description": "Dedicated LLM for skill evaluation, reflection, and extraction. Independent from main chat LLM.",
                    "type": "llm_provider",
                    "fields": [
                        {
                            "key": "llm_provider",
                            "label": "Provider",
                            "type": "select",
                            "options": [
                                {"value": "auto", "label": "Auto-detect (LM Studio / Ollama)"},
                                {"value": "lmstudio", "label": "LM Studio"},
                                {"value": "ollama", "label": "Ollama"},
                                {"value": "openai", "label": "OpenAI"},
                                {"value": "anthropic", "label": "Anthropic"},
                            ],
                            "default": "auto",
                            "value": settings.get("llm_provider", "auto"),
                        },
                        {
                            "key": "llm_base_url",
                            "label": "Base URL",
                            "type": "text",
                            "placeholder": "http://localhost:1234",
                            "default": "",
                            "value": settings.get("llm_base_url", ""),
                            "show_when": {"llm_provider": ["lmstudio", "ollama"]},
                        },
                        {
                            "key": "llm_api_key",
                            "label": "API Key",
                            "type": "password",
                            "placeholder": "sk-...",
                            "default": "",
                            "value": settings.get("llm_api_key", ""),
                            "show_when": {"llm_provider": ["openai", "anthropic"]},
                        },
                        {
                            "key": "llm_model",
                            "label": "Model",
                            "type": "text",
                            "placeholder": "gpt-4o-mini or local-model",
                            "default": "",
                            "value": settings.get("llm_model", ""),
                        },
                    ],
                },
                {
                    "id": "learning",
                    "title": "Learning Settings",
                    "description": "Control autonomous skill learning behavior.",
                    "type": "general",
                    "fields": [
                        {
                            "key": "auto_learn",
                            "label": "Auto-learn from conversations",
                            "type": "toggle",
                            "default": True,
                            "value": settings.get("auto_learn", True),
                        },
                        {
                            "key": "curriculum_enabled",
                            "label": "Curriculum engine (propose new skills)",
                            "type": "toggle",
                            "default": True,
                            "value": settings.get("curriculum_enabled", True),
                        },
                        {
                            "key": "self_reflection",
                            "label": "Self-reflection on failures",
                            "type": "toggle",
                            "default": True,
                            "value": settings.get("self_reflection", True),
                        },
                        {
                            "key": "min_confidence_to_apply",
                            "label": "Min confidence to apply skill",
                            "type": "range",
                            "min": 0.1,
                            "max": 0.9,
                            "step": 0.05,
                            "default": 0.6,
                            "value": settings.get("min_confidence_to_apply", 0.6),
                        },
                        {
                            "key": "eval_after_every_n",
                            "label": "Evaluate every N messages",
                            "type": "select",
                            "options": [
                                {"value": 1, "label": "Every message"},
                                {"value": 2, "label": "Every 2 messages"},
                                {"value": 5, "label": "Every 5 messages"},
                            ],
                            "default": 1,
                            "value": settings.get("eval_after_every_n", 1),
                        },
                        {
                            "key": "max_skills",
                            "label": "Max skills in library",
                            "type": "number",
                            "min": 10,
                            "max": 500,
                            "default": 200,
                            "value": settings.get("max_skills", 200),
                        },
                    ],
                },
            ],
        }

    async def _apply_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply updated settings from the frontend.
        Called when user saves addin settings.

        Args:
            payload: Dict of setting key -> new value.

        Returns:
            Updated settings confirmation.
        """
        settings = (self.config or {}).setdefault("settings", {})
        changed = []

        for key, value in payload.items():
            if key in ("auto_learn", "curriculum_enabled", "self_reflection",
                       "min_confidence_to_apply", "eval_after_every_n",
                       "max_skills", "llm_provider", "llm_base_url",
                       "llm_api_key", "llm_model"):
                settings[key] = value
                changed.append(key)

        # Apply runtime changes immediately
        if "auto_learn" in changed:
            self.auto_learn = bool(settings.get("auto_learn", True))
        if "curriculum_enabled" in changed:
            self.curriculum_enabled = bool(settings.get("curriculum_enabled", True))
        if "min_confidence_to_apply" in changed:
            self.min_confidence = float(settings.get("min_confidence_to_apply", 0.6))
        if "eval_after_every_n" in changed:
            self.eval_every_n = int(settings.get("eval_after_every_n", 1))

        # Re-detect LLM if provider settings changed
        if any(k in changed for k in ("llm_provider", "llm_base_url", "llm_api_key")):
            await self._detect_local_llm()

        return {"success": True, "changed": changed}

    @staticmethod
    def _skill_to_dict(skill: Skill) -> Dict[str, Any]:
        """Convert a Skill to a JSON-serializable dict."""
        return {
            "id": skill.id,
            "name": skill.name,
            "skill_type": skill.skill_type,
            "description": skill.description,
            "strategy": skill.strategy,
            "trigger_patterns": skill.trigger_patterns,
            "confidence": round(skill.confidence, 3),
            "times_used": skill.times_used,
            "times_succeeded": skill.times_succeeded,
            "times_failed": skill.times_failed,
            "parent_skill_ids": skill.parent_skill_ids,
            "child_skill_ids": skill.child_skill_ids,
            "state": skill.state,
            "source": skill.source,
            "created_at": skill.created_at,
            "last_used_at": skill.last_used_at,
        }
