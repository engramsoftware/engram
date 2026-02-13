"""
Settings router.
Handles LLM provider configuration, model detection, and logging controls.
"""

import asyncio
import collections
import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional, Any

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from bson import ObjectId

from config import get_settings
from database import get_database
from routers.auth import get_current_user
from llm.factory import create_provider, get_available_providers
from llm.base import ModelInfo
from utils.encryption import encrypt_api_key, decrypt_api_key, mask_api_key

# Pre-built model lists for providers that don't need a live API call
_STATIC_MODELS: Dict[str, List[str]] = {}

logger = logging.getLogger(__name__)
router = APIRouter()


class ProviderConfigRequest(BaseModel):
    """Request to update a provider's configuration."""
    enabled: bool = False
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None


class BraveSearchConfigRequest(BaseModel):
    """Request to update Brave Search configuration."""
    enabled: bool = False
    api_key: Optional[str] = None


class EmailConfigRequest(BaseModel):
    """Request to update email notification (SMTP) configuration.

    Args:
        enabled: Whether email notifications are active.
        smtp_host: SMTP server hostname (e.g. smtp.gmail.com).
        smtp_port: SMTP port (587 for TLS, 465 for SSL).
        username: SMTP login username (your email address).
        password: SMTP app password (encrypted at rest).
        recipient: Default recipient email for notifications.
        from_name: Display name for the sender (default 'Engram').
    """
    enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    recipient: Optional[str] = None
    from_name: str = "Engram"


class Neo4jConfigRequest(BaseModel):
    """Request to update Neo4j Knowledge Graph configuration.

    Args:
        enabled: Whether the knowledge graph is active.
        uri: Neo4j connection URI (e.g. neo4j+s://xxx.databases.neo4j.io).
        username: Neo4j username (usually 'neo4j').
        password: Neo4j password (encrypted at rest).
        database: Neo4j database name (default 'neo4j').
    """
    enabled: bool = False
    uri: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    database: str = "neo4j"


class OptimizationConfigRequest(BaseModel):
    """Request to update performance optimization settings.

    Args:
        response_validation: Enable LLM-based hallucination check after each response.
            Costs ~3K extra tokens per message. Disable to save tokens/speed.
        history_limit: Max conversation messages to send to the LLM.
            0 = send full history (default). 3-20 = send only last N messages.
    """
    response_validation: bool = True
    history_limit: int = 0


class LLMSettingsRequest(BaseModel):
    """Request to update all LLM settings."""
    providers: Dict[str, ProviderConfigRequest] = {}
    default_provider: Optional[str] = None
    default_model: Optional[str] = None
    brave_search: Optional[BraveSearchConfigRequest] = None
    neo4j: Optional[Neo4jConfigRequest] = None
    email: Optional[EmailConfigRequest] = None
    optimization: Optional[OptimizationConfigRequest] = None


class ProviderConfigResponse(BaseModel):
    """Provider config in API response (masked API key)."""
    enabled: bool
    api_key_set: bool
    api_key_masked: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None
    available_models: List[str] = []


class BraveSearchConfigResponse(BaseModel):
    """Brave Search config in API response (masked key)."""
    enabled: bool = False
    api_key_set: bool = False
    api_key_masked: Optional[str] = None


class EmailConfigResponse(BaseModel):
    """Email notification config in API response (masked password)."""
    enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    username: Optional[str] = None
    password_set: bool = False
    password_masked: Optional[str] = None
    recipient: Optional[str] = None
    from_name: str = "Engram"


class Neo4jConfigResponse(BaseModel):
    """Neo4j config in API response (masked password)."""
    enabled: bool = False
    uri: Optional[str] = None
    username: Optional[str] = None
    password_set: bool = False
    password_masked: Optional[str] = None
    database: str = "neo4j"


class OptimizationConfigResponse(BaseModel):
    """Optimization settings in API response."""
    response_validation: bool = True
    history_limit: int = 0


class LLMSettingsResponse(BaseModel):
    """LLM settings in API response."""
    providers: Dict[str, ProviderConfigResponse]
    default_provider: Optional[str]
    default_model: Optional[str]
    available_providers: List[str]
    brave_search: Optional[BraveSearchConfigResponse] = None
    neo4j: Optional[Neo4jConfigResponse] = None
    email: Optional[EmailConfigResponse] = None
    optimization: Optional[OptimizationConfigResponse] = None


@router.get("/llm", response_model=LLMSettingsResponse)
async def get_llm_settings(current_user: dict = Depends(get_current_user)) -> dict:
    """Get user's LLM provider settings."""
    db = get_database()
    user_id = current_user["id"]
    
    settings = await db.llm_settings.find_one({"userId": user_id})
    
    # Build response with masked API keys
    providers_response = {}
    stored_providers = settings.get("providers", {}) if settings else {}
    
    for provider_name in get_available_providers():
        config = stored_providers.get(provider_name, {})
        
        # Mask API key for display
        api_key = config.get("apiKey", "")
        api_key_masked = None
        if api_key:
            try:
                decrypted = decrypt_api_key(api_key)
                api_key_masked = mask_api_key(decrypted)
            except:
                pass
        
        # For providers with static model lists, always include them
        stored_models = config.get("availableModels", [])
        if not stored_models and provider_name in _STATIC_MODELS:
            stored_models = _STATIC_MODELS[provider_name]

        # Auto-enable providers that don't need an API key
        _NO_KEY_PROVIDERS = {"lmstudio", "ollama"}
        default_enabled = provider_name in _NO_KEY_PROVIDERS

        providers_response[provider_name] = ProviderConfigResponse(
            enabled=config.get("enabled", default_enabled),
            api_key_set=bool(api_key),
            api_key_masked=api_key_masked,
            base_url=config.get("baseUrl"),
            default_model=config.get("defaultModel"),
            available_models=stored_models
        )
    
    # Build Brave Search config
    brave_config = settings.get("braveSearch", {}) if settings else {}
    brave_key = brave_config.get("apiKey", "")
    brave_masked = None
    if brave_key:
        try:
            brave_decrypted = decrypt_api_key(brave_key)
            brave_masked = mask_api_key(brave_decrypted)
        except Exception:
            pass

    brave_response = BraveSearchConfigResponse(
        enabled=brave_config.get("enabled", False),
        api_key_set=bool(brave_key),
        api_key_masked=brave_masked,
    )

    # Build Neo4j config — fall back to .env values when user hasn't
    # configured Neo4j in the UI yet, so existing settings show up
    env_settings = get_settings()
    neo4j_config = settings.get("neo4j", {}) if settings else {}
    neo4j_pw = neo4j_config.get("password", "")
    neo4j_pw_masked = None

    # If user has saved a password in the UI, use that (encrypted)
    if neo4j_pw:
        try:
            neo4j_decrypted = decrypt_api_key(neo4j_pw)
            neo4j_pw_masked = mask_api_key(neo4j_decrypted)
        except Exception:
            pass

    # Fall back to .env values if user hasn't saved Neo4j config yet
    has_user_config = bool(neo4j_config.get("uri"))
    fallback_uri = neo4j_config.get("uri") or env_settings.neo4j_uri
    fallback_username = neo4j_config.get("username") or env_settings.neo4j_username
    fallback_database = neo4j_config.get("database") or env_settings.neo4j_database
    # If no UI password but .env has one, show it as set
    has_env_password = bool(env_settings.neo4j_password) and not neo4j_pw
    if has_env_password:
        neo4j_pw_masked = mask_api_key(env_settings.neo4j_password)

    neo4j_response = Neo4jConfigResponse(
        enabled=neo4j_config.get("enabled", bool(fallback_uri and (neo4j_pw or has_env_password))),
        uri=fallback_uri,
        username=fallback_username,
        password_set=bool(neo4j_pw) or has_env_password,
        password_masked=neo4j_pw_masked,
        database=fallback_database or "neo4j",
    )

    # Build Email config
    email_config = settings.get("email", {}) if settings else {}
    email_pw = email_config.get("password", "")
    email_pw_masked = None
    if email_pw:
        try:
            email_pw_masked = mask_api_key(decrypt_api_key(email_pw))
        except Exception:
            pass

    email_response = EmailConfigResponse(
        enabled=email_config.get("enabled", False),
        smtp_host=email_config.get("smtpHost", "smtp.gmail.com"),
        smtp_port=email_config.get("smtpPort", 587),
        username=email_config.get("username"),
        password_set=bool(email_pw),
        password_masked=email_pw_masked,
        recipient=email_config.get("recipient"),
        from_name=email_config.get("fromName", "Engram"),
    )

    # Build optimization config
    opt_config = settings.get("optimization", {}) if settings else {}
    opt_response = OptimizationConfigResponse(
        response_validation=opt_config.get("responseValidation", True),
        history_limit=opt_config.get("historyLimit", 0),
    )

    return LLMSettingsResponse(
        providers=providers_response,
        default_provider=settings.get("defaultProvider") if settings else None,
        default_model=settings.get("defaultModel") if settings else None,
        available_providers=get_available_providers(),
        brave_search=brave_response,
        neo4j=neo4j_response,
        email=email_response,
        optimization=opt_response,
    )


@router.put("/llm", response_model=LLMSettingsResponse)
async def update_llm_settings(
    request: LLMSettingsRequest,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Update user's LLM provider settings."""
    db = get_database()
    user_id = current_user["id"]
    
    # Get existing settings
    existing = await db.llm_settings.find_one({"userId": user_id})
    existing_providers = existing.get("providers", {}) if existing else {}
    
    # Merge with existing providers (don't overwrite unmentioned providers)
    providers_doc = dict(existing_providers)
    
    # Enforce single-active-provider: if a provider is being enabled,
    # disable all other providers so only one is active at a time.
    newly_enabled = None
    for provider_name, config in request.providers.items():
        if config.enabled:
            existing_was_enabled = existing_providers.get(provider_name, {}).get("enabled", False)
            if not existing_was_enabled:
                newly_enabled = provider_name
    
    if newly_enabled:
        for pname in providers_doc:
            if pname != newly_enabled:
                providers_doc[pname]["enabled"] = False
    
    for provider_name, config in request.providers.items():
        existing_config = existing_providers.get(provider_name, {})
        
        provider_doc = {
            "enabled": config.enabled,
            "baseUrl": config.base_url,
            "defaultModel": config.default_model,
            "availableModels": existing_config.get("availableModels", [])
        }
        
        # Only update API key if provided (not empty)
        if config.api_key:
            provider_doc["apiKey"] = encrypt_api_key(config.api_key)
        else:
            # Keep existing API key
            provider_doc["apiKey"] = existing_config.get("apiKey", "")
        
        providers_doc[provider_name] = provider_doc
    
    update_doc = {
        "userId": user_id,
        "providers": providers_doc,
        "updatedAt": datetime.utcnow()
    }
    
    # Auto-set default provider when a new one is enabled
    if newly_enabled:
        update_doc["defaultProvider"] = newly_enabled
        # Pick first available model as default for the new provider
        new_models = providers_doc.get(newly_enabled, {}).get("availableModels", [])
        if new_models:
            update_doc["defaultModel"] = new_models[0]
        else:
            update_doc["defaultModel"] = None
    elif request.default_provider is not None:
        update_doc["defaultProvider"] = request.default_provider
        if request.default_model is not None:
            update_doc["defaultModel"] = request.default_model
        elif existing:
            update_doc["defaultModel"] = existing.get("defaultModel")
    else:
        if existing:
            update_doc["defaultProvider"] = existing.get("defaultProvider")
        if request.default_model is not None:
            update_doc["defaultModel"] = request.default_model
        elif existing:
            update_doc["defaultModel"] = existing.get("defaultModel")

    # Handle Brave Search config update
    if request.brave_search is not None:
        existing_brave = existing.get("braveSearch", {}) if existing else {}
        brave_doc: Dict = {
            "enabled": request.brave_search.enabled,
        }
        if request.brave_search.api_key:
            brave_doc["apiKey"] = encrypt_api_key(request.brave_search.api_key)
        else:
            brave_doc["apiKey"] = existing_brave.get("apiKey", "")
        update_doc["braveSearch"] = brave_doc
    elif existing:
        update_doc["braveSearch"] = existing.get("braveSearch", {})

    # Handle Neo4j config update
    if request.neo4j is not None:
        existing_neo4j = existing.get("neo4j", {}) if existing else {}
        neo4j_doc: Dict = {
            "enabled": request.neo4j.enabled,
            "uri": request.neo4j.uri or existing_neo4j.get("uri"),
            "username": request.neo4j.username or existing_neo4j.get("username"),
            "database": request.neo4j.database,
        }
        if request.neo4j.password:
            neo4j_doc["password"] = encrypt_api_key(request.neo4j.password)
        else:
            neo4j_doc["password"] = existing_neo4j.get("password", "")
        update_doc["neo4j"] = neo4j_doc
    elif existing:
        update_doc["neo4j"] = existing.get("neo4j", {})

    # Handle Email config update
    if request.email is not None:
        existing_email = existing.get("email", {}) if existing else {}
        email_doc: Dict = {
            "enabled": request.email.enabled,
            "smtpHost": request.email.smtp_host,
            "smtpPort": request.email.smtp_port,
            "username": request.email.username or existing_email.get("username"),
            "recipient": request.email.recipient or existing_email.get("recipient"),
            "fromName": request.email.from_name,
        }
        if request.email.password:
            email_doc["password"] = encrypt_api_key(request.email.password)
        else:
            email_doc["password"] = existing_email.get("password", "")
        update_doc["email"] = email_doc
    elif existing:
        update_doc["email"] = existing.get("email", {})

    # Handle optimization config update
    if request.optimization is not None:
        update_doc["optimization"] = {
            "responseValidation": request.optimization.response_validation,
            "historyLimit": request.optimization.history_limit,
        }
    elif existing:
        update_doc["optimization"] = existing.get("optimization", {})
    
    # Upsert settings
    await db.llm_settings.update_one(
        {"userId": user_id},
        {"$set": update_doc},
        upsert=True
    )
    
    # Return updated settings
    return await get_llm_settings(current_user)


@router.post("/test-connection")
async def test_provider_connection(
    provider_name: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Test connection to an LLM provider."""
    db = get_database()
    user_id = current_user["id"]
    
    # If no API key provided, try to use stored one
    if not api_key:
        settings = await db.llm_settings.find_one({"userId": user_id})
        if settings:
            provider_config = settings.get("providers", {}).get(provider_name, {})
            encrypted_key = provider_config.get("apiKey")
            if encrypted_key:
                try:
                    api_key = decrypt_api_key(encrypted_key)
                except:
                    pass
    
    # Create provider and test
    provider = create_provider(provider_name, api_key=api_key, base_url=base_url)
    
    if not provider:
        return {"success": False, "error": f"Unknown provider: {provider_name}"}
    
    try:
        success = await provider.test_connection()
        return {"success": success, "error": None if success else "Connection failed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/test-brave-search")
async def test_brave_search(
    api_key: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Test Brave Search API connectivity."""
    db = get_database()
    user_id = current_user["id"]

    # If no key provided, try stored one
    if not api_key:
        settings = await db.llm_settings.find_one({"userId": user_id})
        if settings:
            encrypted_key = settings.get("braveSearch", {}).get("apiKey", "")
            if encrypted_key:
                try:
                    api_key = decrypt_api_key(encrypted_key)
                except Exception:
                    pass

    if not api_key:
        return {"success": False, "error": "No Brave Search API key configured"}

    try:
        from search.brave_search import BraveSearchClient
        client = BraveSearchClient(api_key=api_key)
        success = await client.test_connection()
        return {"success": success, "error": None if success else "Connection failed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/models/{provider_name}", response_model=List[ModelInfo])
async def get_provider_models(
    provider_name: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Auto-detect available models for a provider.
    For local providers (LM Studio, Ollama), this detects loaded models.
    For cloud providers, this fetches available models from the API.
    """
    db = get_database()
    user_id = current_user["id"]
    
    # Get stored API key
    api_key = None
    base_url = None
    
    settings = await db.llm_settings.find_one({"userId": user_id})
    if settings:
        provider_config = settings.get("providers", {}).get(provider_name, {})
        encrypted_key = provider_config.get("apiKey")
        base_url = provider_config.get("baseUrl")
        
        if encrypted_key:
            try:
                api_key = decrypt_api_key(encrypted_key)
            except:
                pass
    
    # Create provider and fetch models
    provider = create_provider(provider_name, api_key=api_key, base_url=base_url)
    
    if not provider:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")
    
    try:
        models = await provider.list_models()
        
        # Cache models in settings
        if settings:
            model_ids = [m.id for m in models]
            await db.llm_settings.update_one(
                {"userId": user_id},
                {"$set": {f"providers.{provider_name}.availableModels": model_ids}}
            )
        
        return models
    except Exception as e:
        logger.error(f"Failed to fetch models for {provider_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-neo4j")
async def test_neo4j_connection(
    uri: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: str = "neo4j",
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Test Neo4j Knowledge Graph connectivity.

    Uses provided credentials or falls back to stored ones.

    Returns:
        Dict with success bool and optional error message.
    """
    db = get_database()
    user_id = current_user["id"]

    # Fall back to stored credentials if not provided
    if not uri or not password:
        settings = await db.llm_settings.find_one({"userId": user_id})
        if settings:
            neo4j_cfg = settings.get("neo4j", {})
            uri = uri or neo4j_cfg.get("uri")
            username = username or neo4j_cfg.get("username")
            database = database or neo4j_cfg.get("database", "neo4j")
            if not password and neo4j_cfg.get("password"):
                try:
                    password = decrypt_api_key(neo4j_cfg["password"])
                except Exception:
                    pass

    if not uri or not password:
        return {"success": False, "error": "No Neo4j URI or password configured"}

    try:
        from knowledge_graph.graph_store import Neo4jGraphStore
        store = Neo4jGraphStore(
            uri=uri,
            username=username or "neo4j",
            password=password,
            database=database,
        )
        if store.is_available:
            return {"success": True, "error": None}
        return {"success": False, "error": "Neo4j driver connected but database not reachable"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/test-email")
async def test_email_connection(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Test email SMTP connectivity and send a test message.

    Uses stored credentials from the user's settings.
    Sends a test email to the configured recipient.

    Returns:
        Dict with success bool and optional error message.
    """
    db = get_database()
    user_id = current_user["id"]

    settings = await db.llm_settings.find_one({"userId": user_id})
    if not settings:
        return {"success": False, "error": "No email settings configured"}

    email_cfg = settings.get("email", {})
    if not email_cfg.get("username") or not email_cfg.get("password"):
        return {"success": False, "error": "Email username or app password not configured"}

    recipient = email_cfg.get("recipient") or email_cfg.get("username")
    if not recipient:
        return {"success": False, "error": "No recipient email configured"}

    try:
        smtp_password = decrypt_api_key(email_cfg["password"])
    except Exception:
        return {"success": False, "error": "Failed to decrypt stored password"}

    try:
        from notifications.email_service import EmailService, build_notification_html
        service = EmailService(
            smtp_host=email_cfg.get("smtpHost", "smtp.gmail.com"),
            smtp_port=email_cfg.get("smtpPort", 587),
            username=email_cfg["username"],
            password=smtp_password,
            from_name=email_cfg.get("fromName", "Engram"),
        )

        html = build_notification_html(
            title="Test Notification",
            body="<p>If you're reading this, Engram email notifications are working!</p>"
                 "<p>You'll receive messages here when Engram has reminders, "
                 "summaries, or anything it thinks you should know.</p>",
        )

        success = await service.send(
            to=recipient,
            subject="Engram — Test Notification",
            body="If you're reading this, Engram email notifications are working!",
            html_body=html,
        )

        if success:
            return {"success": True, "error": None}
        return {"success": False, "error": "SMTP send failed — check username and app password"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# Logging Configuration
# ============================================================

# Module groups for granular log level control
_LOG_GROUPS: Dict[str, List[str]] = {
    "pipeline": ["pipeline.inlet", "pipeline.outlet", "retrieval.fusion"],
    "memory": ["memory.memory_extractor", "memory.conflict_resolver", "memory.memory_store", "memory.memory_evolution"],
    "knowledge_graph": ["knowledge_graph.graph_store", "knowledge_graph.entity_extractor", "knowledge_graph.code_extractor"],
    "search": ["search.web_search_gate", "search.brave_search", "search.hybrid_search", "search.hybrid_wrapper"],
    "llm": ["llm.openai_provider", "llm.anthropic_provider", "llm.lmstudio_provider", "llm.ollama_provider", "llm.base"],
    "routers": ["routers.messages", "routers.research", "routers.settings", "routers.auth"],
    "negative_knowledge": ["negative_knowledge.extractor", "negative_knowledge.store"],
    "notifications": ["notifications.scheduler", "notifications.email_service"],
    "rag": ["rag.document_processor"],
}

# Friendly display names for log groups
_GROUP_NAMES: Dict[str, str] = {
    "pipeline": "Message Pipeline",
    "memory": "Memory System",
    "knowledge_graph": "Knowledge Graph",
    "search": "Web & Hybrid Search",
    "llm": "LLM Providers",
    "routers": "API Routes",
    "negative_knowledge": "Negative Knowledge",
    "notifications": "Notifications",
    "rag": "Document RAG",
}

VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class LoggingConfigResponse(BaseModel):
    """Current logging configuration."""
    root_level: str
    groups: Dict[str, Any]


class LogLevelRequest(BaseModel):
    """Request to update log levels."""
    root_level: Optional[str] = None
    groups: Optional[Dict[str, str]] = None


@router.get("/logging", response_model=LoggingConfigResponse)
async def get_logging_config(
    current_user: dict = Depends(get_current_user)
) -> LoggingConfigResponse:
    """Get current logging levels for all module groups."""
    root = logging.getLogger()
    groups: Dict[str, Any] = {}

    for group_key, modules in _LOG_GROUPS.items():
        # Use the effective level of the first module in the group
        sample_logger = logging.getLogger(modules[0])
        groups[group_key] = {
            "name": _GROUP_NAMES.get(group_key, group_key),
            "level": logging.getLevelName(sample_logger.getEffectiveLevel()),
            "modules": modules,
        }

    return LoggingConfigResponse(
        root_level=logging.getLevelName(root.level),
        groups=groups,
    )


@router.put("/logging")
async def update_logging_config(
    request: LogLevelRequest,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Update logging levels. Changes take effect immediately (no restart needed)."""
    changes: List[str] = []

    # Update root level
    if request.root_level:
        level = request.root_level.upper()
        if level not in VALID_LEVELS:
            raise HTTPException(400, f"Invalid level: {level}. Must be one of {VALID_LEVELS}")
        logging.getLogger().setLevel(level)
        changes.append(f"root → {level}")

    # Update group levels
    if request.groups:
        for group_key, level_str in request.groups.items():
            level = level_str.upper()
            if level not in VALID_LEVELS:
                raise HTTPException(400, f"Invalid level: {level}")
            modules = _LOG_GROUPS.get(group_key)
            if not modules:
                raise HTTPException(400, f"Unknown group: {group_key}")
            for mod in modules:
                logging.getLogger(mod).setLevel(level)
            changes.append(f"{group_key} → {level}")

    logger.info(f"Logging config updated: {', '.join(changes)}")
    return {"success": True, "changes": changes}


# ============================================================
# Log Viewer — In-Memory Buffer + Endpoints
# ============================================================

class _LogEntry:
    """Lightweight log record for the in-memory buffer."""
    __slots__ = ("timestamp", "level", "logger_name", "message")

    def __init__(self, timestamp: float, level: str, logger_name: str, message: str):
        self.timestamp = timestamp
        self.level = level
        self.logger_name = logger_name
        self.message = message

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger_name,
            "message": self.message,
        }


# Ring buffer: keeps the last N log entries in memory
_LOG_BUFFER_SIZE = 500
_log_buffer: collections.deque = collections.deque(maxlen=_LOG_BUFFER_SIZE)

# Subscribers for real-time SSE streaming (set of asyncio.Queue)
_log_subscribers: set = set()


class _BufferHandler(logging.Handler):
    """Custom logging handler that captures records into a ring buffer
    and pushes them to any active SSE subscribers."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = _LogEntry(
                timestamp=record.created,
                level=record.levelname,
                logger_name=record.name,
                message=self.format(record),
            )
            _log_buffer.append(entry)

            # Push to all SSE subscribers (non-blocking)
            dead: List[asyncio.Queue] = []
            for q in _log_subscribers:
                try:
                    q.put_nowait(entry)
                except asyncio.QueueFull:
                    pass  # drop if subscriber is too slow
                except Exception:
                    dead.append(q)
            for q in dead:
                _log_subscribers.discard(q)
        except Exception:
            pass  # never let the handler crash the app


# Install the buffer handler on the root logger so it captures everything
_buffer_handler = _BufferHandler()
_buffer_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logging.getLogger().addHandler(_buffer_handler)


@router.get("/logs")
async def get_recent_logs(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(200, ge=1, le=500),
    level: Optional[str] = Query(None, description="Minimum level filter: DEBUG, INFO, WARNING, ERROR"),
    search: Optional[str] = Query(None, description="Search in log messages"),
    logger_name: Optional[str] = Query(None, description="Filter by logger name prefix"),
) -> List[dict]:
    """Get recent log entries from the in-memory buffer."""
    min_level = 0
    if level:
        min_level = getattr(logging, level.upper(), 0)

    results = []
    for entry in reversed(_log_buffer):
        if min_level and getattr(logging, entry.level, 0) < min_level:
            continue
        if logger_name and not entry.logger_name.startswith(logger_name):
            continue
        if search and search.lower() not in entry.message.lower():
            continue
        results.append(entry.to_dict())
        if len(results) >= limit:
            break

    # Return in chronological order (oldest first)
    results.reverse()
    return results


@router.get("/logs/stream")
async def stream_logs(
    level: Optional[str] = Query(None, description="Minimum level filter"),
    token: Optional[str] = Query(None, description="JWT token (EventSource can't send headers)"),
):
    """Stream log entries in real-time via Server-Sent Events (SSE).

    EventSource API doesn't support custom headers, so the JWT token
    is passed as a query parameter instead of an Authorization header.
    """
    # Authenticate via query-param token (EventSource limitation)
    if not token:
        raise HTTPException(401, "Token required")
    from jose import JWTError, jwt as jose_jwt
    settings = get_settings()
    try:
        payload = jose_jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if not payload.get("sub"):
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")

    min_level = 0
    if level:
        min_level = getattr(logging, level.upper(), 0)

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _log_subscribers.add(queue)

    async def event_generator():
        try:
            # Send a keepalive comment so the connection is established
            yield ": connected\n\n"
            while True:
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=30.0)
                    # Apply level filter
                    if min_level and getattr(logging, entry.level, 0) < min_level:
                        continue
                    data = json.dumps(entry.to_dict())
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive to prevent connection timeout
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _log_subscribers.discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
