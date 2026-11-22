"""Finds and reads a repository's `.claude/tezgah.toml`.

The file is looked up at the git root of the folder a tool call acts in, so a
worktree is judged by its own copy. A work tree without one is judged by another
copy in the same repository: the main checkout's, or else the one in the folder
the session runs in. The app cuts worktrees from branches older than the file,
and a main checkout may sit on such a branch; neither may leave bekci inert.
`CLAUDE_PROJECT_DIR` is never read: it names the session's project, which need
not be the repository a command acts on.

`load` has three outcomes: `None` (no file, so bekci is inert there), a
`Config`, or a `Broken` that says what is wrong with the file.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:  # before Python 3.11; see `too_old`
    tomllib = None

CONFIG_PATH = Path(".claude") / "tezgah.toml"
GIT_TIMEOUT_SECONDS = 5


def too_old():
    """Why this Python cannot read the file, or `None`. `tomllib` came with Python 3.11.

    The hooks check this before anything else, so an older Python gets a refusal that says
    what to install instead of a crash, which would block every command.
    """
    if tomllib is not None:
        return None
    return f"bekci needs Python 3.11 or later and was started with Python {sys.version.split()[0]}"


@dataclass(frozen=True)
class Config:
    root: Path
    integration: str
    release: str | None = None
    immutable_paths: tuple[str, ...] = field(default_factory=tuple)
    format_rust: bool = False

    @property
    def long_lived(self):
        """The guarded branches, integration first."""
        branches = [self.integration]
        if self.release and self.release != self.integration:
            branches.append(self.release)
        return branches


@dataclass(frozen=True)
class Broken:
    root: Path
    problem: str


def git_root(folder, location=None):
    """The work tree root git reports for `folder` (or for explicit `location` options).

    `None` outside a work tree. A git that cannot start or times out raises (`OSError`,
    `subprocess.SubprocessError`): only the caller knows whether to fail open or closed.
    """
    args = list(location) if location else ["-C", str(folder)]
    result = subprocess.run(
        ["git", *args, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    text = result.stdout.strip()
    if result.returncode != 0 or not text:
        return None
    return Path(text)


def load(folder, location=None, session=None):
    """The configuration of the repository holding `folder`; `session` as in `load_root`."""
    root = git_root(folder, location)
    if root is None:
        return None
    return load_root(root, session)


def load_root(root, session=None):
    """The configuration governing work tree `root`.

    `session` is the folder the session runs in (the payload's `cwd`), whose copy is the
    last one tried.
    """
    path = find_file(root, session)
    if path is None:
        return None
    # The file's own folder is named when it is broken; the work tree it governs is `root`.
    source = path.parent.parent
    if tomllib is None:
        return Broken(source, too_old())
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        return Broken(source, f"it does not parse: {error}")
    except (OSError, UnicodeDecodeError) as error:
        return Broken(source, f"it cannot be read: {error}")
    config = parse(root, data)
    if isinstance(config, Broken):
        return Broken(source, config.problem)
    return config


def find_file(root, session):
    """The `.claude/tezgah.toml` that governs work tree `root`, or `None`.

    Its own copy first; then the main checkout's when `root` is a linked worktree; then
    the copy in the session's folder when that folder belongs to the same repository.
    The fallbacks cost git calls only when `root` has no copy of its own.
    """
    own = root / CONFIG_PATH
    if own.is_file():
        return own
    main = main_checkout(root)
    if main is not None and (main / CONFIG_PATH).is_file():
        return main / CONFIG_PATH
    if session is None:
        return None
    session_root = git_root(session)
    if session_root is None or not (session_root / CONFIG_PATH).is_file():
        return None
    mine, theirs = common_dir(root), common_dir(session_root)
    if mine is None or mine != theirs:
        return None
    return session_root / CONFIG_PATH


def main_checkout(root):
    """The repository's main work tree when `root` is a linked worktree; otherwise `None`.

    A linked worktree has a `.git` file where a main work tree has a folder, so a main
    checkout costs no git call. A submodule also has a `.git` file, but its common git
    directory is not a `.git` folder, so it has no main work tree to read.
    """
    if not (root / ".git").is_file():
        return None
    common = common_dir(root)
    return common.parent if common is not None and common.name == ".git" else None


def common_dir(root):
    """The git directory every work tree of `root`'s repository shares, resolved."""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    text = result.stdout.strip()
    if result.returncode != 0 or not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def parse(root, data):
    branches = data.get("branches")
    if not isinstance(branches, dict):
        return Broken(root, "`[branches]` is missing")
    integration = branches.get("integration")
    if not isinstance(integration, str) or not integration.strip():
        return Broken(root, "`branches.integration` is missing or not a branch name")
    release = branches.get("release")
    if release is not None and (not isinstance(release, str) or not release.strip()):
        return Broken(root, "`branches.release` is not a branch name")

    immutable = data.get("immutable", {})
    paths = immutable.get("paths", []) if isinstance(immutable, dict) else None
    if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
        return Broken(root, "`immutable.paths` is not a list of strings")

    format_section = data.get("format", {})
    rust = format_section.get("rust", False) if isinstance(format_section, dict) else None
    if not isinstance(rust, bool):
        return Broken(root, "`format.rust` is not true or false")

    return Config(
        root=root,
        integration=integration.strip(),
        release=release.strip() if release else None,
        immutable_paths=tuple(paths),
        format_rust=rust,
    )
