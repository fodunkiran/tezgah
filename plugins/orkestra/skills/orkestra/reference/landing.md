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

The branch rules are the project's and the guards enforce them: nothing is pushed to the integration or the release branch, and no pull request targets the release branch. Promoting the release branch is the maintainer's.
