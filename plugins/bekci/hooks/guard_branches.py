"""PreToolUse guard: no direct push to a long-lived branch, no pull request against the release branch.

The long-lived branches come from `.claude/tezgah.toml` (`branches.integration`, required;
`branches.release`, optional). The guard refuses a `git push` that would update one of
them, a `gh pr create` whose base is the release branch or is left out (the repository's
default branch), a `gh pr edit` that moves a base to the release branch, and `gh api`
calls that do the same. It binds Claude Code only, never a person at a terminal.

The command line is split into words honouring quotes; `;`, `&&`, `||`, `|`, `&` and a
newline separate commands. `cd`/`Set-Location` move the following commands to another
folder, and the configuration and the current branch are read from the folder a push
actually runs in. Commands inside `bash -c`, `powershell -Command`, `eval` and git aliases
go through the same check. A push target is turned into a full ref the way git does it
(`@`, `HEAD`, `heads/x`, globs, `remote.<name>.push`, `push.default`); a refspec that
depends on the shell (a variable, brace expansion) is refused. An unexpected error while
judging a command with a push or a pull request in it refuses that command.
"""

import base64
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import project_config

RULE = "bekci"

# Shell marks that separate commands; quoted ones do not.
SEPARATOR_CHARS = ";&|()\n"
# Commands that change the folder (bash, PowerShell, cmd).
CHANGE_DIRECTORY = {"cd", "pushd", "chdir", "set-location", "sl", "push-location"}
# Shells that run their argument as a command, and the options that carry it.
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "powershell", "pwsh", "cmd"}
SHELL_COMMAND_FLAGS = {"-c", "-command", "/c", "/k", "/r"}
SHELL_ENCODED_FLAGS = {"-encodedcommand", "-enc", "-e", "-ec"}
# The sh family: an option cluster holding `c` introduces the command string. Only
# PowerShell has encoded commands.
SH_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# `sh` options that consume the next word.
SH_OPTIONS_WITH_VALUE = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
# A line continuation: a backslash (Bash) or a backtick (PowerShell) before a line break.
CONTINUATION_ESCAPE = {"bash": "\\", "powershell": "`"}
EVALUATORS = {"eval", "invoke-expression", "iex"}
# The program names `check_command` acts on.
WATCHED = {"git", "gh"} | SHELLS | EVALUATORS
MAX_DEPTH = 4
# A line matching none of these can hold no push and no pull request: no git, no gh,
# no encoded shell command whose text could hide one.
MAY_MATTER = re.compile(r"push|gh|git|-e", re.IGNORECASE)
# Words that, after an unexpected error, make the guard refuse rather than crash.
RISKY_WORDS = re.compile(r"\b(push|send-pack|pr|api)\b")

# `git` options that consume the next word.
GIT_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--config-env",
    "--super-prefix",
    "--attr-source",
}
# `git` options that change which repository and branch are meant; passed on unchanged when
# asking git about it. `-c` is not: the guard must not run git with settings from a command
# that has not been approved.
GIT_LOCATION_OPTIONS = {"-C", "--git-dir", "--work-tree"}
# Subcommands that take refspecs: `send-pack` is the low-level form of push.
PUSH_COMMANDS = {"push", "send-pack"}
# Common subcommands that cannot be aliases; no `alias.<name>` lookup for them.
BUILTINS = {
    "add", "am", "apply", "bisect", "blame", "branch", "cat-file", "check-ignore", "checkout",
    "cherry-pick", "clean", "clone", "commit", "config", "describe", "diff", "fetch",
    "for-each-ref", "format-patch", "gc", "grep", "help", "init", "log", "ls-files", "ls-remote",
    "ls-tree", "merge", "merge-base", "mv", "notes", "pull", "range-diff", "rebase", "reflog",
    "remote", "reset", "restore", "rev-list", "rev-parse", "revert", "rm", "shortlog", "show",
    "show-ref", "sparse-checkout", "stash", "status", "submodule", "switch", "symbolic-ref",
    "tag", "update-ref", "version", "worktree",
}
# `git push` options that consume the next word.
PUSH_OPTIONS_WITH_VALUE = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}
# Pushes that update every branch, the long-lived ones included.
PUSH_ALL_FLAGS = {"--all", "--branches", "--mirror"}

# `gh api` options that consume the next word.
GH_API_OPTIONS_WITH_VALUE = {
    "-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header", "--input",
    "-q", "--jq", "-t", "--template", "--hostname", "-p", "--preview", "--cache",
}
GH_API_FIELD_OPTIONS = {"-f", "--raw-field", "-F", "--field"}
GH_API_METHOD_OPTIONS = {"-X", "--method"}


def deny(reason):
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"{reason} ({RULE})",
            }
        },
        sys.stdout,
    )
    sys.exit(0)


# --- Configuration --------------------------------------------------------------------


_configs = {}


def settings(location, what):
    """The configuration governing a git `location`; `None` leaves the command unguarded.

    A broken configuration refuses `what` (a push or a pull request command).
    """
    key = tuple(location)
    if key not in _configs:
        root = config_root(location)
        _configs[key] = project_config.load_root(root) if root else None
    config = _configs[key]
    if isinstance(config, project_config.Broken):
        deny(
            f"{what} refused: {config.root.as_posix()}/.claude/tezgah.toml is broken "
            f"({config.problem}). Fix the file first."
        )
    return config


def config_root(location):
    """The work tree root of the repository `location` points git at."""
    if "--git-dir" in location and "--work-tree" not in location:
        # Without a work tree git takes the current folder as one; the repository the
        # push goes from is the one around the named git directory.
        git_dir = git(location, "rev-parse", "--absolute-git-dir")
        if git_dir and Path(git_dir).name == ".git":
            return Path(git_dir).parent
    return project_config.git_root(None, location)


def long_lived_reasons(config):
    reasons = {config.integration: f"Work reaches `{config.integration}` only through a pull request."}
    if config.release and config.release != config.integration:
        reasons[config.release] = f"`{config.release}` is advanced only by the maintainer."
    return reasons


# --- Command line ---------------------------------------------------------------------


def join_continuations(line, shell):
    """Removes each line continuation, which keeps the command going on the next line.

    A continuation does not count inside single quotes, where the text is literal.
    """
    escape = CONTINUATION_ESCAPE["powershell" if shell == "powershell" else "bash"]
    if escape + "\n" not in line and escape + "\r\n" not in line:
        return line
    pieces = []
    in_single = in_double = False
    index, length = 0, len(line)
    while index < length:
        character = line[index]
        if in_single:
            in_single = character != "'"
        elif character == escape and index + 1 < length:
            following = line[index + 1 : index + 3]
            if following.startswith("\n"):
                index += 2
                continue
            if following == "\r\n":
                index += 3
                continue
            pieces.append(character + line[index + 1])
            index += 2
            continue
        elif character == '"':
            in_double = not in_double
        elif character == "'" and not in_double:
            in_single = True
        pieces.append(character)
        index += 1
    return "".join(pieces)


def tokens_of(line, shell):
    """Words honouring quotes; separators become words of their own.

    In PowerShell a backslash is a path separator, not an escape.
    """
    line = join_continuations(line, shell)
    lexer = shlex.shlex(line, posix=True, punctuation_chars=SEPARATOR_CHARS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    if shell == "powershell":
        lexer.escape = ""
    try:
        return list(lexer)
    except ValueError:
        # An unclosed quote: split roughly and check anyway.
        return re.findall(r"[^\s;&|()]+|[;&|()\n]+", line)


def commands_of(line, shell):
    """Splits a line into simple commands."""
    commands, current = [], []
    for token in tokens_of(line, shell):
        if token and all(character in SEPARATOR_CHARS for character in token):
            if current:
                commands.append(current)
            current = []
        else:
            current.append(token)
    if current:
        commands.append(current)
    return commands


def program(word):
    name = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.removesuffix(".exe")


def native_path(text):
    """Turns a Git Bash path (`/c/Users`) into one Windows understands."""
    if os.name == "nt":
        match = re.match(r"^/(?:cygdrive/)?([a-zA-Z])(/.*)?$", text)
        if match:
            return f"{match.group(1)}:{match.group(2) or '/'}"
    return text


def directory_change(words, cwd):
    """The new folder if this is a `cd`-like command; otherwise `None`."""
    if not words or program(words[0]) not in CHANGE_DIRECTORY:
        return None
    arguments = [word for word in words[1:] if not word.startswith("-") and word.lower() != "/d"]
    if not arguments:
        return os.path.expanduser("~")
    target = os.path.expandvars(os.path.expanduser(native_path(arguments[0])))
    return os.path.normpath(os.path.join(cwd, target))


def check_line(line, cwd, shell, depth=0):
    if depth > MAX_DEPTH:
        deny("The command nests shells too deeply for pushes and pull requests to be checked.")
    for words in commands_of(line, shell):
        new_cwd = directory_change(words, cwd)
        if new_cwd is not None:
            cwd = new_cwd
            continue
        check_command(words, cwd, shell, depth)


def check_command(words, cwd, shell, depth):
    for index, word in enumerate(words):
        name = program(word)
        if name not in WATCHED:
            continue
        # Slicing only here keeps a very long command line linear.
        rest = words[index + 1 :]
        if name == "git":
            check_git(rest, cwd, shell, depth)
            return
        if name == "gh":
            check_gh(rest, cwd)
            return
        if name in SHELLS:
            inner = shell_command(rest, name)
            if inner is not None:
                inner_shell = "powershell" if name in {"powershell", "pwsh", "cmd"} else "bash"
                check_line(inner, cwd, inner_shell, depth + 1)
                return
        if name in EVALUATORS:
            check_line(" ".join(rest), cwd, shell, depth + 1)
            return


def sh_command(arguments):
    """The command after an option cluster with `c` (`-c`, `-lc`, `-e -c`) of an sh-family shell."""
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in SH_OPTIONS_WITH_VALUE:
            index += 2
        elif re.fullmatch(r"-[A-Za-z]+", argument) and "c" in argument:
            return " ".join(arguments[index + 1 :])
        elif argument.startswith(("-", "+")) and argument != "--":
            index += 1
        else:
            return None
    return None


def shell_command(arguments, shell="powershell"):
    """The command inside `bash -c "..."`, `powershell -Command ...`, `cmd /c ...`."""
    if shell in SH_SHELLS:
        return sh_command(arguments)
    for index, argument in enumerate(arguments):
        flag = argument.lower()
        if flag in SHELL_COMMAND_FLAGS:
            return " ".join(arguments[index + 1 :])
        if flag in SHELL_ENCODED_FLAGS and index + 1 < len(arguments):
            try:
                return base64.b64decode(arguments[index + 1]).decode("utf-16-le")
            except ValueError:
                return arguments[index + 1]
    return None


# --- git ------------------------------------------------------------------------------


def git(location, *args):
    """Runs `git` with the same repository options; empty text when it fails."""
    try:
        result = subprocess.run(
            ["git", *location, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def current_branch(location):
    return git(location, "symbolic-ref", "--quiet", "--short", "HEAD")


def full_ref(name, location):
    """Turns a push target into a full ref name the way git does."""
    if name in {"HEAD", "@"}:
        branch = current_branch(location)
        return f"refs/heads/{branch}" if branch else ""
    if name.startswith("refs/"):
        return name
    if name.startswith(("heads/", "tags/", "remotes/")):
        return f"refs/{name}"
    return f"refs/heads/{name}"


def protected_target(ref, branches):
    """The long-lived branch a ref (possibly a glob) updates, if any."""
    for branch in branches:
        if ref and fnmatch.fnmatchcase(f"refs/heads/{branch}", ref):
            return branch
    return None


def is_unresolvable(spec):
    """A refspec whose target depends on the shell: a variable, a command or brace expansion."""
    return any(mark in spec for mark in "$`%") or re.search(r"\{[^}]*,[^}]*\}", spec)


def check_refspec(spec, location, configured, reasons):
    if is_unresolvable(spec):
        deny(f"`{spec}` depends on the shell, so its target branch cannot be checked. Name the branch.")
    spec = spec.removeprefix("+")
    if spec.startswith("^"):
        return
    if spec == ":":
        deny("The `:` refspec updates every matching branch, the long-lived ones included.")
    source, colon, destination = spec.partition(":")
    if colon:
        targets = [destination]
    else:
        targets = mapped(source, location, configured) or [source]
    for target in targets:
        branch = protected_target(full_ref(target, location), reasons)
        if branch:
            deny(f"`{spec}` pushes to `{branch}`. {reasons[branch]}")


def mapped(source, location, configured):
    """What `remote.<name>.push` maps a source-only refspec to."""
    source_ref = full_ref(source, location)
    targets = []
    for spec in configured:
        pattern, _, destination = spec.removeprefix("+").partition(":")
        pattern_ref = full_ref(pattern, location)
        if "*" in pattern_ref and destination:
            prefix, _, suffix = pattern_ref.partition("*")
            if source_ref.startswith(prefix) and source_ref.endswith(suffix):
                middle = source_ref.removeprefix(prefix).removesuffix(suffix)
                targets.append(destination.replace("*", middle, 1))
        elif pattern_ref == source_ref:
            targets.append(destination or source)
    return targets


def default_remote(location, branch):
    for key in (f"branch.{branch}.pushRemote", "remote.pushDefault", f"branch.{branch}.remote"):
        value = git(location, "config", "--get", key)
        if value:
            return value
    return "origin"


def check_git(args, cwd, shell, depth):
    """`args` are the words after `git`."""
    location = ["-C", cwd]
    aliases = {}
    index = 0
    while index < len(args) and args[index].startswith("-"):
        option, equals, value = args[index].partition("=")
        if option in GIT_OPTIONS_WITH_VALUE and not equals:
            value = args[index + 1] if index + 1 < len(args) else ""
            index += 2
        else:
            index += 1
        if option in GIT_LOCATION_OPTIONS:
            location += [option, native_path(value)]
        if option == "-c" and value.lower().startswith("alias."):
            name, _, expansion = value.partition("=")
            aliases[name.split(".", 1)[1].lower()] = expansion
    if index >= len(args):
        return
    subcommand, rest = args[index], args[index + 1 :]
    if subcommand in PUSH_COMMANDS:
        check_push(rest, location)
        return
    if subcommand in BUILTINS:
        return
    expansion = aliases.get(subcommand.lower()) or git(location, "config", "--get", f"alias.{subcommand}")
    if expansion.startswith("!"):
        check_line(expansion.removeprefix("!"), cwd, "bash", depth + 1)
        return
    expanded = tokens_of(expansion, "bash")
    if expanded and expanded[0] in PUSH_COMMANDS:
        check_push(expanded[1:] + rest, location)


def check_push(args, location):
    config = settings(location, "Push")
    if config is None:
        return
    reasons = long_lived_reasons(config)
    positional = []
    skip = False
    for word in args:
        if skip:
            skip = False
            continue
        if word in PUSH_ALL_FLAGS:
            deny(f"`git push {word}` also updates the long-lived branches ({', '.join(reasons)}).")
        if word in PUSH_OPTIONS_WITH_VALUE:
            skip = True
            continue
        if word.startswith("-"):
            continue
        positional.append(word)
    branch = current_branch(location)
    remote = positional[0] if positional else default_remote(location, branch)
    configured = git(location, "config", "--get-all", f"remote.{remote}.push").splitlines()
    refspecs = positional[1:]
    if refspecs:
        for spec in refspecs:
            check_refspec(spec, location, configured, reasons)
        return
    # No refspec: `remote.<name>.push` decides first, then `push.default`.
    if configured:
        for spec in configured:
            check_refspec(spec, location, [], reasons)
        return
    if branch in reasons:
        deny(f"This checkout is on `{branch}`; a bare `git push` updates it. {reasons[branch]}")
    mode = git(location, "config", "--get", "push.default") or "simple"
    if mode == "matching":
        deny("With `push.default=matching` a bare `git push` also updates the long-lived branches.")
    if mode in {"upstream", "tracking"} and branch:
        upstream = git(location, "for-each-ref", "--format=%(upstream:remoteref)", f"refs/heads/{branch}")
        target = protected_target(upstream, reasons)
        if target:
            deny(f"`{branch}` tracks `{target}`; `push.default={mode}` updates it. {reasons[target]}")


# --- gh -------------------------------------------------------------------------------


def split_option(word, options):
    """`--long=value`, `-Kvalue`, `-K=value` or `-K`/`--long`: (option, value or None)."""
    if word.startswith("--"):
        option, equals, value = word.partition("=")
        return (option, value if equals else None) if option in options else (None, None)
    if word.startswith("-") and len(word) > 1:
        option = word[:2]
        if option in options:
            value = word[2:].removeprefix("=")
            return option, value if len(word) > 2 else None
    return None, None


def option_values(args, options):
    """Every value of an option, in order."""
    values = []
    index = 0
    while index < len(args):
        option, value = split_option(args[index], options)
        if option and value is None:
            value = args[index + 1] if index + 1 < len(args) else ""
            index += 1
        if option:
            values.append(value)
        index += 1
    return values


def check_gh(args, cwd):
    """`args` are the words after `gh`."""
    if len(args) >= 2 and args[0] == "pr" and args[1] in {"create", "new", "edit"}:
        config = settings(["-C", cwd], "Pull request command")
        if config is None or not config.release or config.release == config.integration:
            return
        release, integration = config.release, config.integration
        bases = option_values(args[2:], {"--base", "-B"})
        if args[1] in {"create", "new"} and not bases:
            deny(
                f"`gh pr {args[1]}` without a base targets the default branch (`{release}`). "
                f"Add `--base {integration}`."
            )
        # A repeated option takes its last value; every value is checked.
        if any(base.removeprefix("refs/heads/") == release for base in bases):
            deny(f"Pull requests target `{integration}`, never `{release}` unless the user asks by name.")
    if args and args[0] == "api":
        check_gh_api(args[1:], cwd)


def check_gh_api(args, cwd):
    path, method, fields, has_input = "", None, {}, False
    index = 0
    while index < len(args):
        option, value = split_option(args[index], GH_API_OPTIONS_WITH_VALUE)
        if option and value is None:
            value = args[index + 1] if index + 1 < len(args) else ""
            index += 1
        if option in GH_API_METHOD_OPTIONS:
            method = value.upper()
        elif option in GH_API_FIELD_OPTIONS:
            key, _, field = value.partition("=")
            fields[key] = field
        elif option == "--input":
            has_input = True
        elif option is None and not args[index].startswith("-") and not path:
            path = args[index]
        index += 1
    if method is None:
        method = "POST" if fields or has_input else "GET"
    if method == "GET":
        return
    config = settings(["-C", cwd], "`gh api` call")
    if config is None:
        return
    reasons = long_lived_reasons(config)
    release, integration = config.release, config.integration
    path = path.split("?", 1)[0].rstrip("/")
    ref_match = re.search(r"git/refs/heads/(.+)$", path)
    if ref_match and ref_match.group(1) in reasons:
        deny(f"`gh api {path}` changes `{ref_match.group(1)}` directly.")
    if path.endswith("git/refs") and protected_target(full_ref(fields.get("ref", ""), []), reasons):
        deny("`gh api` changes a long-lived branch directly.")
    if path.endswith("/merges") and (has_input or fields.get("base") in reasons):
        deny("`gh api .../merges` merges into a long-lived branch directly.")
    if release and release != integration:
        if re.search(r"/pulls(/\d+)?$", path) and (has_input or fields.get("base") == release):
            deny(f"Pull requests target `{integration}`; `gh api` cannot open one against `{release}` either.")
    if method in {"PUT", "DELETE"} and re.search(r"(^|/)repos/[^/]+/[^/]+/contents/.", path):
        # A write to a file commits to `branch`, or to the default branch when it is left out.
        branch = fields.get("branch", "").removeprefix("refs/heads/")
        if not branch:
            deny(
                f"`gh api {method} .../contents/...` without a `branch` field commits to the default branch. "
                "Name a topic branch with `-f branch=<name>`."
            )
        if branch in reasons or is_unresolvable(branch):
            deny(f"`gh api {method} .../contents/...` commits straight to `{branch}`. Use a topic branch and a pull request.")
    query = fields.get("query", "")
    names = "|".join(re.escape(branch) for branch in reasons)
    if path == "graphql" and re.search(r"\bmutation\b", query) and re.search(rf"(?<!\w)({names})(?!\w)", query):
        deny(f"A GraphQL mutation that names a long-lived branch is refused; use `gh pr create --base {integration}`.")


# --- Entry ----------------------------------------------------------------------------


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    # Claude Code writes the payload as UTF-8; on Windows stdin defaults to the ANSI code page.
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        payload = None
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    line = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(line, str):
        # Not what Claude Code sends: refuse only what mentions something risky.
        if RISKY_WORDS.search(raw):
            deny("The guard could not read the tool call, and it mentions a push or a pull request.")
        return
    if not MAY_MATTER.search(line):
        return
    shell = "powershell" if payload.get("tool_name") == "PowerShell" else "bash"
    cwd = payload.get("cwd")
    cwd = native_path(cwd if isinstance(cwd, str) and cwd else os.getcwd())
    try:
        check_line(line, cwd, shell)
    except Exception as error:  # the guard must not drop silently
        if RISKY_WORDS.search(line):
            deny(f"The guard could not read the command ({type(error).__name__}); push and pull request commands are refused.")
        raise


if __name__ == "__main__":
    main()
