# Stacked pull requests

A stack is for work that is sequential by nature: each step builds on the one before and is worth reviewing alone. Work that splits by files is not a stack; run it side by side.

GitHub keeps a stack together: when the bottom pull request merges, the rest are rebased and retargeted, and squash merging is supported. The `gh stack` extension drives it (`gh extension install github/gh-stack`).

- **Start one.** `gh stack init --base <integration branch> <branch>`. The trunk defaults to the repository's default branch, so name the integration branch. `gh stack add <branch>` adds a step; `gh stack submit` pushes the branches and opens the pull requests.
- **Tie existing pull requests together.** `gh stack link <bottom> <next> ...`, with branch names or pull request numbers, bottom first. This is the form for steps that different sessions opened.
- **Keep it current.** `gh stack sync`, or `gh stack rebase` after a lower step changed.
- **Merge.** `gh stack merge <pull request>` merges everything up to that step in one operation: all of it or none. It needs the user's word like any merge.

Without the extension, a follower conflicts once its base is squashed, because it still carries the base's original commits. The cure then: after the base lands, the follower's own session merges the integration branch into its branch, every conflict goes to the branch's side, and its checks run again.

As of 2026-11-21 a stack has not been landed this way in a squash-only repository whose trunk is not the default branch. The first one is the trial: write what it showed here and delete this paragraph.
