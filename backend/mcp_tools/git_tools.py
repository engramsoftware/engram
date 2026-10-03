"""Read-only git tools for the MCP server (status, log, diff), safe to point at untrusted checkouts.

The old versions took any repo_path and ran plain `git` there. A checkout's own
.git/config can execute commands (core.fsmonitor, diff.external, textconv,
filter drivers, log.showSignature -> gpg.program), so these:

- only run inside ENGRAM_MCP_GIT_ROOTS (symlinks resolved first), and never let
  git discover a repository above the matching root, or use a work tree or a git
  directory (a `.git` file or symlink can point anywhere) outside the roots;
- override every config knob that can launch a program, and ignore system config;
- block every transport, because a partial clone lazily fetches missing objects
  and the repo config picks the remote (ext::, remote.*.uploadpack, core.sshCommand);
- check return codes, so a non-repo is an error and not "clean";
- run git as an async subprocess with a timeout instead of blocking the event loop.

Errors raise (ValueError for bad input / blocked paths, RuntimeError for git
failures) so the MCP server reports them with isError=true.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from pathlib import Path

logger = logging.getLogger(__name__)

ROOTS_ENV = "ENGRAM_MCP_GIT_ROOTS"
TIMEOUT_SECONDS = 20.0
MAX_STATUS_CHANGES = 500
MAX_LOG_LIMIT = 200
MAX_DIFF_CHARS = 200_000
# Hard cap on what we read from any git process, so a huge repo cannot exhaust memory.
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024

# Command-line scope beats repo config. These go in GIT_CONFIG_COUNT/KEY/VALUE rather than
# `-c key=value`, because `-c` splits at the first "=" and a subsection name (e.g. a filter
# called "a=b") may contain one. Child git processes inherit the variables.
_SAFE_CONFIG: tuple[tuple[str, str], ...] = (
    ("core.fsmonitor", "false"),
    ("core.hooksPath", "/dev/null"),
    ("core.pager", "cat"),
    ("diff.external", ""),
    ("diff.relative", "false"),
    ("log.showSignature", "false"),
)

_UNIT = "\x1f"


def git_available() -> bool:
    return shutil.which("git") is not None


def allowed_roots() -> list[Path]:
    raw = os.environ.get(ROOTS_ENV, "")
    roots = [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]
    return roots or [Path.cwd().resolve()]


def _containing_root(path: Path, roots: list[Path]) -> Path | None:
    for root in roots:
        if path.is_relative_to(root):
            return root
    return None


def _resolve_repo(repo_path: str | None) -> tuple[Path, Path]:
    """Return (resolved directory, the allowed root that contains it)."""
    roots = allowed_roots()
    if repo_path is not None and not isinstance(repo_path, str):
        raise ValueError("repo_path must be a string")
    try:
        if repo_path is None or not repo_path.strip():
            path = roots[0]
        else:
            # Relative paths are relative to the first root, not the server's cwd.
            path = (roots[0] / Path(repo_path).expanduser()).resolve()
        exists, is_dir = path.exists(), path.is_dir()
    except (OSError, RuntimeError, ValueError) as e:
        # NUL bytes, over-long names, "~nosuchuser", symlink loops.
        raise ValueError(f"invalid repo_path: {e}") from e
    if not exists:
        raise ValueError(f"repo_path does not exist: {path}")
    if not is_dir:
        raise ValueError(f"repo_path is not a directory: {path}")
    root = _containing_root(path, roots)
    if root is None:
        raise ValueError(f"repo_path {path} is outside {ROOTS_ENV}")
    return path, root


def _git_env(root: Path) -> dict[str, str]:
    # Drop inherited GIT_* (GIT_DIR, GIT_WORK_TREE, GIT_EXTERNAL_DIFF, GIT_CONFIG_*, ...) so
    # the caller's environment cannot redirect or reconfigure git.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
        # Allow-list of transports that overrides protocol.*.allow in any config; empty = none.
        GIT_ALLOW_PROTOCOL="",
        GIT_NO_LAZY_FETCH="1",
    )
    # Discovery may walk up to the root itself but not into its parent.
    if root.parent != root:
        env["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    return env


class _Git:
    """One validated repo directory plus the hardened way to run git in it."""

    def __init__(self, cwd: Path, root: Path, git: str) -> None:
        self.cwd = cwd
        self.root = root
        self.git = git
        self.base_env = _git_env(root)
        self.config: list[tuple[str, str]] = list(_SAFE_CONFIG)

    def _env(self) -> dict[str, str]:
        env = dict(self.base_env)
        env["GIT_CONFIG_COUNT"] = str(len(self.config))
        for i, (key, value) in enumerate(self.config):
            env[f"GIT_CONFIG_KEY_{i}"] = key
            env[f"GIT_CONFIG_VALUE_{i}"] = value
        return env

    def _kill(self, proc: asyncio.subprocess.Process) -> None:
        # git runs in its own process group; kill helpers too, or they keep the pipes open.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    async def run(
        self, *args: str, ok_codes: tuple[int, ...] = (0,), max_bytes: int = MAX_OUTPUT_BYTES
    ) -> tuple[int, bytes, bool]:
        """Run git; returns (returncode, stdout, truncated). Raises RuntimeError on failure."""
        cmd = [self.git, "--no-pager", *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.cwd),
                env=self._env(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except FileNotFoundError as e:
            raise RuntimeError("git is not installed") from e
        except OSError as e:
            # e.g. E2BIG from a repo config defining thousands of filter drivers.
            raise RuntimeError(f"could not run git: {e}") from e

        truncated = False

        async def read_stdout() -> bytes:
            nonlocal truncated
            buf = bytearray()
            assert proc.stdout is not None
            while chunk := await proc.stdout.read(65536):
                buf += chunk
                if len(buf) > max_bytes:
                    truncated = True
                    self._kill(proc)
                    break
            return bytes(buf)

        async def read_stderr() -> bytes:
            buf = bytearray()
            assert proc.stderr is not None
            while chunk := await proc.stderr.read(65536):
                if len(buf) < MAX_STDERR_BYTES:
                    buf += chunk  # keep draining past the cap so git never blocks on it
            return bytes(buf[:MAX_STDERR_BYTES])

        try:
            out, err = await asyncio.wait_for(
                asyncio.gather(read_stdout(), read_stderr()), TIMEOUT_SECONDS
            )
            code = await asyncio.wait_for(proc.wait(), TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._kill(proc)
            try:
                # asyncio's wait() also waits for the pipes to close; never hang on that.
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                logger.warning("git %s (pid %s) did not exit after SIGKILL", args[0], proc.pid)
            raise RuntimeError(f"git {args[0]} timed out after {TIMEOUT_SECONDS:.0f}s")

        if truncated:
            return 0, out, True
        if code not in ok_codes:
            msg = err.decode("utf-8", "replace").strip()[:2000] or "git failed"
            logger.info("git %s failed in %s (%s): %s", args[0], self.cwd, code, msg)
            raise RuntimeError(msg)
        return code, out, False

    async def _rev_parse_path(self, *flags: str) -> Path:
        _, out, _ = await self.run("rev-parse", *flags)
        # Exactly one trailing newline: directory names may end in whitespace.
        raw = out[:-1] if out.endswith(b"\n") else out
        return Path(os.fsdecode(raw)).resolve()

    async def prepare(self) -> Path:
        """Check this is a work tree inside the roots and neutralise filter drivers; returns the top level."""
        # Separate calls: rev-parse prints one path per line and paths may contain newlines.
        top = await self._rev_parse_path("--show-toplevel")
        # core.worktree in the repo config could point the work tree anywhere.
        if not top.is_relative_to(self.root):
            raise ValueError(f"work tree {top} is outside {ROOTS_ENV}")
        # A `.git` file ("gitdir: ...") or symlink can borrow another repo's history,
        # index and config; a linked worktree's common dir holds the objects.
        roots = allowed_roots()
        for flags in (("--absolute-git-dir",), ("--path-format=absolute", "--git-common-dir")):
            gitdir = await self._rev_parse_path(*flags)
            if _containing_root(gitdir, roots) is None:
                raise ValueError(f"git directory {gitdir} is outside {ROOTS_ENV}")

        # filter.<name>.clean/smudge/process run on status/diff; names are arbitrary,
        # so find every configured driver and blank it (empty command = no filter).
        code, out, _ = await self.run(
            "config", "--null", "--get-regexp", r"^filter\.", ok_codes=(0, 1)
        )
        names: set[str] = set()
        if code == 0:
            for entry in out.decode("utf-8", "replace").split("\0"):
                key = entry.split("\n", 1)[0]
                if key.startswith("filter.") and key.count(".") >= 2:
                    names.add(key[len("filter."):].rsplit(".", 1)[0])
        for name in sorted(names):
            for var, value in (("clean", ""), ("smudge", ""), ("process", ""), ("required", "false")):
                self.config.append((f"filter.{name}.{var}", value))
        return top

    async def branch(self) -> str:
        code, out, _ = await self.run("symbolic-ref", "--short", "-q", "HEAD", ok_codes=(0, 1))
        return out.decode("utf-8", "replace").strip() if code == 0 else "HEAD"


async def _open(repo_path: str | None) -> tuple[_Git, Path]:
    cwd, root = _resolve_repo(repo_path)
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is not installed")
    g = _Git(cwd, root, git)
    top = await g.prepare()
    return g, top


def _parse_branch_header(header: str) -> str:
    # "## main...origin/main [ahead 1]", "## No commits yet on main", "## HEAD (no branch)"
    head = header[3:] if header.startswith("## ") else header
    for prefix in ("No commits yet on ", "Initial commit on "):
        if head.startswith(prefix):
            return head[len(prefix):].strip()
    if head.startswith("HEAD (no branch)"):
        return "HEAD"
    return head.split("...", 1)[0].split(" [", 1)[0].strip()


def _parse_status(raw: bytes, stream_truncated: bool) -> tuple[str, list[dict], bool]:
    fields = raw.decode("utf-8", "replace").split("\0")
    if stream_truncated:
        fields = fields[:-1]  # the last field may be cut mid-path
    branch = ""
    changes: list[dict] = []
    truncated = stream_truncated
    i = 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if not field:
            continue
        if field.startswith("## "):
            branch = _parse_branch_header(field)
            continue
        if len(field) < 4:
            continue
        xy, path = field[:2], field[3:]
        change = {"status": xy.strip() or xy, "path": path}
        # In -z mode a rename/copy is "XY new\0old\0".
        if "R" in xy or "C" in xy:
            if i >= len(fields):
                break
            change["orig_path"] = fields[i]
            i += 1
        if len(changes) >= MAX_STATUS_CHANGES:
            truncated = True
            break
        changes.append(change)
    return branch, changes, truncated


async def git_status(repo_path: str | None = None) -> dict:
    g, top = await _open(repo_path)
    _, out, stream_truncated = await g.run(
        "status", "--porcelain=v1", "-z", "--branch",
        "--untracked-files=all", "--renames", "--ignore-submodules=all",
    )
    branch, changes, truncated = _parse_status(out, stream_truncated)
    return {
        "repo": str(top),
        "branch": branch or await g.branch(),
        "clean": not changes,
        "changes": changes,
        "truncated": truncated,
    }


async def git_log(repo_path: str | None = None, limit: int = 10) -> dict:
    if isinstance(limit, bool):
        raise ValueError("limit must be an integer")
    try:
        limit = int(limit)
    except (TypeError, ValueError, OverflowError) as e:
        raise ValueError("limit must be an integer") from e
    limit = max(1, min(limit, MAX_LOG_LIMIT))
    g, top = await _open(repo_path)
    branch = await g.branch()

    # Exit 1 with no output means HEAD has no commits yet (an empty repo is not an error).
    code, _, _ = await g.run("rev-parse", "--verify", "-q", "HEAD", ok_codes=(0, 1))
    commits: list[dict] = []
    if code == 0:
        # Fixed-format fields first; a stray separator in the author or subject can then
        # only blur those two, never shift the hash or date. --encoding beats
        # i18n.logOutputEncoding (UTF-16 output would break the parse).
        fmt = _UNIT.join(("%H", "%h", "%aI", "%an", "%s"))
        _, out, _ = await g.run(
            "log", "-z", "--no-color", "--no-show-signature", "--encoding=UTF-8",
            f"--max-count={limit}", f"--format=format:{fmt}", "HEAD", "--",
        )
        for record in out.decode("utf-8", "replace").split("\0"):
            if not record:
                continue
            parts = record.split(_UNIT, 4)
            if len(parts) != 5:
                continue
            full, short, date, author, subject = parts
            commits.append(
                {"hash": full, "short": short, "author": author, "date": date, "subject": subject}
            )
    return {"repo": str(top), "branch": branch, "commits": commits}


async def git_diff(repo_path: str | None = None, staged: bool = False) -> dict:
    # bool("false") is True; refuse anything that is not a real boolean.
    if not isinstance(staged, bool):
        raise ValueError("staged must be a boolean")
    g, top = await _open(repo_path)
    args = ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--ignore-submodules=all"]
    if staged:
        args.append("--cached")
    # UTF-8 is at most 4 bytes per character, so this always yields enough text for the cap.
    _, out, stream_truncated = await g.run(*args, max_bytes=MAX_DIFF_CHARS * 4)
    text = out.decode("utf-8", "replace")
    truncated = stream_truncated or len(text) > MAX_DIFF_CHARS
    return {
        "repo": str(top),
        "staged": staged,
        "diff": text[:MAX_DIFF_CHARS],
        "truncated": truncated,
    }
