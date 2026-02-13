"""
Configuration module for the chat application.
Loads environment variables and provides centralized config access.
"""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache

# ============================================================
# Centralized Data Paths
# ============================================================
# All user data lives under <project>/data/ for easy backup/deletion.
# Backend code should import these instead of hardcoding paths.
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# ChromaDB vector stores
CHROMA_MESSAGES_DIR = DATA_DIR / "chroma" / "messages"
CHROMA_MEMORIES_DIR = DATA_DIR / "chroma" / "memories"
CHROMA_NEGATIVE_DIR = DATA_DIR / "chroma" / "negative"
CHROMA_DOCUMENTS_DIR = DATA_DIR / "chroma" / "documents"

# MCP server databases
MCP_DATA_DIR = DATA_DIR / "mcp"
MCP_KNOWLEDGE_DB = MCP_DATA_DIR / "knowledge.db"
MCP_USER_INTERACTIONS_DB = MCP_DATA_DIR / "user_interactions.db"
MCP_AI_REASONING_DB = MCP_DATA_DIR / "ai_reasoning.db"

# Learning / skill transfer data
LEARNING_DIR = DATA_DIR / "learning"
SESSIONS_DIR = LEARNING_DIR / "sessions"
SESSION_LINKS_DIR = LEARNING_DIR / "session_links"
SKILLS_DIR = LEARNING_DIR / "skills"
REFLECTIONS_DIR = LEARNING_DIR / "reflections"
EXPERIMENTS_DIR = LEARNING_DIR / "experiments"

# SQLite database (replaces MongoDB)
SQLITE_DB_PATH = DATA_DIR / "app.db"

# User uploads
UPLOADS_DIR = DATA_DIR / "uploads"

# Web crawl cache
CRAWL_CACHE_DIR = DATA_DIR / "crawl_cache"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Uses pydantic-settings for validation and type coercion.
    """
    
    # ============================================================
    # JWT Authentication
    # ============================================================
    jwt_secret_key: str = "your-super-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 720  # 30 days — avoids re-login on mobile
    
    # ============================================================
    # Encryption for API Keys
    # ============================================================
    encryption_key: str = "your-32-byte-encryption-key-here"
    
    # ============================================================
    # LLM Provider Defaults
    # ============================================================
    # OpenAI
    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    
    # Anthropic
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: str = "https://api.anthropic.com"
    
    # LM Studio (local)
    lmstudio_base_url: str = "http://host.docker.internal:1234/v1"
    
    # Ollama (local)
    ollama_base_url: str = "http://host.docker.internal:11434"
    
    
    # ============================================================
    # Search Configuration
    # ============================================================
    # Path to external hybrid_search.py if available
    hybrid_search_path: Optional[str] = None
    # Reranker model for cross-encoder
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # ============================================================
    # Brave Search API (Optional — free tier: 1 req/sec, 2000/mo)
    # ============================================================
    brave_search_api_key: Optional[str] = None

    # ============================================================
    # Vector DB / Persistence Paths (Optional)
    # ============================================================
    # If unset, each store uses its own default under backend/data/
    chroma_messages_path: Optional[str] = None
    chroma_memories_path: Optional[str] = None
    chroma_negative_path: Optional[str] = None

    # ============================================================
    # Neo4j Knowledge Graph (Optional)
    # ============================================================
    # NOTE: Do not hardcode credentials here. Set these in `.env` instead:
    # NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE
    neo4j_uri: Optional[str] = None
    neo4j_username: Optional[str] = None
    neo4j_password: Optional[str] = None
    neo4j_database: str = "neo4j"
    
    # ============================================================
    # Timezone
    # ============================================================
    # IANA timezone name (e.g. "America/Los_Angeles", "US/Eastern").
    # If not set, auto-detected from the OS.  Used to tell the LLM
    # the current local time and to schedule notifications correctly.
    timezone: str = "America/Los_Angeles"

    # ============================================================
    # Server Configuration
    # ============================================================
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ============================================================
    # HTTPS / SSL (Optional — defaults to HTTP)
    # ============================================================
    # Set both to enable HTTPS.  Leave empty for plain HTTP.
    # Generate a self-signed cert for LAN use:
    #   openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None
    
    # ============================================================
    # CORS Configuration
    # ============================================================
    # Comma-separated origins. Use "*_LAN" as a special token to
    # auto-generate origins for all local network interfaces.
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # ============================================================
    # Network Security
    # ============================================================
    # Extra CIDR ranges to allow beyond standard private networks.
    # Comma-separated, e.g. "10.8.0.0/24" for an OpenVPN subnet.
    # Standard private ranges (10/8, 172.16/12, 192.168/16, 127/8,
    # 100.64/10 for Tailscale) are always allowed.
    allowed_networks: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
    
    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins and auto-add LAN interface origins.

        Always includes localhost origins. Also detects all local network
        interfaces and adds http://<ip>:<port> for both the backend and
        frontend ports so LAN/VPN clients can connect.

        Returns:
            List of allowed origin strings.
        """
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]

        # Auto-detect LAN IPs and add origins for them
        try:
            import socket
            hostname = socket.gethostname()
            # Get all IPs for this host
            local_ips = set()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                local_ips.add(info[4][0])
            # Also try the common approach for the primary LAN IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                try:
                    s.connect(("10.255.255.255", 1))
                    local_ips.add(s.getsockname()[0])
                except Exception:
                    pass

            # Add origins for each LAN IP with common frontend ports
            # Include both http and https when SSL is configured
            schemes = ["http"]
            if self.ssl_certfile and self.ssl_keyfile:
                schemes.append("https")
            frontend_ports = [3000, 5173]
            for ip in local_ips:
                if ip.startswith("127."):
                    continue  # localhost already covered
                for scheme in schemes:
                    for fp in frontend_ports:
                        origin = f"{scheme}://{ip}:{fp}"
                        if origin not in origins:
                            origins.append(origin)
                    # Also allow direct backend access (for mobile browsers etc.)
                    backend_origin = f"{scheme}://{ip}:{self.port}"
                    if backend_origin not in origins:
                        origins.append(backend_origin)
        except Exception:
            pass  # If detection fails, just use the configured origins

        return origins


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to avoid reloading env vars on every call.
    """
    return Settings()
