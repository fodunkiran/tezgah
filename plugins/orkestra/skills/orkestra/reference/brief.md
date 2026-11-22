# Briefing a worker session

A worker starts cold: the brief is all it knows about the task. It reads the repository's own instructions (`AGENTS.md` or `CLAUDE.md`, and the skills they name) by itself, so a brief does not repeat them. A brief carries what only this task has.

## What a brief holds

- **Goal.** The outcome in one or two sentences, and the card it belongs to.
- **Done when.** A short list a reviewer can check: a behaviour, a test that passes, a page that shows something. Write it before the work starts; the review reads against it. For a refactor it says the output stays identical byte for byte; a verbatim move is checked by sorting the lines removed and the lines added and comparing them.
- **Area.** The files and modules this piece owns. Name the files other pieces of the wave also touch, and ask for line-local edits there.
- **Base.** The branch to start from and to open the pull request against: the project's integration branch, from `.claude/tezgah.toml`. Say it even when it seems obvious; a new worktree can start from another branch.
- **Decided already.** What the pieces share and this one must not reopen: a decision record, a signature, a reserved number.
- **Out of scope.** What looks adjacent and belongs to another card.
- **Report.** What to send back: the pull request, what was verified and how, what was left out and why. Facts, not an account of effort.

## Size

One outcome per piece. A piece that would change more than about 800 lines, generated files aside, is usually two pieces. Split it before briefing; a large change costs most in review, where every round reads all of it again.

## What stays out

- **The repository's standing rules.** If a worker would not find a rule on its own, the fix belongs in the repository's instructions, once, and not in every brief.
- **Your idea of the implementation,** unless a decision constrains it. Give the evidence and the direction. A sentence handed over as fact is copied into code and documents unchecked, so read a record before quoting what it says.
- **Scratch file names shared with other pieces.** Workers can share one scratch folder: ask each to name its scratch files after its piece.
