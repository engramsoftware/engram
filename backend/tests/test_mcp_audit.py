"""Tests for the opt-in MCP audit log (mcp_tools.audit)."""
import json
import logging
import os
import stat
import threading
from datetime import datetime
from decimal import Decimal

import pytest

import config
from mcp_tools import audit


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "mcp"
    monkeypatch.setattr(config, "MCP_DATA_DIR", d)
    monkeypatch.delenv(audit.ENV_VAR, raising=False)
    monkeypatch.setattr(audit, "_warned", False)
    audit._close_handler()
    yield d
    audit._close_handler()


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_disabled_by_default_creates_nothing(data_dir):
    assert audit.audit_enabled() is False
    audit.record_tool_call("fetch_url", "success", 12.3)
    assert not data_dir.exists()


@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
def test_only_exact_one_enables(data_dir, monkeypatch, value):
    monkeypatch.setenv(audit.ENV_VAR, value)
    assert audit.audit_enabled() is False


def test_enabled_writes_one_line_per_call_with_only_four_keys(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call("fetch_url", "success", 12.6)
    audit.record_tool_call("git.log", "failure", 3.2)
    entries = _lines(data_dir / "audit.log")
    assert len(entries) == 2
    for e in entries:
        assert set(e) == {"ts", "tool", "outcome", "duration_ms"}
        assert datetime.fromisoformat(e["ts"]).utcoffset().total_seconds() == 0
    assert entries[0] == {**entries[0], "tool": "fetch_url", "outcome": "success", "duration_ms": 13}
    assert entries[1] == {**entries[1], "tool": "git.log", "outcome": "failure", "duration_ms": 3}


def test_toggle_is_read_at_call_time(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call("a", "success", 1)
    monkeypatch.setenv(audit.ENV_VAR, "0")
    audit.record_tool_call("b", "success", 1)
    assert [e["tool"] for e in _lines(data_dir / "audit.log")] == ["a"]


@pytest.mark.parametrize("tool", [
    "", "x" * 65, "has space", "../etc/passwd", "evil\n{\"tool\":\"x\"}",
    "https://example.com", "ünïcode", None, 42,
])
def test_invalid_tool_names_are_sanitized(data_dir, monkeypatch, tool):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call(tool, "success", 1)
    (entry,) = _lines(data_dir / "audit.log")
    assert entry["tool"] == "invalid"


@pytest.mark.parametrize("outcome", ["ok", "SUCCESS", "/home/user/repo", None, ["success"]])
def test_invalid_outcomes_are_sanitized(data_dir, monkeypatch, outcome):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call("fetch_url", outcome, 1)
    (entry,) = _lines(data_dir / "audit.log")
    assert entry["outcome"] == "invalid"


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -5, "10", None])
def test_bad_durations_become_zero(data_dir, monkeypatch, duration):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call("fetch_url", "success", duration)
    (entry,) = _lines(data_dir / "audit.log")
    assert entry["duration_ms"] == 0


def test_rotation_past_max_bytes(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    monkeypatch.setattr(audit, "MAX_BYTES", 200)
    monkeypatch.setattr(audit, "BACKUP_COUNT", 2)
    for _ in range(30):
        audit.record_tool_call("fetch_url", "success", 1)
    log = data_dir / "audit.log"
    assert (data_dir / "audit.log.1").exists()
    assert (data_dir / "audit.log.2").exists()
    assert not (data_dir / "audit.log.3").exists()
    for p in (log, data_dir / "audit.log.1", data_dir / "audit.log.2"):
        assert p.stat().st_size <= 200
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_file_mode_is_600(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    old = os.umask(0o022)
    try:
        audit.record_tool_call("fetch_url", "success", 1)
    finally:
        os.umask(old)
    assert stat.S_IMODE((data_dir / "audit.log").stat().st_mode) == 0o600


def test_handler_follows_path_change(data_dir, tmp_path, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call("first", "success", 1)
    other = tmp_path / "other"
    monkeypatch.setattr(config, "MCP_DATA_DIR", other)
    audit.record_tool_call("second", "success", 1)
    assert [e["tool"] for e in _lines(data_dir / "audit.log")] == ["first"]
    assert [e["tool"] for e in _lines(other / "audit.log")] == ["second"]
    assert audit._handler.baseFilename == str(other / "audit.log")


def test_audit_logger_does_not_propagate(data_dir, monkeypatch):
    seen = []

    class Spy(logging.Handler):
        def emit(self, record):
            seen.append(record)

    spy = Spy(level=logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(spy)
    try:
        monkeypatch.setenv(audit.ENV_VAR, "1")
        audit.record_tool_call("fetch_url", "success", 1)
    finally:
        root.removeHandler(spy)
    assert not logging.getLogger(audit.AUDIT_LOGGER_NAME).handlers
    assert not [r for r in seen if r.name == audit.AUDIT_LOGGER_NAME]


def test_unwritable_dir_does_not_raise_and_warns_once(tmp_path, monkeypatch, caplog, capsys):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    monkeypatch.setattr(config, "MCP_DATA_DIR", blocker / "mcp")
    monkeypatch.setenv(audit.ENV_VAR, "1")
    monkeypatch.setattr(audit, "_warned", False)
    audit._close_handler()
    with caplog.at_level(logging.WARNING, logger=audit.__name__):
        audit.record_tool_call("fetch_url", "success", 1)
        audit.record_tool_call("fetch_url", "success", 1)
    warnings = [r for r in caplog.records if r.name == audit.__name__]
    assert len(warnings) == 1
    assert capsys.readouterr().out == ""


def test_write_error_after_open_is_swallowed(data_dir, monkeypatch, caplog, capsys):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call("fetch_url", "success", 1)

    def boom(self, record):
        raise OSError("disk full")

    # shouldRollover runs inside the handler's own try/except, like a failing write would.
    monkeypatch.setattr(audit._PrivateRotatingFileHandler, "shouldRollover", boom)
    with caplog.at_level(logging.WARNING, logger=audit.__name__):
        audit.record_tool_call("fetch_url", "success", 1)
        audit.record_tool_call("fetch_url", "success", 1)
    assert len([r for r in caplog.records if r.name == audit.__name__]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err


# --- regression tests from adversarial review -------------------------------------------

def test_refuses_to_write_through_symlink(data_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    data_dir.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("orig\n")
    (data_dir / "audit.log").symlink_to(victim)
    audit.record_tool_call("fetch_url", "success", 1)
    assert victim.read_text() == "orig\n"
    assert audit._warned is True
    assert capsys.readouterr().out == ""


def test_refuses_hard_linked_log(data_dir, tmp_path, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    data_dir.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("orig\n")
    os.link(victim, data_dir / "audit.log")
    audit.record_tool_call("fetch_url", "success", 1)
    assert victim.read_text() == "orig\n"


def test_fifo_at_log_path_does_not_block(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    data_dir.mkdir()
    os.mkfifo(data_dir / "audit.log")
    t = threading.Thread(target=audit.record_tool_call, args=("fetch_url", "success", 1),
                         daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive()
    assert audit._warned is True


def test_symlink_planted_before_rollover_is_not_followed(data_dir, tmp_path, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    monkeypatch.setattr(audit, "MAX_BYTES", 200)
    audit.record_tool_call("fetch_url", "success", 1)
    victim = tmp_path / "victim"
    victim.write_text("orig\n")
    # Rollover renames audit.log away and reopens the name; plant a link at the name it reopens.
    real_rotate = audit._PrivateRotatingFileHandler.rotate

    def rotate_then_plant(self, source, dest):
        real_rotate(self, source, dest)
        os.symlink(victim, source)

    monkeypatch.setattr(audit._PrivateRotatingFileHandler, "rotate", rotate_then_plant)
    for _ in range(5):
        audit.record_tool_call("fetch_url", "success", 1)
    assert victim.read_text() == "orig\n"


def test_existing_world_readable_file_is_tightened_to_600(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    data_dir.mkdir()
    log = data_dir / "audit.log"
    log.write_text("")
    log.chmod(0o644)
    audit.record_tool_call("fetch_url", "success", 1)
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert len(_lines(log)) == 1


def test_umask_dropping_owner_write_still_gives_600(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    old = os.umask(0o277)
    try:
        audit.record_tool_call("fetch_url", "success", 1)
    finally:
        os.umask(old)
    log = data_dir / "audit.log"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert len(_lines(log)) == 1


@pytest.mark.parametrize("duration,expected", [
    (10**400, 10**12), (1e300, 10**12), (Decimal("5"), 0), (True, 0),
])
def test_extreme_durations_are_clamped_not_dropped(data_dir, monkeypatch, duration, expected):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call("fetch_url", "success", duration)
    (entry,) = _lines(data_dir / "audit.log")
    assert entry["duration_ms"] == expected
    assert audit._warned is False


def test_str_subclass_cannot_smuggle_content(data_dir, monkeypatch):
    class Sneaky(str):
        def __hash__(self):
            return hash("success")

        def __eq__(self, other):
            return True

    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call(Sneaky("fetch_url"), Sneaky("SECRET-TOKEN"), 1)
    (entry,) = _lines(data_dir / "audit.log")
    assert entry["outcome"] == "invalid"
    assert entry["tool"] == "invalid"
    assert "SECRET" not in (data_dir / "audit.log").read_text()


def test_other_code_logging_to_audit_name_cannot_write_to_file(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    audit.record_tool_call("fetch_url", "success", 1)
    logging.getLogger(audit.AUDIT_LOGGER_NAME).warning("free text /home/user/secret")
    entries = _lines(data_dir / "audit.log")
    assert len(entries) == 1
    assert set(entries[0]) == {"ts", "tool", "outcome", "duration_ms"}


def test_logging_disable_does_not_silence_audit(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    logging.disable(logging.CRITICAL)
    try:
        audit.record_tool_call("fetch_url", "success", 1)
    finally:
        logging.disable(logging.NOTSET)
    assert len(_lines(data_dir / "audit.log")) == 1


def test_concurrent_writes_lose_nothing_across_rotation(data_dir, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    monkeypatch.setattr(audit, "MAX_BYTES", 2000)
    monkeypatch.setattr(audit, "BACKUP_COUNT", 1000)
    n_threads, per_thread = 8, 100

    def work(i):
        for _ in range(per_thread):
            audit.record_tool_call(f"t{i}", "success", 1)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    entries = [e for p in data_dir.iterdir() for e in _lines(p)]
    assert len(entries) == n_threads * per_thread
    assert audit._warned is False


def test_path_changes_from_another_thread_lose_nothing(data_dir, tmp_path, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    a, b = tmp_path / "a", tmp_path / "b"
    stop = threading.Event()

    def flip():
        i = 0
        while not stop.is_set():
            config.MCP_DATA_DIR = a if i % 2 else b
            i += 1
            stop.wait(0.0005)

    t = threading.Thread(target=flip)
    t.start()
    try:
        for _ in range(300):
            audit.record_tool_call("fetch_url", "success", 1)
    finally:
        stop.set()
        t.join()
    total = sum(len(_lines(p / "audit.log")) for p in (a, b) if (p / "audit.log").exists())
    assert total == 300
    assert audit._warned is False


def test_relative_data_dir_is_resolved_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setenv(audit.ENV_VAR, "1")
    monkeypatch.setattr(audit, "_warned", False)
    monkeypatch.setattr(config, "MCP_DATA_DIR", "mcp")
    audit._close_handler()
    try:
        (tmp_path / "one").mkdir()
        (tmp_path / "two").mkdir()
        monkeypatch.chdir(tmp_path / "one")
        audit.record_tool_call("first", "success", 1)
        monkeypatch.chdir(tmp_path / "two")
        audit.record_tool_call("second", "success", 1)
    finally:
        audit._close_handler()
    assert [e["tool"] for e in _lines(tmp_path / "one" / "mcp" / "audit.log")] == ["first"]
    assert [e["tool"] for e in _lines(tmp_path / "two" / "mcp" / "audit.log")] == ["second"]
