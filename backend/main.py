"""
FastAPI main application entry point.

Architecture (production — single port):
  Browser → http://localhost:8000/          → serves built React frontend
  Browser → http://localhost:8000/api/...   → API routes (auth, conversations, etc.)
  Browser → http://localhost:8000/api/v1/.. → OpenAI-compatible endpoint

Architecture (development — two ports):
  Vite dev server on :5173 proxies /api → http://localhost:8000/api
  Backend on :8000 serves API only (no static files needed)

Security model:
  - PrivateNetworkMiddleware blocks all non-LAN/VPN source IPs
  - CORS auto-detects LAN interfaces so devices on the network can connect
  - RateLimitMiddleware prevents brute-force on auth endpoints
  - All data endpoints require JWT authentication
  - Security headers prevent clickjacking, MIME sniffing, etc.
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_settings, PROJECT_ROOT
from database import connect_to_mongodb, close_mongodb_connection
from middleware.private_network import PrivateNetworkMiddleware
from middleware.rate_limit import RateLimitMiddleware

# Import routers
from routers import auth, conversations, messages, search, addins, personas, memories, notes, documents, uploads, openai_compat, users, notifications, graph, setup, data_transfer, budget, email_reader, schedule
from routers import settings as settings_router

# ============================================================
# Logging Configuration
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Suppress noisy third-party log spam
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)
logging.getLogger("neo4j.io").setLevel(logging.WARNING)

# Suppress tokenizer/huggingface warnings that clutter the console
import warnings
warnings.filterwarnings("ignore", message=".*resume_download.*deprecated.*")
warnings.filterwarnings("ignore", message=".*sentencepiece tokenizer.*byte fallback.*")
warnings.filterwarnings("ignore", message=".*truncate to max_length.*")

# Path to pre-built frontend static files
STATIC_DIR = Path(__file__).parent / "static"


# ============================================================
# Application Lifespan (startup/shutdown)
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    # Startup
    logger.info("Starting up chat application...")

    # Warn if JWT secret is still the default — critical security issue
    _settings = get_settings()
    if _settings.jwt_secret_key in (
        "your-super-secret-key-change-in-production",
        "change-me-to-a-random-secret-key",
    ):
        logger.warning(
            "⚠️  JWT_SECRET_KEY is still the default! "
            "Generate a real secret: python -c \"import secrets; print(secrets.token_hex(32))\" "
            "and set it in .env"
        )

    # Log detected CORS origins so the user can verify LAN access
    logger.info(f"CORS origins: {_settings.cors_origins_list}")

    await connect_to_mongodb()

    # Seed built-in personas (tutor, meal planner, budget assistant)
    try:
        from seed_personas import seed_built_in_personas
        await seed_built_in_personas(get_database())
    except Exception as e:
        logger.warning(f"Persona seeding skipped: {e}")

    # Seed built-in add-ins so they appear in the Add-ins tab
    try:
        from seed_addins import seed_built_in_addins
        await seed_built_in_addins(get_database())
    except Exception as e:
        logger.warning(f"Addin seeding skipped: {e}")

    # Load add-in plugins into the runtime registry
    try:
        from addins.loader import AddinLoader
        loader = AddinLoader()
        loaded = await loader.load_all_addins()
        logger.info(f"Loaded {loaded} add-in(s) into runtime registry")
    except Exception as e:
        logger.warning(f"Addin loading skipped: {e}")

    # Start the notification scheduler (sends due emails every 30s)
    try:
        from notifications.scheduler import notification_scheduler
        notification_scheduler.start()
    except Exception as e:
        logger.warning(f"Failed to start notification scheduler: {e}")

    # Log whether frontend static files are available
    if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
        logger.info(f"Serving frontend from {STATIC_DIR}")
    else:
        logger.info("No frontend build found — API-only mode (use Vite dev server)")

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down chat application...")
    try:
        from notifications.scheduler import notification_scheduler
        notification_scheduler.stop()
    except Exception:
        pass
    await close_mongodb_connection()


# ============================================================
# Create FastAPI Application
# ============================================================
app = FastAPI(
    title="Engram API",
    description="Personal AI assistant with autonomous memory, knowledge graphs, and multi-source retrieval",
    version="1.0.0",
    lifespan=lifespan,
    # Move API docs under /api so they don't clash with frontend routes
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# ============================================================
# Middleware Stack (executes bottom-to-top)
# ============================================================
settings = get_settings()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response.

    Prevents clickjacking, MIME sniffing, and other common attacks.
    These are defense-in-depth — the private network middleware is the
    primary security boundary.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Cache static assets (JS/CSS) but not API responses
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif not request.url.path.startswith("/uploads/"):
            response.headers["Cache-Control"] = "no-store"
        return response


# 1. Security headers (outermost — runs on every response)
app.add_middleware(SecurityHeadersMiddleware)

# 2. CORS — auto-detects LAN IPs so devices on the network can connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Rate limiting on auth endpoints (brute-force protection)
app.add_middleware(RateLimitMiddleware)

# 4. Private network gate — blocks all non-LAN/VPN source IPs (innermost)
app.add_middleware(
    PrivateNetworkMiddleware,
    allowed_networks_csv=settings.allowed_networks,
)


# ============================================================
# API Routes — all mounted under /api prefix
# ============================================================
# Routers with their own prefix in the router definition (notifications,
# research) get /api prepended here. Routers without a prefix get one.
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(conversations.router, prefix="/api/conversations", tags=["Conversations"])
app.include_router(messages.router, prefix="/api/messages", tags=["Messages"])
app.include_router(search.router, prefix="/api/search", tags=["Search"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["Settings"])
app.include_router(addins.router, prefix="/api/addins", tags=["Add-ins"])
app.include_router(personas.router, prefix="/api/personas", tags=["Personas"])
app.include_router(memories.router, prefix="/api/memories", tags=["Memories"])
app.include_router(notes.router, prefix="/api/notes", tags=["Notes"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(uploads.router, prefix="/api/uploads", tags=["Uploads"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(notifications.router, prefix="/api", tags=["Notifications"])
app.include_router(openai_compat.router, prefix="/api", tags=["OpenAI Compatible"])
app.include_router(graph.router, prefix="/api/graph", tags=["Knowledge Graph"])
app.include_router(setup.router, prefix="/api/setup", tags=["Setup"])
app.include_router(data_transfer.router, prefix="/api/data", tags=["Data Transfer"])
app.include_router(budget.router, prefix="/api/budget", tags=["Budget"])
app.include_router(email_reader.router, prefix="/api/email", tags=["Email"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["Schedule"])


# ============================================================
# Health Check Endpoints (under /api for consistency)
# ============================================================
@app.get("/api/health")
async def health_check() -> dict:
    """Liveness probe — confirms the process is running."""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/api/health/ready")
async def readiness_check() -> dict:
    """Readiness probe — verifies critical dependencies are available."""
    from config import get_settings
    checks: dict = {}

    # Database (critical)
    try:
        from database import get_database
        db = get_database()
        await db.command("ping")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Neo4j (optional but reported)
    try:
        _s = get_settings()
        if _s.neo4j_uri and _s.neo4j_password:
            from knowledge_graph.graph_store import get_graph_store
            gs = get_graph_store(
                uri=_s.neo4j_uri,
                username=_s.neo4j_username,
                password=_s.neo4j_password,
                database=_s.neo4j_database,
            )
            checks["neo4j"] = "ok" if gs and gs.is_available else "unavailable"
        else:
            checks["neo4j"] = "not configured"
    except Exception as e:
        checks["neo4j"] = f"error: {e}"

    # Fail readiness if database is down (critical dependency)
    if checks.get("database", "").startswith("error"):
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "checks": checks},
        )

    return {"status": "ready", "checks": checks}


# Internal debug endpoint
@app.get("/api/internal/debug/config", include_in_schema=False)
async def _internal_debug_config(request: Request) -> dict:
    """Internal configuration dump for debugging."""
    from search.config_validator import (
        get_debug_config_response,
        check_inbound_request,
    )
    check_inbound_request(
        request_path=str(request.url),
        request_body="",
        request_headers=json.dumps(dict(request.headers)),
        source_ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    return get_debug_config_response()


# ============================================================
# Static Frontend Serving (production mode)
# ============================================================
# If the built frontend exists in backend/static/, serve it.
# Vite builds to frontend/dist/ → build_frontend.py copies to backend/static/
if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
    # Serve static assets (JS, CSS, images) with caching
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="static-assets")

    # SPA catch-all: any non-API route returns index.html so React Router works
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve the React SPA for any non-API route.

        Static files (favicon, manifest, etc.) are served directly.
        All other paths return index.html for client-side routing.
        """
        # Try to serve a static file first (favicon.ico, robots.txt, etc.)
        file_path = STATIC_DIR / full_path
        if full_path and file_path.is_file() and ".." not in full_path:
            return FileResponse(str(file_path))
        # Otherwise return index.html for React Router
        return FileResponse(str(STATIC_DIR / "index.html"))


# ============================================================
# Run with Uvicorn (for development)
# ============================================================
if __name__ == "__main__":
    import uvicorn

    # Build uvicorn kwargs — SSL is optional, defaults to plain HTTP
    uvicorn_kwargs = {
        "app": "main:app",
        "host": settings.host,
        "port": settings.port,
        "reload": settings.debug,
    }

    # Enable HTTPS if both cert and key are configured
    if settings.ssl_certfile and settings.ssl_keyfile:
        if os.path.isfile(settings.ssl_certfile) and os.path.isfile(settings.ssl_keyfile):
            uvicorn_kwargs["ssl_certfile"] = settings.ssl_certfile
            uvicorn_kwargs["ssl_keyfile"] = settings.ssl_keyfile
            logger.info(
                f"HTTPS enabled: cert={settings.ssl_certfile}, "
                f"key={settings.ssl_keyfile}"
            )
        else:
            logger.warning(
                f"SSL files not found (cert={settings.ssl_certfile}, "
                f"key={settings.ssl_keyfile}) — falling back to HTTP"
            )

    uvicorn.run(**uvicorn_kwargs)
