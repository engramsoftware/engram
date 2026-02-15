"""
OpenAI-compatible chat completions endpoint for agent integration.

Enables code agents (Cursor, Continue.dev, Cline, etc.) to access
the memory-augmented chat system. Now with streaming support!

Point your agent at: http://localhost:8000/v1/chat/completions
"""

import logging
import time
import uuid
import json
import asyncio
from typing import List, Optional, Dict, Any, AsyncGenerator
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from database import get_database
from pipeline.inlet import enrich_request
from pipeline.outlet import process_response
from llm.factory import create_provider
from config import get_settings
from memory.memory_store import MemoryStore
from memory.memory_extractor import MemoryExtractor
from memory.conflict_resolver import ConflictResolver
from negative_knowledge.extractor import NegativeKnowledgeExtractor
from negative_knowledge.store import NegativeKnowledgeStore
from knowledge_graph.graph_store import get_graph_store
from addins.registry import get_registry

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


def _estimate_tokens(text: str) -> int:
    """Rough token count estimate (~4 chars per token for English).

    Good enough for usage reporting. Not a substitute for tiktoken
    but avoids adding a heavy dependency.

    Args:
        text: The text to estimate token count for.

    Returns:
        Estimated token count.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


# ============================================================
# OpenAI-compatible request/response models
# ============================================================

class ChatMessage(BaseModel):
    """OpenAI-compatible chat message."""
    role: str = Field(..., description="Role: system, user, or assistant")
    content: str = Field(..., description="Message content")
    name: Optional[str] = Field(None, description="Optional name")


class OpenAIChatRequest(BaseModel):
    """OpenAI-compatible chat completion request."""
    model: str = Field(..., description="Model name")
    messages: List[ChatMessage] = Field(..., description="Conversation messages")
    temperature: Optional[float] = Field(0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1)
    stream: Optional[bool] = Field(False, description="Enable streaming")
    top_p: Optional[float] = Field(1.0, ge=0.0, le=1.0)
    frequency_penalty: Optional[float] = Field(0.0, ge=-2.0, le=2.0)
    presence_penalty: Optional[float] = Field(0.0, ge=-2.0, le=2.0)


class Choice(BaseModel):
    """OpenAI-compatible choice."""
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    """OpenAI-compatible token usage."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIChatResponse(BaseModel):
    """OpenAI-compatible chat completion response."""
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:24]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[Choice]
    usage: Usage = Field(default_factory=Usage)


# ============================================================
# Helper functions
# ============================================================

async def get_or_create_anonymous_user(db, x_user_id: Optional[str] = None) -> str:
    """
    Get or create a user for API access.

    If X-User-Id header is provided, use that user's data.
    Otherwise, use anonymous user.
    """
    # If X-User-Id header provided, use that user's memories/graph
    if x_user_id:
        logger.info(f"Using provided user ID: {x_user_id}")
        return x_user_id

    # Default: find user with the most memories (likely the primary user)
    try:
        # Count memories per user and pick the one with the most
        user_counts: dict = {}
        async for doc in db.autonomous_memories.find({"invalidatedAt": None}):
            uid = doc.get("userId", "")
            user_counts[uid] = user_counts.get(uid, 0) + 1
        if user_counts:
            best_uid = max(user_counts, key=user_counts.get)
            logger.info(f"Using user with most memories: {best_uid} ({user_counts[best_uid]} memories)")
            return best_uid
    except Exception as e:
        logger.debug(f"Could not find user by memories: {e}")

    # Fallback: find non-test user
    try:
        real_user = await db.users.find_one(
            {"email": {"$ne": "agent@anonymous.local"}},
        )
        if real_user:
            user_id = str(real_user["_id"])
            logger.info(f"Using non-test user: {user_id}")
            return user_id
    except Exception as e:
        logger.debug(f"Could not find non-test user: {e}")

    # Fallback to anonymous user
    anonymous_user_id = "anonymous-agent"

    try:
        user = await db.users.find_one({"_id": anonymous_user_id})

        if not user:
            await db.users.insert_one({
                "_id": anonymous_user_id,
                "email": "agent@anonymous.local",
                "hashedPassword": "",
                "createdAt": datetime.utcnow(),
                "settings": {}
            })
            logger.info("Created anonymous agent user")

        return anonymous_user_id

    except Exception as e:
        logger.error(f"Failed to get/create anonymous user: {e}")
        return "anonymous-agent"


async def get_or_create_agent_conversation(db, user_id: str) -> str:
    """
    Get or create a conversation for agent interactions.
    
    Agents typically use a single persistent conversation.
    """
    conversation_id = f"{user_id}-agent-session"
    
    try:
        conversation = await db.conversations.find_one({"_id": conversation_id})
        
        if not conversation:
            await db.conversations.insert_one({
                "_id": conversation_id,
                "userId": user_id,
                "title": "Agent Session",
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            })
            logger.info(f"Created agent conversation: {conversation_id}")
        
        return conversation_id
        
    except Exception as e:
        logger.error(f"Failed to get/create conversation: {e}")
        return conversation_id


# ============================================================
# Main endpoint
# ============================================================

async def generate_sse_stream(
    provider,
    messages_dict: List[Dict],
    model: str,
    temperature: float,
    max_tokens: Optional[int],
    user_id: str,
    conversation_id: str,
    user_message_content: str,
    db,
    memory_store,
    graph_store,
    provider_name: str
) -> AsyncGenerator[str, None]:
    """Generate SSE stream in OpenAI-compatible format."""
    response_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    full_response = ""

    try:
        async for chunk in provider.stream(
            messages=messages_dict,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        ):
            # Handle StreamChunk objects from providers
            if hasattr(chunk, 'content'):
                content = chunk.content
                is_done = getattr(chunk, 'is_done', False)
            else:
                content = str(chunk)
                is_done = False

            if is_done:
                break

            if content:
                full_response += content
                # Format as OpenAI SSE chunk
                data = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": content},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(data)}\n\n"

        # Send final chunk with finish_reason
        final_data = {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(final_data)}\n\n"
        yield "data: [DONE]\n\n"

        # ── Addin interceptors: after_llm ──────────────────────
        try:
            _addin_registry = get_registry()
            _interceptor_ctx = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_id": "",
                "provider": provider_name,
                "model": model,
                "source": "openai_compat_stream",
            }
            full_response = await _addin_registry.run_interceptors_after(
                full_response, _interceptor_ctx
            )
        except Exception as _int_err:
            logger.warning(f"Agent interceptors (after_llm) failed: {_int_err}")

        # Run outlet pipeline after streaming completes
        try:
            negative_store = NegativeKnowledgeStore(mongo_db=db)
            # Use the active chat provider but pick cheap models to keep costs low
            _CHEAP_MODELS = {
                "anthropic": "claude-haiku-4-5-20251001",
                "openai": "gpt-4o-mini",
            }
            ext_provider = provider_name or "lmstudio"
            ext_model = _CHEAP_MODELS.get(provider_name, model)
            # Only pass base_url for local providers; API-key providers use SDK defaults
            _LOCAL_PROVIDERS = {"lmstudio", "ollama"}
            ext_base_url = base_url if ext_provider in _LOCAL_PROVIDERS else None
            memory_extractor = MemoryExtractor(
                provider_name=ext_provider, model=ext_model,
                api_key=api_key, base_url=ext_base_url,
            )
            conflict_resolver = ConflictResolver(
                provider_name=ext_provider, model=ext_model,
                api_key=api_key, base_url=ext_base_url,
            )
            negative_extractor = NegativeKnowledgeExtractor(
                provider_name=ext_provider, model=ext_model,
                api_key=api_key, base_url=ext_base_url,
            )
            # Build a lightweight LLM provider for entity extraction
            from llm.factory import create_provider
            _extraction_provider = create_provider(
                ext_provider, api_key=api_key, base_url=ext_base_url,
            )

            result = await process_response(
                user_query=user_message_content,
                assistant_response=full_response,
                user_id=user_id,
                conversation_id=conversation_id,
                memory_extractor=memory_extractor,
                conflict_resolver=conflict_resolver,
                memory_store=memory_store,
                negative_extractor=negative_extractor,
                negative_store=negative_store,
                graph_store=graph_store,
                llm_provider=_extraction_provider,
                llm_model=ext_model,
            )
            logger.info(f"Agent streaming outlet: {result}")
        except Exception as e:
            logger.warning(f"Agent streaming outlet pipeline skipped: {e}")

    except Exception as e:
        logger.error(f"Streaming error: {e}")
        error_data = {
            "error": {
                "message": str(e),
                "type": "server_error"
            }
        }
        yield f"data: {json.dumps(error_data)}\n\n"


@router.post("/v1/chat/completions")
async def chat_completions(
    request: OpenAIChatRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
) -> dict:
    """
    OpenAI-compatible chat completions endpoint.

    Enables code agents to access the memory-augmented chat system.
    Supports both streaming and non-streaming responses.

    Authentication: Accepts a JWT Bearer token in the Authorization header.
    If provided, the token is validated and the user is identified from it.
    If no token is provided, falls back to X-User-Id header or anonymous user.
    The PrivateNetworkMiddleware ensures only LAN/VPN clients can reach this.

    Usage:
        Point your agent at: http://<lan-ip>:8000/v1/chat/completions
        Pass your JWT token as the API key for authenticated access.

    Example:
        curl http://192.168.1.100:8000/v1/chat/completions \\
          -H "Content-Type: application/json" \\
          -H "Authorization: Bearer <your-jwt-token>" \\
          -d '{
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hello!"}]
          }'
    """
    try:
        # Get database
        # get_database() returns the SQLite database instance (collection-style API), not an awaitable.
        db = get_database()

        # Try to authenticate via JWT if a Bearer token is provided
        authenticated_user_id = None
        if authorization and authorization.startswith("Bearer "):
            token = authorization[7:]
            try:
                from jose import jwt as jose_jwt
                payload = jose_jwt.decode(
                    token,
                    settings.jwt_secret_key,
                    algorithms=[settings.jwt_algorithm],
                )
                authenticated_user_id = payload.get("sub")
                logger.info(f"OpenAI compat: authenticated user {authenticated_user_id}")
            except Exception:
                pass  # Invalid token — fall back to anonymous

        # Use authenticated user or fall back to header/anonymous
        user_id = authenticated_user_id or await get_or_create_anonymous_user(db, x_user_id)
        conversation_id = await get_or_create_agent_conversation(db, user_id)
        
        logger.info(f"Agent request: model={request.model}, messages={len(request.messages)}, stream={request.stream}")
        
        # Convert messages to format expected by pipeline
        messages_dict = [
            {"role": msg.role, "content": msg.content}
            for msg in request.messages
        ]

        # Inject current local time into system message so the LLM
        # knows "now" for scheduling, reminders, and time-sensitive answers
        try:
            from datetime import datetime as _dt
            if settings.timezone:
                import zoneinfo
                _local_tz = zoneinfo.ZoneInfo(settings.timezone)
            else:
                _local_tz = _dt.now().astimezone().tzinfo
            _now = _dt.now(_local_tz)
            _tz_name = settings.timezone or str(_local_tz)
            _time_block = (
                f"\n\n## Current Date & Time\n"
                f"Right now it is: {_now.strftime('%A, %B %d, %Y at %I:%M %p')} "
                f"({_tz_name})"
            )
            if messages_dict and messages_dict[0]["role"] == "system":
                messages_dict[0]["content"] += _time_block
            else:
                messages_dict.insert(0, {"role": "system", "content": _time_block.strip()})
        except Exception:
            pass

        # Get last user message
        user_message = next(
            (msg for msg in reversed(request.messages) if msg.role == "user"),
            None
        )

        if not user_message:
            raise HTTPException(status_code=400, detail="No user message found")

        # Initialize stores for memory/knowledge graph enrichment
        memory_store = None
        graph_store = None
        graph_context = ""

        try:
            memory_store = MemoryStore(mongo_db=db)
            if memory_store.is_available:
                # Get relevant memories
                memories = memory_store.search(user_message.content, user_id=user_id, limit=5, min_confidence=0.3)
                if memories:
                    memory_header = (
                        "## User Profile & Knowledge\n"
                        "These are facts learned from past conversations. Use them to personalize "
                        "your responses, but NEVER tell the user 'you mentioned this before' or "
                        "'you asked about this previously'. Treat every question as new unless "
                        "the current conversation explicitly shows otherwise.\n"
                    )
                    memory_context = memory_header + "\n".join([f"- {m.content}" for m in memories])
                    # Inject into system message or first message
                    if messages_dict and messages_dict[0]["role"] == "system":
                        messages_dict[0]["content"] += f"\n\n{memory_context}"
                    else:
                        messages_dict.insert(0, {"role": "system", "content": memory_context})
                    logger.info(f"Agent: Injected {len(memories)} memories")
        except Exception as e:
            logger.debug(f"Agent memory retrieval skipped: {e}")

        try:
            if settings.neo4j_uri and settings.neo4j_password:
                graph_store = get_graph_store(
                    uri=settings.neo4j_uri,
                    username=settings.neo4j_username,
                    password=settings.neo4j_password,
                    database=settings.neo4j_database
                )
                if graph_store and graph_store.is_available:
                    from fastapi.concurrency import run_in_threadpool
                    graph_results = await run_in_threadpool(graph_store.search_by_query, user_message.content, user_id, 5)
                    if graph_results:
                        graph_context = graph_store.format_context_for_prompt(graph_results)
                        # Inject graph context
                        if messages_dict and messages_dict[0]["role"] == "system":
                            messages_dict[0]["content"] += f"\n\n{graph_context}"
                        else:
                            messages_dict.insert(0, {"role": "system", "content": graph_context})
                        logger.info(f"Agent: Injected graph context with {len(graph_results)} entities")
        except Exception as e:
            logger.debug(f"Agent graph retrieval skipped: {e}")
        
        # Create LLM provider
        # Map model name to provider
        model_lower = request.model.lower()
        provider_name = "openai"  # Default
        if "claude" in model_lower:
            provider_name = "anthropic"
        # If the caller indicates local/llama and LM Studio is configured, prefer LM Studio.
        elif settings.lmstudio_base_url and (
            "local" in model_lower
            or "lmstudio" in model_lower
            # If the model string looks like an LM Studio model id (e.g. "qwen/..."),
            # prefer LM Studio. This also covers most local model IDs.
            or "/" in model_lower
        ):
            provider_name = "lmstudio"
        elif "ollama" in model_lower:
            provider_name = "ollama"

        # Resolve API key: prefer user's encrypted key from MongoDB,
        # fall back to .env settings only if MongoDB has nothing
        api_key: Optional[str] = None
        base_url: Optional[str] = None

        llm_settings = await db.llm_settings.find_one({"userId": user_id})
        if llm_settings:
            provider_config = llm_settings.get("providers", {}).get(provider_name, {})
            encrypted_key = provider_config.get("apiKey")
            if encrypted_key:
                try:
                    from utils.encryption import decrypt_api_key
                    api_key = decrypt_api_key(encrypted_key)
                except Exception as e:
                    logger.warning(f"Failed to decrypt API key for {provider_name}: {e}")
            # Use stored base URL for local providers
            if provider_name in ("lmstudio", "ollama"):
                base_url = provider_config.get("baseUrl")

        # Fall back to .env settings if no user key found
        if not api_key:
            if provider_name == "openai":
                api_key = settings.openai_api_key
            elif provider_name == "anthropic":
                api_key = settings.anthropic_api_key

        # Fall back to .env base URLs if not set from user config
        if not base_url:
            if provider_name == "openai":
                base_url = settings.openai_base_url
            elif provider_name == "anthropic":
                base_url = settings.anthropic_base_url
            elif provider_name == "lmstudio":
                base_url = settings.lmstudio_base_url
            elif provider_name == "ollama":
                base_url = settings.ollama_base_url

        logger.info(f"Agent provider routing: model={request.model} -> provider={provider_name} base_url={base_url}")
        provider = create_provider(provider_name, api_key=api_key, base_url=base_url)

        if not provider:
            raise HTTPException(status_code=500, detail="LLM provider not available")

        # ── Addin interceptors: before_llm ─────────────────────────
        # Let interceptors (e.g. Skill Voyager) classify the query and
        # inject skill strategies before the LLM sees the messages.
        try:
            _addin_registry = get_registry()
            _interceptor_ctx = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "provider": provider_name,
                "model": request.model,
                "source": "openai_compat",
            }
            messages_dict = await _addin_registry.run_interceptors_before(
                messages_dict, _interceptor_ctx
            )
        except Exception as _int_err:
            logger.warning(f"Agent interceptors (before_llm) failed: {_int_err}")

        # Handle streaming requests
        logger.info(f"DEBUG: request.stream type={type(request.stream)}, value={request.stream}")
        if request.stream:
            logger.info(f"Agent streaming request for model={request.model}")
            return StreamingResponse(
                generate_sse_stream(
                    provider=provider,
                    messages_dict=messages_dict,
                    model=request.model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    user_message_content=user_message.content,
                    db=db,
                    memory_store=memory_store,
                    graph_store=graph_store,
                    provider_name=provider_name
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )

        # Non-streaming response
        response = await provider.generate(
            messages=messages_dict,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )

        # ── Addin interceptors: after_llm (non-streaming) ─────
        try:
            _addin_registry = get_registry()
            _interceptor_ctx = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_id": "",
                "provider": provider_name,
                "model": request.model,
                "source": "openai_compat",
            }
            response.content = await _addin_registry.run_interceptors_after(
                response.content, _interceptor_ctx
            )
        except Exception as _int_err:
            logger.warning(f"Agent interceptors (after_llm) failed: {_int_err}")

        # Run outlet pipeline (memory/entity extraction) in background
        try:
            negative_store = NegativeKnowledgeStore(mongo_db=db)
            memory_extractor = MemoryExtractor(provider_name=provider_name, model=request.model)
            conflict_resolver = ConflictResolver(provider_name=provider_name, model=request.model)
            negative_extractor = NegativeKnowledgeExtractor(provider_name=provider_name, model=request.model)

            result = await process_response(
                user_query=user_message.content,
                assistant_response=response.content,
                user_id=user_id,
                conversation_id=conversation_id,
                memory_extractor=memory_extractor,
                conflict_resolver=conflict_resolver,
                memory_store=memory_store,
                negative_extractor=negative_extractor,
                negative_store=negative_store,
                graph_store=graph_store,
                llm_provider=provider,
                llm_model=request.model,
            )
            logger.info(f"Agent outlet: {result}")
        except Exception as e:
            logger.warning(f"Agent outlet pipeline skipped: {e}")

        # Format OpenAI-compatible response
        return OpenAIChatResponse(
            model=request.model,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=response.content
                    ),
                    finish_reason="stop"
                )
            ],
            usage=Usage(
                prompt_tokens=_estimate_tokens(str(messages_dict)),
                completion_tokens=_estimate_tokens(response.content),
                total_tokens=_estimate_tokens(str(messages_dict)) + _estimate_tokens(response.content),
            )
        )
        
    except Exception as e:
        logger.error(f"Chat completion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v1/models")
async def list_models() -> dict:
    """
    List available models (OpenAI-compatible).
    
    Returns a minimal list for agent compatibility.
    """
    return {
        "object": "list",
        "data": [
            {
                "id": "gpt-4o-mini",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "openai"
            },
            {
                "id": "gpt-4o",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "openai"
            },
            {
                "id": "claude-3-haiku-20240307",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "anthropic"
            }
        ]
    }
