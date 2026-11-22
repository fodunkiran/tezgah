"""PostToolUse hook: formats a file Claude Code just edited, with a formatter from a fixed list.

`.claude/tezgah.toml` only switches a formatter on (`format.rust = true`); the command
itself is fixed here, so a cloned repository cannot make the hook run anything else.
Rust files get `rustfmt` with the edition of the nearest `Cargo.toml`, as `cargo fmt`
does. A file rustfmt cannot parse is left alone; the compiler reports that better.
"""

import json
import subprocess
import sys
from pathlib import Path

import project_config
from project_config import tomllib  # None before Python 3.11: then nothing is formatted

FALLBACK_EDITION = "2024"
RUSTFMT_TIMEOUT_SECONDS = 25


def edition_for(path):
    """The edition of the package holding `path`, following `edition.workspace = true`."""
    wants_workspace = False
    for directory in path.parents:
        manifest = directory / "Cargo.toml"
        if not manifest.is_file():
            continue
        try:
            with manifest.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            return FALLBACK_EDITION
        if not wants_workspace:
            edition = table(data, "package").get("edition")
            if isinstance(edition, str):
                return edition
            if isinstance(edition, dict) and edition.get("workspace") is True:
                wants_workspace = True
            elif "package" in data:
                return FALLBACK_EDITION
        workspace_edition = table(table(data, "workspace"), "package").get("edition")
        if wants_workspace and isinstance(workspace_edition, str):
            return workspace_edition
    return FALLBACK_EDITION


def table(data, key):
    """`data[key]` when it is a table; an empty one otherwise, so a malformed manifest is no crash."""
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except (ValueError, RecursionError):
        return
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    raw = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
    if not isinstance(raw, str) or not raw or tomllib is None:
        return
    path = Path(raw)
    if path.suffix != ".rs" or not path.is_file():
        return
    cwd = payload.get("cwd")
    try:
        config = project_config.load(path.resolve().parent, session=cwd if isinstance(cwd, str) and cwd else None)
    except (OSError, subprocess.SubprocessError):
        return
    if not isinstance(config, project_config.Config) or not config.format_rust:
        return
    try:
        subprocess.run(
            ["rustfmt", "--edition", edition_for(path), str(path)],
            capture_output=True,
            timeout=RUSTFMT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        print("rustfmt is not on PATH; the edited file was not formatted. (bekci)", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("rustfmt timed out; the edited file was not formatted. (bekci)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
