"""Opt-in audit log of MCP tool calls.

The old branch wrote every tool call to ``<repo>/data/mcp_audit.log`` unconditionally:
outside the data volume (unwritable for the unprivileged container user), never rotated,
and at odds with main's "no auto-logging of tool calls" rule. This version:

* is OFF unless ``MCP_AUDIT_LOG=1`` (read on every call, not cached at import);
* writes to ``config.MCP_DATA_DIR / "audit.log"`` (the data volume), created with mode 0600
  and rotated by size (``MAX_BYTES`` x ``BACKUP_COUNT`` backups);
* records only ``ts``, ``tool``, ``outcome`` and ``duration_ms`` - never arguments, URLs,
  repo paths, results or user ids. The tool name and outcome are validated against a fixed
  shape so nothing user-controlled can reach the file;
* refuses to write through a symlink, hard link, FIFO or other non-regular file at the log
  path (anyone who can write to the data dir could otherwise redirect our appends, or hang
  every tool call on a FIFO), and forces 0600 on a pre-existing log file;
* writes straight to its own handler under a lock instead of through a named logger, so no
  other code logging to that name can put free text in the file and ``logging.disable``
  cannot silently switch auditing off;
* never raises and never touches stdout (the MCP server's stdout is the JSON-RPC channel).
  An I/O failure is reported once as a warning on this module's logger (stderr).
"""
from __future__ import annotations

import fcntl
import json
import logging
import math
import os
import re
import stat
import sys
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config

ENV_VAR = "MCP_AUDIT_LOG"
AUDIT_FILENAME = "audit.log"
# Name stamped on audit records; no handler is ever attached to a logger of this name.
AUDIT_LOGGER_NAME = "engram.mcp.audit"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3
FILE_MODE = 0o600

_TOOL_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_OUTCOMES = frozenset({"success", "failure"})
# ~31 years; keeps absurd ints (and their float conversion overflow) out of the file.
_MAX_DURATION_MS = 10**12

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_handler: RotatingFileHandler | None = None
# (path, max_bytes, backup_count) the current handler was built for.
_handler_key: tuple[str, int, int] | None = None
_warned = False


def audit_enabled() -> bool:
    """True only when ``MCP_AUDIT_LOG`` is exactly ``"1"``."""
    return os.environ.get(ENV_VAR) == "1"


def _warn_once(exc: BaseException) -> None:
    global _warned
    if _warned:
        return
    _warned = True
    try:
        logger.warning("MCP audit log write failed (further failures are not reported): %s: %s",
                       type(exc).__name__, exc)
    except Exception:  # a broken stderr handler must not turn auditing into a crash
        pass


def _private_opener(path: str, flags: int) -> int:
    # O_NOFOLLOW: no writing through a planted symlink. O_NONBLOCK: a FIFO with no reader
    # fails with ENXIO instead of blocking (while holding _lock) forever.
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, FILE_MODE)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError(f"audit log path is not a regular file: {path}")
        if st.st_nlink != 1:
            raise OSError(f"audit log file has {st.st_nlink} hard links: {path}")
        if stat.S_IMODE(st.st_mode) != FILE_MODE:
            os.fchmod(fd, FILE_MODE)  # pre-existing file, or a umask that dropped owner bits
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)
    except BaseException:
        os.close(fd)
        raise
    return fd


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that creates every file (including after rollover) as 0600
    and reports write errors through ``_warn_once`` instead of printing a traceback."""

    def _open(self):  # type: ignore[override]
        return open(self.baseFilename, self.mode, encoding=self.encoding,
                    errors=self.errors, opener=_private_opener)

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 (logging API)
        exc = sys.exc_info()[1]
        _warn_once(exc if exc is not None else OSError("unknown audit log write error"))


def _get_handler_locked() -> RotatingFileHandler:
    """Return the file handler, (re)building it if the target changed. Caller holds _lock."""
    global _handler, _handler_key
    path = Path(os.path.abspath(Path(config.MCP_DATA_DIR) / AUDIT_FILENAME))
    key = (str(path), MAX_BYTES, BACKUP_COUNT)
    if _handler is not None and _handler_key == key:
        return _handler
    _close_handler_locked()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _PrivateRotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _handler, _handler_key = handler, key
    return handler


def _close_handler_locked() -> None:
    global _handler, _handler_key
    if _handler is not None:
        try:
            _handler.close()
        except OSError:
            pass
    _handler, _handler_key = None, None


def _close_handler() -> None:
    """Close the file handler (used by tests and on shutdown)."""
    with _lock:
        _close_handler_locked()


def _sanitize_duration(duration_ms: object) -> int:
    try:
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)):
            return 0
        if isinstance(duration_ms, float) and not math.isfinite(duration_ms):
            return 0
        if duration_ms < 0:
            return 0
        return int(min(round(duration_ms), _MAX_DURATION_MS))
    except Exception:  # hostile numeric subclasses
        return 0


def record_tool_call(tool: str, outcome: str, duration_ms: float) -> None:
    """Append one JSON line for a tool call if auditing is enabled. Never raises."""
    try:
        if not audit_enabled():
            return
        # Exact str only: a subclass can override __eq__/__hash__ and smuggle its real
        # contents past the checks.
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "tool": tool if type(tool) is str and _TOOL_RE.fullmatch(tool) else "invalid",
            "outcome": outcome if type(outcome) is str and outcome in _OUTCOMES else "invalid",
            "duration_ms": _sanitize_duration(duration_ms),
        }
        record = logging.LogRecord(AUDIT_LOGGER_NAME, logging.INFO, __file__, 0,
                                   json.dumps(entry, separators=(",", ":")), None, None)
        with _lock:
            _get_handler_locked().handle(record)
    except Exception as exc:  # auditing must never break a tool call
        _warn_once(exc)
