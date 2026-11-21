# tezgah — project rules

Small Claude Code plugins for a solo developer who lands work through coding agents: `bekci` (branch guards as hooks), `pano` (a work board skill) and `orkestra` (a procedure for a wave of parallel sessions). `README.md` says what each is, what it costs in context and what is not done yet.

## What every change keeps

- **Next to nothing in the context.** One skill per plugin. Its `SKILL.md` holds what every use needs, in under about 150 lines; the rest goes into `reference/` files one level deep. No text injected at session start, no MCP server, no agent definition. The three plugins together stay under 200 tokens added to every session; when a number in `README.md` changes, measure it again.
- **A hook only for a rule with no exceptions.** A hook prints nothing when it allows. It reads names and patterns from a project's `.claude/tezgah.toml`, never a command, and does nothing in a repository without that file.
- **Hook code is tried before it is trusted.** Every form found to slip through, or to be refused wrongly, becomes a test. Standard library only, no network.
- **Skills are written plainly.** Say what to do and why. No emphasis words, and a rule is stated as absolute only when it is. Delete a caution whose cause is gone; a line in `reference/traps.md` carries the month it was seen.
- **A project's own things stay in the project:** its instructions, its `verify` skill, its CI. A plugin here carries only what is the same everywhere.
- **Everything in the repository is in English.**

## Commands

```bash
python -X utf8 plugins/bekci/tests/test_hooks.py           # the hook tests
claude plugin validate plugins/<name>                       # "no version" is the one expected warning
claude --plugin-dir plugins/<name> plugin details <name>    # what a plugin adds to every session
```

## Working here

- Commit locally in small Conventional Commits, as the maintainer (`git var GIT_AUTHOR_IDENT`), with no tool attribution. There is no remote yet; creating one, pushing and publishing are the maintainer's.
- A plugin is tried in a sandbox project, enabled for that project only. Installing one for the whole account, or changing another project to use it, waits for the maintainer's word.
- The state of work is on the maintainer's work board, not in this repository. `README.md`'s "Status" says what is unfinished.
