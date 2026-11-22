# After a wave lands

- **Cards.** Close each card: `done`, `closed`, its pull requests in `prs`. Remove it from the `deps` of the cards that waited on it. Set the wave document to `closed`.
- **Remote-tracking refs.** `git fetch --prune` drops the refs of branches GitHub deleted on merge; `git config fetch.prune true` makes every fetch do it.
- **Local branches.** A local branch can go when its pull request merged. Squash merging leaves a branch's commits outside the integration branch, so `git branch --merged` does not find it: ask GitHub (`gh pr list --state merged --head <branch>`), and `git cherry -v <merged head> <branch>` marks with `+` any commit the branch gained after the head that merged. A branch that is checked out in a worktree stays until the worktree goes.
- **Sessions and worktrees.** Archive the wave's sessions; the app can do it by itself when a pull request closes. Leave worktree folders to the app, and find a session's folder by the path the app records for it, not by its name: folders are reused under older names.
- **Memory.** One rule per lesson, with how it is known. State does not go to memory; it is on the board.
