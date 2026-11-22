#!/usr/bin/env python3
"""Tries the hooks on sample payloads. Run: python tests/test_hooks.py

Each hook is run the way Claude Code runs it: the payload goes to stdin as UTF-8 JSON and
the decision is read from stdout. The guards are tried in throwaway git repositories, each
with its own `.claude/tezgah.toml` (or none); no real repository and no network is
touched. Standard library and git only; rustfmt is used when it is on PATH.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
passed = 0
cases = 0
# The hooks and git run independent of the developer's global git settings (`push.default`).
ENV = dict(os.environ)
ENV.pop("CLAUDE_PROJECT_DIR", None)

CLASSIC = '[branches]\nintegration = "development"\nrelease = "main"\n'
OTHER_NAMES = '[branches]\nintegration = "trunk"\nrelease = "stable"\n'
NO_RELEASE = '[branches]\nintegration = "development"\n'


def ok(message):
    global passed
    passed += 1
    print(f"  ✓ {message}")


def run_hook(name, payload, env=None, without_tomllib=False):
    command = [sys.executable, str(HOOKS / name)]
    if without_tomllib:
        # A Python older than 3.11, as far as the hooks can tell: `import tomllib` fails.
        command = [sys.executable, "-c", (
            "import runpy, sys; sys.modules['tomllib'] = None; "
            f"sys.path.insert(0, {str(HOOKS)!r}); "
            f"runpy.run_path({str(HOOKS / name)!r}, run_name='__main__')"
        )]
    return subprocess.run(
        command,
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env=env or ENV,
    )


def outcome(name, payload, env=None, without_tomllib=False):
    """(decision, reason); an allow must print nothing at all."""
    global cases
    cases += 1
    result = run_hook(name, payload, env, without_tomllib)
    if result.returncode != 0:
        raise AssertionError(f"{name} crashed: {result.stderr.decode('utf-8', 'replace')}")
    if not result.stdout.strip():
        assert not result.stderr, f"{name} printed on allow: {result.stderr!r}"
        return "allow", ""
    output = json.loads(result.stdout)["hookSpecificOutput"]
    return output["permissionDecision"], output["permissionDecisionReason"]


def decision(name, payload, env=None):
    return outcome(name, payload, env)[0]


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=ENV,
    )


def write_config(repo, text):
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / ".claude" / "tezgah.toml").write_text(text, encoding="utf-8", newline="\n")


def make_repo(parent, name, branch, config=CLASSIC):
    repo = parent / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", branch)
    git(repo, "commit", "-q", "--allow-empty", "-m", "first")
    git(repo, "remote", "add", "origin", "https://example.invalid/repo.git")
    if config is not None:
        write_config(repo, config)
    return repo


# --- guard_branches.py ------------------------------------------------------------------


def expect(command, expected, cwd, tool="Bash", env=None, says=None):
    payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd)}
    actual, reason = outcome("guard_branches.py", payload, env)
    assert actual == expected, f"{tool}: {command!r} in {cwd} -> {actual}, expected {expected} ({reason})"
    if says is not None:
        assert says in reason, f"{command!r}: {says!r} not in {reason!r}"


def test_branch_guard(work):
    feature = make_repo(work, "feature", "feature/x")
    on_main = make_repo(work, "on-main", "main")
    on_development = make_repo(work, "on-development", "development")
    git(feature, "config", "alias.send", "push")

    denied_from_feature = [
        "git push origin main",
        "git push origin development",
        "git push origin HEAD:main",
        "git push origin X:heads/development",
        "git push origin X:refs/heads/development",
        "git push origin +feature/x:main",
        "git push origin 'refs/heads/*'",
        'git push origin "refs/heads/*:refs/heads/*"',
        "git push origin :",
        "git push origin :development",
        "git push --delete origin development",
        "git push --all origin",
        "git push --mirror",
        "git push origin $BRANCH",
        "git push origin {main,feature/x}",
        "git -c alias.p=push p origin main",
        "git send origin main",
        "git send-pack origin main",
        "git status && git push origin main",
        "git status; git push origin main",
        "git status | git push origin main",
        "echo ready & git push origin main",
        "git status\ngit push origin main",
        'bash -c "git push origin main"',
        "eval 'git push origin main'",
        "git push origin main # č Ő ş",
        "gh pr create --title t",
        "gh pr create -Bmain --title t",
        "gh pr create -B=main --title t",
        "gh pr create --base=main --title t",
        "gh pr create -B main --title t",
        "gh pr create --base development --base main",
        "gh pr edit 5 --base main",
        '"/c/Program Files/GitHub CLI/gh.exe" pr create --title t',
        "gh api repos/o/r/pulls -f base=main -f head=x -f title=t",
        "gh api -X PATCH repos/o/r/pulls/5 -f base=main",
        "gh api -X PATCH repos/o/r/git/refs/heads/development -f sha=abc",
        "gh api repos/o/r/git/refs -f ref=refs/heads/main -f sha=abc",
        "gh api repos/o/r/merges -f base=development -f head=x",
        "gh api graphql -f query='mutation { updatePullRequest(input: {baseRefName: \"main\"}) { clientMutationId } }'",
    ]
    for command in denied_from_feature:
        expect(command, "deny", feature)
    expect('powershell -Command "git push origin main"', "deny", feature, tool="PowerShell")
    expect("git push origin main; Write-Output done", "deny", feature, tool="PowerShell")
    ok(f"{len(denied_from_feature) + 2} ways out are refused from a topic branch")

    denied_on_long_lived = [
        "git push",
        "git push origin",
        "git push origin @",
        "git push origin HEAD",
        "git push -u origin HEAD",
        "git push --force-with-lease",
    ]
    for repo in (on_main, on_development):
        for command in denied_on_long_lived:
            expect(command, "deny", repo)
    ok("a bare push, `@` and `HEAD` are refused on a long-lived branch")

    main_path = on_main.as_posix()
    elsewhere = [
        f'cd "{main_path}" && git push',
        f"cd '{main_path}' && git push",
        f'(cd "{main_path}" && git push)',
        f'git -C "{main_path}" push',
        f'git --git-dir "{main_path}/.git" push',
        f'git --git-dir="{main_path}/.git" --work-tree "{main_path}" push',
        f'git --work-tree "{main_path}" --git-dir "{main_path}/.git" push origin HEAD',
    ]
    for command in elsewhere:
        expect(command, "deny", feature)
    expect(f'Set-Location "{on_main}"; git push', "deny", feature, tool="PowerShell")
    expect(f"cd {on_main}; git push", "deny", feature, tool="PowerShell")
    expect(f"cd '{on_development}'; git push", "deny", feature, tool="PowerShell")
    ok("`cd`, `Set-Location`, `-C`, `--git-dir` and `--work-tree` pointing at another checkout are refused")

    git(feature, "config", "push.default", "upstream")
    git(feature, "config", "branch.feature/x.remote", "origin")
    git(feature, "config", "branch.feature/x.merge", "refs/heads/development")
    expect("git push", "deny", feature)
    expect("git push origin", "deny", feature)
    git(feature, "config", "push.default", "matching")
    expect("git push", "deny", feature)
    git(feature, "config", "--unset", "push.default")
    git(feature, "config", "remote.origin.push", "HEAD:refs/heads/development")
    expect("git push", "deny", feature)
    expect("git push origin feature/x", "deny", feature)
    git(feature, "config", "--unset", "remote.origin.push")
    expect("git push", "allow", feature)
    ok("`push.default` and `remote.origin.push` take part in a push's target")

    allowed_from_feature = [
        "git push",
        "git push -u origin feature/x",
        "git push origin HEAD",
        "git push origin @",
        "git push origin feature/x:feature/x",
        "git push origin refs/tags/v1.0",
        "git push --force-with-lease origin feature/x",
        "git status && git log --oneline -3",
        'git commit -m "fix: git push origin main is refused now"',
        "git -c alias.p=status p",
        f'cd "{main_path}" && git status',
        "echo push to main",
        "gh pr create --base development --head feature/x --title t",
        "gh pr create -B development --title t",
        '"/c/Program Files/GitHub CLI/gh.exe" pr create --base development --head fix/shell-tools '
        '--title "fix: shell" --body-file body.md',
        "gh pr edit 5 --title new",
        "gh pr view 5",
        "gh api repos/o/r/pulls",
        "gh api repos/o/r/pulls -f base=development -f head=x -f title=t",
        "cargo test --all-targets",
        "ls -la",
    ]
    for command in allowed_from_feature:
        expect(command, "allow", feature)
    expect("git push -u origin feature/x", "allow", feature, tool="PowerShell")
    ok(f"{len(allowed_from_feature) + 1} ordinary topic-branch commands go through")


def encoded(command):
    return base64.b64encode(command.encode("utf-16-le")).decode("ascii")


def test_powershell_forms(work):
    feature = make_repo(work, "ps-feature", "feature/ps")
    on_main = make_repo(work, "ps-main", "main")
    denied = [
        f"powershell -EncodedCommand {encoded('git push origin main')}",
        f"pwsh -enc {encoded('git push origin development')}",
        "Invoke-Expression 'git push origin main'",
        "iex 'git push origin main'",
        "cmd /c git push origin main",
        "git.exe push origin main",
        f"Push-Location '{on_main}'; git push",
        f"git -C '{on_main}' push",
        r"& 'C:\Program Files\Git\cmd\git.exe' push origin main",
    ]
    for command in denied:
        expect(command, "deny", feature, tool="PowerShell")
    allowed = [
        f"powershell -EncodedCommand {encoded('git status')}",
        "Get-ChildItem; git push origin feature/ps",
        f"Set-Location '{on_main}'; git status",
    ]
    for command in allowed:
        expect(command, "allow", feature, tool="PowerShell")
    ok(f"PowerShell forms: {len(denied)} refused, {len(allowed)} allowed")


def test_no_config(work):
    bare = make_repo(work, "no-config", "main", config=None)
    commands = [
        "git push",
        "git push origin main",
        "git push --all origin",
        "gh pr create --title t",
        "gh api repos/o/r/git/refs -f ref=refs/heads/main -f sha=abc",
    ]
    for command in commands:
        expect(command, "allow", bare)
    expect("git push origin main", "allow", bare, tool="PowerShell")
    outside = work / "not-a-repo"
    outside.mkdir()
    expect("git push origin main", "allow", outside)

    migrations = bare / "migrations"
    migrations.mkdir()
    (migrations / "0001.sql").write_text("SELECT 1;\n", encoding="utf-8", newline="\n")
    git(bare, "add", ".")
    git(bare, "commit", "-q", "-m", "migration")
    assert immutable_decision(migrations / "0001.sql") == "allow"
    ok("without .claude/tezgah.toml every guard is inert, a push to `main` included")


def test_other_branch_names(work):
    feature = make_repo(work, "names-feature", "feature/y", config=OTHER_NAMES)
    on_trunk = make_repo(work, "names-trunk", "trunk", config=OTHER_NAMES)
    on_main = make_repo(work, "names-main", "main", config=OTHER_NAMES)
    denied = [
        ("git push origin trunk", "`trunk`"),
        ("git push origin HEAD:stable", "`stable`"),
        ("gh pr create --title t", "--base trunk"),
        ("gh pr create --base stable", "`stable`"),
        ("gh pr edit 3 --base stable", "`stable`"),
        ("gh api repos/o/r/pulls -f base=stable -f head=x", "`stable`"),
        ("gh api -X PATCH repos/o/r/git/refs/heads/trunk -f sha=abc", "`trunk`"),
    ]
    for command, says in denied:
        expect(command, "deny", feature, says=says)
    expect("git push", "deny", on_trunk)
    allowed = [
        "git push origin main",
        "git push origin development",
        "gh pr create --base trunk --title t",
        "gh pr create --base main --title t",
        "gh api repos/o/r/pulls -f base=main -f head=x",
    ]
    for command in allowed:
        expect(command, "allow", feature)
    expect("git push", "allow", on_main)
    ok(f"`trunk`/`stable` are guarded and `main`/`development` are not ({len(denied) + len(allowed) + 2} commands)")


def test_no_release(work):
    feature = make_repo(work, "norel-feature", "feature/z", config=NO_RELEASE)
    on_main = make_repo(work, "norel-main", "main", config=NO_RELEASE)
    expect("git push origin development", "deny", feature)
    expect("git push origin HEAD:development", "deny", feature)
    expect("gh api repos/o/r/merges -f base=development -f head=x", "deny", feature)
    allowed = [
        "git push origin main",
        "gh pr create --title t",
        "gh pr create --base main --title t",
        "gh pr edit 5 --base main",
        "gh api repos/o/r/pulls -f base=main -f head=x",
    ]
    for command in allowed:
        expect(command, "allow", feature)
    expect("git push", "allow", on_main)
    ok("without `release` only the integration branch is guarded and no pull request rule applies")


def test_broken_config(work):
    unparsable = make_repo(work, "broken-parse", "feature/b", config='[branches\nintegration = "development"\n')
    missing = make_repo(work, "broken-missing", "feature/c", config='[branches]\nrelease = "main"\n')
    for repo in (unparsable, missing):
        for command in (
            "git push origin feature/b",
            "git push",
            "gh pr create --base development --title t",
            "gh pr edit 4 --title t",
            "gh api repos/o/r/pulls -f base=development -f head=x",
        ):
            expect(command, "deny", repo, says="tezgah.toml is broken")
        for command in ("git status", "git commit -m wip", "gh pr view 4", "cargo build"):
            expect(command, "allow", repo)
    expect("git push", "deny", unparsable, says="does not parse")
    expect("git push", "deny", missing, says="branches.integration")
    migrations = unparsable / "migrations"
    migrations.mkdir()
    (migrations / "0001.sql").write_text("SELECT 1;\n", encoding="utf-8", newline="\n")
    assert immutable_decision(migrations / "0001.sql") == "allow"
    ok("a broken file refuses pushes and pull request commands, naming the problem; the rest goes through")


def test_cd_to_other_checkout(work):
    here = make_repo(work, "cd-here", "feature/d", config=OTHER_NAMES)
    integration = make_repo(work, "cd-integration", "trunk", config=OTHER_NAMES)
    unconfigured = make_repo(work, "cd-unconfigured", "trunk", config=None)
    differently = make_repo(work, "cd-differently", "trunk", config=CLASSIC)
    expect(f"cd '{integration.as_posix()}' && git push", "deny", here)
    expect(f"cd '{integration.as_posix()}' && git push origin HEAD", "deny", here)
    expect(f"cd '{unconfigured.as_posix()}' && git push", "allow", here)
    expect(f"cd '{unconfigured.as_posix()}' && git push origin stable", "allow", here)
    expect(f"git -C '{unconfigured.as_posix()}' push origin trunk", "allow", here)
    expect(f"git -C '{integration.as_posix()}' push origin stable", "deny", here)
    # The other checkout's own names decide, not the ones of the payload's cwd.
    expect(f"cd '{differently.as_posix()}' && git push", "allow", here)
    expect(f"cd '{differently.as_posix()}' && git push origin main", "deny", here)
    expect(f"Set-Location '{unconfigured}'; git push origin trunk", "allow", here, tool="PowerShell")
    expect(f"Set-Location '{integration}'; git push", "deny", here, tool="PowerShell")
    # From an unconfigured folder into a configured one.
    expect(f"cd '{integration.as_posix()}' && git push", "deny", unconfigured)
    ok("the folder a push runs in supplies the configuration and the branch")


def test_worktree_without_its_own_file(work):
    checkout = make_repo(work, "wt-main", "feature/main-checkout")
    tree = work / "wt-linked"
    git(checkout, "worktree", "add", "-q", "-b", "development", str(tree))
    # The file is untracked in the main checkout, so the worktree has none: the main
    # checkout's copy governs it, as when the worktree was cut from an older branch.
    expect("git push", "deny", tree)
    expect("git push origin HEAD:main", "deny", tree)
    expect("git push origin HEAD:feature/x", "allow", tree)
    expect(f"cd '{tree.as_posix()}' && git push", "deny", checkout)
    # A worktree's own copy wins over the main checkout's.
    write_config(tree, OTHER_NAMES)
    expect("git push", "allow", tree)
    expect("git push origin HEAD:trunk", "deny", tree)
    ok("a worktree is judged by its own .claude/tezgah.toml, or by the main checkout's when it has none")


def test_main_checkout_without_the_file(work):
    # The maintainer's main checkout sits on the release branch, which predates the file;
    # the session works in a worktree whose branch has it.
    checkout = make_repo(work, "mc-main", "main", config=None)
    tree = work / "mc-linked"
    git(checkout, "worktree", "add", "-q", "-b", "feature/w", str(tree))
    write_config(tree, CLASSIC)
    expect(f"cd '{checkout.as_posix()}' && git push", "deny", tree)
    expect(f"git -C '{checkout.as_posix()}' push origin HEAD", "deny", tree)
    expect(f"Set-Location '{checkout}'; git push", "deny", tree, tool="PowerShell")
    expect(f"cd '{checkout.as_posix()}' && git push origin HEAD:feature/y", "allow", tree)
    # A session in another repository lends its file to no one.
    elsewhere = make_repo(work, "mc-elsewhere", "feature/e")
    expect(f"cd '{checkout.as_posix()}' && git push", "allow", elsewhere)
    # Nor does CLAUDE_PROJECT_DIR, which names the session's project, not this repository.
    lone_tree = work / "mc-unconfigured"
    unconfigured = make_repo(work, "mc-unconfigured-main", "main", config=None)
    git(unconfigured, "worktree", "add", "-q", "-b", "development", str(lone_tree))
    expect("git push", "allow", lone_tree, env=dict(ENV, CLAUDE_PROJECT_DIR=str(elsewhere)))
    ok("a work tree without the file is judged by the session's copy when both are one repository")


def test_borrowed_file_broken_or_immutable(work):
    checkout = make_repo(work, "bf-main", "feature/m", config='[branches\nintegration = "development"\n')
    tree = work / "bf-linked"
    git(checkout, "worktree", "add", "-q", "-b", "feature/t", str(tree))
    expect("git push", "deny", tree, says=f"{checkout.as_posix()}/.claude/tezgah.toml is broken")
    write_config(checkout, CLASSIC + '[immutable]\npaths = ["migrations/*.sql"]\n')
    migrations = tree / "migrations"
    migrations.mkdir()
    (migrations / "0001.sql").write_text("SELECT 1;\n", encoding="utf-8", newline="\n")
    git(tree, "add", "migrations")
    git(tree, "commit", "-q", "-m", "migration")
    assert immutable_decision(migrations / "0001.sql") == "deny"
    (migrations / "0002.sql").write_text("SELECT 2;\n", encoding="utf-8", newline="\n")
    assert immutable_decision(migrations / "0002.sql") == "allow"
    ok("a borrowed file that is broken is named where it lies; its immutable paths hold in the worktree")


def test_python_too_old(work):
    repo = make_repo(work, "old-python", "development", config=CLASSIC + '[immutable]\npaths = ["migrations/*.sql"]\n[format]\nrust = true\n')
    unconfigured = make_repo(work, "old-python-none", "main", config=None)

    def branches(command, cwd):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
        return outcome("guard_branches.py", payload, without_tomllib=True)

    for command in ("git push origin feature/x", "git push", "gh pr create --base development --title t"):
        actual, reason = branches(command, repo)
        assert actual == "deny" and "needs Python 3.11 or later" in reason, f"{command!r} -> {actual} ({reason})"
    for command in ("git status", "git commit -m wip", "cargo build"):
        assert branches(command, repo)[0] == "allow", command
    assert branches("git push origin main", unconfigured)[0] == "allow"
    migrations = repo / "migrations"
    migrations.mkdir()
    (migrations / "0001.sql").write_text("SELECT 1;\n", encoding="utf-8", newline="\n")
    git(repo, "add", "migrations")
    git(repo, "commit", "-q", "-m", "migration")
    edit = {"tool_name": "Edit", "tool_input": {"file_path": str(migrations / "0001.sql")}, "cwd": str(repo)}
    assert outcome("guard_immutable.py", edit, without_tomllib=True)[0] == "allow"
    source = repo / "main.rs"
    source.write_text("fn  main( ) {}\n", encoding="utf-8", newline="\n")
    edit = {"tool_name": "Edit", "tool_input": {"file_path": str(source)}, "cwd": str(repo)}
    assert outcome("format_edited.py", edit, without_tomllib=True)[0] == "allow"
    assert source.read_text(encoding="utf-8") == "fn  main( ) {}\n"
    ok("before Python 3.11 a configured repository refuses only push and pull request commands, saying why")


def test_hook_commands_find_python(work):
    global cases
    sh = shutil.which("sh")
    if sh is None:
        print("  - no `sh` on PATH, so the commands in hooks.json were not tried")
        return
    registered = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    commands = [hook["command"] for groups in registered.values() for group in groups for hook in group["hooks"]]
    for names, expected in ((("python", "python3"), "python"), (("python3",), "python3")):
        shims = work / ("shims-" + "-".join(names))
        shims.mkdir()
        for name in names:
            shim = shims / name
            shim.write_text(f'#!/bin/sh\necho "{name} $1"\n', encoding="utf-8", newline="\n")
            shim.chmod(0o755)
        env = dict(ENV, PATH=str(shims), CLAUDE_PLUGIN_ROOT="/plugin")
        for command in commands:
            cases += 1
            script = re.search(r"hooks/(\w+\.py)", command).group(1)
            result = subprocess.run([sh, "-c", command], capture_output=True, text=True, env=env, timeout=30)
            assert result.stdout.strip() == f"{expected} /plugin/hooks/{script}", (
                f"{command!r} with only {names} on PATH -> {result.stdout!r} {result.stderr!r}"
            )
    ok("each command in hooks.json runs `python`, or `python3` where there is no `python`")


def test_command_substitutions(work):
    repo = make_repo(work, "subst", "feature/s")
    for command in (
        'echo "$(git push origin development)"',
        'X="$(git push origin HEAD:main)"',
        'echo "x `git push origin development` y"',
        "git commit -m \"$(cat <<'EOF'\nok\nEOF\n)\" && echo \"$(git push origin development)\"",
        # The here-document ends at its delimiter, not at the first `)`.
        "echo \"$(cat <<'EOF'\na)\nEOF\ngit push origin main)\"",
        'gh pr create --base "$(echo main)" --title t',
        "gh pr edit 3 --base $BASE",
        'gh api repos/o/r/merges -f base="$(echo main)" -f head=x',
        'gh api -X PATCH "repos/o/r/git/refs/heads/$B" -f sha=1',
    ):
        expect(command, "deny", repo)
    for command in (
        'echo "$(git status)"',
        'cd "$(git rev-parse --show-toplevel)" && git status',
        'echo "\\`git push origin main\\`"',
        "gh api repos/o/r/git/refs/heads/feature%2Fx -X PATCH -f sha=1",
    ):
        expect(command, "allow", repo)
    ok("a command substitution is checked as commands, quoted or not; a base built by the shell is refused")


def test_current_branch_substitution(work):
    feature = make_repo(work, "cb-feature", "feature/c")
    integration = make_repo(work, "cb-integration", "development")
    for command in (
        'git push -u origin "$(git branch --show-current)"',
        "git push origin $(git rev-parse --abbrev-ref HEAD)",
        "git push origin `git symbolic-ref --short HEAD`",
        'git push origin "$(git branch --show-current):refs/heads/feature/c"',
    ):
        expect(command, "allow", feature)
        expect(command.replace("feature/c", "development"), "deny", integration)
    expect('git push origin "$(git branch --show-current)"', "allow", feature, tool="PowerShell")
    expect("git push origin $(git branch --show-current):main", "deny", feature)
    expect("git push origin ${BRANCH}", "deny", feature)
    expect("git push origin $(echo feature/c)", "deny", feature)
    # In a nested shell the quoting decides which shell runs it, and where.
    expect("bash -c 'git push origin $(git branch --show-current)'", "deny", feature)
    expect(f"bash -c \"cd '{integration.as_posix()}' && git push origin $(git branch --show-current)\"", "deny", feature)
    # The shell asks in its own folder, not in the one `git -C` names.
    expect(f"git -C '{integration.as_posix()}' push origin \"$(git branch --show-current)\"", "allow", feature)
    expect(f"git -C '{feature.as_posix()}' push origin \"$(git branch --show-current)\"", "deny", integration)
    expect(f"cd '{integration.as_posix()}' && git push origin $(git branch --show-current)", "deny", feature)
    ok("`$(git branch --show-current)` in a refspec is judged by the branch the shell would print there")


def test_tags_heredocs_and_comments(work):
    repo = make_repo(work, "text", "development")
    for command in ("git push --tags", "git push origin --tags"):
        expect(command, "allow", repo)
    for command in ("git push origin --tags development", "git push --follow-tags"):
        expect(command, "deny", repo)
    for command in (
        "git commit -F - <<'EOF'\nNever git push origin main\nEOF",
        "git commit -m \"$(cat <<'EOF'\nfix: stop `git push origin main`\nEOF\n)\"",
        "cat > notes.md <<'EOF'\ngit push origin development\nEOF\ngit status",
        'gh pr create --base development --title t --body-file - <<"EOF"\nthen gh pr create\nEOF',
        "git status  # before any git push origin main",
    ):
        expect(command, "allow", repo)
    for command in (
        "cat <<'EOF' | bash\ngit push origin development\nEOF",
        "bash <<'EOF'\ngit push origin development\nEOF",
        "cat <<EOF\n$(git push origin development)\nEOF",
        "cat <<'EOF' | $SHELL\ngit push origin development\nEOF",
        "cat > f <<'EOF'\ntext\nEOF\ngit push origin development",
        "cat <<'EOF'\ngit push origin development",
        "git -c alias.x='!sh' x <<'EOF'\ngit push origin development\nEOF",
        "git status # x\ngit push origin main",
        "echo 'a' # git push origin main",
        "cmd <<EOF\necho # & git push origin development\nEOF",
    ):
        expect(command, "deny", repo)
    expect('cmd /c "echo # & git push origin development"', "deny", repo, tool="PowerShell")
    ok("`--tags` alone pushes no branch; a quoted here-document read as text, and a comment on a line without quoting, run nothing")


def test_fails_closed_without_git(work):
    feature = make_repo(work, "nogit", "feature/n")
    empty = work / "empty-path"
    empty.mkdir(exist_ok=True)
    env = dict(ENV, PATH=str(empty))
    expect("git push origin main", "deny", feature, env=env)
    expect("gh pr create --base development", "deny", feature, env=env)
    expect("echo hello", "allow", feature, env=env)
    ok("when git cannot run, push and pull request commands are refused and the rest goes through")


def test_line_continuations(work):
    feature = make_repo(work, "cont-feature", "feature/x")
    for newline in ("\n", "\r\n"):
        bash_denied = [
            f"git push \\{newline}  origin \\{newline}  main",
            f"git push origin \\{newline}  main",
            f"git push -u \\{newline} origin \\{newline} HEAD:main",
            f'bash -c "git push \\{newline} origin main"',
        ]
        for command in bash_denied:
            expect(command, "deny", feature)
        for command in (
            f"gh pr create \\{newline}  --base development",
            f"git push \\{newline} -u origin feature/x",
            f"git status \\{newline} && git log",
        ):
            expect(command, "allow", feature)
        # In single quotes a backslash and a line break are literal text.
        expect(f"git commit -m 'a \\{newline} git push origin main'", "allow", feature)
        # A line break not preceded by a backslash still separates commands.
        expect(f"git status{newline}git push origin main", "deny", feature)
        for command in (
            f"git push `{newline}  origin `{newline}  main",
            f"git push origin `{newline}  main",
            f"git push -u `{newline} origin `{newline} HEAD:main",
        ):
            expect(command, "deny", feature, tool="PowerShell")
        for command in (f"gh pr create `{newline}  --base development", f"git push `{newline} -u origin feature/x"):
            expect(command, "allow", feature, tool="PowerShell")
        # A backslash before a line break is no continuation in PowerShell.
        expect(f"git status \\{newline}git push origin main", "deny", feature, tool="PowerShell")
    ok("a continued line is one command, in Bash with a backslash and in PowerShell with a backtick")


def test_shell_flags(work):
    feature = make_repo(work, "flags-feature", "feature/x")
    on_main = make_repo(work, "flags-main", "main")
    denied = [
        "bash -lc 'git push origin main'",
        "bash -xc 'git push origin main'",
        "bash -ec 'git push origin main'",
        "bash -lic 'git push origin main'",
        "bash -e -c 'git push origin main'",
        "bash -l -c 'git push origin main'",
        "bash -o pipefail -c 'git push origin main'",
        "sh -ec 'git push origin main'",
        "zsh -lc 'git push origin main'",
        "bash -lc 'gh pr create'",
        'bash -lc "gh pr create --base main"',
        "bash -lc 'gh pr new'",
    ]
    for command in denied:
        expect(command, "deny", feature)
    expect("bash -lc 'git push'", "deny", on_main)
    expect("bash -lc 'git status'", "allow", feature)
    expect("bash -lc 'git push -u origin feature/x'", "allow", feature)
    expect("bash -e -c 'git push -u origin feature/x'", "allow", feature)
    expect("bash -lc 'git push'", "allow", feature)
    # `-e` is a PowerShell encoded-command flag; for bash it is an option, so no text is decoded.
    expect("bash -e script.sh status", "allow", feature)
    # The PowerShell forms keep working.
    expect(f"pwsh -e {encoded('git push origin main')}", "deny", feature, tool="PowerShell")
    expect(f"powershell -ec {encoded('git push origin main')}", "deny", feature, tool="PowerShell")
    expect(f"powershell -NoProfile -EncodedCommand {encoded('git push origin main')}", "deny", feature, tool="PowerShell")
    expect(f"pwsh -enc {encoded('git push origin feature/x')}", "allow", feature, tool="PowerShell")
    ok("sh-family option clusters with `c` introduce a command; encoded flags stay PowerShell's")


def test_gh_pr_new(work):
    feature = make_repo(work, "new-feature", "feature/x")
    other = make_repo(work, "new-other", "feature/y", config=OTHER_NAMES)
    for command in ("gh pr new", "gh pr new --title t", "gh pr new --base main", "gh pr new -Bmain", "gh pr new --base development --base main"):
        expect(command, "deny", feature)
    expect("gh pr new --title t", "deny", other, says="--base trunk")
    for command in ("gh pr new --base development", "gh pr new -B development --title t"):
        expect(command, "allow", feature)
    ok("`gh pr new` follows the rules of `gh pr create`")


def test_push_repo_option(work):
    feature = make_repo(work, "repo-feature", "feature/x")
    on_main = make_repo(work, "repo-main", "main")
    # With a bare remote on disk, git takes the first positional word as the repository even
    # after `--repo` (so `--repo origin HEAD:main` looks for a host called "head"), and every
    # word after it as a refspec. Only the second form can push to `main`.
    expect("git push --repo origin HEAD:main", "allow", feature)
    expect("git push --repo=origin HEAD:main", "allow", feature)
    expect("git push --repo origin other HEAD:main", "deny", feature)
    expect("git push --repo=origin other main", "deny", feature)
    expect("git push --repo origin other feature/x", "allow", feature)
    expect("git push --repo origin", "deny", on_main)
    expect("git push --repo origin", "allow", feature)
    ok("`--repo` does not turn the next word into a refspec; the words after the repository are")


def test_gh_api_contents(work):
    feature = make_repo(work, "contents-feature", "feature/x")
    other = make_repo(work, "contents-other", "feature/y", config=OTHER_NAMES)
    path = "repos/o/r/contents/docs/a.md"
    denied = [
        f"gh api -X PUT {path} -f message=m -f content=Yg== -f branch=main",
        f"gh api --method PUT {path} -f message=m -F branch=development",
        f"gh api --method=PUT {path} --raw-field branch=main -f message=m",
        f"gh api --field branch=refs/heads/main -X PUT {path} -f message=m",
        f"gh api -XPUT {path} -f branch=development",
        f"gh api -X DELETE {path} -f message=m -f sha=abc -f branch=main",
        f"gh api -X PUT {path} -f message=m -f content=Yg==",
        f"gh api -X DELETE {path} -f message=m -f sha=abc",
        f"gh api -X PUT {path} --input body.json",
        f"gh api -X PUT /{path}?ref=x -f branch=main",
        f"gh api -X PUT {path} -f message=m -f branch=$BRANCH",
        f"gh api -X PUT {path} -f message=m -f branch=",
    ]
    for command in denied:
        expect(command, "deny", feature)
    expect(f"gh api -X PUT {path} -f branch=stable -f message=m", "deny", other)
    expect(f"gh api -X PUT {path} -f branch=trunk -f message=m", "deny", other)
    allowed = [
        f"gh api -X PUT {path} -f message=m -f content=Yg== -f branch=feature/x",
        f"gh api --method PUT {path} -F branch=chore/docs",
        f"gh api -X DELETE {path} -f message=m -f sha=abc -f branch=feature/x",
        f"gh api {path}",
        f"gh api -X GET {path}",
        "gh api -X PUT repos/o/r/topics -f branch=main",
    ]
    for command in allowed:
        expect(command, "allow", feature)
    expect(f"gh api -X PUT {path} -f branch=main -f message=m", "allow", other)
    ok("`gh api` PUT or DELETE on a contents path needs a `branch` that is not a long-lived one")


def test_not_claude_code_input(work):
    feature = make_repo(work, "bad-feature", "feature/x")
    risky = [
        b"git push origin main",
        b'{"tool_name": "Bash", "tool_input": {"command": "git push origin main"',
        b'{"tool_name": "Bash", "tool_input": {"command": null, "note": "push"}}',
        b'{"tool_name": "Bash", "tool_input": {"command": ["git", "push", "origin", "main"]}}',
        b'{"tool_name": "Bash", "tool_input": {"command": 5, "x": "gh pr create"}}',
        b'{"tool_name": "Bash", "tool_input": "git push origin main"}',
        b'["git push origin main"]',
        b'"gh api repos/o/r"',
    ]
    quiet = [
        b"",
        b"   ",
        b"not json at all",
        b"null",
        b"42",
        b"[]",
        b'{"tool_name": "Bash", "tool_input": {"command": null}}',
        b'{"tool_name": "Bash", "tool_input": {"command": 5}}',
        b'{"tool_name": "Bash", "tool_input": null}',
        b'{"tool_name": "Bash", "tool_input": []}',
        b'{"tool_name": "Bash"}',
        b'{"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": 7}',
        b"\xff\xfe\x00 garbage",
    ]
    global cases
    for raw, expected in [(item, "deny") for item in risky] + [(item, "allow") for item in quiet]:
        cases += 1
        result = subprocess.run(
            [sys.executable, str(HOOKS / "guard_branches.py")], input=raw, capture_output=True, env=ENV, cwd=feature
        )
        assert result.returncode == 0, f"{raw!r} crashed: {result.stderr.decode('utf-8', 'replace')}"
        assert not result.stderr, f"{raw!r} printed to stderr: {result.stderr!r}"
        if expected == "deny":
            assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny", raw
        else:
            assert not result.stdout.strip(), f"{raw!r} -> {result.stdout!r}"
    # A string cwd that is not a folder, or a non-string one, is not a crash either.
    expect("git push origin main", "allow", work / "does-not-exist")
    ok(f"input that is not what Claude Code sends: {len(risky)} risky ones refused, {len(quiet)} others silent")


def test_long_command_line(work):
    feature = make_repo(work, "long-feature", "feature/x")
    filler = "a " * 200_000
    for command, expected in (
        (f"echo {filler}&& git push origin main", "deny"),
        (f"echo {filler}&& git push origin feature/x", "allow"),
        (f"echo {filler}\\\n&& gh pr create", "deny"),
    ):
        started = time.monotonic()
        expect(command, expected, feature)
        elapsed = time.monotonic() - started
        assert elapsed < 4, f"a 200,000-word line took {elapsed:.1f} s"
    ok("a 200,000-word command line is judged correctly in a few seconds")


# --- guard_immutable.py -----------------------------------------------------------------


def immutable_decision(path):
    return decision("guard_immutable.py", {"tool_name": "Edit", "tool_input": {"file_path": str(path)}})


def test_immutable_guard(work):
    repo = make_repo(work, "immutable", "development", config=CLASSIC + '[immutable]\npaths = ["migrations/*.sql"]\n')
    migrations = repo / "migrations"
    migrations.mkdir()
    (migrations / "0001_initial.sql").write_text("SELECT 1;\n", encoding="utf-8", newline="\n")
    git(repo, "add", "migrations")
    git(repo, "commit", "-q", "-m", "migration")
    (migrations / "0002_new.sql").write_text("SELECT 2;\n", encoding="utf-8", newline="\n")
    (repo / "README.sql").write_text("SELECT 3;\n", encoding="utf-8", newline="\n")
    git(repo, "add", "README.sql")
    git(repo, "commit", "-q", "-m", "readme")
    landed = migrations / "0001_initial.sql"

    assert immutable_decision(landed) == "deny"
    assert immutable_decision(migrations / "sub" / ".." / "0001_initial.sql") == "deny"
    assert immutable_decision(migrations / "0002_new.sql") == "allow"
    assert immutable_decision(migrations / "0003_missing.sql") == "allow"
    assert immutable_decision(repo / "README.sql") == "allow"
    variants = [Path(str(landed).replace("migrations", "Migrations").replace(".sql", ".SQL"))]
    if os.name == "nt":
        variants.append(Path(str(landed).replace("/", "\\")))
        variants.append(Path(str(landed).upper()))
    for variant in variants:
        # On a case-sensitive file system this is a separate (new) file.
        expected = "deny" if variant.exists() else "allow"
        assert immutable_decision(variant) == expected, f"{variant} -> expected {expected}"
    ok(f"a landed file is refused, and so are {len(variants)} spellings of its path ({'Windows' if os.name == 'nt' else 'POSIX'})")


def test_immutable_globs_and_ref(work):
    config = (
        '[branches]\nintegration = "trunk"\n'
        '[immutable]\npaths = ["db/Migrations/*.SQL", "schema/**/*.json", "LOCK"]\n'
    )
    repo = make_repo(work, "globs", "feature/g", config=config)
    (repo / "db" / "migrations").mkdir(parents=True)
    (repo / "schema" / "v1").mkdir(parents=True)
    landed = [repo / "db" / "migrations" / "0001.sql", repo / "schema" / "v1" / "a.json", repo / "LOCK"]
    for path in landed:
        path.write_text("x\n", encoding="utf-8", newline="\n")
    git(repo, "add", "db", "schema", "LOCK")
    git(repo, "commit", "-q", "-m", "landed")
    git(repo, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    topic = repo / "db" / "migrations" / "0002.sql"
    topic.write_text("y\n", encoding="utf-8", newline="\n")
    git(repo, "add", "db")
    git(repo, "commit", "-q", "-m", "topic only")
    for path in landed:
        assert immutable_decision(path) == "deny", path
    # Committed on HEAD but not on origin/trunk: still on its topic branch.
    assert immutable_decision(topic) == "allow"
    if os.name == "nt":
        assert immutable_decision(Path(str(landed[0]).replace("migrations", "MIGRATIONS"))) == "deny"
    other = repo / "schema" / "notes.txt"
    other.write_text("z\n", encoding="utf-8", newline="\n")
    assert immutable_decision(other) == "allow"

    plain = make_repo(work, "no-immutable", "development", config=CLASSIC)
    (plain / "migrations").mkdir()
    (plain / "migrations" / "0001.sql").write_text("x\n", encoding="utf-8", newline="\n")
    git(plain, "add", "migrations")
    git(plain, "commit", "-q", "-m", "m")
    assert immutable_decision(plain / "migrations" / "0001.sql") == "allow"
    ok("globs match case-insensitively; `origin/<integration>` decides when it exists; no `[immutable]`, no guard")


# --- format_edited.py -------------------------------------------------------------------


UNFORMATTED = "fn main(){}\n"


def format_file(path, env=None):
    result = run_hook("format_edited.py", {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}, env=env)
    global cases
    cases += 1
    return result


def test_formatter(work):
    on = make_repo(work, "fmt-on", "feature/f", config=CLASSIC + "[format]\nrust = true\n")
    off = make_repo(work, "fmt-off", "feature/f", config=CLASSIC)
    none = make_repo(work, "fmt-none", "feature/f", config=None)
    (on / "Cargo.toml").write_text('[package]\nname = "x"\nedition.workspace = true\n', encoding="utf-8")
    for repo in (off, none):
        source = repo / "main.rs"
        source.write_text(UNFORMATTED, encoding="utf-8", newline="\n")
        result = format_file(source)
        assert result.returncode == 0 and not result.stdout and not result.stderr
        assert source.read_text(encoding="utf-8") == UNFORMATTED
    ok("without `[format]` or without the file, an edited .rs file is left as it is")

    source = on / "main.rs"
    source.write_text(UNFORMATTED, encoding="utf-8", newline="\n")
    # git stays reachable so the configuration can be found; rustfmt does not.
    git_only = str(Path(shutil.which("git")).parent)
    assert not shutil.which("rustfmt", path=git_only)
    env = dict(ENV, PATH=git_only)
    result = format_file(source, env=env)
    assert result.returncode == 1
    message = result.stderr.decode("utf-8")
    assert "the edited file was not formatted" in message, message
    skipped = format_file(on / "notes.md", env=env)
    assert skipped.returncode == 0 and not skipped.stderr
    ok("a missing rustfmt is reported in UTF-8; a non-Rust file is not touched")

    if shutil.which("rustfmt"):
        result = format_file(source)
        assert result.returncode == 0 and not result.stdout, result.stderr
        assert source.read_text(encoding="utf-8").replace("\r\n", "\n") == "fn main() {}\n"
        ok("with `format.rust = true` rustfmt formats the edited file")
    else:
        print("  - rustfmt is not on PATH; the formatting itself was not tried")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # the Windows console cannot print '✓' otherwise
    if not shutil.which("git"):
        sys.exit("git is not on PATH")
    with tempfile.TemporaryDirectory(prefix="bekci-test-") as directory:
        work = Path(directory).resolve()
        empty_config = work / "gitconfig"
        empty_config.write_text("", encoding="utf-8")
        ENV.update(GIT_CONFIG_GLOBAL=str(empty_config), GIT_CONFIG_NOSYSTEM="1")
        for test in (
            test_branch_guard,
            test_powershell_forms,
            test_no_config,
            test_other_branch_names,
            test_no_release,
            test_broken_config,
            test_cd_to_other_checkout,
            test_worktree_without_its_own_file,
            test_main_checkout_without_the_file,
            test_borrowed_file_broken_or_immutable,
            test_python_too_old,
            test_hook_commands_find_python,
            test_command_substitutions,
            test_current_branch_substitution,
            test_tags_heredocs_and_comments,
            test_fails_closed_without_git,
            test_line_continuations,
            test_shell_flags,
            test_gh_pr_new,
            test_push_repo_option,
            test_gh_api_contents,
            test_not_claude_code_input,
            test_long_command_line,
            test_immutable_guard,
            test_immutable_globs_and_ref,
            test_formatter,
        ):
            print(test.__name__)
            test(work)
    print(f"All checks passed ({passed} groups, {cases} hook runs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
