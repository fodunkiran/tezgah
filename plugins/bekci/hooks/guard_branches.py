"""PreToolUse guard: no direct push to a long-lived branch, no pull request against the release branch.

The long-lived branches come from `.claude/tezgah.toml` (`branches.integration`, required;
`branches.release`, optional). The guard refuses a `git push` that would update one of
them, a `gh pr create` whose base is the release branch or is left out (the repository's
default branch), a `gh pr edit` that moves a base to the release branch, and `gh api`
calls that do the same. It binds Claude Code only, never a person at a terminal.

The command line is split into words honouring quotes and grouped the way the shell runs
it: `;`, `&&`, `||`, `&` and a newline end a command, `|` joins a pipeline, `( )` is a
subshell and a redirection takes its target out of the command. `cd`/`Set-Location` move
the following commands to another folder, except in a subshell, a pipeline stage or the
background, or when the folder does not exist; the configuration and the current branch
are read from the folder a push actually runs in. A command that moves HEAD makes a later
push that depends on HEAD unknowable. Commands inside `bash -c`, `powershell -Command`,
`eval`, a shell fed a here-string or `echo`, git aliases, `rebase --exec`, `submodule
foreach` and `bisect run` go through the same check, and so does every command
substitution, quoted or not. A push
target is turned into a full ref the way git does it (`@`, `HEAD`, `heads/x`, globs,
`remote.<name>.push`, `push.default`); a refspec or a base that depends on the shell (a
variable, brace expansion, a command) is refused, except `$(git branch --show-current)` and
its like, whose branch is asked of git. Text the shell never runs is not checked where that
is certain without parsing quotes: comments on a line without quoting, and the body of a
quoted here-document that only a text reader takes. An unexpected error while judging a
command with a push or a pull request in it refuses that command.
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

# Shell marks that separate commands or redirect them; quoted ones do not.
SEPARATOR_CHARS = ";&|()\n<>"
# The operators a run of those marks holds, longest first.
OPERATOR = re.compile(r"<<<|<<-|<<|&>>|>>|>&|<&|&>|>\||<>|\|\||&&|\|&|;;|[;&|()<>\n]")
# Redirections: the next word is a file (or, after `<<<`, text), not an argument.
REDIRECTS = {"<", ">", ">>", ">&", "<&", "&>", "&>>", ">|", "<>", "<<", "<<-", "<<<"}
# Commands that change the folder (bash, PowerShell, cmd).
CHANGE_DIRECTORY = {"cd", "pushd", "chdir", "set-location", "sl", "push-location"}
PUSH_DIRECTORY = {"pushd", "push-location"}
POP_DIRECTORY = {"popd", "pop-location"}
# Where a command substitution or a PowerShell expression stood: a word the shell fills in.
SUBSTITUTION_WORD = "$bekci_substitution"
# `$(git rev-parse --show-toplevel)`: the repository's root, which the guard can ask for.
TOPLEVEL_MARK = "@bekci-toplevel@"
TOPLEVEL = re.compile(r"\$\(\s*git\s+rev-parse\s+--show-toplevel\s*\)|`\s*git\s+rev-parse\s+--show-toplevel\s*`")
# The folder after a `cd` whose target the shell supplies (a variable, a command).
UNKNOWN_FOLDER = "\0unknown folder"
# Shells that run their argument as a command, and the options that carry it.
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ash", "mksh", "fish", "csh", "tcsh", "powershell", "pwsh", "cmd"}
SHELL_COMMAND_FLAGS = {"-c", "-command", "/c", "/k", "/r"}
SHELL_ENCODED_FLAGS = {"-encodedcommand", "-enc", "-e", "-ec"}
# The sh family: an option cluster holding `c` introduces the command string. Only
# PowerShell has encoded commands.
SH_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ash", "mksh", "fish", "csh", "tcsh"}
# Programs whose output an earlier pipeline stage may be: their words are the script a shell
# reads from standard input.
PRINTERS = {"echo", "printf", "write-output", "write-host"}
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

# Commands that print the current branch. As a command substitution at the top of the line the
# guard asks git for that branch in the folder the shell has reached, so
# `git push -u origin "$(git branch --show-current)"` is judged by its branch instead of refused.
CURRENT_BRANCH_COMMAND = (
    r"git\s+(?:branch\s+--show-current|rev-parse\s+--abbrev-ref\s+HEAD|symbolic-ref\s+--short\s+HEAD)"
)
CURRENT_BRANCH = {
    "bash": re.compile(rf"\$\(\s*{CURRENT_BRANCH_COMMAND}\s*\)|`\s*{CURRENT_BRANCH_COMMAND}\s*`"),
    "powershell": re.compile(rf"\$\(\s*{CURRENT_BRANCH_COMMAND}\s*\)"),
}
CURRENT_BRANCH_MARK = "@bekci-current-branch@"
CURRENT_BRANCH_UNKNOWN = "$(git branch --show-current)"
# A here-document whose delimiter is quoted is never expanded. Read by a program that takes it as
# text, its body never runs, so it is not checked: commit messages and pull request bodies.
HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'(\w+)'|\"(\w+)\"|\\(\w+))")
TEXT_READERS = {"cat", "tee", "git", "gh"}
# Programs that may run what they read; one anywhere on the line keeps the body checked.
RUNS_INPUT = SHELLS | EVALUATORS | {"xargs", "source", "."}
# Characters that make a line's quoting a matter of parsing. Comments are dropped only from a
# line without any of them, and a here-document only when the rest of its line has none.
QUOTING = re.compile(r"[\"'`\\$]")

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
# `gh` options that may stand before a subcommand's action (`gh pr -R o/r create`).
GH_REPO_OPTIONS = {"-R", "--repo"}
# git subcommands after which HEAD may name another branch; `branch -m` and a two-argument
# `symbolic-ref` too.
HEAD_MOVERS = {"checkout", "switch"}
# How many aliases deep an alias may lead to another.
MAX_ALIASES = 8
# Before Python 3.11: the commands refused in a configured repository.
OLD_PYTHON_RISKY = re.compile(
    r"\b(push|send-pack)\b|\bpr\s+(create|new|edit)\b|\bapi\b.*\s(-X|--method|-f|-F|--field|--raw-field|--input)\b"
)


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
# The folder the session runs in (the payload's `cwd`). Its copy of the file also governs a
# work tree of the same repository that has none, such as a main checkout on an old branch.
_session = {"folder": None}
# What earlier commands on the line changed: HEAD moved by a checkout, aliases defined.
_line = {"head_moved": False, "aliases": {}}


def settings(location, what):
    """The configuration governing a git `location`; `None` leaves the command unguarded.

    A broken configuration refuses `what` (a push or a pull request command), and so does a
    folder the shell supplies, whose repository cannot be known.
    """
    if UNKNOWN_FOLDER in location:
        deny(
            f"{what} refused: the folder it runs in comes from the shell (a variable or a command), "
            "so its repository cannot be checked. Name the folder."
        )
    key = tuple(location)
    if key not in _configs:
        root = config_root(location)
        _configs[key] = project_config.load_root(root, _session["folder"]) if root else None
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

    A continuation does not count inside single quotes, where the text is literal, nor in a
    comment, which a line break ends whatever comes before it.
    """
    escape = CONTINUATION_ESCAPE["bash" if shell == "bash" else "powershell"]
    if escape + "\n" not in line and escape + "\r\n" not in line:
        return line
    pieces = []
    in_single = in_double = in_comment = False
    index, length = 0, len(line)
    while index < length:
        character = line[index]
        if in_comment:
            if character == escape and line[index + 1 : index + 2] in {"\n", "\r"}:
                # A backslash ending a comment escapes nothing; the line break stays a break.
                index += 1
                continue
            in_comment = character != "\n"
        elif in_single:
            in_single = character != "'"
        elif character == "#" and shell != "cmd" and not in_double and (index == 0 or line[index - 1] in " \t\n;&|()<>"):
            in_comment = True
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


def drop_inert_text(line, shell):
    """Removes text the shell never runs, where that is certain without parsing quotes.

    It runs before line continuations are joined: a backslash ends no comment. Comments go
    only from a bash or PowerShell line (`cmd` has no `#` comments) with no quoting and no
    here-document, whose reader might be such a program. A here-document body goes only in
    bash, when its delimiter is quoted (so it is never expanded), a text reader takes it,
    nothing on its line could run it, and the rest of that line has no quoting. Anything else
    stays and is checked: refusing harmless text costs less than letting a push through.
    """
    if shell == "cmd" or ("#" not in line and "<<" not in line):
        return line
    if not QUOTING.search(line) and "<<" not in line:
        return "\n".join(strip_comment(part) for part in line.split("\n"))
    if shell == "powershell" or "<<" not in line:
        return line
    lines = line.split("\n")
    kept = []
    index = 0
    while index < len(lines):
        kept.append(lines[index])
        end = here_document_end(lines, index)
        index = end + 1 if end is not None else index + 1
    return "\n".join(kept)


def strip_comment(text):
    """`text` up to a `#` that starts a word."""
    for index, character in enumerate(text):
        if character == "#" and (index == 0 or text[index - 1] in " \t;&|("):
            return text[:index]
    return text


def here_document_end(lines, index):
    """The index of the line that ends a here-document opened on `lines[index]`, when its
    body may be dropped; otherwise `None`."""
    current = lines[index]
    found = list(HEREDOC.finditer(current))
    if len(found) != 1 or current.count("<<") != 1:
        return None
    match = found[0]
    before, after = current[: match.start()], current[match.end() :]
    if QUOTING.search(before + after):
        return None
    if any(program(word) in RUNS_INPUT for word in re.findall(r"[^\s;&|()<>]+", before + " " + after)):
        return None
    words = re.split(r"[;&|(]", before)[-1].split()
    if not words or program(words[0]) not in TEXT_READERS:
        return None
    if program(words[0]) == "git" and not git_builtin(words[1:]):
        return None
    delimiter = match.group(2) or match.group(3) or match.group(4)
    for end in range(index + 1, len(lines)):
        if (lines[end].lstrip("\t") if match.group(1) else lines[end]) == delimiter:
            return end
    return None


def git_builtin(args):
    """Whether the git subcommand in `args` (the words after `git`) is a builtin, not an alias."""
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in GIT_OPTIONS_WITH_VALUE else 1
    return index < len(args) and args[index] in BUILTINS


def tokens_of(line, shell):
    """Words honouring quotes; separators become words of their own.

    In PowerShell a backslash is a path separator, not an escape.
    """
    line = join_continuations(drop_inert_text(line, shell), shell)
    lexer = shlex.shlex(line, posix=True, punctuation_chars=SEPARATOR_CHARS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    if shell != "bash":
        lexer.escape = ""
    try:
        return list(lexer)
    except ValueError:
        # An unclosed quote: split roughly and check anyway.
        return re.findall(r"[^\s;&|()<>]+|[;&|()<>\n]+", line)


def units_of(line, shell):
    """The line as ("word", text) and ("op", operator) pairs."""
    units = []
    for token in tokens_of(line, shell):
        if token and all(character in SEPARATOR_CHARS for character in token):
            units.extend(("op", operator) for operator in OPERATOR.findall(token))
        else:
            units.append(("word", token))
    return units


def new_command(pipe=False):
    return {"words": [], "inner": [], "herestrings": [], "pipe": pipe, "end": ""}


def structure(units):
    """The commands of a line in order, grouped the way the shell runs them.

    A simple command is a dict: its `words`; `inner`, the command lists of the substitutions
    and expressions in it, which run before it in a process of their own; its `herestrings`;
    `pipe`, true for a pipeline stage; `end`, the operator after it. A subshell is a list of
    the same. A `$(...)` (or a PowerShell `(...)`) inside a command stands as one word,
    SUBSTITUTION_WORD, so the command keeps the arguments after it; a redirection drops its
    target.
    """
    root = []
    container, command = root, None
    stack = []
    pipe_next = False
    redirect = None
    for kind, text in units:
        if kind == "word":
            if redirect is not None:
                if redirect == "<<<" and command is not None:
                    command["herestrings"].append(text)
                redirect = None
                continue
            if command is None:
                command = new_command(pipe_next)
                pipe_next = False
                container.append(command)
            command["words"].append(text)
        elif text in REDIRECTS:
            redirect = text
        elif text == "(":
            if redirect is not None or (command is not None and command["words"]):
                # A command substitution, a process substitution or an expression argument.
                if command is None:
                    command = new_command(pipe_next)
                    pipe_next = False
                    container.append(command)
                if redirect is None:
                    words = command["words"]
                    if words[-1].endswith("$"):
                        words[-1] = words[-1][:-1] + SUBSTITUTION_WORD
                    else:
                        words.append(SUBSTITUTION_WORD)
                redirect = None
                group = []
                command["inner"].append(group)
                stack.append((container, command, group))
            else:
                group = []
                container.append(group)
                stack.append((container, None, group))
                pipe_next = False
            container, command = group, None
        elif text == ")":
            if stack:
                container, command, group = stack.pop()
                if command is not None and command["words"] and asks_toplevel(group):
                    command["words"][-1] = command["words"][-1].replace(SUBSTITUTION_WORD, TOPLEVEL_MARK)
        elif text in {"|", "|&"}:
            if command is not None:
                command["pipe"] = True
            pipe_next = True
            command = None
        else:
            # `;`, `&&`, `||`, `&`, `;;` or a line break ends the command.
            if command is not None:
                command["end"] = text
            command = None
            pipe_next = False
    return root


def asks_toplevel(group):
    """Whether a substitution's commands are exactly `git rev-parse --show-toplevel`."""
    return len(group) == 1 and isinstance(group[0], dict) and group[0]["words"] == ["git", "rev-parse", "--show-toplevel"]


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


def directory_change(words, cwd, previous, stack):
    """(folder, stack) after a `cd`-like command, or `None` when the command is not one.

    A target the shell supplies gives UNKNOWN_FOLDER. A folder that does not exist leaves the
    shell where it was: the `cd` fails, and after `;` the next command runs here.
    """
    if not words:
        return None
    name = program(words[0])
    if name in POP_DIRECTORY:
        return (stack[-1], stack[:-1]) if stack else (cwd, stack)
    if name not in CHANGE_DIRECTORY:
        return None
    arguments = [word for word in words[1:] if word == "-" or not (word.startswith("-") or word.lower() == "/d")]
    target = arguments[0] if arguments else "~"
    folder = (previous or cwd) if target == "-" else resolve_folder(target, cwd)
    return folder, stack + [cwd] if name in PUSH_DIRECTORY else stack


def resolve_folder(target, cwd):
    """The folder a `cd` to `target` reaches from `cwd`."""
    if target == TOPLEVEL_MARK or TOPLEVEL.fullmatch(target):
        root = project_config.git_root(cwd) if cwd != UNKNOWN_FOLDER else None
        return str(root) if root else UNKNOWN_FOLDER
    target = os.path.expandvars(os.path.expanduser(native_path(target)))
    if is_unresolvable(target) or (cwd == UNKNOWN_FOLDER and not os.path.isabs(target)):
        return UNKNOWN_FOLDER
    folder = os.path.normpath(os.path.join(cwd, target))
    return folder if os.path.isdir(folder) else cwd


def check_line(line, cwd, shell, depth=0):
    if depth > MAX_DEPTH:
        deny("The command nests shells too deeply for pushes and pull requests to be checked.")
    if depth == 0:
        line = CURRENT_BRANCH["powershell" if shell == "powershell" else "bash"].sub(CURRENT_BRANCH_MARK, line)
    walk(structure(units_of(line, shell)), cwd, shell, depth)


def walk(nodes, cwd, shell, depth):
    """Checks commands in order, following the folder the shell is in.

    A subshell, a substitution, a pipeline stage and a background command run in a process of
    their own, so a `cd` there does not move the commands after them.
    """
    previous, stack, stage = None, [], None
    for node in nodes:
        if isinstance(node, list):
            walk(node, cwd, shell, depth)
            stage = None
            continue
        for inner in node["inner"]:
            walk(inner, cwd, shell, depth + 1)
        moved = directory_change(node["words"], cwd, previous, stack)
        if moved is not None:
            if not node["pipe"] and node["end"] != "&":
                previous, (cwd, stack) = cwd, moved
            stage = None
            continue
        check_command(node, cwd, shell, depth, stage)
        stage = node if node["pipe"] else None


def piped_text(stage):
    """The script an earlier pipeline stage prints: `echo`/`printf` words, or a lone string."""
    if not stage or not stage["words"]:
        return []
    words = stage["words"]
    if program(words[0]) in PRINTERS:
        words = [word for word in words[1:] if not re.fullmatch(r"-[neE]+", word)]
    elif len(words) > 1:
        return []
    return [" ".join(words).replace("\\n", "\n")] if words else []


def check_command(node, cwd, shell, depth, stage=None):
    words = node["words"]
    # A command substitution runs what it holds, quoted or not. Unquoted ones are in `inner`
    # already; quoted ones are still inside a word.
    for word in words:
        for inner in substitutions(word, shell):
            check_line(inner, cwd, shell, depth + 1)
    for index, word in enumerate(words):
        name = program(word)
        if name not in WATCHED:
            continue
        # Slicing only here keeps a very long command line linear.
        rest = words[index + 1 :]
        if any(CURRENT_BRANCH_MARK in item for item in rest):
            rest = with_current_branch(rest, cwd if name == "git" and depth == 0 else None)
        if name == "git":
            check_git(rest, cwd, shell, depth)
            return
        if name == "gh":
            check_gh(rest, cwd)
            return
        if name in SHELLS:
            inner_shell = "cmd" if name == "cmd" else ("powershell" if name in {"powershell", "pwsh"} else "bash")
            inner = shell_command(rest, name)
            # Without a command argument a shell reads its script from standard input: a
            # here-string, or what an `echo` before it in the pipeline prints.
            for text in [inner] if inner is not None else node["herestrings"] + piped_text(stage):
                check_line(text, cwd, inner_shell, depth + 1)
            return
        if name in EVALUATORS:
            for text in [" ".join(rest)] if rest else node["herestrings"] + piped_text(stage):
                check_line(text, cwd, shell, depth + 1)
            return


def substitutions(word, shell):
    """What a word runs as commands: everything after a `$(` (which holds at least the
    substitution) and, in bash, the text between each pair of backticks. An escaped one is text."""
    found = []
    index = 0
    while index < len(word):
        escaped = index > 0 and word[index - 1] == "\\"
        if word.startswith("$(", index) and not escaped:
            found.append(word[index + 2 :])
            break
        if word[index] == "`" and shell == "bash" and not escaped:
            end = word.find("`", index + 1)
            if end < 0:
                found.append(word[index + 1 :])
                break
            found.append(word[index + 1 : end])
            index = end
        index += 1
    return found


def with_current_branch(words, folder):
    """Puts the branch back where the line said `$(git branch --show-current)`.

    `folder` is where the shell runs that command: the folder the line has reached, for a git
    command of the line itself. For a nested shell the quoting decides which shell runs it, and
    where, so `folder` is `None` and the text stays unresolvable; so it does after a command
    that moved HEAD.
    """
    known = folder and folder != UNKNOWN_FOLDER and not _line["head_moved"]
    branch = current_branch(["-C", folder]) if known else ""
    return [word.replace(CURRENT_BRANCH_MARK, branch or CURRENT_BRANCH_UNKNOWN) for word in words]


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
    if _line["head_moved"] and source in {"HEAD", "@"} and not colon:
        deny(
            f"An earlier command on this line moves HEAD, so the branch `{source}` pushes to "
            "cannot be checked. Name the branch."
        )
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
    aliases = dict(_line["aliases"])
    index = 0
    while index < len(args) and args[index].startswith("-"):
        option, equals, value = args[index].partition("=")
        if option in GIT_OPTIONS_WITH_VALUE and not equals:
            value = args[index + 1] if index + 1 < len(args) else ""
            index += 2
        else:
            index += 1
        if option in GIT_LOCATION_OPTIONS:
            location += [option, location_value(value, cwd)]
        if option == "-c" and value.lower().startswith("alias."):
            name, _, expansion = value.partition("=")
            aliases[name.split(".", 1)[1].lower()] = expansion
    if index >= len(args):
        return
    check_subcommand(args[index], args[index + 1 :], location, aliases, cwd, depth, set())


def location_value(value, cwd):
    """A `-C`, `--git-dir` or `--work-tree` value as a folder git can be asked about."""
    if value == TOPLEVEL_MARK or TOPLEVEL.fullmatch(value):
        root = project_config.git_root(cwd) if cwd != UNKNOWN_FOLDER else None
        return str(root) if root else UNKNOWN_FOLDER
    return UNKNOWN_FOLDER if is_unresolvable(value) else native_path(value)


def check_subcommand(subcommand, rest, location, aliases, cwd, depth, seen):
    """A git subcommand and the words after it; an alias is followed to what it runs."""
    if subcommand in PUSH_COMMANDS:
        check_push(rest, location)
        return
    if subcommand == "git":
        # `sudo -u git git push`: the first `git` was a word for another program.
        check_git(rest, cwd, "bash", depth)
        return
    positional = [word for word in rest if not word.startswith("-")]
    if (
        subcommand in HEAD_MOVERS
        or (subcommand == "branch" and any(word in {"-m", "-M", "--move"} for word in rest))
        or (subcommand == "symbolic-ref" and len(positional) >= 2)
    ):
        _line["head_moved"] = True
    if subcommand == "config":
        remember_alias(rest)
    for command in commands_run_by(subcommand, rest):
        check_line(command, cwd, "bash", depth + 1)
    if subcommand in BUILTINS or subcommand.lower() in seen or len(seen) >= MAX_ALIASES:
        return
    seen.add(subcommand.lower())
    expansion = aliases.get(subcommand.lower()) or git(location, "config", "--get", f"alias.{subcommand}")
    if expansion.startswith("!"):
        # git runs it with the alias's own arguments after it.
        check_line(" ".join([expansion[1:], *map(shlex.quote, rest)]), cwd, "bash", depth + 1)
        return
    expanded = tokens_of(expansion, "bash")
    if expanded:
        check_subcommand(expanded[0], expanded[1:] + rest, location, aliases, cwd, depth, seen)


def commands_run_by(subcommand, rest):
    """The shell commands a builtin runs: `rebase --exec`, `submodule foreach`, `bisect run`."""
    if subcommand == "rebase":
        return option_values(rest, {"-x", "--exec"})
    if subcommand == "submodule" and rest[:1] == ["foreach"]:
        words = [word for word in rest[1:] if word not in {"--recursive", "--quiet", "-q"}]
        return [" ".join(words)] if words else []
    if subcommand == "bisect" and rest[:1] == ["run"] and len(rest) > 1:
        return [" ".join(rest[1:])]
    return []


def remember_alias(rest):
    """`git config alias.<name> <value>` earlier on the line defines an alias for what follows."""
    words, skip = [], False
    for word in rest:
        if skip:
            skip = False
        elif word in {"-f", "--file", "--blob", "--type"}:
            skip = True
        elif not word.startswith("-"):
            words.append(word)
    if len(words) >= 2 and words[0].lower().startswith("alias."):
        _line["aliases"][words[0].split(".", 1)[1].lower()] = " ".join(words[1:])


def check_push(args, location):
    config = settings(location, "Push")
    if config is None:
        return
    if any(word in {"--help", "-h", "--dry-run"} or re.fullmatch(r"-[46dfquv]*n[46dfquv]*", word) for word in args):
        # Help, or a dry run (`-n`, alone or in a cluster): nothing is pushed.
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
    if "--tags" in args:
        # `--tags` names what to push, so neither `remote.<name>.push` nor `push.default` adds a branch.
        return
    # No refspec: `remote.<name>.push` decides first, then `push.default`.
    if configured:
        for spec in configured:
            check_refspec(spec, location, [], reasons)
        return
    if _line["head_moved"]:
        deny(
            "An earlier command on this line moves HEAD, so the branch a bare `git push` takes "
            "cannot be checked. Name the branch, or push in a command of its own."
        )
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


def without_repo_option(args):
    """`args` without gh's `-R`/`--repo` option, which may stand before the action."""
    kept, skip = [], False
    for word in args:
        if skip:
            skip = False
            continue
        option, value = split_option(word, GH_REPO_OPTIONS)
        if option:
            skip = value is None
            continue
        kept.append(word)
    return kept


def check_gh(args, cwd):
    """`args` are the words after `gh`."""
    args = without_repo_option(args)
    if any(word in {"--help", "-h"} for word in args):
        return
    if args[:2] == ["pr", "checkout"]:
        _line["head_moved"] = True
    if len(args) >= 2 and args[0] == "pr" and args[1] in {"create", "new", "edit"} and "--dry-run" not in args:
        config = settings(["-C", cwd], "Pull request command")
        if config is None or not config.release or config.release == config.integration:
            return
        release, integration = config.release, config.integration
        bases = option_values(args[2:], {"--base", "-B"})
        if any(is_unresolvable(base) for base in bases):
            deny("The pull request's base depends on the shell, so it cannot be checked. Name the branch.")
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
    # The values that name a branch must be plain words; `%` stays allowed for URL escapes.
    if any(re.search(r"[$`]", value) for value in (path, fields.get("base", ""), fields.get("ref", ""), fields.get("branch", ""))):
        deny("`gh api` names a branch through the shell, so its target cannot be checked. Name the branch.")
    path = path.split("?", 1)[0].rstrip("/")
    ref_match = re.search(r"git/refs/heads/(.+)$", path)
    if ref_match and ref_match.group(1) in reasons:
        deny(f"`gh api {path}` changes `{ref_match.group(1)}` directly.")
    if path.endswith("git/refs") and protected_target(full_ref(fields.get("ref", ""), []), reasons):
        deny("`gh api` changes a long-lived branch directly.")
    if path.endswith("/merges") and (has_input or fields.get("base") in reasons):
        deny("`gh api .../merges` merges into a long-lived branch directly.")
    synced = fields.get("branch", "").removeprefix("refs/heads/")
    if path.endswith("/merge-upstream") and (has_input or not synced or synced in reasons):
        deny("`gh api .../merge-upstream` updates a long-lived branch directly.")
    renamed = re.search(r"/branches/([^/]+)/rename$", path)
    if renamed and renamed.group(1) in reasons:
        deny(f"`gh api {path}` renames `{renamed.group(1)}`.")
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
    _session["folder"] = cwd
    problem = project_config.too_old()
    if problem:
        # The file cannot be read. Where the session's repository has one, refuse what may
        # push or open a pull request and say why; let everything else through.
        try:
            root = project_config.git_root(cwd)
            guarded = root is not None and project_config.find_file(root, cwd) is not None
        except (OSError, subprocess.SubprocessError):
            guarded = True
        if guarded and OLD_PYTHON_RISKY.search(line):
            deny(f"{problem}. Push and pull request commands are refused until it is upgraded.")
        return
    try:
        check_line(line, cwd, shell)
    except Exception as error:  # the guard must not drop silently
        if RISKY_WORDS.search(line):
            deny(f"The guard could not read the command ({type(error).__name__}); push and pull request commands are refused.")
        raise


if __name__ == "__main__":
    main()
