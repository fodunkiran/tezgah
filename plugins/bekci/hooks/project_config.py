"""Finds and reads a repository's `.claude/tezgah.toml`.

The file is looked up at the git root of the folder a tool call runs in, never
through `CLAUDE_PROJECT_DIR`: in a worktree session that variable names the
main checkout, and the worktree must be judged by its own copy.

`load` has three outcomes: `None` (no file, so bekci is inert there), a
`Config`, or a `Broken` that says what is wrong with the file.
"""

import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(".claude") / "tezgah.toml"
GIT_TIMEOUT_SECONDS = 5


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


def load(folder, location=None):
    """The configuration of the repository holding `folder`."""
    root = git_root(folder, location)
    if root is None:
        return None
    return load_root(root)


def load_root(root):
    path = root / CONFIG_PATH
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        return Broken(root, f"it does not parse: {error}")
    except (OSError, UnicodeDecodeError) as error:
        return Broken(root, f"it cannot be read: {error}")
    return parse(root, data)


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
