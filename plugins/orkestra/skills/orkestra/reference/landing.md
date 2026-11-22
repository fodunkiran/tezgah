# Landing a wave

Pull requests that passed alone can still break together. Check the pieces as one state, then merge them in the order that state was built in.

## Before merging

1. **Predict conflicts** without touching a worktree. For each pull request, `git merge-tree --write-tree --name-only <expected integration state> <head>` lists the files that would conflict. Check each one against the state the earlier ones leave, not against today's integration branch.
2. **Build the integrated state** in a scratch worktree: merge the heads in landing order (migrations by number), run the project's full verification there once, and look at the pages when the wave changes any.
3. **Record it** on the wave document: the order, the base commit, and the tree of the verified state. A session that picks the wave up later lands from this record.

Run the verification when the machine is quiet. A build or a test loop in another session makes timing-sensitive tests fail; a path in a process list does not show that a build is running, so look for the compiler itself.

## Merging

- **On the user's word,** given in the chat for this wave.
- **In the recorded order,** each with `gh pr merge <number> --squash --match-head-commit <sha>`, so that only the reviewed head lands.
- **Then compare.** The integration branch's tree must equal the verified tree: `git diff <verified> origin/<integration>` prints nothing. Say so in the report.
- **A pull request that conflicts once an earlier one landed** goes back to its own session: it merges the integration branch into its branch and its checks run again. A conflict of meaning that only the integrated build showed goes back the same way, with the evidence.
- **"No checks reported" is not a pass.** CI attaches no checks while a pull request conflicts with its base, and none to a draft.
- **On green, read once.** "Merge when green" is one read of the checks after the run ends, never a poll. Auto-fix wakes a session on a failure, not when the checks pass, so tell the user the run is still going and offer to look then.
- **The description can become the squash message,** depending on the repository's settings. Trim notes meant only for the review ("stacked on", "as in the first draft") before merging.
- **A branch that a worktree still holds:** merge without `--delete-branch`. It deletes the local branch too, which git refuses while a worktree holds it; a repository set to delete merged branches removes the remote one by itself. Run the merge from the main checkout: one run from inside a worktree keeps that worktree from being removed.

## When a branch moves

- **Tell the others what moved.** When a pull request lands, message the wave's other sessions what it changed in the files they share.
- **Check a re-merge without redoing it.** After a branch moved, `git merge-tree --write-tree --merge-base <old head> <old verified merge> <new head>` prints the tree to expect, and every file outside the ones resolved by hand must equal it. When only part of a verified set lands, work out that part's tree before merging (`git merge-tree --write-tree --merge-base <base> <head 1> <head 2>`) and compare `origin/<integration>^{tree}` with it afterwards.
- **A rebased follower is still the reviewed one** when `git range-diff <old base>..<old head> origin/<integration>..<new head>` shows `=` on every commit.
- **Look for markers before committing a merge.** `git rerere` can replay part of a file's resolution and leave the rest between bare markers (`<<<<<<<` with no label); `git grep -n -E '^(<{7}|={7}|>{7})( |$)'` finds them.

The branch rules are the project's and the guards enforce them: nothing is pushed to the integration or the release branch, and no pull request targets the release branch. Promoting the release branch is the maintainer's.
