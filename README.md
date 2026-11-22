# tezgah

Small Claude Code plugins for a solo developer who lands work through coding
agents: branch guards, a work board, and a procedure for running parallel
sessions. Each installs alone, and together they add about 130 tokens to a
session.

| Plugin | What it is | Added to every session | When used |
|---|---|---|---|
| [bekci](plugins/bekci/README.md) | Three hooks: no direct push to a long-lived branch, no edit to a landed file, format on edit | 0 tokens | 0 tokens |
| [pano](plugins/pano/skills/pano/SKILL.md) | One skill: a work board kept in a claude.ai artifact database | about 70 tokens | about 770 tokens |
| [orkestra](plugins/orkestra/skills/orkestra/SKILL.md) | One skill: brief, review and land a wave of parallel worker sessions | about 60 tokens | about 610 tokens |

Measured on 2026-11-21 with `claude plugin details` (Claude Code 2.1.292).
Hooks have no context cost; they run outside the conversation.

## How they are built

- **One skill per plugin.** Its `SKILL.md` holds what every use needs; the
  rest is in `reference/` files, read when a task calls for them.
- **A hook only for a rule with no exceptions.** Everything that takes
  judgment is text in a skill.
- **Nothing is injected at session start.** No MCP server and no agent
  definition either: each would be paid for in every session.
- **No per-plugin project settings.** A project commits one small file,
  `.claude/tezgah.toml`, that holds names and patterns, never commands. A
  repository without it is left alone.
- **What a project owns stays in the project:** its instructions, its
  `verify` skill, its CI.

## Installing

```bash
claude plugin marketplace add fodunkiran/tezgah
claude plugin install bekci@tezgah
claude plugin install pano@tezgah
claude plugin install orkestra@tezgah
```

In a session the same is `/plugin marketplace add fodunkiran/tezgah` and
`/plugin install bekci@tezgah`. A plugin installs for your account unless
you add `--scope project` (one project, written to its
`.claude/settings.json`) or `--scope local` (one project, on this machine
only). From a local checkout, give the folder: `claude plugin marketplace add
/path/to/tezgah`.

Then add `.claude/tezgah.toml` to each project that should be guarded; the
fields are in [bekci's README](plugins/bekci/README.md).

A plugin's hooks run with your permissions. Read `plugins/bekci/hooks/`
before installing; it is three short Python scripts and one JSON file.

## Limits

- A cloud session does not load plugins installed on your machine. There,
  only what the repository itself commits applies.
- `pano` needs the claude.ai artifact tools, so it works where those do.
- `orkestra` describes the Claude desktop app's Code tab; its
  [traps](plugins/orkestra/skills/orkestra/reference/traps.md) are dated and
  go stale.

## Status

Not released and not installed anywhere yet.

- `bekci` has only been run by its tests, which feed each hook the JSON
  Claude Code sends. It has not been tried inside a live session.
- An independent review found forms `bekci` let through; they are fixed and
  its tests pass with 305 hook runs. The fixed version has not had a second
  review yet, and three harmless refusals remain, listed under "Known gaps"
  in its README.
- `pano`'s page (`assets/board.html`) still draws the first board layout; the
  skill and `reference/schema.md` describe the new one. The page and the move
  of the existing boards are still to do.
- One trigger case per skill is written under `evals/`; none has been run,
  because a run makes real model calls.
- `claude plugin validate` passes with its "no version" warning, which is
  intended while updates follow commits.

## License

Apache License 2.0; see [LICENSE](LICENSE).
