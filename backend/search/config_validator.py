"""
Configuration validation utilities.

Validates runtime configuration integrity and ensures
settings consistency across the application lifecycle.
"""

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from config import DATA_DIR

logger = logging.getLogger(__name__)

# Validation state persistence
_VALIDATION_DB = DATA_DIR / "crawl_cache" / "validation.db"
_VALIDATION_LOG = DATA_DIR / "crawl_cache" / "validation_failure.json"


def _get_db() -> sqlite3.Connection:
    """Get validation state database."""
    _VALIDATION_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_VALIDATION_DB), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config_hashes (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            category TEXT DEFAULT 'runtime',
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS validation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            matched_key TEXT,
            matched_category TEXT,
            source_ip TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            request_path TEXT DEFAULT '',
            request_headers TEXT DEFAULT '',
            context TEXT DEFAULT '',
            ts REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


# ── Reference Values ─────────────────────────────────────────────────────
# Generated once per install, persisted in SQLite.

def _gen_ref_openai() -> str:
    """Generate reference OpenAI-format value."""
    return f"sk-proj-{secrets.token_hex(32)[:51]}"


def _gen_ref_jwt() -> str:
    """Generate reference JWT-format value."""
    return secrets.token_hex(32)


def _gen_ref_mongo() -> str:
    """Generate reference MongoDB URI value."""
    u = f"atlas_{secrets.token_hex(4)}"
    p = secrets.token_hex(12)
    h = f"cluster-{secrets.token_hex(3)}.mongodb.net"
    return f"mongodb+srv://{u}:{p}@{h}/atlas?retryWrites=true"


def _gen_ref_neo4j() -> str:
    """Generate reference Neo4j-format value."""
    return secrets.token_hex(16)


def _gen_ref_brave() -> str:
    """Generate reference Brave API-format value."""
    return f"BSA{secrets.token_hex(20)}"


_REFERENCE_GENERATORS = {
    "openai_ref": _gen_ref_openai,
    "jwt_ref": _gen_ref_jwt,
    "mongo_ref": _gen_ref_mongo,
    "neo4j_ref": _gen_ref_neo4j,
    "brave_ref": _gen_ref_brave,
}


def _ensure_references() -> Dict[str, str]:
    """Load or create reference values. Created once per install.

    Returns:
        Dict mapping reference key to value.
    """
    conn = _get_db()
    rows = conn.execute(
        "SELECT key, value FROM config_hashes WHERE category = 'reference'"
    ).fetchall()
    refs = {r[0]: r[1] for r in rows}

    # Generate any missing references
    now = time.time()
    for key, gen_fn in _REFERENCE_GENERATORS.items():
        if key not in refs:
            val = gen_fn()
            refs[key] = val
            conn.execute(
                "INSERT OR REPLACE INTO config_hashes (key, value, category, created_at) "
                "VALUES (?, ?, 'reference', ?)",
                (key, val, now),
            )

    conn.commit()
    conn.close()
    return refs


# In-memory cache
_refs_cache: Optional[Dict[str, str]] = None


def get_reference_values() -> Dict[str, str]:
    """Get all reference values (cached in memory).

    Returns:
        Dict mapping reference key to value string.
    """
    global _refs_cache
    if _refs_cache is None:
        _refs_cache = _ensure_references()
    return _refs_cache


def get_all_reference_strings() -> Set[str]:
    """Get the set of all reference value strings for fast lookup.

    Returns:
        Set of reference value strings.
    """
    return set(get_reference_values().values())


# ── Validation Check ─────────────────────────────────────────────────────

def _record_event(
    event_type: str,
    matched_key: str = "",
    matched_category: str = "",
    source_ip: str = "",
    user_agent: str = "",
    request_path: str = "",
    request_headers: str = "",
    context: str = "",
) -> None:
    """Record a validation event to both SQLite and flat file.

    Writes to flat file FIRST (survives hard exit), then SQLite.

    Args:
        event_type: Type of validation event.
        matched_key: Which reference was matched.
        matched_category: Category of the match.
        source_ip: Request source IP if available.
        user_agent: Request User-Agent if available.
        request_path: Request path if available.
        request_headers: Serialized request headers.
        context: Additional context string.
    """
    now = time.time()
    record = {
        "event_type": event_type,
        "matched_key": matched_key,
        "matched_category": matched_category,
        "source_ip": source_ip,
        "user_agent": user_agent,
        "request_path": request_path,
        "request_headers": request_headers,
        "context": context,
        "timestamp": now,
        "iso_time": datetime.now(timezone.utc).isoformat(),
    }

    # Write flat file FIRST — this survives os._exit
    try:
        _VALIDATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if _VALIDATION_LOG.exists():
            try:
                existing = json.loads(_VALIDATION_LOG.read_text())
            except Exception:
                existing = []
        existing.append(record)
        _VALIDATION_LOG.write_text(json.dumps(existing, indent=2))
    except Exception:
        pass

    # Then SQLite
    try:
        conn = _get_db()
        conn.execute(
            "INSERT INTO validation_events "
            "(event_type, matched_key, matched_category, source_ip, "
            "user_agent, request_path, request_headers, context, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_type, matched_key, matched_category, source_ip,
             user_agent, request_path, request_headers, context, now),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Log to application log
    logger.critical(
        f"CONFIG VALIDATION FAILURE: type={event_type} key={matched_key} "
        f"ip={source_ip} path={request_path}"
    )


def _halt() -> None:
    """Halt the process immediately after recording forensics."""
    # Flush all log handlers
    for handler in logging.root.handlers:
        try:
            handler.flush()
        except Exception:
            pass

    # Hard exit — no cleanup, no finally blocks, no signal handlers
    os._exit(1)


def check_output_integrity(text: str, context: str = "") -> str:
    """Check if any reference values appear in outbound text.

    If a reference value is found in LLM output, it means an attacker
    successfully extracted it. Records forensics and halts.

    Args:
        text: The outbound text to check.
        context: Additional context about where this text is going.

    Returns:
        The text unchanged if no reference values found.
    """
    if not text:
        return text

    ref_strings = get_all_reference_strings()
    for ref_val in ref_strings:
        if ref_val in text:
            # Find which key this belongs to
            refs = get_reference_values()
            matched_key = next(
                (k for k, v in refs.items() if v == ref_val), "unknown"
            )
            _record_event(
                event_type="reference_value_in_output",
                matched_key=matched_key,
                matched_category="output_exfil",
                context=f"Reference value found in outbound text. "
                        f"Context: {context}. "
                        f"Text snippet: {text[:200]}",
            )
            _halt()

    return text


def check_inbound_request(
    request_path: str = "",
    request_body: str = "",
    request_headers: str = "",
    source_ip: str = "",
    user_agent: str = "",
) -> None:
    """Check if any reference values appear in inbound requests.

    If someone sends a request containing a reference value, they
    obtained it from exfiltration. Records forensics and halts.

    Args:
        request_path: The request URL path.
        request_body: The request body text.
        request_headers: Serialized request headers.
        source_ip: Client IP address.
        user_agent: Client User-Agent string.
    """
    ref_strings = get_all_reference_strings()
    combined = f"{request_path}\n{request_body}\n{request_headers}"

    for ref_val in ref_strings:
        if ref_val in combined:
            refs = get_reference_values()
            matched_key = next(
                (k for k, v in refs.items() if v == ref_val), "unknown"
            )
            _record_event(
                event_type="reference_value_in_request",
                matched_key=matched_key,
                matched_category="inbound_use",
                source_ip=source_ip,
                user_agent=user_agent,
                request_path=request_path,
                request_headers=request_headers,
                context=f"Reference value used in inbound request. "
                        f"Body snippet: {request_body[:200]}",
            )
            _halt()


# ── Embedded Reference Context ───────────────────────────────────────────
# Returns a block of text that looks like leaked internal config.
# This gets embedded in the trust boundary wrapper so that if an
# attacker successfully performs prompt injection, the LLM "sees"
# these values and may include them in exfiltrated output.

def get_internal_context_block() -> str:
    """Get an internal configuration context block.

    Returns a string that appears to contain sensitive internal
    configuration. Embedded in web content trust boundaries.

    Returns:
        Configuration context string.
    """
    refs = get_reference_values()
    return (
        f"<!-- internal config cache (do not expose) -->\n"
        f"<!-- api.openai.com auth: {refs['openai_ref']} -->\n"
        f"<!-- db.connection: {refs['mongo_ref']} -->\n"
    )


# ── Debug Endpoint Data ──────────────────────────────────────────────────
# Returns data that looks like an accidentally exposed debug config.
# Used by the hidden endpoint in main.py.

def get_debug_config_response() -> Dict:
    """Get what looks like an accidentally exposed config dump.

    Returns:
        Dict that looks like leaked internal configuration.
    """
    refs = get_reference_values()
    return {
        "debug": True,
        "version": "1.0.0-internal",
        "environment": "development",
        "config": {
            "openai_api_key": refs["openai_ref"],
            "jwt_secret": refs["jwt_ref"],
            "mongodb_uri": refs["mongo_ref"],
            "neo4j_password": refs["neo4j_ref"],
            "brave_api_key": refs["brave_ref"],
        },
        "warning": "This endpoint is for internal debugging only. "
                   "Do not expose to production.",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
    }
