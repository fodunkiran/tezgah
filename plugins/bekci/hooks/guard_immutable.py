"""PreToolUse guard: a file that has landed and must not change stays unchanged.

An `Edit` or `Write` is refused when the file's path, relative to its repository, matches
one of `immutable.paths` in `.claude/tezgah.toml` and the file exists on
`origin/<integration>`; a file still on its topic branch stays editable. Without that
remote ref the test is "committed on HEAD". Edits made by a shell command are not seen.

On Windows the file system ignores case: `Migrations\\0001_X.SQL` is the same file. So the
path is resolved, written relative to the repository root, and compared with the names in
git and with the patterns regardless of case and separator.
"""

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

import project_config


def git(root, *args):
    """The output of `git`; `None` when it fails."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def landed_file(path, session=None):
    """(ref, name in git) when the path is an immutable file that has landed; otherwise `None`.

    `session` is the folder the session runs in; see `project_config.load_root`.
    """
    # The edit tools resolve a path lexically: `sub/..` collapses even if `sub` does not
    # exist, while a POSIX kernel stops at the missing `sub`. Simplify first, as the tool does.
    path = Path(os.path.abspath(path))
    if not path.is_file():
        return None
    resolved = path.resolve()
    config = project_config.load(resolved.parent, session=session)
    if not isinstance(config, project_config.Config) or not config.immutable_paths:
        return None
    root = config.root.resolve()
    try:
        relative = resolved.relative_to(root).as_posix().casefold()
    except ValueError:
        # On Windows the drive letter or a folder name may be written in another case.
        relative = Path(str(resolved).casefold()).relative_to(Path(str(root).casefold())).as_posix()
    patterns = [pattern.replace("\\", "/").casefold() for pattern in config.immutable_paths]
    if not any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns):
        return None
    landed_ref = f"origin/{config.integration}"
    ref = landed_ref if git(root, "rev-parse", "--verify", "--quiet", landed_ref) is not None else "HEAD"
    # `-z` keeps names with non-ASCII characters unquoted.
    listing = git(root, "ls-tree", "-r", "-z", "--name-only", ref) or ""
    for name in listing.split("\0"):
        if name.casefold() == relative:
            return ref, name
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    # Claude Code writes the payload as UTF-8; on Windows stdin defaults to the ANSI code page.
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    raw = payload.get("tool_input", {}).get("file_path", "")
    # A Python too old to read the file lets edits through, as a broken file does.
    if not raw or project_config.too_old():
        return
    cwd = payload.get("cwd")
    try:
        landed = landed_file(Path(raw), session=cwd if isinstance(cwd, str) and cwd else None)
    except (OSError, ValueError, subprocess.SubprocessError):
        landed = None
    if landed is None:
        return
    ref, name = landed
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"{name} is on {ref} and matches `immutable.paths`, so it must not change. "
                    "Make the change in a new file. (bekci)"
                ),
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
