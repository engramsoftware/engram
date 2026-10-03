"""Hardened MCP git tools against throwaway repositories.

Covers the old branch's failure modes: a non-repo reported as clean, paths outside
the allowed roots, a missing directory reported as "git not found", and repo-local
config (core.fsmonitor, diff.external, filter drivers, partial-clone lazy fetch)
executing commands.
"""
import asyncio
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

if shutil.which("git") is None:
    pytest.skip("git is not installed", allow_module_level=True)

from mcp_tools import git_tools  # noqa: E402
from mcp_tools.git_tools import git_diff, git_log, git_status  # noqa: E402


def git(repo: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout


def executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def make_repo(path: Path, *, commit: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "commit.gpgsign", "false")
    if commit:
        (path / "a.txt").write_text("one\n")
        (path / "old name.txt").write_text("rename me\n")
        git(path, "add", ".")
        git(path, "commit", "-q", "-m", "first")
    return path


def marker_script(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """A script that creates a marker file when run (passes stdin through, for filters)."""
    marker = tmp_path / f"{name}.ran"
    script = tmp_path / f"{name}.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\ncat\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script, marker


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    root = tmp_path / "roots"
    root.mkdir()
    monkeypatch.setenv("ENGRAM_MCP_GIT_ROOTS", str(root))
    return root


# --- roots ---------------------------------------------------------------------

def test_allowed_roots_env_and_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_MCP_GIT_ROOTS", os.pathsep.join([str(tmp_path / "a"), "", str(tmp_path / "b")]))
    assert git_tools.allowed_roots() == [(tmp_path / "a").resolve(), (tmp_path / "b").resolve()]
    monkeypatch.delenv("ENGRAM_MCP_GIT_ROOTS")
    monkeypatch.chdir(tmp_path)
    assert git_tools.allowed_roots() == [tmp_path.resolve()]


def test_default_repo_is_first_root(roots):
    make_repo(roots)
    assert run(git_status())["repo"] == str(roots.resolve())


# --- status --------------------------------------------------------------------

def test_status_clean(roots):
    repo = make_repo(roots / "r")
    result = run(git_status(str(repo)))
    assert result == {
        "repo": str(repo.resolve()),
        "branch": "main",
        "clean": True,
        "changes": [],
        "truncated": False,
    }


def test_status_dirty(roots):
    repo = make_repo(roots / "r")
    git(repo, "checkout", "-q", "-b", "feature/x")
    (repo / "a.txt").write_text("two\n")
    (repo / "new file.txt").write_text("untracked\n")
    git(repo, "mv", "old name.txt", "new name.txt")

    result = run(git_status(str(repo)))
    assert result["branch"] == "feature/x"
    assert result["clean"] is False
    by_path = {c["path"]: c for c in result["changes"]}
    assert by_path["a.txt"]["status"] == "M"
    assert by_path["new file.txt"]["status"] == "??"
    assert by_path["new name.txt"]["status"] == "R"
    assert by_path["new name.txt"]["orig_path"] == "old name.txt"
    assert len(result["changes"]) == 3


def test_status_caps_changes(roots, monkeypatch):
    repo = make_repo(roots / "r")
    for i in range(5):
        (repo / f"u{i}.txt").write_text("x")
    monkeypatch.setattr(git_tools, "MAX_STATUS_CHANGES", 3)
    result = run(git_status(str(repo)))
    assert len(result["changes"]) == 3
    assert result["truncated"] is True


def test_status_empty_repo_branch(roots):
    repo = make_repo(roots / "r", commit=False)
    result = run(git_status(str(repo)))
    assert result["branch"] == "main"
    assert result["clean"] is True


# --- path validation -----------------------------------------------------------

def test_non_repo_inside_roots_raises(roots):
    plain = roots / "plain"
    plain.mkdir()
    for call in (git_status(str(plain)), git_log(str(plain)), git_diff(str(plain))):
        with pytest.raises(RuntimeError, match="not a git repository"):
            run(call)


def test_path_outside_roots_raises(roots, tmp_path):
    outside = make_repo(tmp_path / "outside")
    with pytest.raises(ValueError, match="outside ENGRAM_MCP_GIT_ROOTS"):
        run(git_status(str(outside)))
    with pytest.raises(ValueError, match="outside ENGRAM_MCP_GIT_ROOTS"):
        run(git_log(str(roots / ".." / "outside")))


def test_missing_directory_is_value_error(roots):
    with pytest.raises(ValueError, match="does not exist"):
        run(git_status(str(roots / "nope")))


def test_file_is_not_a_directory(roots):
    f = roots / "file.txt"
    f.write_text("x")
    with pytest.raises(ValueError, match="not a directory"):
        run(git_diff(str(f)))


def test_symlink_pointing_outside_is_rejected(roots, tmp_path):
    outside = make_repo(tmp_path / "outside")
    link = roots / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside ENGRAM_MCP_GIT_ROOTS"):
        run(git_status(str(link)))


def test_worktree_outside_roots_is_rejected(roots, tmp_path):
    repo = make_repo(roots / "r")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    git(repo, "config", "core.worktree", str(elsewhere))
    with pytest.raises(ValueError, match="work tree"):
        run(git_status(str(repo)))


# --- log -----------------------------------------------------------------------

def test_log_clamps_limit(roots):
    repo = make_repo(roots / "r")
    git(repo, "commit", "-q", "--allow-empty", "-m", "second\x1f with | odd \t chars")
    assert len(run(git_log(str(repo), limit=-5))["commits"]) == 1

    result = run(git_log(str(repo), limit=10**6))
    assert result["branch"] == "main"
    commits = result["commits"]
    assert 1 < len(commits) <= 200
    assert commits[0]["subject"] == "second\x1f with | odd \t chars"
    assert commits[1]["subject"] == "first"
    assert commits[0]["author"] == "Test"
    assert len(commits[0]["hash"]) == 40
    assert commits[0]["hash"].startswith(commits[0]["short"])
    assert commits[0]["date"][:4].isdigit()


def test_log_empty_repo(roots):
    repo = make_repo(roots / "r", commit=False)
    assert run(git_log(str(repo))) == {"repo": str(repo.resolve()), "branch": "main", "commits": []}


def test_log_bad_limit(roots):
    repo = make_repo(roots / "r")
    with pytest.raises(ValueError):
        run(git_log(str(repo), limit="many"))


# --- diff ----------------------------------------------------------------------

def test_diff_working_vs_staged(roots):
    repo = make_repo(roots / "r")
    (repo / "a.txt").write_text("staged\n")
    git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("working\n")

    working = run(git_diff(str(repo)))
    staged = run(git_diff(str(repo), staged=True))
    assert working["staged"] is False and staged["staged"] is True
    assert "-staged\n+working" in working["diff"]
    assert "-one\n+staged" in staged["diff"]
    assert not working["truncated"] and not staged["truncated"]


def test_diff_clean_is_empty(roots):
    repo = make_repo(roots / "r")
    assert run(git_diff(str(repo)))["diff"] == ""


def test_diff_truncates_big_output(roots):
    repo = make_repo(roots / "r")
    (repo / "a.txt").write_text("".join(f"line {i} {'x' * 60}\n" for i in range(10_000)))
    result = run(git_diff(str(repo)))
    assert result["truncated"] is True
    assert len(result["diff"]) == git_tools.MAX_DIFF_CHARS


# --- repo-local config must not execute anything -------------------------------

def test_fsmonitor_hook_not_run(roots, tmp_path):
    repo = make_repo(roots / "r")
    script, marker = marker_script(tmp_path, "fsmonitor")
    git(repo, "config", "core.fsmonitor", str(script))
    (repo / "a.txt").write_text("changed\n")

    run(git_status(str(repo)))
    run(git_diff(str(repo)))
    run(git_diff(str(repo), staged=True))
    run(git_log(str(repo)))
    assert not marker.exists()


def test_diff_external_not_run(roots, tmp_path):
    repo = make_repo(roots / "r")
    script, marker = marker_script(tmp_path, "extdiff")
    git(repo, "config", "diff.external", str(script))
    (repo / ".gitattributes").write_text("*.txt diff=evil\n")
    git(repo, "config", "diff.evil.command", str(script))
    git(repo, "config", "diff.evil.textconv", str(script))
    (repo / "a.txt").write_text("changed\n")
    git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("changed again\n")

    working = run(git_diff(str(repo)))
    staged = run(git_diff(str(repo), staged=True))
    assert "+changed again" in working["diff"]
    assert "+changed" in staged["diff"]
    assert not marker.exists()


def test_filter_driver_not_run(roots, tmp_path):
    repo = make_repo(roots / "r")
    script, marker = marker_script(tmp_path, "filter")
    (repo / ".gitattributes").write_text("*.txt filter=evil\n")
    git(repo, "config", "filter.evil.clean", str(script))
    git(repo, "config", "filter.evil.smudge", str(script))
    git(repo, "config", "filter.evil.required", "true")
    # Same content, new mtime: git has to re-read (and would filter) the file.
    st = (repo / "a.txt").stat()
    os.utime(repo / "a.txt", (st.st_atime + 100, st.st_mtime + 100))

    run(git_status(str(repo)))
    run(git_diff(str(repo)))
    assert not marker.exists()


def test_status_does_not_rewrite_index(roots):
    repo = make_repo(roots / "r")
    index = repo / ".git" / "index"
    st = (repo / "a.txt").stat()
    os.utime(repo / "a.txt", (st.st_atime + 100, st.st_mtime + 100))
    before = index.stat().st_mtime_ns
    run(git_status(str(repo)))
    assert index.stat().st_mtime_ns == before


# --- git missing ---------------------------------------------------------------

def test_git_missing_raises_runtime_error(roots, monkeypatch):
    repo = make_repo(roots / "r")
    monkeypatch.setattr(git_tools.shutil, "which", lambda name: None)
    assert git_tools.git_available() is False
    for call in (git_status(str(repo)), git_log(str(repo)), git_diff(str(repo))):
        with pytest.raises(RuntimeError, match="git is not installed"):
            run(call)


def test_missing_dir_beats_missing_git(roots, monkeypatch):
    monkeypatch.setattr(git_tools.shutil, "which", lambda name: None)
    with pytest.raises(ValueError):
        run(git_status(str(roots / "nope")))


def test_timeout_raises(roots, monkeypatch):
    repo = make_repo(roots / "r")
    monkeypatch.setattr(git_tools, "TIMEOUT_SECONDS", 0.0)
    with pytest.raises(RuntimeError, match="timed out"):
        run(git_status(str(repo)))


# --- regressions from the adversarial review -----------------------------------

def test_filter_name_containing_equals_not_run(roots, tmp_path):
    # `-c filter.a=b.clean=` would split at the first "=" and leave the driver live.
    repo = make_repo(roots / "r")
    script, marker = marker_script(tmp_path, "filter")
    (repo / ".gitattributes").write_text("*.txt filter=a=b\n")
    git(repo, "config", "filter.a=b.clean", str(script))
    git(repo, "config", "filter.a=b.required", "true")
    st = (repo / "a.txt").stat()
    os.utime(repo / "a.txt", (st.st_atime + 100, st.st_mtime + 100))

    run(git_status(str(repo)))
    run(git_diff(str(repo)))
    assert not marker.exists()


def _partial_clone_missing_blob(repo: Path, tmp_path: Path, kind: str) -> Path:
    """Make diff need a blob the repo claims a promisor remote can lazily supply."""
    script, marker = marker_script(tmp_path, f"lazy-{kind}")
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")  # no `cat`: nothing to pass through
    blob = git(repo, "rev-parse", "HEAD:a.txt").strip()
    (repo / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
    git(repo, "config", "core.repositoryformatversion", "1")
    git(repo, "config", "extensions.partialClone", "origin")
    git(repo, "config", "remote.origin.promisor", "true")
    git(repo, "config", "protocol.allow", "always")
    for proto in ("ext", "file", "ssh"):
        git(repo, "config", f"protocol.{proto}.allow", "always")
    if kind == "ext":
        git(repo, "config", "remote.origin.url", f"ext::{script}")
    elif kind == "uploadpack":
        git(repo, "config", "remote.origin.url", f"file://{tmp_path}")
        git(repo, "config", "remote.origin.uploadpack", f"{script}; git-upload-pack")
    else:
        git(repo, "config", "remote.origin.url", "ssh://example.invalid/x")
        git(repo, "config", "core.sshCommand", str(script))
    (repo / "a.txt").write_text("two\n")
    return marker


@pytest.mark.parametrize("kind", ["ext", "uploadpack", "ssh"])
@pytest.mark.parametrize("keep_lazy_fetch_guard", [True, False])
def test_partial_clone_lazy_fetch_runs_nothing(roots, tmp_path, monkeypatch, kind, keep_lazy_fetch_guard):
    # Without GIT_NO_LAZY_FETCH (older git ignores it) the transport block must hold alone.
    if not keep_lazy_fetch_guard:
        orig = git_tools._git_env
        monkeypatch.setattr(
            git_tools, "_git_env", lambda root: {k: v for k, v in orig(root).items() if k != "GIT_NO_LAZY_FETCH"}
        )
    repo = make_repo(roots / "r")
    marker = _partial_clone_missing_blob(repo, tmp_path, kind)
    for call in (git_diff(str(repo)), git_diff(str(repo), staged=True), git_status(str(repo))):
        try:
            run(call)
        except RuntimeError:
            pass  # the missing blob is an error; running the remote's command is the bug
    assert not marker.exists()


def test_gitfile_pointing_outside_is_rejected(roots, tmp_path):
    outside = make_repo(tmp_path / "secret")
    inner = roots / "r"
    inner.mkdir()
    (inner / ".git").write_text(f"gitdir: {outside / '.git'}\n")
    for call in (git_status(str(inner)), git_log(str(inner)), git_diff(str(inner))):
        with pytest.raises(ValueError, match="git directory .* outside"):
            run(call)


def test_symlinked_dotgit_pointing_outside_is_rejected(roots, tmp_path):
    outside = make_repo(tmp_path / "secret")
    inner = roots / "r"
    inner.mkdir()
    (inner / ".git").symlink_to(outside / ".git", target_is_directory=True)
    with pytest.raises(ValueError, match="git directory .* outside"):
        run(git_log(str(inner)))


def test_linked_worktree_inside_roots_works(roots):
    repo = make_repo(roots / "r")
    git(repo, "worktree", "add", "-q", "-b", "wt", str(roots / "wt"))
    result = run(git_log(str(roots / "wt")))
    assert result["branch"] == "wt"
    assert result["commits"][0]["subject"] == "first"


def test_repo_above_root_is_not_discovered(tmp_path, monkeypatch):
    make_repo(tmp_path / "up")
    (tmp_path / "up" / "sub").mkdir()
    monkeypatch.setenv("ENGRAM_MCP_GIT_ROOTS", str(tmp_path / "up" / "sub"))
    with pytest.raises(RuntimeError, match="not a git repository"):
        run(git_status())


def test_pathological_filenames(roots):
    repo = make_repo(roots / "r")
    names = {"new\nline.txt", '-rf "q".txt', "## x", "R  y", "tab\tx", "--help"}
    for name in names:
        (repo / name).write_text("x")
    git(repo, "add", "--", "-rf \"q\".txt")
    git(repo, "commit", "-q", "-m", "q")
    git(repo, "mv", "--", "-rf \"q\".txt", "-n\nx.txt")
    changes = run(git_status(str(repo)))["changes"]
    by_path = {c["path"]: c for c in changes}
    assert set(by_path) == (names - {'-rf "q".txt'}) | {"-n\nx.txt"}
    assert by_path["-n\nx.txt"] == {"status": "R", "path": "-n\nx.txt", "orig_path": '-rf "q".txt'}


def test_directory_name_with_trailing_whitespace(roots):
    repo = make_repo(roots / "r \n")
    assert run(git_status(str(repo)))["repo"] == str(repo.resolve())


@pytest.mark.parametrize("bad", ["a\0b", "x" * 5000, "~no_such_user_zz/x"])
def test_unusable_repo_path_is_value_error(roots, bad):
    with pytest.raises(ValueError):
        run(git_status(bad))


def test_relative_repo_path_is_relative_to_first_root(roots, tmp_path, monkeypatch):
    make_repo(roots / "r")
    monkeypatch.chdir(tmp_path)
    assert run(git_status("r"))["repo"] == str((roots / "r").resolve())
    with pytest.raises(ValueError, match="outside"):
        run(git_status("../outside"))


@pytest.mark.parametrize("limit", [float("inf"), True])
def test_log_rejects_odd_limits(roots, limit):
    repo = make_repo(roots / "r")
    with pytest.raises(ValueError, match="limit"):
        run(git_log(str(repo), limit=limit))


def test_diff_staged_must_be_bool(roots):
    repo = make_repo(roots / "r")
    with pytest.raises(ValueError, match="staged"):
        run(git_diff(str(repo), staged="false"))


def test_log_author_with_separator_keeps_hash_and_date(roots):
    repo = make_repo(roots / "r")
    git(repo, "-c", "user.name=Ev\x1fil", "commit", "-q", "--allow-empty", "-m", "s")
    commit = run(git_log(str(repo)))["commits"][0]
    assert len(commit["hash"]) == 40
    assert commit["date"][:4].isdigit()
    assert commit["author"] == "Ev"


def test_log_ignores_repo_output_encoding(roots):
    repo = make_repo(roots / "r")
    git(repo, "config", "i18n.logOutputEncoding", "UTF-16")
    commits = run(git_log(str(repo)))["commits"]
    assert [c["subject"] for c in commits] == ["first"]


def test_thousands_of_filter_drivers_is_runtime_error(roots):
    repo = make_repo(roots / "r")
    with open(repo / ".git" / "config", "a") as f:
        for i in range(60_000):
            f.write(f'[filter "{"n" * 40}{i}"]\n\tclean = x\n')
    with pytest.raises(RuntimeError):
        run(git_status(str(repo)))


def test_timeout_kills_helper_processes(roots, tmp_path, monkeypatch):
    # asyncio's wait() blocks until every pipe closes, so a surviving child that
    # inherited stdout used to hang the tool forever despite the timeout.
    fake = executable(tmp_path / "fake-git", "#!/bin/sh\nsleep 30 &\nsleep 30\n")
    monkeypatch.setattr(git_tools.shutil, "which", lambda name: str(fake))
    monkeypatch.setattr(git_tools, "TIMEOUT_SECONDS", 0.5)
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        run(git_status(str(roots)))
    assert time.monotonic() - start < 10


def test_huge_stderr_is_drained_and_capped(roots, tmp_path, monkeypatch):
    fake = executable(tmp_path / "fake-git", "#!/bin/sh\nhead -c 3000000 /dev/zero | tr '\\0' e >&2\nexit 1\n")
    monkeypatch.setattr(git_tools.shutil, "which", lambda name: str(fake))
    with pytest.raises(RuntimeError) as excinfo:
        run(git_status(str(roots)))
    assert 0 < len(str(excinfo.value)) <= 2000
