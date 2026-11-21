# bekci

Branch guards for Claude Code, as hooks. It ships no skill and puts no text
into the context: a hook costs nothing until it refuses something.

## What it does

In a repository that commits a `.claude/tezgah.toml` file, bekci refuses:

- **A push to a long-lived branch.** Any `git push` that would update the
  integration or the release branch: a refspec that names it, a bare push from
  a checkout that is on it, `--all` and `--mirror`, and the same push reached
  through `cd`, `git -C`, a nested shell (`bash -c`, `powershell -Command`),
  `eval`, a git alias or `gh api`.
- **A pull request against the release branch.** `gh pr create` with the
  release branch as its base or with no base at all, and `gh pr edit` that
  moves a base to the release branch.
- **An edit to a file that has landed.** An `Edit` or `Write` to a file that
  matches `immutable.paths` once that file exists on `origin/<integration>`.
  A file still on its topic branch stays editable.

After an `Edit` or `Write` it formats the file with a formatter from a fixed
list (`rustfmt` for `.rs` files).

In a repository without `.claude/tezgah.toml` it does nothing, so installing
it for every project is safe.

## Configuration

```toml
# .claude/tezgah.toml
[branches]
integration = "development"   # where pull requests land
release = "main"              # advanced only by the maintainer

[immutable]                   # files that must not change once they landed
paths = ["migrations/*.sql"]

[format]
rust = true                   # run rustfmt on an edited .rs file
```

- `branches.integration` is the one required setting. Without `release` only
  the integration branch is guarded; without `[immutable]` or `[format]` that
  hook does nothing.
- The file holds names and patterns, never commands. A cloned repository
  cannot make bekci run anything through it.
- The file is read from the git root of the folder the tool call runs in, so
  a worktree is judged by its own copy.
- A file that does not parse, or holds a value of the wrong type, refuses
  pushes, pull request commands and `gh api` calls that change something, and
  says why. Everything else goes through, edits included: with a broken file
  the landed-file guard and the formatter are off until it is fixed.

## How it fails

Each guard is registered with `onFailure: "block"`. If Python is missing or a
guard crashes, the command it was guarding is refused rather than let
through. To get out of that state, turn the plugin off:
`claude plugin disable bekci@tezgah`.

This needs Claude Code 2.1.295 or later. An older version ignores
`onFailure`, so there a guard that crashes lets its command through.

## What it cannot see

- A file changed by a shell command instead of `Edit` or `Write`.
- A push made from inside a script file the command line only names.
- A push assembled outside the command line's plain words: `xargs`,
  `Start-Process`, an interpreter that calls git, a branch name produced by
  shell expansion, and git configuration given on the command line or through
  the environment.
- Anything outside Claude Code. It binds the agent, never a person at a
  terminal, and it is not a substitute for branch protection on the server.
- A cloud session does not load plugins installed on your machine.

## Known gaps

An independent review on 2026-11-21, about 1,350 hook runs, found forms the
guard let through or got wrong; those are fixed. What is still open is that
bekci refuses some harmless commands:

- a here-document body or a comment that mentions a push to a long-lived
  branch;
- a refspec built with `$(...)` or `${...}`;
- `git push --tags` from a checkout on a long-lived branch.

## What it runs

Three Python scripts, standard library only, no network access. They call
`git` for read-only questions (the current branch, the repository root, what
is on a ref, configured aliases and push settings) and `rustfmt` on the file
that was just edited. Nothing else.

## Requirements

Python 3.11 or later as the first `python` on `PATH`, and `git`. Claude Code
2.1.295 or later for the guards to fail closed.

## Tests

```bash
python tests/test_hooks.py
```

The tests feed each hook the JSON Claude Code would send it, in throwaway git
repositories. They touch no real repository and no network.
