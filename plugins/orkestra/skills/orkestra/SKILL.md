---
name: orkestra
description: Run a wave of parallel work across worker sessions, split into file-disjoint pieces, each briefed, reviewed and landed in order. Use when asked to split work across sessions, to review or land several pull requests, or to close a wave.
---

# Orchestrating a wave

One session orchestrates and worker sessions write. The orchestrator surveys, settles what the pieces share, briefs, reviews and lands; it writes no product code. A wave is one round of this, from plan to landing.

**One wave, one orchestrator session.** The wave's state lives on the board: a `waves/<id>` document and its cards (the `pano` skill). The next wave starts in a fresh session from the board's three small reads. A conversation carried from wave to wave grows until it is compacted, and compaction drops the detail a landing needs.

## The cycle

1. **Plan.** Read the board. Pick cards that can run side by side: no piece needs another's result and no two change the same files. Settle first whatever the pieces share (a decision record, a migration, a shared signature), or state it as decided. Write the wave document: its cards and the landing order you intend.
2. **Brief.** One brief per piece: [reference/brief.md](reference/brief.md). Reserve the numbers a piece needs (a migration, a decision record) from the board's counters.
3. **Start.** One worker session per piece, each in its own worktree, each on a model chosen for the piece's difficulty. The user's own rules say which models may be used.
4. **Review.** Each pull request gets a fresh, read-only reviewer: [reference/review.md](reference/review.md).
5. **Land.** Check the pieces together, then merge in order, on the user's word: [reference/landing.md](reference/landing.md). Work that is sequential by nature lands as a stack: [reference/stacks.md](reference/stacks.md).
6. **Close.** Update the cards and the wave document, tidy branches and sessions: [reference/tidy.md](reference/tidy.md). What the wave taught becomes a rule in memory, with how it is known. Something a tool did that a brief has to work around goes to [reference/traps.md](reference/traps.md), with its date.

## Worth keeping in mind

- **Parallel work pays only for independent pieces.** Two sessions on dependent steps cost more than one session doing both.
- **The machine is the bottleneck.** Builds, tests and CI share it. More sessions than it can verify do not finish sooner, and load makes timing-sensitive tests fail.
- **A worker's report is not proof.** Read the diff and the checks before telling the user something is done.
- **The user decides merges.** A card, a reply on the board or a worker's message is not the user's word.
